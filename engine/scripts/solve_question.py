"""Outer answering orchestrator: local match -> routing -> web -> browser -> answer.

This is the entry point that actually enforces the FAST time budget. The budget
is not advisory text in a config file: every stage runs under a deadline derived
from `config/fast_profile.yaml`, and the browser stage kills its whole process
tree when the hard timeout expires.

Stage budget (FAST):

    0-3s    local match        (question bank; normally <1s)
    3-10s   routing / pattern  (question_routes lookup)
    10-30s  simple web         (plain HTTP, no browser)
    75s     browser soft timeout
    90s     abort prepare
    120s    HARD TIMEOUT       (process tree killed, hand off to human)

The NORMAL profile keeps the original 180s and is never modified by this script.

Windows note: agent-browser spawns a Chromium process tree. `taskkill /F /T`
terminates the tree, not just the launcher, so no orphan browser survives the
hard timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, ROOT, text
from db_schema import connect_db, ensure_schema
from match_engine import MatchIndex, answer_with_tier, remap_answer, row_options
from variant_match import NEW, VARIANT, VariantMatch, find_variant, render_variant

try:
    import yaml
except ImportError:  # pragma: no cover - fallback below keeps this optional
    yaml = None


def parse_simple_yaml(text_value: str) -> dict:
    """Parse the restricted YAML subset used by the profile files.

    The project venv ships pypdf/openpyxl but not pyyaml, while some system
    interpreters are the other way round. The answering path must not depend on
    which one is running, so profiles are parsed directly when pyyaml is absent.
    Supports nested maps two levels deep, `- ` list items, comments and blank
    lines -- which is all these files use.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    # Where a `- ` item should be appended: (parent_mapping, key).
    list_target: tuple[dict, str] | None = None

    for raw_line in text_value.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if line.startswith("- "):
            if list_target is not None:
                parent, key = list_target
                if not isinstance(parent.get(key), list):
                    parent[key] = []
                parent[key].append(_coerce(line[2:].strip()))
            continue

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        current = stack[-1][1]

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()

        if value == "":
            # Either a nested mapping or a list block; decided by what follows.
            child: dict = {}
            current[key] = child
            stack.append((indent, child))
            list_target = (current, key)
            continue

        current[key] = _coerce(value)
        list_target = (current, key)

    return root


def _coerce(value: str):
    # YAML only starts an inline comment after whitespace, and never inside a
    # quoted scalar. The profile files use inline comments liberally.
    if value[:1] not in {'"', "'"}:
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip('"').strip("'")




DEFAULT_PROFILE = ROOT / "config" / "fast_profile.yaml"
URLS_PATH = ROOT / "config" / "official_urls.json"

# Question phrasing that means a human must drive the browser. Kept narrow on
# purpose: a false positive costs a correct answer, so only unambiguous markers
# trigger an early handoff.
HANDOFF_PATTERNS: dict[str, tuple[str, ...]] = {
    "wechat_mp_or_miniprogram": ("微信公众号", "微信小程序", "公众号", "微信中搜索", "微信指数"),
    "app_only": ("APP的", "APP中", "手机APP", "客户端中", "安装国家反诈"),
    "qr_login": ("扫码登录", "扫描二维码", "二维码登录"),
    "sms_verification": ("短信验证", "手机验证码"),
    "campus_authentication": ("校园网", "统一身份认证", "学号登录", "校园认证"),
    "drm_pdf": ("DRM", "加密PDF"),
    "dynamic_player": ("视频时长", "视频前", "播放时长"),
}


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

@dataclass
class Profile:
    mode: str = "FAST"
    timeouts: dict[str, float] = field(default_factory=dict)
    max_browser_failures: int = 2
    early_stop_triggers: tuple[str, ...] = ()
    answer_first: bool = True
    verbose: bool = False
    prefer: str = "agent-browser"
    fallback: str = "playwright"

    def t(self, name: str, default: float) -> float:
        return float(self.timeouts.get(name, default))


def load_profile(path: Path) -> Profile:
    raw = Path(path).read_text(encoding="utf-8")
    payload = (yaml.safe_load(raw) if yaml is not None else None) or parse_simple_yaml(raw)
    timeouts = payload.get("timeouts") or {}
    browser = payload.get("browser") or {}
    output = payload.get("output") or {}
    return Profile(
        mode=text(payload.get("mode")) or "FAST",
        timeouts={k: float(v) for k, v in timeouts.items()},
        max_browser_failures=int(browser.get("max_browser_failures", 2)),
        early_stop_triggers=tuple(browser.get("early_stop_requires_human") or ()),
        answer_first=bool(output.get("answer_first", True)),
        verbose=bool(output.get("verbose", False)),
        prefer=text(browser.get("prefer")) or "agent-browser",
        fallback=text(browser.get("fallback")) or "playwright",
    )


# --------------------------------------------------------------------------
# process control
# --------------------------------------------------------------------------

def split_command(binary: str) -> list[str]:
    """Split a command line on whitespace, honouring double quotes.

    `shlex` is not usable here: in posix mode it treats backslashes as escapes
    and mangles Windows paths, and in non-posix mode it does not strip quotes.
    This project's own path contains a space ("ai+ 2"), so quote handling is
    load-bearing rather than cosmetic.
    """
    return [quoted or bare for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', binary)]


def build_argv(binary: str, extra: list[str]) -> list[str]:
    """Resolve a command line into an argv that CreateProcess can launch.

    `agent-browser` installs as a `.CMD` shim on Windows, and CreateProcess
    cannot execute a batch file directly -- it must go through cmd.exe. Doing
    that keeps the launcher as the process-tree root, so `taskkill /T` still
    reaches node and Chromium underneath it.
    """
    parts = [p for p in split_command(binary) if p.strip()]
    if not parts:
        return list(extra)
    resolved = shutil.which(parts[0]) or parts[0]
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", resolved, *parts[1:], *extra]
    return [resolved, *parts[1:], *extra]


def kill_process_tree(pid: int) -> bool:
    """Terminate a process and every descendant. Returns True if it acted."""
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False


# agent-browser does not run its browser inside the CLI process. It starts a
# long-lived daemon and spawns headless Chromium with its own profile dir, so
# `taskkill` on the CLI wrapper reaches neither. Verified on this machine: the
# wrapper exited, the daemon and 22 headless browser processes survived.
BROWSER_MARKERS = (
    "agent-browser-chrome",
    "agent-browser-win32",
    "agent-browser.exe",
    "ms-playwright",
    "playwright-mcp",
)


def list_marked_processes(markers: tuple[str, ...] = BROWSER_MARKERS) -> list[tuple[int, str]]:
    """Processes whose command line carries a browser-automation marker."""
    if os.name != "nt":
        return []
    clauses = " -or ".join(f"$_.CommandLine -like '*{m}*'" for m in markers)
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -ne $null -and ({clauses}) }} | "
        'ForEach-Object { "$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)" }'
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # Exclude only our own process and its direct child (the PowerShell query,
    # whose own command line contains the markers). Excluding by executable name
    # would blind the sweep to genuinely python-hosted browser tooling.
    self_pid = os.getpid()
    found: list[tuple[int, str]] = []
    for line in (result.stdout or "").splitlines():
        pid_text, _, rest = line.strip().partition("|")
        ppid_text, _, name = rest.partition("|")
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == self_pid or (ppid_text.isdigit() and int(ppid_text) == self_pid):
            continue
        found.append((pid, name.strip()))
    return found


def sweep_browser_processes(notes: list[str],
                            markers: tuple[str, ...] = BROWSER_MARKERS) -> int:
    """Kill any browser-automation process still alive after an abort."""
    killed = 0
    for pid, _name in list_marked_processes(markers):
        if kill_process_tree(pid):
            killed += 1
    if killed:
        notes.append(f"清理残留浏览器/守护进程 {killed} 个")
    return killed


def abort_browser(profile: "Profile", notes: list[str]) -> None:
    """Stop the browser for real: close sessions, then sweep survivors."""
    for binary in (profile.prefer, profile.fallback):
        if not binary:
            continue
        head = (split_command(binary) or [""])[0].lower()
        # Only these CLIs have a `close` subcommand; a stand-in would just hang.
        if not any(key in head for key in ("agent-browser", "playwright")):
            continue
        try:
            run_process(build_argv(binary, ["close", "--all"]), timeout=15, cwd=ROOT)
        except (OSError, subprocess.SubprocessError):
            pass
    sweep_browser_processes(notes)


def run_process(cmd: list[str], timeout: float, cwd: Path | None = None) -> dict:
    """Run a command under a hard timeout, killing the whole tree on expiry."""
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        creationflags=creationflags,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
        killed = False
    except subprocess.TimeoutExpired:
        killed = kill_process_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = "", ""
        timed_out = True
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": out or "",
        "stderr": err or "",
        "timed_out": timed_out,
        "tree_killed": killed,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
    }


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

@dataclass
class Outcome:
    # ANSWER                本地原题命中，直接作答
    # OFFICIAL_MOCK_VARIANT 同平台同型题，参数变了：给配方，不给答案
    # NEEDS_HUMAN           转人工交接
    # NO_ROUTE              题库与变体都没命中
    status: str
    answer: str = ""
    tier: str = ""
    label: str = ""
    question_id: str = ""
    route: dict | None = None
    stage: str = ""
    elapsed_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    variant: VariantMatch | None = None


def detect_handoff(question_text: str, route: dict | None, profile: Profile) -> str | None:
    """Decide whether a human must drive this one. Returns a trigger name."""
    if route:
        # 变体路由的 requires_login / manual_only 复用的是**参照题**的备注，
        # 描述的是那道题的权限情况，不是本题的事实。若让别人的登录备注否决
        # 整个变体流程，变体匹配就形同虚设了。真正被拦时，浏览器阶段或
        # 平台本身会转人工 —— 这里只在备注里提示可能需登录。
        if text(route.get("route_source")) != "variant_match":
            if int(route.get("manual_only") or 0) == 1:
                return "route_manual_only"
            if text(route.get("requires_login")) == "YES":
                return "route_requires_login"
    haystack = text(question_text)
    for trigger, needles in HANDOFF_PATTERNS.items():
        if profile.early_stop_triggers and trigger not in profile.early_stop_triggers:
            continue
        for needle in needles:
            if needle in haystack:
                return trigger
    return None


def lookup_route(conn, question_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM question_routes WHERE question_id = ? "
        "ORDER BY (deep_link <> '') DESC, route_confidence LIMIT 1",
        (question_id,),
    ).fetchone()
    return dict(row) if row else None


def route_from_variant(variant: VariantMatch | None) -> dict | None:
    """把同型题的配方转成 route 形状，供人工交接文本复用。

    变体题没有自己的题库行，因此没有 question_routes 记录；但人工交接需要
    的入口、步骤和检索式，同型题的配方里全都有。
    """
    if variant is None or variant.status != VARIANT:
        return None
    recipe = variant.recipe
    steps = text(recipe.get("retrieval_recipe")) or text(recipe.get("retrieval_path"))
    return {
        "platform_key": text(recipe.get("platform_key")) or variant.platform,
        "official_platform": variant.platform or text(recipe.get("platform")),
        "official_url": text(recipe.get("official_url")),
        "deep_link": text(recipe.get("official_url")),
        "retrieval_recipe": steps,
        "manual_recipe": text(recipe.get("manual_recipe")),
        "retrieval_query": text(recipe.get("retrieval_query")),
        "requires_login": text(recipe.get("requires_login")) or "UNKNOWN",
        "manual_only": int(recipe.get("manual_only") or 0),
        "route_source": "variant_match",
    }


def simple_web_fetch(url: str, timeout: float) -> dict:
    """Plain HTTP read. No browser, no JS."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; ai-info-literacy-local-bank)"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
            return {
                "ok": True, "status": response.status, "bytes": len(body),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            }
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        return {
            "ok": False, "error": str(exc),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }


def handoff_text(question_text: str, route: dict | None, trigger: str) -> str:
    url = text((route or {}).get("deep_link")) or text((route or {}).get("official_url"))
    platform = text((route or {}).get("official_platform")) or "题目指定平台"
    recipe = text((route or {}).get("retrieval_recipe"))
    lines = [
        "🔴 需要你操作",
        f"（触发原因：{trigger}）",
        "",
        f"官网/入口：{url or '题目未给出，需按平台名进入'}",
        f"平台：{platform}",
        "",
    ]
    if recipe:
        for index, step in enumerate(recipe.split(" → "), 1):
            lines.append(f"{index}. {step}")
    else:
        lines += [
            "1. 打开上面的入口。",
            "2. 按题干关键词进入对应栏目或检索框。",
            "3. 记录题干要求字段。",
        ]
    query = text((route or {}).get("retrieval_query"))
    if query:
        lines += ["", "复制：", f"`{query}`"]
    lines += ["", "看：题干要求的结果字段，并截图回传。"]
    return "\n".join(lines)


def solve(args) -> Outcome:
    profile = load_profile(Path(args.profile))
    if args.hard_timeout_override:
        profile.timeouts["hard_timeout_seconds"] = float(args.hard_timeout_override)
    if args.browser_cmd:
        profile.prefer = args.browser_cmd
        profile.fallback = ""

    hard = profile.t("hard_timeout_seconds", 120.0)
    started = time.monotonic()
    notes: list[str] = []

    conn = connect_db(args.db)
    ensure_schema(conn)

    # ---- stage 1: local match (budget 0-3s, normally <1s) -------------------
    options = {letter: getattr(args, f"option_{letter.lower()}") for letter in "ABCD"}
    # An all-empty option dict means "not supplied"; passing it through would
    # make remap_answer compare against blank options and refuse to map.
    supplied = {letter: value for letter, value in options.items() if text(value)}
    index = MatchIndex(conn)
    result = index.lookup(args.question_text, options)
    local_deadline = profile.t("local_match_timeout_seconds", 3.0)

    if result.row is not None and result.method in {"exact", "normalized_exact"}:
        answer, tier, label = answer_with_tier(result.row)
        if not answer:
            # Matched the bank but the row carries no answer: fall through to
            # routing rather than reporting an empty answer.
            notes.append("本地命中但该题无答案，继续走路由")
        else:
            mapping = remap_answer(result.row, supplied or None, answer)
            if mapping["status"].startswith("UNRESOLVED"):
                notes.append(f"选项内容无法安全重映射：{mapping['status']}")
            else:
                shown = mapping["answer"] or answer
                return Outcome(
                    status="ANSWER", answer=shown, tier=tier, label=label,
                    question_id=result.row["id"], stage="local_match",
                    elapsed_ms=round((time.monotonic() - started) * 1000, 1),
                    notes=notes,
                )

    # ---- stage 1b: variant match (OFFICIAL_MOCK_VARIANT) -------------------
    # 正式题与模拟题「同平台、同操作、换参数」时，原题命中会失败，但旧题的
    # 配方仍然可用。这里找同型题并复用配方 —— 绝不复用旧题答案。
    variant: VariantMatch | None = None
    if result.row is None or result.method not in {"exact", "normalized_exact"}:
        variant = find_variant(conn, args.question_text, index.rows)
        if variant.status == VARIANT:
            notes.append(
                f"同型题：{variant.source_row['id']} 相似度 {variant.similarity:.2f}"
                f"（{variant.template or '未判定模板'}）"
            )
        else:
            notes.append("无同型题，按平台配方处理")

    if time.monotonic() - started > local_deadline:
        notes.append(f"本地匹配超出 {local_deadline}s 预算")

    # ---- stage 2: routing / pattern (budget 3-10s) -------------------------
    route = None
    if result.row is not None:
        route = lookup_route(conn, result.row["id"])
    if route:
        notes.append(
            f"路由：{route['platform_key']} / {route['official_platform']}"
            f"（{route['route_source']}）"
        )

    # 变体路由来自正确的参照题，必须优先于「模糊命中行」的路由。
    # 模糊命中的那一行是另一道题：它的登录备注不该否决本次变体，它的入口
    # 也不该顶掉参照题入口，否则变体会被莫名其妙地推去人工交接。
    variant_route = route_from_variant(variant)
    if variant_route:
        for key, value in (route or {}).items():
            if not variant_route.get(key):
                variant_route[key] = value
        route = variant_route
        notes.append(f"路由：变体复用 {route['platform_key']}")
        if text(route.get("requires_login")) == "YES":
            notes.append("参照题配方标注需登录；若本题被拦，转人工交接")

    trigger = detect_handoff(args.question_text, route, profile)
    if trigger:
        return Outcome(
            status="NEEDS_HUMAN", question_id=(result.row["id"] if result.row else ""),
            route=route, stage="handoff_detected", variant=variant,
            elapsed_ms=round((time.monotonic() - started) * 1000, 1), notes=notes,
        )

    # 同型题命中：给配方，不给答案。正式题换了参数，旧答案必然不适用。
    # 注意这里**不能**加 `result.row is None` 前置条件：模糊匹配会让
    # result.row 非空，加了就会把变体题漏到末尾的 routed_needs_reading。
    if variant is not None and variant.status == VARIANT:
        return Outcome(
            status="OFFICIAL_MOCK_VARIANT", variant=variant,
            question_id=(variant.source_row["id"] if variant.source_row else ""),
            route=route, stage="variant_match",
            elapsed_ms=round((time.monotonic() - started) * 1000, 1), notes=notes,
        )

    if result.row is None:
        return Outcome(
            status="NO_ROUTE", stage="local_miss",
            elapsed_ms=round((time.monotonic() - started) * 1000, 1), notes=notes,
        )

    # ---- stage 3: simple web (budget 10-30s) -------------------------------
    web_deadline = profile.t("simple_web_timeout_seconds", 30.0)
    target = text((route or {}).get("deep_link")) or text((route or {}).get("official_url"))
    if target and not args.skip_web:
        remaining = hard - (time.monotonic() - started)
        web_result = simple_web_fetch(target, max(1.0, min(web_deadline, remaining)))
        notes.append(f"直接网页：{'ok' if web_result.get('ok') else 'fail'}"
                     f" ({web_result.get('elapsed_ms')}ms)")

    # ---- stage 4: browser (soft 75s / abort 90s / hard 120s) ---------------
    if args.allow_browser and target:
        browser_result = run_browser_stage(target, profile, started, notes)
        if browser_result == "TIMEOUT":
            return Outcome(
                status="NEEDS_HUMAN", question_id=result.row["id"], route=route,
                stage="hard_timeout",
                elapsed_ms=round((time.monotonic() - started) * 1000, 1), notes=notes,
            )

    # A routed but locally-unmatched question still needs a human/agent to read
    # the page; we never guess an answer from routing metadata alone.
    return Outcome(
        status="NEEDS_HUMAN", question_id=result.row["id"], route=route,
        stage="routed_needs_reading",
        elapsed_ms=round((time.monotonic() - started) * 1000, 1), notes=notes,
    )


def run_browser_stage(target: str, profile: Profile, started: float,
                      notes: list[str]) -> str:
    """Drive the browser under the staged budget. Returns 'OK' or 'TIMEOUT'."""
    hard = profile.t("hard_timeout_seconds", 120.0)
    soft = profile.t("browser_soft_timeout_seconds", 75.0)
    failures = 0
    binary = profile.prefer

    while failures < profile.max_browser_failures:
        remaining = hard - (time.monotonic() - started)
        if remaining <= 0:
            notes.append("硬超时：无剩余预算")
            abort_browser(profile, notes)
            return "TIMEOUT"
        budget = min(soft, remaining)
        outcome = run_process(build_argv(binary, ["open", target]), timeout=budget, cwd=ROOT)
        notes.append(
            f"browser[{binary}] rc={outcome['returncode']} "
            f"{outcome['elapsed_ms']}ms timed_out={outcome['timed_out']} "
            f"tree_killed={outcome['tree_killed']}"
        )
        if outcome["timed_out"]:
            notes.append("浏览器软超时，进程树已终止")
            abort_browser(profile, notes)
            return "TIMEOUT"
        if outcome["returncode"] == 0:
            return "OK"
        failures += 1
        notes.append(f"浏览器失败 {failures}/{profile.max_browser_failures}")
        if failures >= profile.max_browser_failures:
            notes.append("连续失败达到上限，转人工")
            abort_browser(profile, notes)
            return "TIMEOUT"
        if binary == profile.prefer and profile.fallback:
            binary = profile.fallback
    return "TIMEOUT"


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def render(outcome: Outcome, args, question_text: str) -> str:
    if outcome.status == "ANSWER":
        if outcome.tier == "standard_answer":
            badge = "🟢 本地题库原题命中"
        elif outcome.tier == "mock_key":
            badge = "🟢 2026模拟题题源命中"
        else:
            badge = "🟠 本地题库原题命中（题源答案未官方核验）"
        lines = [f"答案：{outcome.answer}", badge]
        if args.explain:
            lines.append(f"题库ID：{outcome.question_id}  阶段：{outcome.stage}  "
                         f"{outcome.elapsed_ms:.0f}ms")
        return "\n".join(lines)

    if outcome.status == "OFFICIAL_MOCK_VARIANT" and outcome.variant is not None:
        body = render_variant(outcome.variant, question_text)
        if args.explain and outcome.notes:
            body += "\n\n[notes]\n" + "\n".join(f"- {n}" for n in outcome.notes)
        return body

    if outcome.status == "NEEDS_HUMAN":
        body = handoff_text(question_text, outcome.route, outcome.stage)
        if args.explain and outcome.notes:
            body += "\n\n[notes]\n" + "\n".join(f"- {n}" for n in outcome.notes)
        return body

    lines = ["未命中本地题库，且未解析出可用平台路由。", "请给出题目指定平台后重试。"]
    if args.explain and outcome.notes:
        lines += ["", "[notes]"] + [f"- {n}" for n in outcome.notes]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question_text")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--option-a", default="")
    parser.add_argument("--option-b", default="")
    parser.add_argument("--option-c", default="")
    parser.add_argument("--option-d", default="")
    parser.add_argument("--allow-browser", action="store_true",
                        help="允许进入浏览器阶段（默认只做本地+路由+直接网页）")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--hard-timeout-override", type=float, default=0.0)
    parser.add_argument("--browser-cmd", default="",
                        help="覆盖 profile 的浏览器命令（测试或换用其它 CLI 时使用）")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    outcome = solve(args)
    if args.json:
        payload = {
            "status": outcome.status, "answer": outcome.answer, "tier": outcome.tier,
            "question_id": outcome.question_id, "stage": outcome.stage,
            "elapsed_ms": outcome.elapsed_ms, "notes": outcome.notes,
        }
        if outcome.variant is not None:
            payload["variant"] = {
                "status": outcome.variant.status,
                "reference_question_id": (outcome.variant.source_row["id"]
                                          if outcome.variant.source_row else ""),
                "similarity": round(outcome.variant.similarity, 3),
                "platform": outcome.variant.platform,
                "template": outcome.variant.template,
                "recipe": outcome.variant.recipe,
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(outcome, args, args.question_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

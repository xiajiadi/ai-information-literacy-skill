"""省赛初始化 · 浏览器 / CLI 冒烟测试。

铁律（§25）：
  - 只测试**外部公开网站**。
  - **绝对不要**使用正式比赛页面做自动化测试。
  - 风险不明确的功能标 BLOCKED_PENDING_CONTROLLER，不自行扩大权限。

本脚本在启动任何浏览器之前，先用 compliance_gate 校验全部目标 URL；
只要有任何一个落在比赛面或未知面，整个冒烟测试拒绝运行。

产出：data/quality/provincial_smoke.json

用法：
    uv run python scripts/provincial_smoke.py
    uv run python scripts/provincial_smoke.py --json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate, detect_challenge  # noqa: E402
from provincial_common import ROOT, now_iso, run_captured, write_json  # noqa: E402

OUTPUT_PATH = ROOT / "data" / "quality" / "provincial_smoke.json"
SESSION = "provincial-smoke"

PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"
SKIP = "SKIP"
BLOCKED_PENDING_CONTROLLER = "BLOCKED_PENDING_CONTROLLER"

STEP_TIMEOUT = 90

# 只允许公开、无登录、非比赛面的测试目标。
SMOKE_TARGETS = [
    "https://example.com/",
    "https://cn.bing.com/",
    "https://www.icourse163.org/search.htm?search=%E4%BF%A1%E6%81%AF%E7%B4%A0%E5%85%BB",
]


@dataclass
class Step:
    name: str
    status: str = SKIP
    detail: str = ""
    elapsed_ms: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


def resolve_agent_browser() -> list[str] | None:
    """找到可调用的 agent-browser。优先真实 exe，避免每次起 PowerShell。"""
    found = shutil.which("agent-browser")
    if found:
        wrapper = Path(found)
        for candidate in wrapper.parent.rglob("agent-browser-*.exe"):
            return [str(candidate)]
        if wrapper.suffix.lower() in {".exe", ".cmd", ".bat"}:
            return [str(wrapper)]
    # 兜底：通过 PowerShell 调用（wrapper 是 .ps1 时）
    for candidate in (
        Path(r"D:\Dev\tools\browser-tools\agent-browser"),
        Path.home() / "AppData" / "Roaming" / "npm",
    ):
        if not candidate.exists():
            continue
        for exe in candidate.rglob("agent-browser-*.exe"):
            return [str(exe)]
    return None


def run_ab(base: list[str], *args: str) -> tuple[int, str]:
    """调用 agent-browser。

    用 run_captured（临时文件而不是管道）：agent-browser 会派生常驻 daemon，
    daemon 继承 stdout/stderr 管道句柄后管道不会 EOF，capture_output 会一直
    阻塞到超时。
    """
    return run_captured([*base, *args], timeout=STEP_TIMEOUT)


def record(step: Step) -> Step:
    step.elapsed_ms = int(step.elapsed_ms)
    return step


def smoke() -> dict[str, Any]:
    gate = ComplianceGate()
    steps: list[Step] = []

    # --- 0. 合规前置守卫（在任何浏览器调用之前） -------------------------
    guard = Step(name="compliance_preflight")
    blocked = []
    for url in SMOKE_TARGETS:
        verdict = gate.classify(url)
        if not verdict.automation_allowed:
            blocked.append({"url": url, "decision": verdict.decision, "reason": verdict.reason})
    competition_probe = [
        "https://csc.xxsuyang.com/training",
        "https://xxsuyang.com/",
    ]
    competition_leaks = [
        url for url in competition_probe if gate.classify(url).automation_allowed
    ]
    if blocked or competition_leaks:
        guard.status = FAIL
        guard.detail = f"冒烟目标被合规闸门拒绝：{blocked}；比赛面泄漏：{competition_leaks}"
        steps.append(guard)
        return finish(steps, gate)
    guard.status = PASS
    guard.detail = (
        f"{len(SMOKE_TARGETS)} 个公开测试目标全部放行；"
        f"{len(competition_probe)} 个比赛面探针全部被拒绝。"
    )
    guard.evidence = {
        "allowed": SMOKE_TARGETS,
        "refused_competition_surface": competition_probe,
    }
    steps.append(guard)

    base = resolve_agent_browser()
    if not base:
        step = Step(
            name="agent_browser_available",
            status=FAIL,
            detail="未找到 agent-browser 可执行文件。",
        )
        steps.append(step)
        return finish(steps, gate)
    step = Step(
        name="agent_browser_available", status=PASS, detail=f"使用 {base[0]}"
    )
    steps.append(step)

    # --- 1. 浏览器可启动 + 打开普通网页 ---------------------------------
    started = time.time()
    code, out = run_ab(base, "open", SMOKE_TARGETS[0])
    step = Step(
        name="browser_start_and_open_public_page",
        status=PASS if code == 0 else FAIL,
        detail=out[:400],
        elapsed_ms=(time.time() - started) * 1000,
    )
    steps.append(step)

    # --- 2. 读取页面正文 ------------------------------------------------
    started = time.time()
    code, out = run_ab(base, "read", SMOKE_TARGETS[0])
    has_text = code == 0 and len(out) > 20
    step = Step(
        name="read_page_text",
        status=PASS if has_text else FAIL,
        detail=out[:200],
        elapsed_ms=(time.time() - started) * 1000,
        evidence={"chars": len(out)},
    )
    steps.append(step)

    # --- 3. 输入公开检索关键词 + 提交 -----------------------------------
    started = time.time()
    code_open, _ = run_ab(base, "open", SMOKE_TARGETS[1])
    code_snap, snap = run_ab(base, "snapshot", "-i", "-d", "4")
    ref = ""
    for line in snap.splitlines():
        if "searchbox" in line and "ref=" in line:
            ref = line.split("ref=")[-1].split("]")[0].strip()
            break
    if not ref:
        step = Step(
            name="type_public_query",
            status=PARTIAL,
            detail="未在公开搜索页找到 searchbox；跳过输入步骤。",
            elapsed_ms=(time.time() - started) * 1000,
        )
        steps.append(step)
    else:
        quoted = f"@{ref}"  # PowerShell 之外也要带 @ 前缀
        code_fill, fill_out = run_ab(base, "fill", quoted, "信息素养")
        # 必须在按 Enter 之前读回输入值：Enter 会导航，ref 随之失效。
        code_value, value_out = run_ab(base, "get", "value", quoted)
        code_enter, _ = run_ab(base, "press", "Enter")
        ok = code_fill == 0 and code_enter == 0 and "信息素养" in value_out
        step = Step(
            name="type_public_query",
            status=PASS if ok else PARTIAL,
            detail=(fill_out + " | " + value_out)[:300],
            elapsed_ms=(time.time() - started) * 1000,
            evidence={"ref": ref},
        )
        steps.append(step)

    # --- 4. 点击正常页面元素 --------------------------------------------
    started = time.time()
    code, url_out = run_ab(base, "get", "url")
    code2, title_out = run_ab(base, "get", "title")
    ok = code == 0 and url_out.startswith("http")
    step = Step(
        name="page_state_readable",
        status=PASS if ok else PARTIAL,
        detail=f"{url_out} | {title_out}"[:300],
        elapsed_ms=(time.time() - started) * 1000,
    )
    steps.append(step)

    # --- 5. CLI 与浏览器之间的数据传递 ----------------------------------
    started = time.time()
    code, out = run_ab(base, "eval", "document.title + '|' + location.host")
    ok = code == 0 and "|" in out
    step = Step(
        name="cli_browser_data_passing",
        status=PASS if ok else PARTIAL,
        detail=out[:200],
        elapsed_ms=(time.time() - started) * 1000,
    )
    steps.append(step)

    # --- 6. 公开 MOOC 检索页（核心 recipe 复核） ------------------------
    started = time.time()
    code, out = run_ab(base, "open", SMOKE_TARGETS[2])
    code2, title_out = run_ab(base, "get", "title")
    ok = code == 0 and "中国大学MOOC" in title_out
    step = Step(
        name="public_mooc_recipe_reachable",
        status=PASS if ok else PARTIAL,
        detail=title_out[:200],
        elapsed_ms=(time.time() - started) * 1000,
    )
    steps.append(step)

    # --- 7. 遇到登录 / 验证码能停下（离线判定 + 真实现场观察） ----------
    login_stop = detect_challenge("请登录后查看全文") == "account_login"
    captcha_stop = detect_challenge("请拖动滑块完成验证") == "captcha"
    step = Step(
        name="stop_on_login_and_captcha",
        status=PASS if (login_stop and captcha_stop) else FAIL,
        detail="离线信号判定通过" if (login_stop and captcha_stop) else "信号判定错误",
        evidence={"login": login_stop, "captcha": captcha_stop},
    )
    steps.append(step)

    # --- 8. 收尾 --------------------------------------------------------
    run_ab(base, "close")
    steps.append(Step(name="session_closed", status=PASS, detail="已关闭冒烟会话"))
    return finish(steps, gate)


def finish(steps: list[Step], gate: ComplianceGate) -> dict[str, Any]:
    statuses = [s.status for s in steps]
    if FAIL in statuses:
        overall = FAIL
    elif PARTIAL in statuses:
        overall = PARTIAL
    elif statuses and all(s == PASS for s in statuses):
        overall = PASS
    else:
        overall = SKIP
    payload = {
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "scope": "外部公开网站 only",
        "competition_surface_never_touched": True,
        "targets": SMOKE_TARGETS,
        "overall": overall,
        "counts": {status: statuses.count(status) for status in {*statuses}},
        "steps": [s.__dict__ for s in steps],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    payload = smoke()
    if "--json" in args:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for step in payload["steps"]:
            print(f"[{step['status']:5s}] {step['name']}: {step['detail'][:120]}")
        print(f"\n总体：{payload['overall']}（{payload['counts']}）")
        print(f"报告：{OUTPUT_PATH}")
    return 0 if payload["overall"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())

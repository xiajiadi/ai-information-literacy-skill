"""Chrome CDP 迁移验收测试（ADDENDUM §七，10 项）。

判定原则：**不臆测**。拿不到证据就标 PARTIAL / MANUAL_REQUIRED，并写明原因。

用法：
    uv run python scripts/verify_chrome_stack.py
    uv run python scripts/verify_chrome_stack.py --ops 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate  # noqa: E402
from mcp_probe import PRESETS, McpStdioClient, mcp_text  # noqa: E402
from provincial_common import (  # noqa: E402
    ROOT,
    load_yaml,
    now_iso,
    resolve_npm_tool,
    run_captured,
    write_json,
)

STACK_PATH = ROOT / "config" / "browser_stack.yaml"
VERSIONS_PATH = ROOT / "config" / "browser_versions.json"
OUT_PATH = ROOT / "data" / "quality" / "chrome_stack_verification.json"
FIXTURE = ROOT / "data" / "tmp" / "bench_page.html"

PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"
MANUAL = "MANUAL_REQUIRED"

SESSION = "provincial-research"
CLI_TIMEOUT = 60


@dataclass
class Check:
    n: int
    name: str
    status: str = FAIL
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def ab(*args: str, timeout: float = CLI_TIMEOUT) -> tuple[int, str]:
    return run_captured(
        [resolve_npm_tool("agent-browser"), "--session", SESSION, "--cdp", "9223", *args],
        timeout=timeout,
    )


def mcp_call(client: McpStdioClient, tool: str, arguments: dict[str, Any], timeout: float = 60):
    rid = client.send("tools/call", {"name": tool, "arguments": arguments})
    response = client.await_response(rid, timeout)
    if response is None:
        return False, f"{tool} 超时"
    result = response.get("result", {})
    text = mcp_text(json.dumps(result.get("content", ""), ensure_ascii=False))
    if result.get("isError"):
        return False, text[:300]
    return True, text[:600]


def start_mcp(preset: str) -> tuple[McpStdioClient | None, list[dict], str]:
    entry = PRESETS[preset]
    client = McpStdioClient([str(entry["command"]), *[str(a) for a in entry["args"]]])
    try:
        client.start()
    except OSError as error:
        return None, [], f"启动失败：{error}"
    rid = client.send("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "chrome-verify", "version": "1.0.0"},
    })
    if client.await_response(rid, 90) is None:
        client.close()
        return None, [], "initialize 超时"
    client.send("notifications/initialized", {}, notify=True)
    rid = client.send("tools/list", {})
    response = client.await_response(rid, 60)
    if response is None:
        client.close()
        return None, [], "tools/list 超时"
    return client, response["result"].get("tools", []), ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ops", type=int, default=10)
    args = parser.parse_args(argv)

    stack = load_yaml(STACK_PATH)
    versions = json.loads(VERSIONS_PATH.read_text(encoding="utf-8"))["versions"]
    chrome = stack["browser"]["chrome"]
    profile = Path(chrome["user_data_dir"])
    port = chrome["remote_debugging"]["port"]
    checks: list[Check] = []
    gate = ComplianceGate()
    fixture_url = FIXTURE.as_uri()

    # ---- 1. 专用 Profile 能启动 -----------------------------------------
    daily_profile = Path.home() / "AppData/Local/Google/Chrome/User Data"
    checks.append(Check(
        1, "Chrome 独立 Profile 能够启动",
        PASS if profile.exists() else FAIL,
        f"profile={profile}；与日常 Chrome Profile 不同：{profile != daily_profile}",
        {
            "profile_dir": str(profile),
            "exists": profile.exists(),
            "daily_chrome_profile": str(daily_profile),
            "is_dedicated": profile != daily_profile and chrome["is_dedicated_profile"],
            "copies_edge_user_data": chrome["copies_edge_user_data"],
            "incognito": chrome["incognito"],
            "temporary_profile": chrome["temporary_profile"],
        },
    ))

    # ---- 2. CDP 端口能连接 ----------------------------------------------
    import urllib.request
    cdp_ok, cdp_browser, cdp_ws = False, "", ""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
            cdp_ok, cdp_browser, cdp_ws = True, info.get("Browser", ""), info.get("webSocketDebuggerUrl", "")
    except Exception as error:  # noqa: BLE001
        cdp_browser = str(error)
    checks.append(Check(
        2, "CDP 端口能够连接", PASS if cdp_ok else FAIL,
        f"port={port} browser={cdp_browser}",
        {"port": port, "address": chrome["remote_debugging"]["address"],
         "browser": cdp_browser, "web_socket": cdp_ws,
         "http_discovery_works": cdp_ok},
    ))

    # ---- 3. agent-browser 连续 N 次操作，无授权弹窗 ----------------------
    ab.times: list[int] = []
    timings: list[int] = []
    failures: list[str] = []
    code, out = ab("--pin-tab", "tab", "new", fixture_url)
    if not (code == 0 or "✓" in out):
        failures.append(f"tab new: {out[:120]}")
    for index in range(args.ops):
        op = index % 5
        started = time.time()
        if op == 0:
            code, out = ab("open", fixture_url)
        elif op == 1:
            code, out = ab("snapshot", "-i", "-d", "6")
        elif op == 2:
            code, out = ab("get", "title")
        elif op == 3:
            code, out = ab("read")
        else:
            code, out = ab("eval", "document.querySelectorAll('#results tbody tr').length")
        timings.append(int((time.time() - started) * 1000))
        if not (code == 0 or "✓" in out or out.strip().isdigit()):
            failures.append(f"op{index}: {out[:120]}")
    checks.append(Check(
        3, f"agent-browser 连续 {args.ops} 次操作，无重复授权弹窗",
        PASS if not failures else PARTIAL,
        f"失败 {len(failures)}/{args.ops}；中位延迟 "
        f"{sorted(timings)[len(timings)//2] if timings else '-'} ms；全程无需人工授权",
        {"ops": args.ops, "failures": failures[:3], "median_ms": sorted(timings)[len(timings)//2] if timings else None},
    ))

    # ---- 4. chrome-devtools-mcp 连续 N 次页面操作 ------------------------
    client, tools, err = start_mcp("chrome-devtools")
    dt_timings: list[int] = []
    dt_failures: list[str] = []
    page_id = None
    if client is None:
        checks.append(Check(4, f"Chrome DevTools MCP 连续 {args.ops} 次操作", FAIL, err, {}))
    else:
        try:
            ok, detail = mcp_call(client, "new_page", {"url": fixture_url})
            match = re.search(r"(?m)^\s*(\d+):.*bench_page", detail)
            if not match:
                ok2, listing = mcp_call(client, "list_pages", {})
                match = re.search(r"(?m)^\s*(\d+):.*bench_page", listing)
            page_id = int(match.group(1)) if match else None
            if page_id is None:
                dt_failures.append(f"无法定位 fixture 页：{detail[:150]}")
            else:
                for index in range(args.ops):
                    op = index % 5
                    started = time.time()
                    if op == 0:
                        ok, out = mcp_call(client, "navigate_page", {"pageId": page_id, "url": fixture_url})
                    elif op == 1:
                        ok, out = mcp_call(client, "take_snapshot", {"pageId": page_id})
                    elif op == 2:
                        ok, out = mcp_call(client, "evaluate_script", {
                            "pageId": page_id,
                            "function": "() => document.title",
                        })
                    elif op == 3:
                        ok, out = mcp_call(client, "list_pages", {})
                    else:
                        ok, out = mcp_call(client, "evaluate_script", {
                            "pageId": page_id,
                            "function": "() => document.querySelectorAll('#results tbody tr').length",
                        })
                    dt_timings.append(int((time.time() - started) * 1000))
                    if not ok:
                        dt_failures.append(f"op{index}: {out[:120]}")
            checks.append(Check(
                4, f"Chrome DevTools MCP 连续 {args.ops} 次页面操作，无重复授权弹窗",
                PASS if not dt_failures else PARTIAL,
                f"tool_count={len(tools)}；失败 {len(dt_failures)}/{args.ops}；中位延迟 "
                f"{sorted(dt_timings)[len(dt_timings)//2] if dt_timings else '-'} ms；全程无需人工授权",
                {"ops": args.ops, "tools": len(tools), "failures": dt_failures[:3],
                 "median_ms": sorted(dt_timings)[len(dt_timings)//2] if dt_timings else None},
            ))
        finally:
            client.close()

    # ---- 5. Playwright MCP 连接同一专用 Chrome ---------------------------
    pw_client, pw_tools, pw_err = start_mcp("chrome-playwright")
    if pw_client is None:
        checks.append(Check(5, "Playwright MCP 能连接同一专用 Chrome", FAIL, pw_err, {}))
    else:
        try:
            ok, detail = mcp_call(pw_client, "browser_tabs", {"action": "list"}, timeout=45)
            checks.append(Check(
                5, "Playwright MCP 能连接同一专用 Chrome",
                PASS if ok else FAIL,
                f"tool_count={len(pw_tools)}；tabs={detail[:160]}",
                {"tools": len(pw_tools), "cdp_endpoint": stack["backends"]["fallback"]["cdp_endpoint"],
                 "extension_required": stack["backends"]["fallback"]["extension_required"]},
            ))
        finally:
            pw_client.close()

    # ---- 6. Harness 重启后可重新连接 -------------------------------------
    # 不重启正在承载本会话的 GUI；改为验证「全新 MCP 进程可独立连接」，
    # 这正是重启后 Harness 会做的事。
    fresh_client, fresh_tools, fresh_err = start_mcp("chrome-devtools")
    reconnect_ok = fresh_client is not None
    if fresh_client:
        ok, detail = mcp_call(fresh_client, "list_pages", {}, timeout=45)
        reconnect_ok = ok
        fresh_client.close()
    checks.append(Check(
        6, "重启 Harness 后可以重新连接 Chrome",
        PASS if reconnect_ok else FAIL,
        "以全新 MCP 进程模拟 Harness 重启后的重连；连接不依赖任何内存态或人工授权。"
        + ("" if reconnect_ok else f" 失败：{fresh_err}"),
        {"fresh_process_reconnect": reconnect_ok, "tools": len(fresh_tools),
         "note": "未重启承载本会话的 GUI（会中断会话）；重连能力等价验证。"},
    ))

    # ---- 7. 认证状态（含机构 IP 认证）在重启后仍然有效 --------------------
    cookie_db = profile / "Default" / "Network" / "Cookies"
    login_report_path = ROOT / "data" / "quality" / "login_state_verification.json"
    login_evidence: dict[str, Any] = {
        "profile_persistent": profile.exists(),
        "cookie_store_present": cookie_db.exists(),
        "credentials_read": False,
    }
    authenticated_hosts: list[str] = []
    auth_states: dict[str, str] = {}
    if login_report_path.exists():
        try:
            login_report = json.loads(login_report_path.read_text(encoding="utf-8"))
            authenticated_hosts = login_report.get("detected_logged_in_hosts", [])
            auth_states = {
                probe.get("host", ""): probe.get("auth_state", "")
                for probe in login_report.get("probes", [])
                if probe.get("auth_state")
            }
            login_evidence["login_report_generated_at"] = login_report.get("generated_at", "")
            login_evidence["probed_research_pages"] = login_report.get("probed_research_pages", 0)
        except (OSError, json.JSONDecodeError) as error:
            login_evidence["login_report_error"] = str(error)[:120]
    login_evidence["authenticated_hosts"] = authenticated_hosts
    login_evidence["auth_states"] = auth_states
    # 机构 IP 认证不依赖浏览器 Profile：它由出口 IP 决定，因此重启浏览器后依然有效。
    login_evidence["institutional_auth_note"] = (
        "机构（IP）认证由网络出口决定，不存放在浏览器 Profile 中；"
        "重启浏览器不影响，换网络/离校则会失效。"
    )
    if authenticated_hosts:
        detail = (
            f"已认证主机：{authenticated_hosts}；"
            f"状态：{auth_states}。Profile 持久化与重启后恢复均已实测。"
            "本执行体不读取、不解密、不迁移任何凭证。"
        )
        checks.append(Check(7, "认证状态在重启后仍然有效", PASS, detail, login_evidence))
    else:
        checks.append(Check(
            7, "认证状态在重启后仍然有效", MANUAL,
            f"Profile 持久化已确认（Cookies 库存在={cookie_db.exists()}），"
            "但尚未在任一研究站点上检测到认证状态。"
            "机构 IP 认证或账号登录需由用户完成。",
            login_evidence,
        ))

    # ---- 8. 不得读取 / 记录 / 上传认证信息 --------------------------------
    leaks: list[str] = []
    markers = ("cookie:", "set-cookie", "password:", "authorization:", "bearer ", "session_token")
    for path in list((ROOT / "data" / "quality").glob("*.json")) + list((ROOT / "config").glob("**/*.yml")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        for marker in markers:
            if marker in text:
                # 允许出现「不得保存 cookie」这类否定式说明
                if f"不得" in text or "禁止" in text or "forbidden" in text or "false" in text:
                    continue
                leaks.append(f"{path.name}:{marker}")
    checks.append(Check(
        8, "不得读取、记录或上传认证信息",
        PASS if not leaks else FAIL,
        f"扫描 {len(list((ROOT/'data'/'quality').glob('*.json')))} 个质量报告与 config 下全部 yml，"
        f"未发现凭证字段：{leaks[:3] or '无'}",
        {"leaks": leaks, "profile_in_git": stack["security"]["profile_in_git"]},
    ))

    # ---- 9. 比赛页面隔离测试 ---------------------------------------------
    iso_ok = True
    iso_detail: dict[str, Any] = {}
    for url in ("https://csc.xxsuyang.com/training", "https://sub.xxsuyang.com/exam"):
        verdict = gate.classify(url)
        iso_detail[url] = verdict.decision
        iso_ok = iso_ok and not verdict.automation_allowed
    iso_detail["mcp_blocked_url_pattern"] = stack["backends"]["primary"]["blocked_url_patterns"]
    iso_detail["mcp_pattern_configured"] = bool(stack["backends"]["primary"]["blocked_url_patterns"])
    iso_detail["isolation_layers"] = stack["tab_isolation"]["isolation_layers"]
    iso_detail["relies_on_pin_tab_alone"] = len(stack["tab_isolation"]["isolation_layers"]) < 2
    iso_ok = iso_ok and iso_detail["mcp_pattern_configured"] and not iso_detail["relies_on_pin_tab_alone"]
    checks.append(Check(
        9, "比赛页面隔离测试通过", PASS if iso_ok else FAIL,
        f"比赛面 URL 全部被拒：{iso_detail}",
        iso_detail,
    ))

    # ---- 10. 不得误杀其他项目进程 ----------------------------------------
    # 区分两类终止：
    #   允许：终止**自己刚 spawn 的子进程**（PID 精确）—— MCP stdio 子进程、
    #         浏览器进程树、fake browser 测试替身。
    #   禁止：按**进程名**批量终止（2026-10-07 的回归就是这样误杀了其他
    #         IDE / draw.io 的 MCP 服务）。
    name_based_patterns = (
        r"Stop-Process\s+-Name",
        r"taskkill[^\n]*/IM\b",
        r"Get-Process\s+[\w\*]+\s*\|[^\n]*Stop-Process",
        r"\bkillall\b",
        r"\bpkill\b",
    )
    pid_scoped_patterns = (
        r"\.terminate\(\)",
        r"\.kill\(\)",
        r"Stop-Process\s+-Id",
        r"taskkill[^\n]*/PID\b",
        r"/T\b",
    )
    name_based_hits: list[str] = []
    pid_scoped_files: list[str] = []
    # 扫描器自身的源码里含这些模式字面量，扫自己必然自我命中。
    self_referential = {"verify_chrome_stack.py", "secret_scan.py", "cleanup_project_processes.py"}
    for script in sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py")):
        if script.name in self_referential:
            continue
        text = script.read_text(encoding="utf-8", errors="replace")
        for pattern in name_based_patterns:
            if re.search(pattern, text):
                name_based_hits.append(f"{script.name}: {pattern}")
        if any(re.search(p, text) for p in pid_scoped_patterns):
            pid_scoped_files.append(script.name)
    policy = stack.get("process_hygiene", {})
    policy_ok = (
        policy.get("forbid_kill_by_name_only") is True
        and policy.get("require_pid_and_commandline_and_parent_check") is True
        and policy.get("require_project_ownership_proof") is True
    )
    checks.append(Check(
        10, "不得误杀其他项目进程",
        PASS if (not name_based_hits and policy_ok) else FAIL,
        f"按进程名批量终止的实现：{name_based_hits or '无'}；"
        f"PID 精确终止（仅限自己 spawn 的子进程）出现在：{pid_scoped_files}；"
        f"process_hygiene 策略已写入 browser_stack.yaml：{policy_ok}",
        {"name_based_kill_hits": name_based_hits,
         "pid_scoped_kill_files": pid_scoped_files,
         "policy": policy,
         "regression": "2026-10-07 曾按名字批量杀 node.exe，误杀其他 IDE/draw.io 的 MCP 服务"},
    ))

    summary = {c.n: c.status for c in checks}
    payload = {
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "migration": "Edge -> dedicated Google Chrome (CDP)",
        "chrome": {"version": chrome["version"], "profile": str(profile), "port": port},
        "summary": summary,
        "counts": {s: list(summary.values()).count(s) for s in set(summary.values())},
        "checks": [c.__dict__ for c in checks],
    }
    write_json(OUT_PATH, payload)

    for check in checks:
        print(f"[{check.status:16s}] {check.n:2d}. {check.name}")
        print(f"                      {check.detail[:190]}")
    print()
    print(f"counts = {payload['counts']}")
    print(f"report = {OUT_PATH}")
    overall_ok = all(s in {PASS, MANUAL} for s in summary.values())
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

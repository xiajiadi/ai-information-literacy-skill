"""一键启动 / 恢复 Research 浏览器（§25）。

原则：
  - **不关闭现有 Edge**，不重启浏览器，不动用户 Profile。
  - 不打开比赛页面。
  - Edge 未开启 Remote Debugging 时，退化为 agent-browser 独立会话，
    并明确报告「与用户 Edge 登录态隔离」，绝不假装登录态可用。

输出末尾必须是 RESEARCH_BROWSER_READY 或 ACTION_REQUIRED。

用法：
    uv run python scripts/start_research_browser.py
    uv run python scripts/start_research_browser.py --session provincial-research
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_router import BrowserTask, BackendRouter, load_browser_stack  # noqa: E402
from compliance_gate import ComplianceGate  # noqa: E402
from provincial_common import (  # noqa: E402
    ROOT,
    load_yaml,
    now_iso,
    run_captured,
    write_json,
)

STACK_PATH = ROOT / "config" / "browser_stack.yaml"
HEALTH_PATH = ROOT / "data" / "quality" / "browser_stack_health.json"
STATE_PATH = ROOT / "data" / "quality" / "research_browser_state.json"

READY = "RESEARCH_BROWSER_READY"
ACTION = "ACTION_REQUIRED"
BLOCKED = "BLOCKED"

# 只用于占位 Research Tab 的安全公开页；不是比赛面。
RESEARCH_HOME = "https://example.com/"

DEFAULT_SESSION = "provincial-research"
COMMAND_TIMEOUT = 60


def run(cmd: list[str], timeout: int = COMMAND_TIMEOUT) -> tuple[int, str]:
    # 见 provincial_common.run_captured 的说明：agent-browser 有常驻 daemon，
    # 用管道捕获会一直阻塞到超时。
    return run_captured(cmd, timeout=timeout)


def read_devtools_port(stack: dict[str, Any]) -> int | None:
    path = Path(stack["browser"]["edge"]["devtools_active_port_file"])
    if not path.exists():
        return None
    try:
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        return int(first.strip())
    except (OSError, ValueError, IndexError):
        return None


def load_health() -> dict[str, Any]:
    if HEALTH_PATH.exists():
        try:
            return json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    session = DEFAULT_SESSION
    if "--session" in args:
        index = args.index("--session")
        session = args[index + 1] if index + 1 < len(args) else DEFAULT_SESSION

    stack = load_browser_stack()
    gate = ComplianceGate()
    steps: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str, **extra: Any) -> None:
        steps.append({"name": name, "status": status, "detail": detail, **extra})

    # 1. Edge 是否在运行（不重启它）
    edge_exe = Path(stack["browser"]["edge"]["executable"])
    code, out = run([
        "powershell", "-NoProfile", "-Command",
        "(Get-Process msedge -ErrorAction SilentlyContinue | Measure-Object).Count",
    ])
    edge_count = 0
    try:
        edge_count = int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        edge_count = 0
    step(
        "edge_running", "PASS" if edge_count > 0 else "FAIL",
        f"{edge_count} 个 msedge 进程（不重启、不关闭现有 Edge）",
        edge_count=edge_count, executable=str(edge_exe),
    )

    # 2. Remote Debugging
    port = read_devtools_port(stack)
    step(
        "remote_debugging", "PASS" if port else "FAIL",
        f"DevToolsActivePort 端口 {port}" if port
        else "未开启 Remote Debugging（DevToolsActivePort 不存在）",
        port=port,
    )

    # 3. MCP readiness（读最近一次健康检查，避免重复联网）
    health = load_health()
    summary = health.get("summary", {})
    step(
        "mcp_readiness", "PASS" if health else "UNKNOWN",
        json.dumps(summary, ensure_ascii=False) if summary else "尚无健康检查报告",
        health_generated_at=health.get("generated_at", ""),
    )

    # 4. 合规：Research Home 必须是研究面
    verdict = gate.classify(RESEARCH_HOME)
    if not verdict.automation_allowed:
        step("compliance", "FAIL", f"{RESEARCH_HOME} 未通过合规闸门：{verdict.reason}")
        payload = finish(BLOCKED, steps, session, None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    step("compliance", "PASS", f"{RESEARCH_HOME} 属于研究面，可用于占位 Research Tab")

    # 5. 绑定并固定 Research Tab
    ab = shutil.which("agent-browser")
    if not ab:
        step("agent_browser", "FAIL", "PATH 上找不到 agent-browser")
        payload = finish(ACTION, steps, session, None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    base = [ab, "--session", session, "--pin-tab"]
    if port:
        base = [ab, "--session", session, "--pin-tab", "--cdp", str(port)]
        step(
            "attach_mode", "PASS",
            f"通过 CDP {port} 连接用户正在运行的 Edge（复用其登录态）",
            cdp_port=port,
        )
    else:
        step(
            "attach_mode", "PARTIAL",
            "Edge 未开启 Remote Debugging；本轮使用 agent-browser 独立会话。"
            "该会话**不带**用户 Edge 的登录态，受控平台仍需人工交接。",
            cdp_port=None,
        )

    code, out = run([*base, "open", RESEARCH_HOME])
    step(
        "research_tab_created", "PASS" if code == 0 else "FAIL",
        out[:300], returncode=code,
    )
    if code != 0:
        payload = finish(ACTION, steps, session, port)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    code, tabs = run([ab, "--session", session, "tab", "list"])
    step("tab_list", "PASS" if code == 0 else "PARTIAL", tabs[:400], returncode=code)

    code, url = run([ab, "--session", session, "get", "url"])
    step("pinned_tab_url", "PASS" if code == 0 else "PARTIAL", url[:200], returncode=code)

    # 6. Tab 隔离守卫自检
    router = BackendRouter(stack=stack, gate=gate)
    decision = router.check_tab(RESEARCH_HOME, tab_name="Research-1")
    step(
        "tab_isolation_guard", "PASS" if decision.backend == "AGENT_BROWSER" else "FAIL",
        decision.reason,
    )
    competition_probe = router.check_tab("https://csc.xxsuyang.com/training")
    step(
        "competition_tab_protected",
        "PASS" if competition_probe.backend == "BLOCKED_COMPETITION" else "FAIL",
        competition_probe.reason,
    )
    simple = router.decide(BrowserTask(kind="READ_COUNT", url=RESEARCH_HOME))
    step("router_simple_task", simple.backend, simple.reason)

    state = READY if port else ACTION
    payload = finish(state, steps, session, port)
    payload["note"] = (
        "Edge Remote Debugging 已开启，PRIMARY 路线可用。"
        if port else
        "Edge Remote Debugging 未开启：FAST CLI 独立会话可用，"
        "PRIMARY（Chrome DevTools MCP over 用户 Edge）与复用登录态不可用。"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()
    print(state)
    return 0 if state == READY else 1


def finish(state: str, steps: list[dict[str, Any]], session: str, port: int | None) -> dict[str, Any]:
    payload = {
        "generated_at": now_iso(),
        "state": state,
        "session": session,
        "cdp_port": port,
        "edge_restarted": False,
        "competition_page_opened": False,
        "steps": steps,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(STATE_PATH, payload)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())

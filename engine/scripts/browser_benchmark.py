"""浏览器后端 Benchmark（§20）。

对三条路线分别测量同一组典型动作：

    agent-browser / chrome-devtools-mcp / playwright-mcp

每个动作至少 3 次，记录 startup_ms / navigation_ms / interaction_ms /
snapshot_ms / total_ms / success / failure_reason，最终给出

    FAST_DEFAULT / PRIMARY_FULL / FALLBACK

的选型建议。

测试目标只用**本地 fixture 页**与**公开简单网页**，不请求真实数据库，
避免触发风控（§21）。

产出：data/quality/browser_backend_benchmark.json

用法：
    uv run python scripts/browser_benchmark.py --backends agent-browser
    uv run python scripts/browser_benchmark.py --backends all --repeat 3
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_probe import PRESETS, McpStdioClient  # noqa: E402
from provincial_common import (  # noqa: E402
    ROOT,
    now_iso,
    resolve_npm_tool,
    run_captured,
    write_json,
)

BENCH_PATH = ROOT / "data" / "quality" / "browser_backend_benchmark.json"
FIXTURE = ROOT / "data" / "tmp" / "bench_page.html"
PUBLIC_SIMPLE = "https://example.com/"

# 通过本机临时 HTTP 提供 fixture，而不是 file://。
#
# 原因（实测）：Playwright MCP 默认**阻止 file: 协议导航**
# （"Access to \"file:\" protocol is blocked"）。用 http://127.0.0.1 既避开该限制，
# 又不必打开 --allow-unrestricted-file-access 而削弱文件隔离；同时更贴近真实
# 检索场景（外部页面都是 https/http，而不是本地文件）。
FIXTURE_URL = ""  # 由 main() 在启动临时服务器后赋值

AGENT_BROWSER = "agent-browser"
EDGE_DEVTOOLS_MCP = "chrome-devtools-mcp"
EDGE_PLAYWRIGHT_MCP = "playwright-mcp"
ALL_BACKENDS = [AGENT_BROWSER, EDGE_DEVTOOLS_MCP, EDGE_PLAYWRIGHT_MCP]

SESSION = "provincial-benchmark"
CLI_TIMEOUT = 60
MCP_TIMEOUT = 60


@dataclass
class Measurement:
    backend: str
    action: str
    iteration: int
    success: bool
    total_ms: int
    detail: str = ""
    failure_reason: str = ""


@dataclass
class BackendReport:
    backend: str
    startup_ms: int = 0
    tool_ready_ms: int = 0
    tool_count: int = 0
    available: bool = False
    failure_reason: str = ""
    measurements: list[Measurement] = field(default_factory=list)

    def medians(self) -> dict[str, int]:
        buckets: dict[str, list[int]] = {}
        for item in self.measurements:
            if item.success:
                buckets.setdefault(item.action, []).append(item.total_ms)
        return {
            action: int(statistics.median(values))
            for action, values in buckets.items()
            if values
        }

    def success_rate(self) -> float:
        if not self.measurements:
            return 0.0
        return sum(1 for m in self.measurements if m.success) / len(self.measurements)


# ---------------------------------------------------------------------------
# agent-browser（FAST CLI）
# ---------------------------------------------------------------------------

def agent_browser_ops() -> dict[str, Callable[[], tuple[bool, str]]]:
    wrapper = resolve_npm_tool("agent-browser")
    base = [wrapper, "--session", SESSION, "--pin-tab"]
    fixture_url = FIXTURE_URL or FIXTURE.as_uri()

    def cli(*args: str) -> tuple[int, str]:
        return run_captured([*base, *args], timeout=CLI_TIMEOUT)

    def op_open() -> tuple[bool, str]:
        code, out = cli("open", fixture_url)
        return code == 0, out[:200]

    def op_snapshot() -> tuple[bool, str]:
        code, out = cli("snapshot", "-i", "-d", "6")
        return code == 0 and "textbox" in out, out[:200]

    def op_fill() -> tuple[bool, str]:
        _, snapshot = cli("snapshot", "-i", "-d", "6")
        ref = ""
        for line in snapshot.splitlines():
            if "textbox" in line and "ref=" in line:
                ref = "@" + line.split("ref=")[-1].split("]")[0].strip()
                break
        if not ref:
            return False, "未找到 textbox ref"
        code, out = cli("fill", ref, "信息素养")
        return code == 0, out[:200]

    def op_click() -> tuple[bool, str]:
        _, snapshot = cli("snapshot", "-i", "-d", "6")
        ref = ""
        for line in snapshot.splitlines():
            if "button" in line and "检索" in line and "ref=" in line:
                ref = "@" + line.split("ref=")[-1].split("]")[0].strip()
                break
        if not ref:
            return False, "未找到按钮 ref"
        code, out = cli("click", ref)
        return code == 0, out[:200]

    def op_read_result() -> tuple[bool, str]:
        code, out = cli("get", "text", "#total")
        return code == 0 and "结果总数" in out, out[:200]

    def op_switch_tab() -> tuple[bool, str]:
        code, out = cli("open", PUBLIC_SIMPLE)
        if code != 0:
            return False, out[:200]
        code2, tabs = cli("tab", "list")
        return code2 == 0 and "example.com" in tabs, tabs[:200]

    def op_extract_table() -> tuple[bool, str]:
        code, out = cli("eval", "document.querySelectorAll('#results tbody tr').length")
        return code == 0 and "3" in out, out[:200]

    return {
        "open": op_open,
        "snapshot": op_snapshot,
        "fill": op_fill,
        "click": op_click,
        "read_result": op_read_result,
        "extract_table": op_extract_table,
        # switch_tab 会离开 fixture 页，必须放在最后。
        "switch_tab": op_switch_tab,
    }


# ---------------------------------------------------------------------------
# MCP 后端
# ---------------------------------------------------------------------------

def pick_tool(tools: list[dict[str, Any]], patterns: list[str]) -> str:
    """按名称子串挑选工具，兼容不同版本的工具命名。"""
    names = [t.get("name", "") for t in tools]
    for pattern in patterns:
        for name in names:
            if name == pattern:
                return name
    for pattern in patterns:
        for name in names:
            if pattern in name:
                return name
    return ""


class _QuietHandler(SimpleHTTPRequestHandler):
    """只服务 data/tmp 目录，且不打印访问日志。"""

    def log_message(self, *args: Any) -> None:  # noqa: D102
        return


def serve_fixture() -> dict[str, Any]:
    """在 127.0.0.1 的临时端口上提供 data/tmp，返回 fixture 的 http URL。

    为什么不用 file://：Playwright MCP 默认阻止 file: 协议导航
    （实测报 "Access to \"file:\" protocol is blocked"）。走本机 HTTP 既避开该
    限制，也不必打开 --allow-unrestricted-file-access 去削弱文件隔离。
    只绑定 127.0.0.1，且随 benchmark 结束关闭。
    """
    from functools import partial
    from http.server import ThreadingHTTPServer

    handler = partial(_QuietHandler, directory=str(FIXTURE.parent))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return {
        "url": f"http://127.0.0.1:{port}/{FIXTURE.name}",
        "port": port,
        "shutdown": httpd.shutdown,
    }


def mcp_text(result_text: str) -> str:
    """把 tools/call 的结果还原成纯文本，便于解析。

    MCP 返回的是 content 块数组；直接 json.dumps 会把换行转义成 \\n，
    让 '## Pages\\n1: …' 这类文本变成一行，正则也随之失效。
    """
    if not result_text:
        return ""
    try:
        parsed = json.loads(result_text)
    except (TypeError, ValueError):
        return result_text
    if isinstance(parsed, list):
        parts = []
        for block in parsed:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts)
    return result_text


def mcp_call(
    client: McpStdioClient, tool: str, arguments: dict[str, Any]
) -> tuple[bool, str]:
    if not tool:
        return False, "工具不存在"
    request_id = client.send("tools/call", {"name": tool, "arguments": arguments})
    response = client.await_response(request_id, MCP_TIMEOUT)
    if response is None:
        return False, f"{tool} 超时"
    if "error" in response:
        return False, json.dumps(response["error"], ensure_ascii=False)[:300]
    result = response.get("result", {})
    text = mcp_text(json.dumps(result.get("content", ""), ensure_ascii=False))
    if result.get("isError"):
        return False, text[:300] or "isError"
    return True, text[:600]


def attach_probe(
    preset: str, tools: list[dict[str, Any]], client: McpStdioClient
) -> tuple[bool, str]:
    """真正的连通性预检：列出页面。

    Edge 未开 Remote Debugging 时这里会给出明确原因
    （ENOENT: ... DevToolsActivePort）。扩展缺失时也会给出明确原因。
    """
    list_pages = pick_tool(tools, ["list_pages"])
    if list_pages:
        return mcp_call(client, list_pages, {})
    tabs = pick_tool(tools, ["browser_tabs"])
    if tabs:
        return mcp_call(client, tabs, {"action": "list"})
    return False, "没有可用于连通性预检的工具"


def extract_uid(snapshot_text: str, role: str = "") -> str:
    """从 snapshot 文本里取元素 uid / ref。

    chrome-devtools-mcp 的 take_snapshot 输出形如 `uid=1_2 textbox "检索词"`；
    Playwright MCP 的 browser_snapshot 输出形如 `- textbox "检索词" [ref=e2]`。
    """
    if not snapshot_text:
        return ""
    lines = snapshot_text.splitlines()
    for pattern in (r"uid=([0-9_]+)", r"\[ref=([^\]]+)\]"):
        for line in lines:
            if role and role.lower() not in line.lower():
                continue
            match = re.search(pattern, line)
            if match:
                return match.group(1)
    return ""


def extract_page_id(result_text: str, url_marker: str = "") -> int | None:
    """从 list_pages / new_page 的文本里取 pageId。

    文本形如：
        ## Pages
        1: 新建标签页 (chrome-search://local-ntp/local-ntp.html)
        2: Provincial Benchmark Fixture (file:///D:/.../bench_page.html)

    **只在 URL 命中 url_marker 时才返回**，这样绝不会选中用户自己打开的标签页。
    """
    if not result_text:
        return None
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"(?m)^\s*(\d+):\s*(.*)$", result_text):
        candidates.append((int(match.group(1)), match.group(2)))
    if not candidates:
        match = re.search(r'"id"\s*:\s*(\d+)', result_text)
        return int(match.group(1)) if match else None
    if url_marker:
        marker = url_marker.lower()
        for page_id, line in candidates:
            if marker in line.lower():
                return page_id
        return None
    return candidates[0][0]


def mcp_ops(
    preset: str, client: McpStdioClient, tools: list[dict[str, Any]]
) -> dict[str, Callable[[], tuple[bool, str]]]:
    """构造 MCP 操作集。

    安全约束：**一律新建自己的 Research 页**，绝不复用用户已经打开的标签页。
    """
    fixture_url = FIXTURE_URL or FIXTURE.as_uri()
    is_devtools = preset == "chrome-devtools"

    def call(tool: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        return mcp_call(client, tool, arguments)

    nav = pick_tool(tools, ["navigate_page", "browser_navigate"])
    snap = pick_tool(tools, ["take_snapshot", "browser_snapshot"])
    fill = pick_tool(tools, ["fill", "browser_type"])
    click = pick_tool(tools, ["click", "browser_click"])
    evaluate = pick_tool(tools, ["evaluate_script", "browser_evaluate"])
    new_page = pick_tool(tools, ["new_page", "browser_tabs"])
    close_page = pick_tool(tools, ["close_page"])

    state: dict[str, Any] = {"page_id": None, "snapshot_text": ""}
    list_pages_tool = pick_tool(tools, ["list_pages"])
    FIXTURE_MARKER = "bench_page"

    def ensure_page() -> tuple[bool, str]:
        """确保有一个只属于 benchmark 的 Research 页。

        只用 URL 命中 fixture 的页；绝不选用户自己打开的标签页。
        """
        if state["page_id"] is not None:
            return True, str(state["page_id"])
        if is_devtools:
            ok, detail = call(new_page, {"url": fixture_url})
            if not ok:
                return False, detail
            probe_ok, probe = call(list_pages_tool, {})
            source = probe if probe_ok else detail
            page_id = extract_page_id(source, FIXTURE_MARKER)
            if page_id is None and probe_ok:
                page_id = extract_page_id(detail, FIXTURE_MARKER)
            if page_id is None:
                return False, f"无法确定 fixture 页的 pageId：{source[:200]}"
            state["page_id"] = page_id
            return True, detail
        # Playwright MCP：browser_tabs 必须带 action
        ok, detail = call(new_page, {"action": "new", "url": fixture_url})
        return ok, detail

    def op_open() -> tuple[bool, str]:
        ready, detail = ensure_page()
        if not ready:
            return False, detail
        if is_devtools:
            return call(nav, {"pageId": state["page_id"], "url": fixture_url})
        return call(nav, {"url": fixture_url})

    def op_snapshot() -> tuple[bool, str]:
        arguments = {"pageId": state["page_id"]} if is_devtools else {}
        ok, detail = call(snap, arguments)
        state["snapshot_text"] = detail
        return ok, detail

    def op_fill() -> tuple[bool, str]:
        uid = extract_uid(state["snapshot_text"], "textbox")
        if not uid:
            return False, "快照里没有 textbox"
        if is_devtools:
            return call(fill, {"pageId": state["page_id"], "uid": uid, "value": "信息素养"})
        # Playwright MCP 的 browser_type 必填 target + text（见其 inputSchema），
        # **不是** DevTools 的 uid/value。
        return call(fill, {"target": uid, "text": "信息素养", "element": "检索词输入框"})

    def op_click() -> tuple[bool, str]:
        uid = extract_uid(state["snapshot_text"], "button")
        if not uid:
            return False, "快照里没有 button"
        if is_devtools:
            return call(click, {"pageId": state["page_id"], "uid": uid})
        # Playwright MCP 的 browser_click 必填 target。
        return call(click, {"target": uid, "element": "检索按钮"})

    def op_read_result() -> tuple[bool, str]:
        expression = "() => document.getElementById('total').textContent"
        if is_devtools:
            return call(evaluate, {"pageId": state["page_id"], "function": expression})
        return call(evaluate, {"function": expression})

    def op_extract_table() -> tuple[bool, str]:
        expression = "() => document.querySelectorAll('#results tbody tr').length"
        if is_devtools:
            return call(evaluate, {"pageId": state["page_id"], "function": expression})
        return call(evaluate, {"function": expression})

    def op_switch_tab() -> tuple[bool, str]:
        if is_devtools:
            ok, detail = call(new_page, {"url": PUBLIC_SIMPLE})
            if not ok:
                return False, detail
            probe_ok, probe = call(list_pages_tool, {})
            source = probe if probe_ok else detail
            return extract_page_id(source, "example.com") is not None, source
        ok, detail = call(new_page, {"action": "new", "url": PUBLIC_SIMPLE})
        return ok, detail

    def op_close() -> tuple[bool, str]:
        if is_devtools and state["page_id"] is not None and close_page:
            return call(close_page, {"pageId": state["page_id"]})
        return True, "skip"

    return {
        "open": op_open,
        "snapshot": op_snapshot,
        "fill": op_fill,
        "click": op_click,
        "read_result": op_read_result,
        "extract_table": op_extract_table,
        # switch_tab 会离开 fixture 页，必须放在最后。
        "switch_tab": op_switch_tab,
    }, op_close


def bench_agent_browser(repeat: int) -> BackendReport:
    report = BackendReport(backend=AGENT_BROWSER)
    started = time.time()
    code, out = run_captured(
        [resolve_npm_tool("agent-browser"), "--session", SESSION, "open",
         FIXTURE_URL or FIXTURE.as_uri()],
        timeout=CLI_TIMEOUT,
    )
    report.startup_ms = int((time.time() - started) * 1000)
    if code != 0:
        report.failure_reason = out[:300]
        return report
    report.available = True
    report.tool_count = 0  # CLI，无 tool schema

    ops = agent_browser_ops()
    for iteration in range(1, repeat + 1):
        for action, operation in ops.items():
            started_at = time.time()
            try:
                ok, detail = operation()
                reason = "" if ok else detail
            except Exception as error:  # noqa: BLE001 - benchmark 不应因单步崩溃而中止
                ok, detail, reason = False, "", f"{type(error).__name__}: {error}"
            report.measurements.append(
                Measurement(
                    backend=AGENT_BROWSER,
                    action=action,
                    iteration=iteration,
                    success=ok,
                    total_ms=int((time.time() - started_at) * 1000),
                    detail=detail,
                    failure_reason=reason,
                )
            )
    run_captured(
        [resolve_npm_tool("agent-browser"), "--session", SESSION, "close"],
        timeout=30,
    )
    return report


def bench_mcp(preset: str, backend_name: str, repeat: int) -> BackendReport:
    report = BackendReport(backend=backend_name)
    entry = PRESETS[preset]
    command = [str(entry["command"]), *[str(a) for a in entry["args"]]]
    client = McpStdioClient(command)
    started = time.time()
    try:
        client.start()
    except OSError as error:
        report.failure_reason = f"无法启动：{error}"
        return report
    try:
        request_id = client.send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "provincial-benchmark", "version": "1.0.0"},
            },
        )
        response = client.await_response(request_id, MCP_TIMEOUT)
        report.startup_ms = int((time.time() - started) * 1000)
        if response is None or "error" in (response or {}):
            report.failure_reason = (
                "initialize 失败："
                + json.dumps((response or {}).get("error") or "timeout", ensure_ascii=False)[:200]
            )
            return report
        client.send("notifications/initialized", {}, notify=True)

        tools_started = time.time()
        tools_id = client.send("tools/list", {})
        tools_response = client.await_response(tools_id, MCP_TIMEOUT)
        report.tool_ready_ms = int((time.time() - tools_started) * 1000)
        if tools_response is None or "error" in (tools_response or {}):
            report.failure_reason = "tools/list 失败"
            return report
        tools = tools_response["result"].get("tools", [])
        report.tool_count = len(tools)

        ops, cleanup = mcp_ops(preset, client, tools)
        # 连通性预检：能列出页面才算可用
        probe_ok, probe_detail = attach_probe(preset, tools, client)
        if not probe_ok:
            report.failure_reason = f"attach 预检失败：{probe_detail[:250]}"
            return report
        report.available = True

        for iteration in range(1, repeat + 1):
            for action, operation in ops.items():
                started_at = time.time()
                try:
                    ok, detail = operation()
                    reason = "" if ok else detail
                except Exception as error:  # noqa: BLE001
                    ok, detail, reason = False, "", f"{type(error).__name__}: {error}"
                report.measurements.append(
                    Measurement(
                        backend=backend_name,
                        action=action,
                        iteration=iteration,
                        success=ok,
                        total_ms=int((time.time() - started_at) * 1000),
                        detail=detail,
                        failure_reason=reason,
                    )
                )
        try:
            cleanup()
        except Exception:  # noqa: BLE001 - 收尾失败不影响报告
            pass
        return report
    finally:
        client.close()


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def recommendation(reports: list[BackendReport]) -> dict[str, str]:
    by_name = {r.backend: r for r in reports}
    fast = by_name.get(AGENT_BROWSER)
    primary = by_name.get(EDGE_DEVTOOLS_MCP)
    fallback = by_name.get(EDGE_PLAYWRIGHT_MCP)
    return {
        "FAST_DEFAULT": (
            f"{AGENT_BROWSER}（可用={fast.available}）" if fast else AGENT_BROWSER
        ),
        "PRIMARY_FULL": (
            f"{EDGE_DEVTOOLS_MCP}（可用={primary.available}）" if primary else EDGE_DEVTOOLS_MCP
        ),
        "FALLBACK": (
            f"{EDGE_PLAYWRIGHT_MCP}（可用={fallback.available}）"
            if fallback
            else EDGE_PLAYWRIGHT_MCP
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    repeat = 3
    if "--repeat" in args:
        index = args.index("--repeat")
        try:
            repeat = max(1, int(args[index + 1]))
        except (IndexError, ValueError):
            repeat = 3

    targets = ALL_BACKENDS
    if "--backends" in args:
        index = args.index("--backends")
        value = args[index + 1] if index + 1 < len(args) else "all"
        targets = ALL_BACKENDS if value == "all" else [
            b for b in value.split(",") if b in ALL_BACKENDS
        ]

    if not FIXTURE.exists():
        print(f"缺少本地 fixture：{FIXTURE}", file=sys.stderr)
        return 2

    # 用本机临时 HTTP 提供 fixture（Playwright MCP 默认阻止 file: 协议）。
    global FIXTURE_URL
    server = serve_fixture()
    FIXTURE_URL = server["url"]
    print(f"fixture served at {FIXTURE_URL}", file=sys.stderr)

    reports: list[BackendReport] = []
    try:
        if AGENT_BROWSER in targets:
            reports.append(bench_agent_browser(repeat))
        if EDGE_DEVTOOLS_MCP in targets:
            reports.append(bench_mcp("chrome-devtools", EDGE_DEVTOOLS_MCP, repeat))
        if EDGE_PLAYWRIGHT_MCP in targets:
            reports.append(bench_mcp("chrome-playwright", EDGE_PLAYWRIGHT_MCP, repeat))
    finally:
        server["shutdown"]()

    payload = {
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "repeat": repeat,
        "fixture": str(FIXTURE),
        "public_simple_page": PUBLIC_SIMPLE,
        "policy": "只用本地 fixture 与公开简单网页；不请求真实数据库，不触发风控。",
        "backends": [
            {
                "backend": r.backend,
                "available": r.available,
                "startup_ms": r.startup_ms,
                "tool_ready_ms": r.tool_ready_ms,
                "tool_count": r.tool_count,
                "success_rate": round(r.success_rate(), 3),
                "median_ms": r.medians(),
                "failure_reason": r.failure_reason,
                "measurements": [m.__dict__ for m in r.measurements],
            }
            for r in reports
        ],
        "recommendation": recommendation(reports),
    }
    write_json(BENCH_PATH, payload)

    for report in reports:
        print(f"[{report.backend}] available={report.available} tools={report.tool_count} "
              f"startup={report.startup_ms}ms success={report.success_rate():.2f}")
        if report.failure_reason:
            print(f"    failure: {report.failure_reason[:200]}")
        for action, ms in report.medians().items():
            print(f"    {action:16s} median {ms:6d} ms")
    print()
    print(json.dumps(payload["recommendation"], ensure_ascii=False, indent=2))
    print(f"report = {BENCH_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

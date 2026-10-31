"""独立的 MCP stdio 探针（用于 Smoke Test A / B / E 与 benchmark 计时）。

为什么需要它：`@deepseek-ai/dsh-mcp-client` 只在 DSH **启动时**把 MCP 工具注册到
`ctx.tools`，所以当前会话看不到新装的 MCP 工具。本脚本用最小 JSON-RPC 客户端
直接跟 MCP server 说话，从而在**不重启 Harness** 的前提下验证：

    - server 能否启动（initialize）
    - 暴露了哪些 tool（tools/list）
    - 能否真的调用一个 tool（tools/call），例如列出 Edge 页面

它不读写任何凭证，也不碰比赛面。

用法：
    uv run python scripts/mcp_probe.py --preset edge-devtools --list-tools
    uv run python scripts/mcp_probe.py --preset edge-devtools --call list_pages
    uv run python scripts/mcp_probe.py --command npx --arg -y --arg pkg@1.0 --list-tools
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    ROOT,
    load_json,
    now_iso,
    resolve_npm_tool,
    write_json,
)

VERSIONS_PATH = ROOT / "config" / "browser_versions.json"
BENCH_DIR = ROOT / "data" / "quality"

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "provincial-mcp-probe", "version": "1.0.0"}

NPX = resolve_npm_tool("npx")

# 专用研究 Chrome 的 CDP 端点（见 scripts/start_research_chrome.py）。
CHROME_CDP_PORT = 9223
CHROME_CDP_URL = f"http://127.0.0.1:{CHROME_CDP_PORT}"

# 与 config/browser_stack.yaml 的 backends 保持一致。
#
# 2026-10-08 迁移：研究浏览器从 Microsoft Edge 改为**专用 Google Chrome**
# （独立 User Data，--remote-debugging-port，不会反复弹授权）。
# Edge 预设保留用于回滚，但已不是默认路线。
PRESETS: dict[str, dict[str, Any]] = {
    "chrome-devtools": {
        "command": NPX,
        "args": [
            "-y", "chrome-devtools-mcp@1.10.1",
            # 用 --browser-url 而不是 --autoConnect：
            # --autoConnect 依赖 Edge 的 edge://inspect 开关，会反复弹授权，
            # 且其 CDP HTTP 发现端点是 404。
            f"--browser-url={CHROME_CDP_URL}",
            "--no-usage-statistics",
            "--no-category-performance",
            "--no-category-memory",
            "--no-category-emulation",
            "--blockedUrlPattern=*://*.xxsuyang.com/*",
            "--blockedUrlPattern=*://xxsuyang.com/*",
        ],
    },
    "chrome-playwright": {
        "command": NPX,
        "args": [
            "-y", "@playwright/mcp@0.0.83",
            # CDP 模式连接同一专用 Chrome，**不依赖浏览器扩展**。
            f"--cdp-endpoint={CHROME_CDP_URL}",
            # 比赛面隔离：作为纵深防御的一层（官方文档说明它不是安全边界，
            # 也不影响重定向，因此不作为唯一防线）。
            "--blocked-origins=https://csc.xxsuyang.com;https://xxsuyang.com;https://*.xxsuyang.com",
            "--timeout-navigation=8000",
            "--timeout-action=5000",
            "--timeout-settle=500",
        ],
    },
    # ---- 回滚用（Edge 路线，已停用） ----
    "edge-devtools": {
        "command": NPX,
        "args": [
            "-y", "chrome-devtools-mcp@1.10.1",
            "--autoConnect",
            "--user-data-dir=C:\\Users\\<user>\\AppData\\Local\\Microsoft\\Edge\\User Data",
            "--no-usage-statistics",
            "--no-category-performance",
            "--no-category-memory",
            "--no-category-emulation",
            "--blockedUrlPattern=*://*.xxsuyang.com/*",
            "--blockedUrlPattern=*://xxsuyang.com/*",
        ],
    },
    "edge-playwright": {
        "command": NPX,
        "args": [
            "-y", "@playwright/mcp@0.0.83",
            "--extension",
            "--browser=msedge",
            "--profile-dir-name=Default",
            "--timeout-navigation=8000",
            "--timeout-action=5000",
            "--timeout-settle=500",
        ],
    },
}


@dataclass
class ProbeResult:
    preset: str = ""
    command: list[str] = field(default_factory=list)
    started: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)
    startup_ms: int = 0
    tool_ready_ms: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_count: int = 0
    call_result: Any = None
    call_ms: int = 0
    success: bool = False
    failure_reason: str = ""
    stderr_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        # 只保留工具名与描述，避免把整份 schema 塞进报告。
        payload["tools"] = [
            {"name": t.get("name"), "description": (t.get("description") or "")[:160]}
            for t in self.tools
        ]
        return payload


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
        parts: list[str] = []
        for block in parsed:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts)
    return result_text


class McpStdioClient:
    """最小 MCP stdio 客户端：newline-delimited JSON-RPC 2.0。"""
    def __init__(self, command: list[str], cwd: str | None = None) -> None:
        self.command = command
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._next_id = 0

    def start(self) -> None:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self.cwd,
            env=env,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._queue.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 60:
                del self._stderr_lines[0]

    def send(self, method: str, params: dict[str, Any] | None = None, notify: bool = False) -> int:
        assert self.proc and self.proc.stdin
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self._next_id += 1
            message["id"] = self._next_id
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return message.get("id", 0)

    def await_response(self, request_id: int, timeout: float) -> dict[str, Any] | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.05, deadline - time.time())
            try:
                message = self._queue.get(timeout=remaining)
            except queue.Empty:
                return None
            if message.get("id") == request_id:
                return message
        return None

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines[-12:])

    def close(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self.proc.kill()
            except OSError:
                pass


def probe(
    preset: str,
    command: list[str],
    call_tool: str = "",
    call_args: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> ProbeResult:
    result = ProbeResult(preset=preset, command=command)
    client = McpStdioClient(command)
    started_at = time.time()
    try:
        client.start()
        result.started = True
    except OSError as error:
        result.failure_reason = f"无法启动 MCP server：{error}"
        return result

    try:
        request_id = client.send(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        response = client.await_response(request_id, timeout)
        if response is None:
            result.failure_reason = (
                "initialize 超时（MCP SDK 默认握手 60s；Edge 未开启 Remote Debugging "
                "时 autoConnect 会卡在这里）"
            )
            result.stderr_tail = client.stderr_tail()
            return result
        if "error" in response:
            result.failure_reason = f"initialize 失败：{response['error']}"
            result.stderr_tail = client.stderr_tail()
            return result
        result.startup_ms = int((time.time() - started_at) * 1000)
        result.server_info = response.get("result", {}).get("serverInfo", {})

        client.send("notifications/initialized", {}, notify=True)

        tools_started = time.time()
        tools_id = client.send("tools/list", {})
        tools_response = client.await_response(tools_id, timeout)
        if tools_response is None or "error" in (tools_response or {}):
            result.failure_reason = (
                f"tools/list 失败：{(tools_response or {}).get('error') or 'timeout'}"
            )
            result.stderr_tail = client.stderr_tail()
            return result
        result.tools = tools_response["result"].get("tools", [])
        result.tool_count = len(result.tools)
        result.tool_ready_ms = int((time.time() - tools_started) * 1000)
        result.success = True

        if call_tool:
            call_started = time.time()
            call_id = client.send(
                "tools/call", {"name": call_tool, "arguments": call_args or {}}
            )
            call_response = client.await_response(call_id, timeout)
            result.call_ms = int((time.time() - call_started) * 1000)
            if call_response is None:
                result.failure_reason = f"tools/call {call_tool} 超时"
                result.success = False
            elif "error" in call_response:
                result.failure_reason = f"tools/call {call_tool} 失败：{call_response['error']}"
                result.success = False
            else:
                result.call_result = call_response["result"]
        return result
    finally:
        client.close()


def parse_command(args: list[str]) -> tuple[str, list[str]]:
    preset = ""
    if "--preset" in args:
        index = args.index("--preset")
        preset = args[index + 1] if index + 1 < len(args) else ""
        if preset not in PRESETS:
            raise SystemExit(f"未知 preset：{preset}；可用：{', '.join(PRESETS)}")
        entry = PRESETS[preset]
        return preset, [str(entry["command"]), *[str(a) for a in entry["args"]]]

    if "--command" not in args:
        raise SystemExit("需要 --preset 或 --command")
    index = args.index("--command")
    command = [args[index + 1]]
    rest = args[index + 2:]
    position = 0
    while position < len(rest):
        token = rest[position]
        if token == "--arg":
            if position + 1 < len(rest):
                command.append(rest[position + 1])
                position += 2
                continue
            break
        if token.startswith("--"):
            break
        command.append(token)
        position += 1
    return "custom", command


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    preset, command = parse_command(args)

    call_tool = ""
    if "--call" in args:
        index = args.index("--call")
        call_tool = args[index + 1] if index + 1 < len(args) else ""

    timeout = 90.0
    if "--timeout" in args:
        index = args.index("--timeout")
        try:
            timeout = float(args[index + 1])
        except (IndexError, ValueError):
            pass

    result = probe(preset, command, call_tool=call_tool, timeout=timeout)

    if "--save" in args:
        BENCH_DIR.mkdir(parents=True, exist_ok=True)
        target = BENCH_DIR / f"mcp_probe_{preset}.json"
        payload = {"generated_at": now_iso(), **result.as_dict()}
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"saved {target}", file=sys.stderr)

    if "--json" in args:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"preset        : {result.preset}")
        print(f"started       : {result.started}")
        print(f"success       : {result.success}")
        print(f"server        : {json.dumps(result.server_info, ensure_ascii=False)}")
        print(f"startup_ms    : {result.startup_ms}")
        print(f"tool_ready_ms : {result.tool_ready_ms}")
        print(f"tool_count    : {result.tool_count}")
        if result.tools:
            names = [t.get("name", "") for t in result.tools]
            print(f"tools         : {', '.join(names[:30])}")
        if call_tool:
            print(f"call {call_tool} ms : {result.call_ms}")
            preview = json.dumps(result.call_result, ensure_ascii=False)[:1200]
            print(f"call result   : {preview}")
        if result.failure_reason:
            print(f"failure       : {result.failure_reason}")
        if result.stderr_tail:
            print("stderr tail   :")
            print(result.stderr_tail)

    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

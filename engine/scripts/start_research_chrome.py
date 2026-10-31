"""启动 / 复用专用研究 Chrome（独立 User Data，CDP 仅监听本机）。

设计要点：
  - 专用 Profile：D:\\Dev\\tools\\provincial-chrome-profile（与日常 Chrome 完全隔离）
  - CDP：--remote-debugging-port=<port> --remote-debugging-address=127.0.0.1
  - **不使用 --autoConnect**（那是 Edge inspect 开关的路径，会反复弹授权）
  - **不复制 Edge 的 User Data**，不触碰日常 Chrome Profile
  - 不关闭沙箱 / 安全浏览 / 证书检查；不使用隐身或临时 Profile
  - 先探测端口占用，再决定用 9223 还是回退端口
  - 已在运行时**复用**，不重启（避免反复弹授权、丢失登录态）
  - Agent / MCP 退出时**不删除** Profile

用法：
    uv run python scripts/start_research_chrome.py            # 启动或复用
    uv run python scripts/start_research_chrome.py --status   # 只报告
    uv run python scripts/start_research_chrome.py --stop     # 只停本项目启动的实例
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, now_iso, write_json  # noqa: E402

STATE_PATH = ROOT / "data" / "quality" / "research_chrome_state.json"
PROFILE_DIR = Path(r"D:\Dev\tools\provincial-chrome-profile")
PREFERRED_PORT = 9223
FALLBACK_PORTS = (9224, 9225, 9226)
CDP_ADDRESS = "127.0.0.1"

CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)

# 只做 UI 便利，不影响沙箱 / 安全浏览 / 证书检查等安全功能。
UI_CONVENIENCE_FLAGS = ("--no-first-run", "--no-default-browser-check")

# 资源调度类 flag（**不是**安全功能）：
#
# 实测：当专用 Chrome 窗口被其他窗口完全遮挡时，Chrome 的原生遮挡检测
# （CalculateNativeWinOcclusion）会把页面标记为 document.visibilityState="hidden"。
# 此时 requestAnimationFrame 停摆，Playwright MCP 的 click/type 会卡在
# actionability 的「visible, enabled and stable」检查上直到超时，
# 无障碍快照也会退化。browser_evaluate 不走 actionability，所以它仍然可用。
#
# 这两个开关只关掉「遮挡即降频/隐藏」的资源优化，不改变沙箱、安全浏览、
# 证书校验或任何安全特性。
RENDERING_FLAGS = (
    "--disable-backgrounding-occluded-windows",
    "--disable-features=CalculateNativeWinOcclusion",
)

# 比赛面隔离的**浏览器级**强制层。
#
# 为什么必须放在浏览器层：实测发现 agent-browser 的**原始 CLI 没有任何域名拦截**
# 能力（`--allowed-domains` 与 `--cdp` 互斥，启用会让 CDP 路线失效）。也就是说
# 只靠项目路由器，任何人直接敲 `agent-browser --cdp 9223 open https://csc.xxsuyang.com/...`
# 都能载入比赛页。而三个后端连接的是**同一个专用 Chrome**，因此在浏览器层
# 把比赛域解析到黑洞，可以一次性覆盖所有客户端（CLI、MCP、以及未来的任何工具）。
#
# --host-resolver-rules 只改写本浏览器的 DNS 解析，不关闭沙箱、安全浏览或证书检查，
# 也不影响其他浏览器实例。
COMPETITION_HOST_RULES = (
    "--host-resolver-rules="
    "MAP *.xxsuyang.com 127.0.0.1,"
    "MAP xxsuyang.com 127.0.0.1,"
    "MAP *.zxhnzq.com 127.0.0.1,"
    "MAP zxhnzq.com 127.0.0.1"
)


@dataclass
class ChromeState:
    chrome_path: str = ""
    chrome_version: str = ""
    port: int = 0
    profile_dir: str = ""
    launched_by_us: bool = False
    reused: bool = False
    pid: int = 0
    cdp_ready: bool = False
    web_socket_url: str = ""
    browser: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def find_chrome() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        if candidate and candidate.exists():
            return candidate
    return None


def chrome_version(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{path}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=60,
        )
        return (completed.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def port_in_use(port: int, host: str = CDP_ADDRESS) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        return sock.connect_ex((host, port)) == 0


def pick_port(preferred: int = PREFERRED_PORT) -> int:
    for candidate in (preferred, *FALLBACK_PORTS):
        if not port_in_use(candidate):
            return candidate
    raise RuntimeError(f"{preferred} 及回退端口 {FALLBACK_PORTS} 均被占用")


def cdp_version(port: int, timeout: float = 3.0) -> dict[str, Any] | None:
    """读取 CDP /json/version。

    通过 --remote-debugging-port 启动的 Chrome 会提供 HTTP 发现端点；
    与 Edge 的 edge://inspect 开关不同（后者只给 WebSocket，HTTP 返回 404）。
    """
    url = f"http://{CDP_ADDRESS}:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def running_our_chrome() -> list[dict[str, Any]]:
    """找出使用本项目专用 Profile 的 chrome.exe 进程（按命令行精确匹配）。"""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
        "| Select-Object ProcessId,ParentProcessId,CommandLine "
        "| ConvertTo-Json -Compress -Depth 3"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = parsed if isinstance(parsed, list) else [parsed]
    marker = str(PROFILE_DIR).lower()
    return [
        row for row in rows
        if row.get("CommandLine") and marker in str(row["CommandLine"]).lower()
    ]


def launch(chrome: Path, port: int) -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        str(chrome),
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={CDP_ADDRESS}",
        f"--user-data-dir={PROFILE_DIR}",
        *UI_CONVENIENCE_FLAGS,
        *RENDERING_FLAGS,
        COMPETITION_HOST_RULES,
        "about:blank",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    return process.pid


def wait_for_cdp(port: int, timeout: float = 45.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = cdp_version(port)
        if info:
            return info
        time.sleep(0.7)
    return None


def ensure(status_only: bool = False) -> ChromeState:
    state = ChromeState(profile_dir=str(PROFILE_DIR))
    chrome = find_chrome()
    if chrome is None:
        state.errors.append(
            "未找到 Google Chrome Stable。请安装后重试："
            "https://www.google.com/chrome/"
        )
        return state
    state.chrome_path = str(chrome)
    state.chrome_version = chrome_version(chrome)

    # 1. 本项目已有实例？复用（不重启，保住登录态）
    ours = running_our_chrome()
    if ours:
        ports = []
        for row in ours:
            command = str(row.get("CommandLine") or "")
            for token in command.split():
                if token.startswith("--remote-debugging-port="):
                    try:
                        ports.append(int(token.split("=", 1)[1]))
                    except ValueError:
                        pass
        port = ports[0] if ports else PREFERRED_PORT
        info = cdp_version(port)
        if info:
            state.port = port
            state.reused = True
            state.cdp_ready = True
            state.browser = info.get("Browser", "")
            state.web_socket_url = info.get("webSocketDebuggerUrl", "")
            state.pid = int(ours[0].get("ProcessId") or 0)
            return state
        state.errors.append(
            f"发现本项目 Chrome 进程（PID {ours[0].get('ProcessId')}）但端口 {port} 无 CDP 响应。"
        )
        if status_only:
            return state

    if status_only:
        state.errors.append("本项目专用 Chrome 未运行。")
        return state

    # 2. 新启动
    try:
        port = pick_port()
    except RuntimeError as error:
        state.errors.append(str(error))
        return state
    state.port = port
    try:
        state.pid = launch(chrome, port)
        state.launched_by_us = True
    except OSError as error:
        state.errors.append(f"启动 Chrome 失败：{error}")
        return state

    info = wait_for_cdp(port)
    if not info:
        state.errors.append(f"Chrome 已启动（PID {state.pid}）但 {port} 上 CDP 未就绪。")
        return state
    state.cdp_ready = True
    state.browser = info.get("Browser", "")
    state.web_socket_url = info.get("webSocketDebuggerUrl", "")
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动/复用专用研究 Chrome（CDP，仅本机）")
    parser.add_argument("--status", action="store_true", help="只报告状态，不启动")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    state = ensure(status_only=args.status)
    payload = {"generated_at": now_iso(), **state.as_dict()}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(STATE_PATH, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"chrome        : {state.chrome_path or '(未找到)'}  {state.chrome_version}")
        print(f"profile       : {state.profile_dir}")
        print(f"port          : {state.port or '-'}  (CDP 仅 {CDP_ADDRESS})")
        print(f"cdp_ready     : {state.cdp_ready}")
        print(f"reused        : {state.reused}   launched_by_us={state.launched_by_us}  pid={state.pid}")
        print(f"browser       : {state.browser}")
        for error in state.errors:
            print(f"error         : {error}")
    return 0 if state.cdp_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""无头 Chrome 检索助手（CDP，独立 profile，不碰用户浏览器）。

特点：
- `--headless=new`，**不弹出任何窗口**
- 独立 user-data-dir（data/browser/headless-profile），不复用也不读取
  用户日常 Chrome / Edge 的登录态，不碰其 Profile 数据库
- 常驻一个实例，后续调用复用，冷启动只发生一次
- 支持：取正文、执行 JS、点击选择器、截图

用法：
    # 取正文
    .venv\\Scripts\\python.exe scripts\\headless_chrome.py --url https://example.com

    # 等 SPA 渲染后取正文
    .venv\\Scripts\\python.exe scripts/headless_chrome.py --url URL --wait-ms 3000

    # 执行 JS（结果 JSON 序列化后打印）
    .venv\\Scripts\\python.exe scripts/headless_chrome.py --url URL \\
        --js "document.querySelectorAll('li').length"

    # 点击后取正文
    .venv\\Scripts\\python.exe scripts/headless_chrome.py --url URL \\
        --click ".el-checkbox" --wait-ms 2000

    # 截图
    .venv\\Scripts\\python.exe scripts/headless_chrome.py --url URL --shot out.png

    # 关闭常驻实例
    .venv\\Scripts\\python.exe scripts/headless_chrome.py --shutdown
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "data" / "browser" / "headless-profile"
PID_FILE = ROOT / "data" / "browser" / "headless.pid"
DEFAULT_PORT = 9333

CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> Path:
    for path in CHROME_CANDIDATES:
        if path.exists():
            return path
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return Path(found)
    raise SystemExit("找不到 Chrome/Edge 可执行文件")


def debug_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def http_json(url: str, method: str = "GET", timeout: float = 3.0):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_up(port: int) -> bool:
    try:
        http_json(debug_url(port, "/json/version"), timeout=1.5)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def ensure_browser(port: int, browser: Path) -> None:
    if is_up(port):
        return

    PROFILE.mkdir(parents=True, exist_ok=True)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    args = [
        str(browser),
        "--headless=new",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-sync",
        "--disable-background-networking",
        "--hide-scrollbars",
        "--mute-audio",
        "--window-size=1440,900",
        "about:blank",
    ]
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + 20
    while time.time() < deadline:
        if is_up(port):
            return
        time.sleep(0.3)
    raise SystemExit("无头浏览器启动超时")


class CDP:
    def __init__(self, ws_url: str, timeout: float = 30.0):
        import websocket  # websocket-client

        self.ws = websocket.create_connection(
            ws_url, timeout=timeout, suppress_origin=True
        )
        self._id = 0
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method,
                                 "params": params or {}}))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"CDP 调用超时: {method}")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def wait_ready(cdp: CDP, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = cdp.call("Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            if result.get("result", {}).get("value") == "complete":
                return
        except Exception:
            pass
        time.sleep(0.25)


def evaluate(cdp: CDP, expression: str):
    result = cdp.call("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    })
    if "exceptionDetails" in result:
        details = result["exceptionDetails"]
        raise RuntimeError(details.get("text") or str(details))
    return result.get("result", {}).get("value")


def shutdown(port: int) -> int:
    if not PID_FILE.exists():
        print("没有记录的无头实例")
        return 0
    pid_text = PID_FILE.read_text(encoding="utf-8").strip()
    PID_FILE.unlink(missing_ok=True)
    if not pid_text.isdigit():
        return 0
    pid = int(pid_text)
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, check=False)
        print(f"已关闭无头实例 pid={pid}")
    except Exception as exc:  # noqa: BLE001
        print(f"关闭失败: {exc}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="")
    parser.add_argument("--js", default="")
    parser.add_argument("--click", default="")
    parser.add_argument("--focus", default="", help="聚焦的 CSS 选择器")
    parser.add_argument("--type", dest="type_text", default="", help="像真人一样输入文本")
    parser.add_argument("--enter", action="store_true", help="输入后按回车")
    parser.add_argument("--shot", default="")
    parser.add_argument("--wait-ms", type=int, default=800)
    parser.add_argument("--ua", default="",
                        help="覆盖 User-Agent；默认把 HeadlessChrome 换成 Chrome")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile", default=str(PROFILE))
    parser.add_argument("--keep-tab", action="store_true")
    parser.add_argument("--shutdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.shutdown:
        return shutdown(args.port)

    if not args.url:
        parser.error("--url 必填（或使用 --shutdown）")

    browser = find_browser()
    ensure_browser(args.port, browser)

    tab = http_json(debug_url(args.port, "/json/new?about:blank"), method="PUT")
    cdp = CDP(tab["webSocketDebuggerUrl"], timeout=args.timeout)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        # 无头 Chrome 的 UA 默认带 HeadlessChrome，部分站点会直接返回 412。
        # 换成同一版本号的普通 UA，属于常规兼容处理，不改指纹、不绕验证。
        ua = args.ua or evaluate(cdp, "navigator.userAgent").replace(
            "HeadlessChrome", "Chrome")
        cdp.call("Network.enable")
        cdp.call("Network.setUserAgentOverride", {"userAgent": ua})

        cdp.call("Page.navigate", {"url": args.url})
        wait_ready(cdp, args.timeout)
        if args.wait_ms:
            time.sleep(args.wait_ms / 1000)

        if args.click:
            evaluate(cdp, f"document.querySelector({json.dumps(args.click)})?.click()")
            time.sleep(args.wait_ms / 1000 if args.wait_ms else 1.0)

        if args.focus:
            evaluate(cdp, f"document.querySelector({json.dumps(args.focus)})?.focus()")
        if args.type_text:
            cdp.call("Input.insertText", {"text": args.type_text})
            time.sleep(0.8)
        if args.enter:
            for kind in ("keyDown", "keyUp"):
                cdp.call("Input.dispatchKeyEvent", {
                    "type": kind, "key": "Enter", "code": "Enter",
                    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                })
            time.sleep(2.5)

        if args.shot:
            data = cdp.call("Page.captureScreenshot", {"format": "png"})
            Path(args.shot).write_bytes(base64.b64decode(data["data"]))
            print(f"截图已保存: {args.shot}")

        if args.js:
            value = evaluate(cdp, args.js)
            print(json.dumps(value, ensure_ascii=False) if args.json else value)
        elif not args.shot:
            print(evaluate(cdp, "document.body.innerText"))

        if not args.keep_tab:
            try:
                http_json(debug_url(args.port, f"/json/close/{tab['id']}"))
            except Exception:
                pass
    finally:
        cdp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

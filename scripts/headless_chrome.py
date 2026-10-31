#!/usr/bin/env python3
"""Headless Chrome helper over CDP (no window, isolated profile).

Requires: websocket-client  (pip install websocket-client)

Examples:
    python headless_chrome.py --url https://example.com
    python headless_chrome.py --url URL --js "document.title"
    python headless_chrome.py --url URL --click ".el-checkbox" --wait-ms 2500
    python headless_chrome.py --url URL --focus "#kw" --type "keyword" --enter
    python headless_chrome.py --url URL --shot out.png
    python headless_chrome.py --shutdown

The helper reuses one background Chrome instance. It uses a separate user-data
directory, so it never reads or modifies a browser profile you use day to day.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# Local CDP traffic must never go through an HTTP proxy.
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

PROFILE = Path(tempfile.gettempdir()) / "cdp-headless-profile"
PID_FILE = Path(tempfile.gettempdir()) / "cdp-headless.pid"
DEFAULT_PORT = 9333

BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> Path:
    for path in BROWSER_CANDIDATES:
        if path.exists():
            return path
    found = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")
    if found:
        return Path(found)
    raise SystemExit("Chrome/Edge not found. Pass --browser <path>.")


def debug_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


# Never send the local CDP port through an HTTP proxy: HTTP_PROXY in the
# environment would otherwise make 127.0.0.1:PORT return 502.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(url: str, method: str = "GET", timeout: float = 3.0):
    req = urllib.request.Request(url, method=method)
    with _OPENER.open(req, timeout=timeout) as resp:
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
    raise SystemExit("headless browser start timed out")


class CDP:
    def __init__(self, ws_url: str, timeout: float = 30.0):
        import websocket  # websocket-client

        self.ws = websocket.create_connection(
            ws_url,
            timeout=timeout,
            suppress_origin=True,
            http_no_proxy=["127.0.0.1", "localhost"],
        )
        self._id = 0
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
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
        raise TimeoutError(f"CDP timeout: {method}")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def wait_ready(cdp: CDP, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = cdp.call("Runtime.evaluate", {"expression": "document.readyState",
                                                   "returnByValue": True})
            if result.get("result", {}).get("value") == "complete":
                return
        except Exception:
            pass
        time.sleep(0.25)


def evaluate(cdp: CDP, expression: str):
    result = cdp.call("Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    })
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"].get("text") or str(result["exceptionDetails"]))
    return result.get("result", {}).get("value")


def shutdown() -> int:
    if not PID_FILE.exists():
        print("no running instance recorded")
        return 0
    pid = PID_FILE.read_text(encoding="utf-8").strip()
    PID_FILE.unlink(missing_ok=True)
    if not pid.isdigit():
        return 0
    subprocess.run(["taskkill", "/PID", pid, "/F", "/T"] if os.name == "nt"
                   else ["kill", "-9", pid], capture_output=True, check=False)
    print(f"stopped pid={pid}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="")
    parser.add_argument("--js", default="")
    parser.add_argument("--click", default="")
    parser.add_argument("--focus", default="", help="CSS selector to focus")
    parser.add_argument("--type", dest="type_text", default="", help="text to type")
    parser.add_argument("--enter", action="store_true")
    parser.add_argument("--shot", default="")
    parser.add_argument("--wait-ms", type=int, default=800)
    parser.add_argument("--ua", default="", help="override User-Agent")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--shutdown", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.shutdown:
        return shutdown()
    if not args.url:
        parser.error("--url is required (or use --shutdown)")

    browser = Path(args.browser) if args.browser else find_browser()
    ensure_browser(args.port, browser)

    tab = http_json(debug_url(args.port, "/json/new?about:blank"), method="PUT")
    cdp = CDP(tab["webSocketDebuggerUrl"], timeout=args.timeout)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        # Some sites answer 412 to "HeadlessChrome" in the UA. Using the same
        # browser's normal UA string is a compatibility fix, not an auth bypass.
        ua = args.ua or evaluate(cdp, "navigator.userAgent").replace("HeadlessChrome", "Chrome")
        cdp.call("Network.enable")
        cdp.call("Network.setUserAgentOverride", {"userAgent": ua})

        cdp.call("Page.navigate", {"url": args.url})
        wait_ready(cdp, args.timeout)
        if args.wait_ms:
            time.sleep(args.wait_ms / 1000)

        if args.click:
            evaluate(cdp, f"document.querySelector({json.dumps(args.click)})?.click()")
            time.sleep((args.wait_ms or 1000) / 1000)

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
            print(f"screenshot saved: {args.shot}")

        if args.js:
            value = evaluate(cdp, args.js)
            print(json.dumps(value, ensure_ascii=False) if args.json else value)
        elif not args.shot:
            print(evaluate(cdp, "document.body.innerText"))
    finally:
        cdp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

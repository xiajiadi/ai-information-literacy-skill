#!/usr/bin/env python3
"""等待本地答题台出现未回答的问题。

设计成"阻塞直到有活就退出"，这样把它放到后台运行时，
进程一退出就会唤醒当前 Claude 会话去接单。

用法：
    .venv\\Scripts\\python.exe scripts/webui_wait.py            # 默认等 30 分钟
    .venv\\Scripts\\python.exe scripts/webui_wait.py --timeout 3600

退出码：
    0  有新问题（JSON 打到 stdout）
    2  超时，没有新问题
    3  服务没启动
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def get_pending() -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/api/pending", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8")).get("pending", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            pending = get_pending()
        except urllib.error.URLError:
            print("服务未启动：请先运行 webui/server.py", file=sys.stderr)
            return 3
        if pending:
            print(json.dumps({"pending": pending}, ensure_ascii=False, indent=2))
            return 0
        time.sleep(args.interval)

    print("timeout", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

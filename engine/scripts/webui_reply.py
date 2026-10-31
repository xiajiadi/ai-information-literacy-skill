#!/usr/bin/env python3
"""把答案回填到本地答题台。

用法：
    .venv\\Scripts\\python.exe scripts\\webui_reply.py --to 3 --text "答案：A"
    .venv\\Scripts\\python.exe scripts\\webui_reply.py --to 3 --text-file ans.md \\
        --confidence "🟢 HIGH" --source "维普官网实测"

--to 是问题的 seq（webui_wait.py 返回的 id）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", type=int, required=True, dest="reply_to")
    parser.add_argument("--text", default="")
    parser.add_argument("--text-file", default="")
    parser.add_argument("--confidence", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    text = args.text
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    if not text.strip():
        print("答案为空", file=sys.stderr)
        return 2

    meta = {}
    if args.confidence:
        meta["confidence"] = args.confidence
    if args.source:
        meta["来源"] = args.source
    if args.note:
        meta["备注"] = args.note

    payload = json.dumps(
        {"reply_to": args.reply_to, "text": text, "meta": meta},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/answer",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(resp.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""停止**本项目专用**研究 Chrome（PID 精确 + 归属复核）。

与 `cleanup_project_processes.py` 同一套纪律：
  - 绝不按进程名批量终止；
  - 只处理命令行含本专用 Profile 路径的 chrome.exe；
  - 终止前对每个 PID **再次**复核命令行仍属于本项目；
  - 日常 Chrome、其他浏览器、其他项目进程一律不动。

用法：
    uv run python scripts/stop_research_chrome.py            # dry-run
    uv run python scripts/stop_research_chrome.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, load_yaml, now_iso, run_captured, write_json  # noqa: E402

STACK_PATH = ROOT / "config" / "browser_stack.yaml"
OUT_PATH = ROOT / "data" / "quality" / "research_chrome_stop.json"

LIST_SCRIPT = (
    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
    "| Select-Object ProcessId,ParentProcessId,CommandLine "
    "| ConvertTo-Json -Compress -Depth 3"
)


def our_chrome(profile: str) -> list[dict[str, Any]]:
    code, raw = run_captured(["powershell", "-NoProfile", "-Command", LIST_SCRIPT], timeout=180)
    if code != 0 or not (raw or "").strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = parsed if isinstance(parsed, list) else [parsed]
    marker = profile.lower()
    return [
        r for r in rows
        if r.get("CommandLine") and marker in str(r["CommandLine"]).lower()
    ]


def stop(pid: int, profile: str) -> str:
    marker = profile.replace("'", "''")
    script = (
        f"$x = Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
        f"-ErrorAction SilentlyContinue; "
        f"if ($x -and $x.CommandLine -like '*{marker}*') "
        f"{{ Stop-Process -Id {pid} -Force; 'TERMINATED' }} else {{ 'REFUSED' }}"
    )
    code, out = run_captured(["powershell", "-NoProfile", "-Command", script], timeout=60)
    return (out or "").strip() or f"NO_OUTPUT({code})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="停止本项目专用研究 Chrome")
    parser.add_argument("--apply", action="store_true", help="真正终止（默认 dry-run）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    stack = load_yaml(STACK_PATH)
    profile = stack["browser"]["chrome"]["user_data_dir"]
    rows = our_chrome(profile)

    actions: list[dict[str, Any]] = []
    for row in rows:
        pid = int(row["ProcessId"])
        action = {
            "pid": pid,
            "parent_pid": int(row.get("ParentProcessId") or 0),
            "command_line": str(row.get("CommandLine"))[:160],
        }
        # 只终止浏览器主进程（有 --remote-debugging-port 的那个），
        # 子进程（renderer/gpu/crashpad）会随主进程退出。
        is_browser = "--remote-debugging-port" in str(row.get("CommandLine") or "")
        if not args.apply:
            action["result"] = "DRY_RUN"
        elif not is_browser:
            action["result"] = "SKIP_CHILD_PROCESS"
        else:
            action["result"] = stop(pid, profile)
        actions.append(action)

    time.sleep(2)
    payload = {
        "generated_at": now_iso(),
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "profile": profile,
        "policy": "PID + 命令行归属复核；不按进程名批量终止；日常 Chrome 不受影响",
        "candidates": actions,
        "terminated": [a for a in actions if a.get("result") == "TERMINATED"],
        "remaining_after": len(our_chrome(profile)),
    }
    write_json(OUT_PATH, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"mode={payload['mode']} profile={profile}")
        for action in actions:
            print(f"  pid={action['pid']:6d} {action['result']:20s} {action['command_line'][:90]}")
        print(f"remaining after = {payload['remaining_after']}")
        print(f"report = {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

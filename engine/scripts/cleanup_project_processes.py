"""安全清理本项目启动的孤儿进程（防误杀回归）。

背景：2026-10-07 曾按进程名批量终止 `node.exe`，误杀了其他 IDE 与 draw.io 的
MCP 服务。**禁止再按名字杀进程。**

本脚本的规则：

  1. **绝不**按进程名批量终止。
  2. 每个候选进程必须同时拿到：PID、完整命令行、父进程 PID。
  3. 必须证明**项目归属**：命令行里出现本项目的路径标记、本项目使用的固定
     版本包名 + 本项目端口，或本项目的 agent-browser 安装路径。
  4. 命中受保护进程族（其他 IDE / Codex / draw.io / DSH host / 独立 MCP）直接跳过。
  5. **默认 dry-run**，只有显式 `--apply` 才真正终止。
  6. 只终止自己 spawn 的 stdio 子进程；不触碰用户浏览器主进程。

用法：
    uv run python scripts/cleanup_project_processes.py            # dry-run
    uv run python scripts/cleanup_project_processes.py --apply
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, now_iso, run_captured, write_json  # noqa: E402

OUT_PATH = ROOT / "data" / "quality" / "project_process_cleanup.json"

# 归属证据：命令行里出现任一标记，才算本项目启动的进程。
OWNERSHIP_MARKERS = (
    r"D:\Dev\projects\ai+ 2",
    r"ai%2B%202/data/tmp",
    "chrome-devtools-mcp@1.10.1",
    "browser-url=http://127.0.0.1:9223",
    "autoConnect",
    "@playwright/mcp@0.0.83",
    "cdp-endpoint=http://127.0.0.1:9223",
    r"D:\Dev\tools\browser-tools\agent-browser",
    "provincial-research",
    "provincial-validate",
)

# 受保护进程族：即使命中归属标记也不动（宁可漏清，不可误杀）。
PROTECTED_MARKERS = (
    "drawio",
    "@drawio/mcp",
    "codex",
    "vscode",
    "cursor",
    "windsurf",
    "claude",
    "gemini",
    "dsh",
    "deepseek",
    "provincial-chrome-profile",
)


@dataclass
class Candidate:
    pid: int
    name: str
    parent_pid: int
    command_line: str
    ownership_markers: list[str] = field(default_factory=list)
    protected_markers: list[str] = field(default_factory=list)
    decision: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def list_processes() -> list[dict[str, Any]]:
    script = (
        "Get-CimInstance Win32_Process "
        "| Select-Object ProcessId,ParentProcessId,Name,CommandLine "
        "| ConvertTo-Json -Compress -Depth 3"
    )
    # 用 run_captured：它按 UTF-8 解码且写文件而非管道，命令行里的中文
    # 不会让默认 GBK 解码炸掉（UnicodeDecodeError）。
    code, raw = run_captured(
        ["powershell", "-NoProfile", "-Command", script], timeout=180
    )
    raw = (raw or "").strip()
    if code != 0 or not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [r for r in rows if isinstance(r, dict)]


def classify(rows: list[dict[str, Any]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for row in rows:
        command = str(row.get("CommandLine") or "")
        name = str(row.get("Name") or "")
        if not command:
            continue
        ownership = [m for m in OWNERSHIP_MARKERS if m.lower() in command.lower()]
        if not ownership:
            continue
        protected = [m for m in PROTECTED_MARKERS if m.lower() in command.lower()]
        candidate = Candidate(
            pid=int(row.get("ProcessId") or 0),
            name=name,
            parent_pid=int(row.get("ParentProcessId") or 0),
            command_line=command,
            ownership_markers=ownership,
            protected_markers=protected,
        )
        if protected:
            candidate.decision = "SKIP"
            candidate.reason = f"命中受保护进程族：{protected}"
        elif name.lower() not in {"node.exe", "chrome.exe", "agent-browser-win32-x64.exe"}:
            candidate.decision = "SKIP"
            candidate.reason = f"进程名不在可清理白名单：{name}"
        else:
            candidate.decision = "CANDIDATE"
            candidate.reason = f"归属证据：{ownership}"
        candidates.append(candidate)
    return candidates


def terminate(candidate: Candidate) -> str:
    marker = candidate.ownership_markers[0].replace("'", "''")
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={candidate.pid}\" "
        f"-ErrorAction SilentlyContinue; "
        f"if ($p -and $p.CommandLine -like '*{marker}*') "
        f"{{ Stop-Process -Id {candidate.pid} -Force; 'TERMINATED' }} else {{ 'REFUSED_REVALIDATION' }}"
    )
    code, out = run_captured(
        ["powershell", "-NoProfile", "-Command", script], timeout=60
    )
    return out.strip() or f"NO_OUTPUT(code={code})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="安全清理本项目孤儿进程（默认 dry-run，且必须逐 PID 显式确认）"
    )
    parser.add_argument("--apply", action="store_true", help="真正终止（默认只报告）")
    parser.add_argument(
        "--confirm-retired",
        default="",
        help="逗号分隔的 PID 列表；只有列在这里、且被判定为 CANDIDATE 的进程才会被终止。"
             "这是防误杀的结构性要求：无法证明「已废弃」就不清理。",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    confirmed = {
        int(token) for token in args.confirm_retired.replace(" ", "").split(",") if token.strip().isdigit()
    }

    rows = list_processes()
    candidates = classify(rows)

    actions: list[dict[str, Any]] = []
    for candidate in candidates:
        action = candidate.as_dict()
        if candidate.decision != "CANDIDATE":
            action["result"] = "SKIPPED"
        elif not args.apply:
            action["result"] = "DRY_RUN"
        elif candidate.pid not in confirmed:
            # 不能证明「已废弃」就不清理 —— 尤其不能在误杀事故之后再犯。
            action["result"] = "RETAINED_UNPROVEN"
            action["reason"] += "；未在 --confirm-retired 中显式确认已废弃"
        else:
            action["result"] = terminate(candidate)
        actions.append(action)

    payload = {
        "generated_at": now_iso(),
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "confirmed_retired_pids": sorted(confirmed),
        "policy": {
            "kill_by_name_forbidden": True,
            "requires_pid_commandline_parent_and_ownership": True,
            "requires_explicit_per_pid_retirement_confirmation": True,
            "protected_families": list(PROTECTED_MARKERS),
            "default_decision_when_unprovable": "RETAIN",
        },
        "scanned_processes": len(rows),
        "candidates": actions,
        "terminated": [a for a in actions if a.get("result") == "TERMINATED"],
        "retained": [a for a in actions if a.get("result") == "RETAINED_UNPROVEN"],
        "skipped": [a for a in actions if a.get("result") == "SKIPPED"],
    }
    write_json(OUT_PATH, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"mode={payload['mode']} scanned={len(rows)} candidates={len(actions)} "
              f"terminated={len(payload['terminated'])} retained={len(payload['retained'])}")
        for action in actions:
            print(f"  [{action['decision']:9s}] pid={action['pid']:6d} {action['name']:28s} "
                  f"{action['result']:20s} {action['reason'][:80]}")
        print(f"\nreport = {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

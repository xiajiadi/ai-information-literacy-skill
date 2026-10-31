"""把专用研究 Chrome 窗口恢复到前台。

为什么需要：实测发现 Playwright MCP 的 `browser_click` / `browser_type` 走
**actionability 门控**（要求元素 visible / enabled / **stable**）。当专用 Chrome
窗口被最小化或被遮挡时，Chrome 会把页面标记为 `document.visibilityState="hidden"`，
此时 requestAnimationFrame 不再推进，元素的 stable 检查永远无法完成 ——
点击会在超时后失败，同时无障碍快照也会退化。

`browser_evaluate` 不经过 actionability，所以它在窗口隐藏时仍然可用。
这解释了「evaluate 成功、click 超时」的现象。

本脚本只操作**本项目专用 Chrome** 的窗口（按进程命令行含专用 Profile 路径识别），
不触碰日常 Chrome，也不改变任何页面内容。

用法：
    uv run python scripts/focus_research_chrome.py
    uv run python scripts/focus_research_chrome.py --check    # 只报告是否可见
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, load_yaml, now_iso, run_captured, write_json  # noqa: E402

STACK_PATH = ROOT / "config" / "browser_stack.yaml"
OUT_PATH = ROOT / "data" / "quality" / "research_chrome_window.json"

FOCUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Focus {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
}
"@
$marker = '__MARKER__'
$rows = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($marker) }
$result = @()
foreach ($row in $rows) {
  $proc = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
  if (-not $proc -or $proc.MainWindowHandle -eq 0) { continue }
  $h = $proc.MainWindowHandle
  $before = [Win32Focus]::IsIconic($h)
  [Win32Focus]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
  [Win32Focus]::SetForegroundWindow($h) | Out-Null
  Start-Sleep -Milliseconds 400
  $result += [pscustomobject]@{
    pid = $row.ProcessId
    was_minimized = $before
    now_minimized = [Win32Focus]::IsIconic($h)
    window_visible = [Win32Focus]::IsWindowVisible($h)
  }
}
$result | ConvertTo-Json -Compress -Depth 3
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="恢复专用研究 Chrome 窗口到前台")
    parser.add_argument("--check", action="store_true", help="只报告，不恢复")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    stack = load_yaml(STACK_PATH)
    profile = stack["browser"]["chrome"]["user_data_dir"]

    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "profile": profile,
        "mode": "CHECK" if args.check else "FOCUS",
        "why": "Playwright MCP 的 click/type 需要元素可见且 stable；窗口隐藏时 visibilityState=hidden，stable 永不成立。",
    }

    if args.check:
        code, out = run_captured([
            "powershell", "-NoProfile", "-Command",
            "$rows = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -and $_.CommandLine.ToLower().Contains('{profile.lower()}') }}; "
            "$r = foreach ($row in $rows) { $p = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue; "
            "if ($p -and $p.MainWindowHandle -ne 0) { [pscustomobject]@{ pid=$row.ProcessId; minimized=$p.MainWindowTitle } } }; "
            "$r | ConvertTo-Json -Compress -Depth 3",
        ], timeout=150)
        payload["windows"] = out
        payload["note"] = "CHECK 模式不改变窗口状态"
    else:
        script = FOCUS_SCRIPT.replace("__MARKER__", profile.lower())
        code, out = run_captured(["powershell", "-NoProfile", "-Command", script], timeout=180)
        payload["focus_result_raw"] = out
        try:
            parsed = json.loads(out[out.find("["):out.rfind("]") + 1]) if "[" in out else json.loads(out)
            payload["windows"] = parsed
        except (ValueError, json.JSONDecodeError):
            payload["windows"] = out

    write_json(OUT_PATH, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"mode={payload['mode']} profile={profile}")
        print(payload.get("focus_result_raw") or payload.get("windows"))
        print(f"report = {OUT_PATH}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

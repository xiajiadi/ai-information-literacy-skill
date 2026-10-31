"""PHASE 2 修正 §4 · 统一合规检查（针对**生成的执行计划与全部输出字段**）。

Controller 要求：

  * 「扩大测试范围到所有来源字段、嵌套结构、备用入口和**生成的执行计划**」
  * 「必须阻止被屏蔽的比赛 URL 进入自动化执行路径」
  * 「所有新字段必须经过**统一**合规检查」

已有防线覆盖了历史题库的 `reusable_recipe`，但**路由自己生成的输出**同样可能携带 URL：
`primary_entry` / `fallback_entry` / `entry_avoid` / 查询构建器生成的 `steps` 与
`field_instructions` / 以及未来任何新增字段。逐个字段手工检查会漏，
因此这里提供**唯一的收口函数** `enforce_output_compliance()`：
对任意嵌套结构做一次扫描，任何 `://` 字符串都过同一个合规闸门。

设计要点：
  * **快**：只用 `"://" in s` 做预筛，绝大多数短字符串直接跳过；
  * **全**：dict / list / tuple / set / 任意深度；
  * **可追溯**：返回被拦截字段路径与被拦截 surface，但**不保留原始 URL 文本**；
  * **不误伤**：允许的研究面 URL 原样保留。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate  # noqa: E402

URL_RE = re.compile(r"https?://[^\s\)）\]，,；;\"'<>]+")

_GATE: ComplianceGate | None = None


def _gate() -> ComplianceGate:
    global _GATE
    if _GATE is None:
        _GATE = ComplianceGate()
    return _GATE


def _walk(value: Any, path: str, report: dict[str, Any], allow: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _walk(item, f"{path}.{key}" if path else str(key), report, allow)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_walk(item, f"{path}[]", report, allow) for item in value]
    if isinstance(value, set):
        return [_walk(item, f"{path}[]", report, allow) for item in value]
    if not isinstance(value, str):
        return value
    # 快速预筛：没有 "://" 的字符串不可能含 URL，直接返回（保证低延迟）
    if "://" not in value:
        return value

    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        if url in allow:
            return url
        try:
            verdict = _gate().classify(url)
        except (ValueError, OSError):
            return url
        if verdict.automation_allowed:
            return url
        report.setdefault("blocked", []).append({
            "path": path,
            # 只留 host 与判定，不留原始 URL 文本
            "host": _host(url),
            "surface": verdict.surface,
        })
        return f"⛔[{verdict.surface}]"

    return URL_RE.sub(replace, value)


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def enforce_output_compliance(payload: Any, allow: set[str] | None = None) -> tuple[Any, dict[str, Any]]:
    """对任意结构做统一合规检查。

    返回 (清洗后的结构, 报告)。报告中 `clean=True` 表示没有任何被拦的 URL。
    """
    report: dict[str, Any] = {"blocked": [], "checked": True}
    cleaned = _walk(payload, "", report, allow or set())
    report["blocked_count"] = len(report["blocked"])
    report["clean"] = report["blocked_count"] == 0
    report["blocked_surfaces"] = sorted({item["surface"] for item in report["blocked"]})
    if isinstance(cleaned, dict):
        cleaned["_output_compliance"] = {
            "clean": report["clean"],
            "blocked_count": report["blocked_count"],
            "blocked_surfaces": report["blocked_surfaces"],
            "blocked_fields": [item["path"] for item in report["blocked"]][:8],
            "note": "本字段由 enforce_output_compliance() 写入：输出中任何 URL 都过同一合规闸门。",
        }
    return cleaned, report


def extract_urls(payload: Any) -> list[str]:
    """取出结构中所有 URL（供测试与审计用）。"""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        elif isinstance(value, str) and "://" in value:
            found.extend(URL_RE.findall(value))

    walk(payload)
    return found


if __name__ == "__main__":
    import json

    demo = {
        "primary_entry": "https://www.cnki.net/",
        "fallback_entry": "https://csc.xxsuyang.com/detail?id=1",
        "steps": [
            "打开 https://www.cnki.net/",
            "若失败则访问 https://sub.xxsuyang.com/exam",
        ],
        "nested": {"deep": {"urls": ["https://example.com/ok", "https://xxsuyang.com/"]}},
    }
    cleaned, report = enforce_output_compliance(demo)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print(json.dumps(cleaned, ensure_ascii=False, indent=2))

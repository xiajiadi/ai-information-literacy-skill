"""PHASE 2 修正 · 题库对账：288（解析到） vs 290（原始标记）。

只做对账，**不补造题目**。产出：
    data/quality/phase2/QUESTION_BANK_RECONCILIATION.md
    data/quality/phase2/reconciliation.json

方法：
  1. 从 handoff/question_bank.md 里**独立**抽取所有「题号」字符串
     （用比解析器更宽松的扫描，避免"解析器没匹配到"被误当成"题目不存在"）；
  2. 与 `scripts/phase2_dataset.py` 的实际解析结果做集合差；
  3. 对差异题号逐个定位源文件行号并给出原因。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase2_dataset import parse_handoff  # noqa: E402
from provincial_common import ROOT, now_iso, write_json  # noqa: E402

HANDOFF = ROOT / "handoff" / "question_bank.md"
OUT_DIR = ROOT / "data" / "quality" / "phase2"
OUT_JSON = OUT_DIR / "reconciliation.json"
OUT_MD = OUT_DIR / "QUESTION_BANK_RECONCILIATION.md"

# 宽松扫描：任何以「### 前缀-数字.」开头的行都算一次题号声明，
# 不管题型标记是否规范、是否重复。
LOOSE_HEAD_RE = re.compile(r"^###\s+([^\s.]+?)-(\d+)\s*\.")
# 也扫描汇总里可能出现的计数声明
COUNT_RE = re.compile(r"(初赛|模拟|样题|公开样题|真题)[^\d]{0,12}(\d+)\s*道")


def loose_scan(text: str) -> list[dict]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = LOOSE_HEAD_RE.match(line)
        if match:
            found.append({
                "part": match.group(1),
                "index": int(match.group(2)),
                "id": f"{match.group(1)}-{match.group(2)}",
                "line": lineno,
                "raw": line[:120],
            })
    return found


def main() -> int:
    text = HANDOFF.read_text(encoding="utf-8")
    loose = loose_scan(text)
    parsed = parse_handoff(text)

    loose_ids = [item["id"] for item in loose]
    parsed_ids = [item["id"] for item in parsed]

    # 重复题号：同一 id 在源文件里出现多次
    from collections import Counter

    loose_counter = Counter(loose_ids)
    duplicated = {k: v for k, v in loose_counter.items() if v > 1}
    parsed_counter = Counter(parsed_ids)
    parsed_dup = {k: v for k, v in parsed_counter.items() if v > 1}

    missing_from_parser = sorted(set(loose_ids) - set(parsed_ids))
    extra_in_parser = sorted(set(parsed_ids) - set(loose_ids))

    by_part_loose: dict[str, int] = {}
    for item in loose:
        by_part_loose[item["part"]] = by_part_loose.get(item["part"], 0) + 1
    by_part_parsed: dict[str, int] = {}
    for item in parsed:
        by_part_parsed[item["part"]] = by_part_parsed.get(item["part"], 0) + 1

    counts_declared = COUNT_RE.findall(text)
    summary_lines = [
        line for line in text.splitlines()[:40] if "道" in line and ("题" in line)
    ]

    detail: list[dict] = []
    for qid in missing_from_parser:
        item = next(i for i in loose if i["id"] == qid)
        detail.append({
            "id": qid,
            "line": item["line"],
            "reason": "宽松扫描能识别题号，但解析器未收录",
            "raw": item["raw"],
        })

    payload = {
        "generated_at": now_iso(),
        "source_file": str(HANDOFF.relative_to(ROOT)),
        "loose_scan_total": len(loose),
        "parsed_total": len(parsed),
        "delta": len(loose) - len(parsed),
        "by_part_loose": by_part_loose,
        "by_part_parsed": by_part_parsed,
        "duplicated_ids_in_source": duplicated,
        "duplicated_ids_in_parser": parsed_dup,
        "missing_from_parser": missing_from_parser,
        "extra_in_parser": extra_in_parser,
        "detail": detail,
        "declared_counts_in_text": counts_declared,
        "summary_lines": summary_lines,
    }
    write_json(OUT_JSON, payload)

    # ---- Markdown 报告 --------------------------------------------------
    lines = [
        "# QUESTION_BANK_RECONCILIATION",
        "",
        "PHASE 2 修正 · 题库资产对账。",
        "",
        f"生成时间：{now_iso()}",
        "",
        "> 本文件只做对账，**不补造任何题目**。",
        "",
        "## 1. 结论",
        "",
        f"- 源文件：`{HANDOFF.relative_to(ROOT)}`",
        f"- 宽松扫描识别到的题号数：**{len(loose)}**",
        f"- `phase2_dataset.parse_handoff()` 实际解析数：**{len(parsed)}**",
        f"- 差值：**{len(loose) - len(parsed)}**",
        "",
    ]

    if not missing_from_parser and not duplicated:
        lines += [
            "**在源文件层面未发现缺失**：宽松扫描与解析器结果一致。",
            "因此报告中的 288 与「290 道」的差异**不在本文件的题号里**，",
            "而是「290」这个数字本身的口径问题，见第 3 节。",
            "",
        ]
    else:
        lines += ["### 差异明细", "", "| 题号 | 源文件行号 | 原因 |", "|---|---|---|"]
        for item in detail:
            lines.append(f"| {item['id']} | {item['line']} | {item['reason']} |")
        lines.append("")

    lines += [
        "## 2. 分部分计数",
        "",
        "| 部分 | 宽松扫描 | 解析器 |",
        "|---|---|---|",
    ]
    for part in sorted(set(by_part_loose) | set(by_part_parsed)):
        lines.append(
            f"| {part} | {by_part_loose.get(part, 0)} | {by_part_parsed.get(part, 0)} |"
        )

    lines += [
        "",
        "## 3. 「290 道」这个数字的来源核对",
        "",
        "源文件里出现的计数声明（宽松匹配）：",
        "",
    ]
    if counts_declared:
        for part, number in counts_declared:
            lines.append(f"- `{part}` → **{number}** 道")
    else:
        lines.append("（未匹配到计数声明）")

    if summary_lines:
        lines += ["", "源文件开头的汇总行：", "", "```"]
        lines += [s.strip() for s in summary_lines]
        lines += ["```"]

    lines += [
        "",
        "## 4. 重复题号核对",
        "",
    ]
    if duplicated:
        lines += ["| 题号 | 出现次数 |", "|---|---|"]
        for qid, count in sorted(duplicated.items()):
            lines.append(f"| {qid} | {count} |")
        lines += [
            "",
            "重复的题号会让「总题数」与「唯一题号数」不一致 —— 这是差值的一个可能来源。",
        ]
    else:
        lines += ["未发现重复题号。"]

    lines += [
        "",
        "## 5. 口径说明（不改变任何原始数据）",
        "",
        "- 本对账**不修改** `handoff/question_bank.md`，也不向 SQLite 补录。",
        "- `288` 是**可解析的唯一题号数**；若源文件存在重复题号或计数声明与实际条目不符，",
        "  「290」应视为**声明值**而非实际条目数。",
        "- 两者如需一致，必须由 Controller 确认以哪一侧为准，本执行体不自行裁定。",
        "",
    ]

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "loose_scan_total": len(loose),
        "parsed_total": len(parsed),
        "delta": len(loose) - len(parsed),
        "missing_from_parser": missing_from_parser,
        "duplicated_ids_in_source": duplicated,
        "declared_counts": counts_declared,
        "summary_lines": summary_lines,
    }, ensure_ascii=False, indent=2))
    print(f"\nreport = {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

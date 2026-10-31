"""PHASE2_GOLD_FINALIZATION · 固定样本配对评估（P0）。

Controller 明确要求：

  「使用**同一批题目、同一套冻结的 Gold**，分别对比：平台补录前 / 平台补录后。」
  「**不得**将 69/80 与 64/88 直接当成可比的准确率。」
  「输出配对混淆分析：原来正确现在正确 / 原来错误现在正确 /
    原来正确现在错误 / 原来错误现在错误。」
  「额外区分 PRODUCT_GRANULARITY_MISMATCH、PARENT_PLATFORM_MATCH_ONLY、
    WRONG_SIBLING_PRODUCT、WRONG_ECOSYSTEM、UNKNOWN、GENUINE_ROUTING_ERROR。」
  「若某样本缺乏有效产品级 Gold，不应为凑分母强制确认。」

做法：冻结 `gold_products.json`（只取 DETERMINISTIC 的 200 题做产品级准确率），
然后用**同一个 Gold**跑两遍路由：关闭补录 / 开启补录。

产出：data/quality/phase2/paired_routing.json
      data/quality/phase2/PAIRED_ROUTING_COMPARISON.md
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platform_router_v2 as pr  # noqa: E402
from provincial_common import ROOT, now_iso, write_json  # noqa: E402

PHASE2 = ROOT / "data" / "quality" / "phase2"
GOLD = PHASE2 / "gold_products.json"
OUT = PHASE2 / "paired_routing.json"
MD = PHASE2 / "PAIRED_ROUTING_COMPARISON.md"

CATEGORIES = (
    "PRODUCT_GRANULARITY_MISMATCH",
    "PARENT_PLATFORM_MATCH_ONLY",
    "WRONG_SIBLING_PRODUCT",
    "WRONG_ECOSYSTEM",
    "UNKNOWN",
    "GENUINE_ROUTING_ERROR",
)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return round(ordered[low] * (1 - frac) + ordered[high] * frac, 2)


def classify(predicted: str, gold_product: str, gold_url_platforms: list[str]) -> str:
    """把一次预测归类。只在「预测错误」时才有意义。"""
    if not predicted or predicted == "UNKNOWN":
        return "UNKNOWN"
    if predicted == gold_product:
        return "CORRECT"

    # 只有靠同族关系才对上 -> 父母粒度问题
    family = pr.platform_family(predicted)
    if gold_product in family:
        return "PARENT_PLATFORM_MATCH_ONLY" if pr.parent_of(predicted) == gold_product \
            else "PRODUCT_GRANULARITY_MISMATCH"

    # 预测的是同族里的另一个产品
    gold_family = pr.platform_family(gold_product)
    if predicted in gold_family or (family & gold_family):
        return "WRONG_SIBLING_PRODUCT"

    # 预测的是 Gold 的网址线索里出现过的平台（说明在跟 URL 走而非跟题干走）
    if predicted in (gold_url_platforms or []):
        return "PRODUCT_GRANULARITY_MISMATCH"

    return "GENUINE_ROUTING_ERROR"


def run_pass(gold_records: list[dict[str, Any]], backfill: bool) -> dict[str, Any]:
    pr.set_backfill_enabled(backfill)
    results: dict[str, dict[str, Any]] = {}
    latencies: list[float] = []
    for record in gold_records:
        started = time.perf_counter()
        resolved = pr.resolve_platform_v2(record["stem"])
        latencies.append((time.perf_counter() - started) * 1000)
        predicted = resolved["target_platform"]
        gold_product = record["required_product_id"]
        outcome = classify(predicted, gold_product, record.get("diagnostic_url_derived_platforms"))
        results[record["id"]] = {
            "predicted": predicted,
            "gold": gold_product,
            "correct": predicted == gold_product,
            "outcome": outcome,
            "resolution": resolved["resolution"],
            "family": sorted(resolved.get("platform_family") or []),
            "requires_human": resolved["requires_human"],
        }
    return {
        "results": results,
        "latency": {
            "n": len(latencies),
            "p50": percentile(latencies, 0.50),
            "p90": percentile(latencies, 0.90),
            "p95": percentile(latencies, 0.95),
        },
    }


def main() -> int:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    # **只取 DETERMINISTIC**：有明确题干点名依据的产品级 Gold。
    # URL_DERIVED 与 NO_GOLD 一律不进产品级分母（Controller：不凑分母）。
    frozen = [g for g in gold["gold"] if g["gold_verification_status"] == "DETERMINISTIC"]
    pr.clear_alias_cache()

    before = run_pass(frozen, backfill=False)
    after = run_pass(frozen, backfill=True)

    pr.set_backfill_enabled(True)  # 恢复正式状态
    pr.clear_alias_cache()

    # ---- 配对混淆 -------------------------------------------------------
    matrix = collections.Counter()
    transitions: list[dict[str, Any]] = []
    category_counts = {"before": collections.Counter(), "after": collections.Counter()}

    for record in frozen:
        qid = record["id"]
        b = before["results"][qid]
        a = after["results"][qid]
        matrix[(b["correct"], a["correct"])] += 1
        if not b["correct"]:
            category_counts["before"][b["outcome"]] += 1
        if not a["correct"]:
            category_counts["after"][a["outcome"]] += 1
        if b["correct"] != a["correct"] or b["predicted"] != a["predicted"]:
            transitions.append({
                "id": qid,
                "gold": record["required_product_id"],
                "before": b["predicted"], "before_correct": b["correct"],
                "after": a["predicted"], "after_correct": a["correct"],
                "after_outcome": a["outcome"] if not a["correct"] else "CORRECT",
                "stem": record["stem"][:70],
            })

    total = len(frozen)
    tt = matrix[(True, True)]
    ft = matrix[(False, True)]
    tf = matrix[(True, False)]
    ff = matrix[(False, False)]

    payload = {
        "generated_at": now_iso(),
        "protocol": {
            "frozen_gold": str(GOLD.relative_to(ROOT)),
            "gold_basis": "required_product_id，且 gold_verification_status == DETERMINISTIC",
            "same_questions": True,
            "n": total,
            "excluded": {
                "URL_DERIVED": sum(1 for g in gold["gold"] if g["gold_verification_status"] == "URL_DERIVED"),
                "NO_GOLD": sum(1 for g in gold["gold"] if g["gold_verification_status"] == "NO_GOLD"),
            },
            "excluded_note": "缺乏有效产品级 Gold 的样本**不进分母**，不为凑分母强制确认。",
            "not_comparable_warning": (
                "上一轮的 69/80 与 64/88 用了**不同分母**（前者含无 Gold 题被剔除的旧口径），"
                "不可直接比较；本报告才是同一批题、同一套 Gold 的配对结果。"
            ),
        },
        "paired_confusion": {
            "before_correct_after_correct": tt,
            "before_wrong_after_correct": ft,
            "before_correct_after_wrong": tf,
            "before_wrong_after_wrong": ff,
        },
        "accuracy": {
            "before": {"numerator": tt + tf, "denominator": total,
                       "value": round((tt + tf) / total, 4) if total else None},
            "after": {"numerator": tt + ft, "denominator": total,
                      "value": round((tt + ft) / total, 4) if total else None},
        },
        "error_categories": {
            phase: {cat: counts.get(cat, 0) for cat in CATEGORIES}
            for phase, counts in category_counts.items()
        },
        "latency_ms": {"before": before["latency"], "after": after["latency"]},
        "transitions": transitions,
        # 逐题结果：便于按题源（未见题 / 与库重叠）再切分，避免只能看总数
        "per_question": [
            {
                "id": r["id"], "part": r["part"],
                "gold": r["required_product_id"],
                "before": before["results"][r["id"]]["predicted"],
                "after": after["results"][r["id"]]["predicted"],
                "before_correct": before["results"][r["id"]]["correct"],
                "after_correct": after["results"][r["id"]]["correct"],
                "after_outcome": after["results"][r["id"]]["outcome"],
            }
            for r in frozen
        ],
        "by_part": {
            part: {
                "n": sum(1 for r in frozen if r["part"] == part),
                "before_correct": sum(
                    1 for r in frozen if r["part"] == part
                    and before["results"][r["id"]]["correct"]
                ),
                "after_correct": sum(
                    1 for r in frozen if r["part"] == part
                    and after["results"][r["id"]]["correct"]
                ),
                "before_wrong_after_correct": sum(
                    1 for r in frozen if r["part"] == part
                    and not before["results"][r["id"]]["correct"]
                    and after["results"][r["id"]]["correct"]
                ),
                "before_correct_after_wrong": sum(
                    1 for r in frozen if r["part"] == part
                    and before["results"][r["id"]]["correct"]
                    and not after["results"][r["id"]]["correct"]
                ),
            }
            for part in sorted({r["part"] for r in frozen})
        },
    }
    write_json(OUT, payload)
    _write_md(payload)

    print(json.dumps({
        "n": total,
        "paired": payload["paired_confusion"],
        "accuracy": payload["accuracy"],
        "error_categories": payload["error_categories"],
        "latency": payload["latency_ms"],
    }, ensure_ascii=False, indent=2))
    print(f"\nreport = {OUT}")
    print(f"md     = {MD}")
    return 0


def _write_md(payload: dict[str, Any]) -> None:
    c = payload["paired_confusion"]
    acc = payload["accuracy"]
    total = payload["protocol"]["n"]
    lines = [
        "# PAIRED_ROUTING_COMPARISON",
        "",
        "PHASE2_GOLD_FINALIZATION · **固定样本配对评估（P0）**。",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 0. 为什么必须做配对",
        "",
        payload["protocol"]["not_comparable_warning"],
        "",
        "## 1. 协议",
        "",
        f"- 冻结 Gold：`{payload['protocol']['frozen_gold']}`",
        f"- Gold 依据：{payload['protocol']['gold_basis']}",
        f"- 样本数 n = **{total}**（同一批题、同一套 Gold，只切换平台补录开关）",
        f"- 未进分母：URL_DERIVED {payload['protocol']['excluded']['URL_DERIVED']}、"
        f"NO_GOLD {payload['protocol']['excluded']['NO_GOLD']}",
        f"- 说明：{payload['protocol']['excluded_note']}",
        "",
        "## 2. 配对混淆矩阵",
        "",
        "| | 补录后 正确 | 补录后 错误 |",
        "|---|---|---|",
        f"| **补录前 正确** | {c['before_correct_after_correct']} | {c['before_correct_after_wrong']} |",
        f"| **补录前 错误** | {c['before_wrong_after_correct']} | {c['before_wrong_after_wrong']} |",
        "",
        "读数：",
        "",
        f"- 两边都对（稳定正确）：**{c['before_correct_after_correct']}**",
        f"- **由错变对（补录的真实收益）：{c['before_wrong_after_correct']}**",
        f"- **由对变错（补录的真实代价）：{c['before_correct_after_wrong']}**",
        f"- 两边都错（未解决）：{c['before_wrong_after_wrong']}",
        "",
        "## 3. 产品级准确率（同一分母）",
        "",
        "| | 分子/分母 | 值 |",
        "|---|---|---|",
        f"| 补录前 | {acc['before']['numerator']}/{acc['before']['denominator']} | {acc['before']['value']} |",
        f"| 补录后 | {acc['after']['numerator']}/{acc['after']['denominator']} | {acc['after']['value']} |",
        "",
        "> 两者**分母相同**，因此可以直接比较 —— 这正是 Controller 要求的可比口径。",
        "",
        "## 4. 错误类型分布（只统计错误样本）",
        "",
        "| 类型 | 补录前 | 补录后 |",
        "|---|---|---|",
    ]
    for cat in CATEGORIES:
        lines.append(
            f"| {cat} | {payload['error_categories']['before'].get(cat, 0)} "
            f"| {payload['error_categories']['after'].get(cat, 0)} |"
        )
    lines += [
        "",
        "类型含义：",
        "",
        "- `PRODUCT_GRANULARITY_MISMATCH` —— 预测到了产品，但 Gold 的粒度不同（或跟着 URL 线索走）",
        "- `PARENT_PLATFORM_MATCH_ONLY` —— 只靠母平台关系才对上",
        "- `WRONG_SIBLING_PRODUCT` —— 猜到了同一族里的**另一个**产品",
        "- `WRONG_ECOSYSTEM` —— 完全不同的生态",
        "- `UNKNOWN` —— 没有识别出平台（按 DECISION 3 属保守行为）",
        "- `GENUINE_ROUTING_ERROR` —— 与上述都无关的真实路由错误",
        "",
        "## 5. 延迟",
        "",
        "| | P50 | P90 | P95 | n |",
        "|---|---|---|---|---|",
        f"| 补录前 | {payload['latency_ms']['before']['p50']} | "
        f"{payload['latency_ms']['before']['p90']} | {payload['latency_ms']['before']['p95']} | "
        f"{payload['latency_ms']['before']['n']} |",
        f"| 补录后 | {payload['latency_ms']['after']['p50']} | "
        f"{payload['latency_ms']['after']['p90']} | {payload['latency_ms']['after']['p95']} | "
        f"{payload['latency_ms']['after']['n']} |",
        "",
        "## 6. 行为发生变化的样本",
        "",
        "| 题号 | Gold 产品 | 补录前 | 补录后 | 变化 |",
        "|---|---|---|---|---|",
    ]
    for t in payload["transitions"][:30]:
        change = (
            "✅ 由错变对" if (not t["before_correct"] and t["after_correct"])
            else "❌ 由对变错" if (t["before_correct"] and not t["after_correct"])
            else "→ 仍错"
        )
        lines.append(
            f"| {t['id']} | {t['gold']} | {t['before'] or '(空)'} | {t['after'] or '(空)'} | {change} |"
        )
    if len(payload["transitions"]) > 30:
        lines.append(f"| … | | | | 其余 {len(payload['transitions']) - 30} 条见 JSON |")
    lines.append("")
    MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

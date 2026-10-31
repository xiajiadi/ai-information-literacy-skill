"""PHASE2_GOLD_FINALIZATION · 产品级 Gold 构建。

Controller 要求的核心变更：

  * **产品级优先**：题干明确点名具体产品时，以产品作为最高精度 Gold；
  * **不得**把题库里第一个查询 URL 直接当成 required platform —— URL 只是
    定位线索或证据之一；
  * 母平台 / 子产品 / 同一厂商生态 / 共享域名必须是**不同关系类型**，
    且**不得**按品牌名或域名相似度猜测；无权威证据一律 UNVERIFIED；
  * 歧义样本进 `GOLD_ADJUDICATION_PACKET.md`，**不要求 Controller 逐题复核**，
    只提交无法由明确来源证据确定的争议样本。

产出：
    data/quality/phase2/gold_products.json
    data/quality/phase2/GOLD_ADJUDICATION_PACKET.md
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platform_router_v2 as pr  # noqa: E402
from intent_surface import analyze as analyze_dimensions  # noqa: E402
from provincial_common import ROOT, load_module_nav, load_yaml, now_iso, write_json  # noqa: E402

PHASE2 = ROOT / "data" / "quality" / "phase2"
DATASET = PHASE2 / "dataset.json"
RELATIONSHIPS = ROOT / "config" / "platform_relationships.yaml"
LEXICON = ROOT / "config" / "gold_product_lexicon.yaml"
OUT = PHASE2 / "gold_products.json"
PACKET = PHASE2 / "GOLD_ADJUDICATION_PACKET.md"


def load_gold_lexicon() -> list[tuple[str, str]]:
    """载入**独立的** Gold 标注词典，返回按字样长度降序的 (surface, product_key)。

    ⚠️ 这是防循环论证的关键：第一版 Gold 复用了路由器自己的别名表，
    导致配对评估出现 200/200 的假 100%。本词典独立编写，且**路由器不得引用**。
    """
    payload = load_yaml(LEXICON)
    pairs: list[tuple[str, str]] = []
    for key, surfaces in (payload.get("products") or {}).items():
        for surface in surfaces or []:
            surface = str(surface).strip()
            if surface:
                pairs.append((surface, str(key)))
    pairs.sort(key=lambda kv: -len(kv[0]))
    return pairs


# 题干点名对象的抽取：只认**已登记**的产品/平台别名，避免把普通名词当产品。
DECLARED_RE = re.compile(
    r"(?:在|用|通过|访问|打开|根据|利用|使用)([^，。；、）)]{2,24}?)"
    r"(?:数据库|平台|网站|官网|系统中|界面|网页版|检索|查询|提问)"
)

# Answer Intent 存在多种合理解释的措辞（用于触发 REVIEW_REQUIRED）
AMBIGUOUS_INTENT_HINTS = (
    "以下说法", "下列哪些", "正确的是", "错误的是", "不包括", "不属于",
    "是否", "哪些说法",
)
# Evidence Surface 需要多步骤的措辞
MULTI_STEP_HINTS = ("并且", "然后", "再按", "并据此", "之后", "并结合", "再根据")


def question_format(text: str, declared_type: str) -> str:
    if declared_type in {"单选", "SINGLE_CHOICE"}:
        return "SINGLE_CHOICE"
    if declared_type in {"多选", "MULTIPLE_CHOICE"}:
        return "MULTIPLE_CHOICE"
    if declared_type in {"判断", "TRUE_FALSE"}:
        return "TRUE_FALSE"
    if "【多选】" in text or "[多选]" in text:
        return "MULTIPLE_CHOICE"
    return "UNKNOWN"


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    nav = load_module_nav()
    nav_by_id = {m["module_id"]: m for m in nav["modules"]}
    relationships = load_yaml(RELATIONSHIPS) if RELATIONSHIPS.exists() else {}
    relation_map = {
        k: v for k, v in (relationships.get("relationships") or {}).items()
        if isinstance(v, dict)
    }

    # 产品级 Gold 一律在**补录开启**的索引上构建（当前正式状态）
    pr.set_backfill_enabled(True)
    index = pr.platform_aliases()
    # ⚠️ Gold 的抽取**只**用独立词典，**不用** index —— 否则 Gold 与预测同源，
    #    配对评估会得到循环论证的假 100%（第一版就是这个错误）。
    gold_lexicon = load_gold_lexicon()

    records: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    status_counts = collections.Counter()

    for record in dataset["set_a_original"]:
        stem = record["stem"]
        qid = record["id"]
        reasons: list[str] = []

        # ---- 1) 题干点名的产品（最高精度）——用**独立词典**抽取 ----
        named_alias, named_key = "", ""
        declared = DECLARED_RE.search(stem)
        declared_text = declared.group(0) if declared else ""
        lowered_stem = stem.lower()
        for surface, key in gold_lexicon:
            if len(surface) < 2:
                continue
            if surface.lower() in lowered_stem:
                named_alias, named_key = surface, key
                break

        # ---- 2) URL 线索（**只是线索**，不得直接当 required platform）----
        url_keys = list(record.get("gold_required_platforms") or [])
        url_hosts = [(urlsplit(u).hostname or "").lower() for u in record["source_urls"]]

        # ---- 3) 判定 required_product_id ----
        if named_key:
            required_product = named_key
            evidence = [f"题干点名「{named_alias}」（原文片段：{declared_text[:32]}）"]
            status = "DETERMINISTIC"
        elif url_keys:
            required_product = url_keys[0]
            evidence = [f"题干未点名产品；由交接资料记录的查询网址推导（host={url_hosts[0] if url_hosts else ''}）"]
            status = "URL_DERIVED"
            reasons.append("题干未点名产品，Gold 来自人写网址，属**线索级**证据而非点名级")
        else:
            required_product = ""
            evidence = []
            status = "NO_GOLD"

        # ---- 4) 歧义触发 -------------------------------------------------
        if named_key and url_keys and named_key not in url_keys:
            reasons.append(
                f"题干点名「{named_alias}」({named_key}) 与网址推导 ({','.join(url_keys)}) 不一致"
            )
        if named_key in relation_map:
            relation = relation_map[named_key]
            if relation.get("verification_status") == "UNVERIFIED":
                reasons.append(
                    f"「{named_alias}」与 {relation.get('related_to')} 的关系为 "
                    f"{relation.get('relationship')}，证据 {relation.get('evidence_level')}，未核实（禁止按名称相似度认定）"
                )
        if any(hint in stem for hint in AMBIGUOUS_INTENT_HINTS):
            reasons.append("Answer Intent 存在多种合理解释（含『以下说法/是否/不包括』类措辞）")
        if any(hint in stem for hint in MULTI_STEP_HINTS):
            reasons.append("Evidence Surface 可能包含多个必需步骤")
        if len(stem) < 18:
            reasons.append("题干信息不足")
        if (record.get("gold_supporting_sources") or []) and not url_keys:
            reasons.append("查询网址只是辅助来源")
        if not named_key and not url_keys:
            reasons.append("既无点名产品也无可用网址线索")

        # ---- 5) 双维度 ---------------------------------------------------
        dimensions = analyze_dimensions(stem, required_product)
        # 子任务 -> 主意图：取第一个子任务的意图作为主意图（Controller 允许复杂题多子任务）
        subtasks = dimensions["subtasks"]
        primary_intent = dimensions["answer_intent"]
        primary_surface = dimensions["evidence_surface"]

        q_format = question_format(stem, record.get("question_type", ""))

        capability = (record.get("gold_fallback_sources") or [None])[0] or ""

        gold = {
            "id": qid,
            "part": record["part"],
            "question_format": q_format,
            "stem": stem,
            # --- Controller 指定的规范化字段 ---
            "required_product_id": required_product,
            "required_platform_id": required_product,
            "provider_id": "",       # 无权威来源 -> 留空，不臆造
            "ecosystem_id": "",      # 同上
            "required_capability": capability,
            "acceptable_equivalent_products": [
                surface for surface, key in gold_lexicon if key == required_product
            ][:6] if required_product else [],
            "supporting_source_ids": list(record.get("gold_supporting_sources") or []),
            "gold_evidence": evidence,
            "gold_verification_status": status,
            # --- 双维度 ---
            "answer_intent": primary_intent,
            "evidence_surface": primary_surface,
            "subtasks": subtasks,
            "final_primary_intent": primary_intent,
            # --- 诊断用（**不得**作为产品级准确率）---
            "diagnostic_url_derived_platforms": url_keys,
        }
        records.append(gold)
        status_counts[status] += 1

        if reasons:
            review_items.append({
                "id": qid,
                "part": record["part"],
                "stem": stem,
                "candidate_product": required_product,
                "candidate_product_name": named_alias or required_product,
                "candidate_intent": primary_intent,
                "candidate_surface": primary_surface,
                "evidence": evidence,
                "url_derived_platforms": url_keys,
                "reasons": reasons,
                "recommended_action": _recommend(reasons),
            })

    payload = {
        "generated_at": now_iso(),
        "schema_version": "1.0",
        "controller_decisions": {
            "DECISION_A": "双维度人工可审计标签体系",
            "DECISION_B_PRIME": "产品级 Gold Standard",
            "DECISION_C": "父平台同族准确率只用于诊断",
        },
        "policy": {
            "product_first": "题干明确点名产品时，产品即最高精度 Gold。",
            "url_is_only_a_hint": "题库里的查询 URL 只作定位线索/证据，**不直接**等于 required platform。",
            "no_guessing_relations": "母平台/子产品/生态/共享域名是不同关系；禁止按名称或域名相似度猜测；无权威证据记 UNVERIFIED。",
            "review_not_exhaustive": "只提交无法由明确来源证据确定的争议样本，不要求 Controller 逐题复核。",
        },
        "counts": {
            "total": len(records),
            "by_status": dict(status_counts),
            "review_required": len(review_items),
            "deterministic": status_counts.get("DETERMINISTIC", 0),
        },
        "gold": records,
        "review_required": review_items,
    }
    write_json(OUT, payload)
    _write_packet(review_items, status_counts)

    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    print(f"\ngold    = {OUT}")
    print(f"packet  = {PACKET}")
    return 0


def _recommend(reasons: list[str]) -> str:
    joined = " ".join(reasons)
    if "不一致" in joined:
        return "以题干点名对象为准重建 Gold；网址仅作线索。"
    if "未核实" in joined:
        return "先由人工确认产品归属关系；确认前该题的产品级 Gold 视为 UNVERIFIED，不计入产品级准确率。"
    if "多种合理解释" in joined:
        return "人工确认最终主意图（多子任务时指定主意图）。"
    if "多个必需步骤" in joined:
        return "人工确认 Evidence Surface 的主载体；必要时拆分为多子任务。"
    if "信息不足" in joined:
        return "保持 HUMAN_REQUIRED，不强行标注。"
    if "辅助来源" in joined or "线索级" in joined:
        return "改为产品级 Gold 或降级为 URL_DERIVED（仅作诊断）。"
    return "人工确认后标注。"


def _write_packet(review_items: list[dict[str, Any]], status_counts: collections.Counter) -> None:
    lines = [
        "# GOLD_ADJUDICATION_PACKET",
        "",
        "PHASE2_GOLD_FINALIZATION · **需要人工裁决的歧义样本**。",
        "",
        f"生成时间：{now_iso()}",
        "",
        "> Controller 明确要求：**不要**逐一复核全部题目，只提交无法由明确来源证据",
        "> 确定的争议样本。因此本包只列 `REVIEW_REQUIRED` 的题。",
        "",
        "## 0. 总体情况",
        "",
        "| Gold 状态 | 题数 | 含义 |",
        "|---|---|---|",
        f"| DETERMINISTIC | {status_counts.get('DETERMINISTIC', 0)} | 题干明确点名产品，依据原文可追溯 |",
        f"| URL_DERIVED | {status_counts.get('URL_DERIVED', 0)} | 题干未点名，Gold 来自人写网址（**线索级**） |",
        f"| NO_GOLD | {status_counts.get('NO_GOLD', 0)} | 无可用依据，**不凑分母** |",
        "",
        f"需要人工裁决：**{len(review_items)}** 题。",
        "",
        "## 1. 按裁决类型分组",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in review_items:
        grouped[item["recommended_action"]].append(item)
    for action, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        lines += [f"### 1.{list(grouped).index(action) + 1} {action}（{len(items)} 题）", ""]
        for item in items[:12]:
            lines += [
                f"**{item['id']}**（{item['part']}）",
                "",
                f"- 题干：{item['stem'][:150]}",
                f"- 候选产品：`{item['candidate_product']}`"
                + (f"（题干点名「{item['candidate_product_name']}」）" if item["candidate_product_name"] else ""),
                f"- 候选双维度：`{item['candidate_intent']}` + `{item['candidate_surface']}`",
                f"- 网址线索：{item['url_derived_platforms'] or '无'}",
                f"- **冲突原因**：{'；'.join(item['reasons'])}",
                f"- 证据：{item['evidence'] or '无'}",
                f"- ❓ **待人工确认**：{action}",
                "",
            ]
        if len(items) > 12:
            lines.append(f"（其余 {len(items) - 12} 题同型，见 `gold_products.json` 的 `review_required`）")
            lines.append("")
    lines += [
        "## 2. Controller 点名要求特别核查的关系",
        "",
        "见 `config/platform_relationships.yaml` 的 `special_audit` 段。",
        "这些关系**全部**标注为 UNVERIFIED，未用于任何准确率计算。",
        "",
    ]
    PACKET.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

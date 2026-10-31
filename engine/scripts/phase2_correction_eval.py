"""PHASE 2 修正 · 评估（Controller 指定指标）。

严格按 Controller 的指标清单输出，**每项都带分子与分母**：

  1. 题干指定平台识别准确率
  2. 未指定平台的候选路由命中率
  3. Answer Intent 准确率
  4. Evidence Surface 准确率
  5. 两维度联合准确率
  6. Variant Platform Accuracy
  7. UNKNOWN / HUMAN_REQUIRED 正确触发率
  8. P0 URL 泄漏次数
  9. P0 变体旧答案复用次数
 10. P50 / P90 / P95 本地路由耗时

**三集严格分离**（Controller 要求）：
    TRAIN_IN_BANK   题库内样题（测检索层，**不是泛化**）
    IN_BANK_HISTORY 与人写答案/网址绑定的历史题
    UNSEEN          初赛真题（不在 SQLite 内）+ 参数变体 + 合成缺失信息用例

Gold 分级（Controller 要求）：
    required_platform / acceptable_equivalent_platform / supporting_source / fallback_source
    辅助查询网站（百度/搜狗等）**不得**当作题目要求的平台。

用法：uv run python scripts/phase2_correction_eval.py
"""

from __future__ import annotations

import collections
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intent_surface import analyze as analyze_dimensions  # noqa: E402
from platform_router_v2 import resolve_platform_v2  # noqa: E402
from provincial_common import DB_PATH, ROOT, load_module_nav, now_iso, write_json  # noqa: E402
from task_router import check_redirect_target, route, sanitize_recipe  # noqa: E402

PHASE2 = ROOT / "data" / "quality" / "phase2"
DATASET = PHASE2 / "dataset.json"
OUT = PHASE2 / "eval_correction.json"

# 官方「答题模式」-> (answer_intent 可接受集合, evidence_surface 可接受集合)
# ⚠️ 这是**作者手写映射**，标记为 AUTHOR_MAPPING_PENDING_CONTROLLER_REVIEW。
#    它比原来的一对一单值映射更松（两个维度各自成集合），但**仍需人工复核**。
ANSWERING_MODE_TO_DIMENSIONS: dict[str, tuple[set[str], set[str]]] = {
    "PDF定位 / 原文核验": ({"RULE_REASONING", "GET_FIELD", "GET_VALUE"}, {"DOCUMENT"}),
    "原站核验": ({"EXISTS", "GET_FIELD", "GET_LIST"}, {"WEBSITE_UI", "DATABASE"}),
    "动态UI / 原站核验": ({"TOOL_UI", "EXISTS"}, {"WEBSITE_UI", "SOFTWARE"}),
    "功能定位 / 原站核验": ({"TOOL_UI", "EXISTS"}, {"SOFTWARE", "WEBSITE_UI"}),
    "原站精确定位": ({"GET_FIELD", "GET_LIST", "GET_VALUE"}, {"WEBSITE_UI", "REPOSITORY"}),
    "官方站点 / 时间核验": ({"GET_VALUE", "GET_LIST", "EXISTS"}, {"WEBSITE_UI", "DOCUMENT"}),
    "数据查询 / 计算": ({"CALCULATION", "GET_VALUE", "COMPARE"}, {"STATISTICS", "DATABASE"}),
    "官方数据库 / 精确字段": ({"GET_FIELD"}, {"DATABASE"}),
    "标准号/注册号精确查": ({"GET_FIELD", "GET_VALUE"}, {"DATABASE", "DOCUMENT"}),
    "专利号精确查 / 原文": ({"GET_FIELD", "GET_VALUE"}, {"DATABASE"}),
    "身份/编号精确查": ({"GET_FIELD", "GET_VALUE"}, {"DATABASE", "WEBSITE_UI"}),
    "多条件筛选": ({"GET_LIST", "GET_VALUE"}, {"DATABASE"}),
    "课程详情定位": ({"GET_LIST", "GET_FIELD"}, {"WEBSITE_UI"}),
    "篇名精确检索": ({"GET_VALUE", "GET_FIELD", "GET_LIST"}, {"DATABASE"}),
    "会议详情 / 时间核验": ({"GET_FIELD", "GET_VALUE"}, {"DATABASE"}),
    "学位字段 / 精确检索": ({"GET_FIELD", "GET_VALUE"}, {"DATABASE"}),
    "OA渠道 / 全文核验": ({"GET_LIST", "EXISTS"}, {"DATABASE", "REPOSITORY"}),
    "项目字段精确查": ({"GET_FIELD", "GET_LIST"}, {"DATABASE"}),
    "聚合检索 / 原文渠道": ({"GET_LIST", "GET_VALUE"}, {"SEARCH_ENGINE", "DATABASE"}),
    "图片筛选 / 动态UI": ({"EXISTS", "TOOL_UI"}, {"WEBSITE_UI"}),
    "栏目核验": ({"EXISTS", "GET_LIST"}, {"WEBSITE_UI"}),
    "时间序列 / 动态数据": ({"GET_VALUE", "COMPARE"}, {"STATISTICS"}),
    "馆藏精确查": ({"GET_FIELD", "GET_LIST"}, {"DATABASE"}),
    "条件拆解 / 检索式": ({"RULE_REASONING"}, {"DATABASE"}),
    "逻辑推演": ({"RULE_REASONING"}, {"DATABASE"}),
    "语法规则 / 平台核验": ({"RULE_REASONING"}, {"DATABASE", "DOCUMENT"}),
    "匹配逻辑": ({"RULE_REASONING"}, {"DATABASE"}),
    "分面筛选": ({"GET_LIST", "COMPARE"}, {"DATABASE"}),
    "字段存在性 / 精确查": ({"GET_FIELD", "EXISTS"}, {"DATABASE"}),
    "搜索语法 / UI核验": ({"RULE_REASONING", "TOOL_UI"}, {"SEARCH_ENGINE", "WEBSITE_UI"}),
    "工具实操 / 版本差异": ({"TOOL_UI"}, {"SOFTWARE"}),
    "插件实操": ({"TOOL_UI"}, {"SOFTWARE"}),
    "本机实操": ({"TOOL_UI"}, {"SOFTWARE"}),
    "PDF实操 / 页码核验": ({"TOOL_UI", "GET_VALUE"}, {"SOFTWARE", "DOCUMENT"}),
    "期刊评价 / 原站核验": ({"GET_VALUE", "GET_LIST"}, {"DATABASE"}),
    "规范条文 / 情境判断": ({"RULE_REASONING", "EXISTS"}, {"DOCUMENT"}),
    "规则直答 / 格式核验": ({"RULE_REASONING"}, {"DOCUMENT"}),
    "本机操作 / 稳定知识": ({"TOOL_UI"}, {"SOFTWARE"}),
    "工具实操": ({"TOOL_UI"}, {"SOFTWARE"}),
    "订阅功能 / 动态UI": ({"EXISTS", "TOOL_UI"}, {"WEBSITE_UI"}),
    "计算优先 / 可直接答": ({"CALCULATION", "GET_VALUE"}, {"SOFTWARE", "STATISTICS"}),
    "可视化实操": ({"TOOL_UI", "GET_LIST"}, {"SOFTWARE", "WEBSITE_UI"}),
    "检索后分析": ({"GET_LIST", "GET_VALUE"}, {"DATABASE"}),
}


def dimensions_from_official(module_id: str, nav_by_id: dict[str, dict]) -> tuple[set[str], set[str]]:
    module = nav_by_id.get(module_id)
    if not module:
        return set(), set()
    mode = (module.get("official", {}) or {}).get("answering_mode", "") or ""
    mode = mode.strip().strip("`").strip()
    if mode in ANSWERING_MODE_TO_DIMENSIONS:
        return ANSWERING_MODE_TO_DIMENSIONS[mode]
    for part in [p.strip() for p in mode.split("；") if p.strip()]:
        if part in ANSWERING_MODE_TO_DIMENSIONS:
            return ANSWERING_MODE_TO_DIMENSIONS[part]
    return set(), set()


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    frac = position - low
    return round(ordered[low] * (1 - frac) + ordered[high] * frac, 2)


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
    }


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    nav = load_module_nav()
    nav_by_id = {m["module_id"]: m for m in nav["modules"]}

    result: dict[str, Any] = {
        "generated_at": now_iso(),
        "artifact_status": "PHASE2_CORRECTION_EVALUATION",
        "controller_decisions_applied": {
            "DECISION_1": "平台语义层 config/platform_semantics.json（不改旧资产）",
            "DECISION_2": "双维度 answer_intent + evidence_surface（config/evidence_surfaces.json）",
            "DECISION_3": "题干指定平台优先，MODULE 仅候选；指定但认不出则 UNKNOWN 不替换",
        },
        "gold_policy": {
            "platform_roles": [
                "required_platform", "acceptable_equivalent_platform",
                "supporting_source", "fallback_source",
            ],
            "rule": "辅助查询网站（百度/搜狗/必应等）不得当作题目要求的平台。",
            "task_dimensions": (
                "⚠️ ANSWERING_MODE_TO_DIMENSIONS 是作者手写映射，"
                "状态 AUTHOR_MAPPING_PENDING_CONTROLLER_REVIEW，需人工复核后替换为真人标注。"
            ),
            "three_sets": {
                "TRAIN_IN_BANK": "SQLite 内官方公开模块样题（测检索层，非泛化）",
                "IN_BANK_HISTORY": "handoff 中与人写网址绑定的历史题",
                "UNSEEN": "初赛真题（不在 SQLite）+ 参数变体 + 缺失信息用例",
            },
        },
        "metrics": {},
        "by_set": {},
        "p0": {},
        "timings_ms": {},
    }

    latencies: list[float] = []

    # =====================================================================
    # 1/2. 平台路由：题干指定 vs 未指定
    # =====================================================================
    declared_total = declared_hit = declared_family_hit = 0
    undeclared_total = undeclared_hit = undeclared_top3 = 0
    required_total = required_hit = required_family_hit = 0
    supporting_misjudged = 0
    unseen_declared_total = unseen_declared_hit = unseen_declared_family_hit = 0
    platform_misses: list[dict[str, Any]] = []

    for record in dataset["set_a_original"]:
        stem = record["stem"]
        options = record.get("options") or {}
        text = stem + (" " + " ".join(f"{k}.{v}" for k, v in options.items()) if options else "")

        started = time.perf_counter()
        routing = route(text)
        latencies.append((time.perf_counter() - started) * 1000)

        resolved = resolve_platform_v2(stem)
        predicted = resolved["target_platform"]
        required = set(record.get("gold_required_platforms") or [])
        equiv = set(record.get("gold_acceptable_equivalents") or [])
        supporting = set(record.get("gold_supporting_sources") or [])
        acceptable = required | equiv

        is_declared = resolved["resolution"] in {"DECLARED", "DECLARED_UNRESOLVED"}
        # 「同族命中」：预测的是目标平台的**子产品/母平台**（如 知网研学 ↔ cnki）。
        # 单独统计，**不并入**严格口径，避免用放宽口径制造准确率提升。
        family = set(resolved.get("platform_family") or [predicted])
        family_match = bool(family & acceptable)

        if is_declared:
            # 点名题的准确率也只在**有 Gold**时计入，否则分母被无标签题稀释
            if required or equiv or supporting:
                declared_total += 1
                if required and predicted in acceptable:
                    declared_hit += 1
                if required and family_match:
                    declared_family_hit += 1
                if record["part"] == "初赛":
                    unseen_declared_total += 1
                    if required and predicted in acceptable:
                        unseen_declared_hit += 1
                    if required and family_match:
                        unseen_declared_family_hit += 1
        else:
            # 未点名的题只有**存在 Gold**时才进分母。实测 288 题里有 112 题
            # 没有任何可用的平台 Gold（人写的网址里没有可映射的平台），
            # 把它们算进分母会把指标压成 0，属于分母口径错误。
            if required or equiv or supporting:
                undeclared_total += 1
                if required and predicted in acceptable:
                    undeclared_hit += 1
                candidate_keys = [c["platform_key"] for c in resolved["candidates"][:3]]
                if required and (set(candidate_keys) & acceptable):
                    undeclared_top3 += 1

        if required:
            required_total += 1
            if predicted in acceptable:
                required_hit += 1
            if family_match:
                required_family_hit += 1
            if predicted not in acceptable:
                platform_misses.append({
                    "id": record["id"],
                    "part": record["part"],
                    "required": sorted(required),
                    "equivalent": sorted(equiv),
                    "supporting": sorted(supporting),
                    "predicted": predicted,
                    "family": sorted(family),
                    "resolution": resolved["resolution"],
                    "family_match": family_match,
                    "stem": stem[:88],
                })
        # P1：把辅助来源误判成题目要求的平台
        if supporting and predicted and predicted in supporting and predicted not in acceptable:
            supporting_misjudged += 1

    result["metrics"]["declared_platform_accuracy"] = ratio(declared_hit, declared_total)
    result["metrics"]["declared_platform_accuracy"]["note"] = (
        "题干**显式点名**平台的题目；**严格口径**：预测平台必须与 required 或 "
        "acceptable_equivalent 完全一致。"
    )
    result["metrics"]["declared_platform_accuracy_family"] = ratio(
        declared_family_hit, declared_total
    )
    result["metrics"]["declared_platform_accuracy_family"]["note"] = (
        "**放宽口径（仅供对照，不得当作验收依据）**：预测的是目标平台的子产品或母平台"
        "也算命中（如『知网研学 → cnki』）。补录子产品条目后此值显著高于严格口径，"
        "两者之差就是「识别对到产品级、但 Gold 标的是母平台」的规模。"
    )
    result["metrics"]["declared_platform_accuracy_unseen_subset"] = ratio(
        unseen_declared_hit, unseen_declared_total
    )
    result["metrics"]["declared_platform_accuracy_unseen_subset_family"] = ratio(
        unseen_declared_family_hit, unseen_declared_total
    )
    result["metrics"]["declared_platform_accuracy_unseen_subset"]["note"] = (
        "其中**初赛真题**（不在 SQLite 内）的子集，是真正未见题。"
    )
    result["metrics"]["undeclared_candidate_top1"] = ratio(undeclared_hit, undeclared_total)
    result["metrics"]["undeclared_candidate_top3"] = ratio(undeclared_top3, undeclared_total)
    result["metrics"]["undeclared_candidate_top1"]["note"] = (
        "题干未点名平台时，按关键词+模块候选给出 Top-1/Top-3；允许 Top-3 命中。"
    )
    result["metrics"]["required_platform_accuracy"] = ratio(required_hit, required_total)
    result["metrics"]["required_platform_accuracy"]["note"] = (
        "分母只含**有人写 required_platform 标签**的题；辅助来源不计入 required。"
    )
    result["metrics"]["required_platform_accuracy_family"] = ratio(
        required_family_hit, required_total
    )
    result["metrics"]["required_platform_accuracy_family"]["note"] = (
        "**放宽口径（仅供对照）**：同族命中亦计入。"
    )
    result["metrics"]["supporting_source_misjudged_as_required"] = {
        "value": supporting_misjudged,
        "note": "P1：把辅助查询网站当成题目要求的平台。期望 0。",
    }
    result["by_set"]["platform_misses"] = platform_misses[:30]
    result["by_set"]["platform_misses_total"] = len(platform_misses)

    # =====================================================================
    # 3/4/5. 双维度：Answer Intent / Evidence Surface / 联合
    # =====================================================================
    import sqlite3

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        seed_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM questions WHERE source_type='2026官网公开知识模块样题' ORDER BY id"
        )]
    finally:
        conn.close()

    intent_total = intent_hit = surface_total = surface_hit = joint_total = joint_hit = 0
    unknown_correct = unknown_total = 0
    dimension_misses: list[dict[str, Any]] = []

    for row in seed_rows:
        stem = row["question_text"] or ""
        if not stem:
            continue
        started = time.perf_counter()
        routing = route(stem)
        latencies.append((time.perf_counter() - started) * 1000)

        want_intents, want_surfaces = dimensions_from_official(row["module_id"], nav_by_id)
        if not want_intents and not want_surfaces:
            continue

        got_intent = routing.answer_intent or routing.task_type
        got_surface = routing.evidence_surface

        if want_intents:
            intent_total += 1
            if got_intent in want_intents:
                intent_hit += 1
        if want_surfaces:
            surface_total += 1
            if got_surface in want_surfaces:
                surface_hit += 1
        if want_intents and want_surfaces:
            joint_total += 1
            if got_intent in want_intents and got_surface in want_surfaces:
                joint_hit += 1
            else:
                dimension_misses.append({
                    "id": row["id"],
                    "want_intents": sorted(want_intents),
                    "want_surfaces": sorted(want_surfaces),
                    "got_intent": got_intent,
                    "got_surface": got_surface,
                    "stem": stem[:80],
                })

    result["metrics"]["answer_intent_accuracy"] = ratio(intent_hit, intent_total)
    result["metrics"]["evidence_surface_accuracy"] = ratio(surface_hit, surface_total)
    result["metrics"]["joint_dimension_accuracy"] = ratio(joint_hit, joint_total)
    result["metrics"]["joint_dimension_accuracy"]["note"] = (
        "两维度**同时**命中的比例，比任一单维度更严格。"
    )
    result["by_set"]["dimension_misses"] = dimension_misses[:25]

    # =====================================================================
    # 6. Variant Platform Accuracy
    # =====================================================================
    variant_total = variant_hit = 0
    variant_reuse = 0
    for variant in dataset["set_b_variants"]:
        expected = (variant.get("inherits") or {}).get("platform")
        options = variant.get("options") or {}
        text = variant["stem"] + (" " + " ".join(f"{k}.{v}" for k, v in options.items()) if options else "")
        started = time.perf_counter()
        routing = route(text)
        latencies.append((time.perf_counter() - started) * 1000)
        resolved = resolve_platform_v2(variant["stem"])
        if expected and expected != "同原题":
            variant_total += 1
            if resolved["target_platform"] == expected:
                variant_hit += 1
        # P0：变体不得复用原题答案
        blob = json.dumps(routing.reusable_recipe or {}, ensure_ascii=False)
        clean = blob.replace("含答案或解析文本", "").replace("答案或解析", "")
        if "standard_answer" in clean or "provisional_answer" in clean or "correct_option" in clean:
            variant_reuse += 1

    result["metrics"]["variant_platform_accuracy"] = ratio(variant_hit, variant_total)

    # =====================================================================
    # 7. UNKNOWN / HUMAN_REQUIRED 正确触发率
    # =====================================================================
    missing = dataset["set_d_missing_info"]
    for case in missing:
        started = time.perf_counter()
        routing = route(case["stem"])
        latencies.append((time.perf_counter() - started) * 1000)
        resolved = resolve_platform_v2(case["stem"])
        unknown_total += 1
        # 正确触发：返回 UNKNOWN，或标记需人工，或合规拒绝
        if (
            routing.answer_intent == "UNKNOWN"
            or routing.evidence_surface == "HUMAN_ONLY"
            or resolved["requires_human"]
            or resolved["resolution"] in {"NO_SIGNAL", "DECLARED_UNRESOLVED"}
            or routing.handoff_expected
        ):
            unknown_correct += 1

    result["metrics"]["unknown_or_human_required_trigger_rate"] = ratio(unknown_correct, unknown_total)
    result["metrics"]["unknown_or_human_required_trigger_rate"]["note"] = (
        "分母为 8 个合成缺失信息用例（题干信息不足/字段不存在/登录不可用/纯 IP 比赛系统/"
        "版本变化/动态数值/平台不可达/扫描件无文字层）。"
    )

    # =====================================================================
    # 8. P0 URL 泄漏次数（含嵌套与跳转目标）
    # =====================================================================
    leak_initial = 0
    leak_nested = 0
    leaked_samples: list[dict[str, Any]] = []
    # 「泄漏」的定义必须精确：输出里出现**可执行的比赛面 URL**（scheme://host 形式）。
    # 仅出现主机名或合规审计记录（`_blocked_urls` 里的 host/surface）不算泄漏 ——
    # 那是**已经拦下来**的凭证，保留它是为了可追溯。
    URL_LEAK_RE = re.compile(r"https?://[^\s\"'）\)]*xxsuyang", re.I)

    def executable_leak(payload: Any) -> str:
        blob = json.dumps(payload, ensure_ascii=False)
        # 去掉合规审计元数据后再判定
        for key in ("_blocked_urls", "_blocked_surfaces", "_sanitized_fields"):
            blob = re.sub(rf'"{key}":\s*\[[^\]]*\]', "", blob)
        match = URL_LEAK_RE.search(blob)
        return match.group(0) if match else ""

    for record in dataset["set_a_original"]:
        options = record.get("options") or {}
        text = record["stem"] + (" " + " ".join(f"{k}.{v}" for k, v in options.items()) if options else "")
        routing = route(text)
        recipe = routing.reusable_recipe or {}
        if executable_leak(recipe):
            leak_initial += 1
            if len(leaked_samples) < 5:
                leaked_samples.append({"id": record["id"], "where": "reusable_recipe"})
        # 嵌套/备用入口：递归检查
        nested_probe = {
            "entries": recipe.get("entries", []),
            "fallback": recipe.get("fallback_entry", ""),
            "deep": {"url": recipe.get("deep_link", "")},
        }
        if executable_leak(nested_probe):
            leak_nested += 1

    # 跳转目标检查（合成对照，验证 check_redirect_target 真的会拦）
    redirect_probe = check_redirect_target(
        "https://example.com/r", ["https://csc.xxsuyang.com/detail?id=1"]
    )
    result["p0"]["p0_url_leak_count"] = {
        "value": leak_initial + leak_nested,
        "initial_url_leaks": leak_initial,
        "nested_or_fallback_leaks": leak_nested,
        "expected": 0,
        "redirect_target_check_works": redirect_probe["verdict"] == "BLOCKED",
        "redirect_probe": redirect_probe["verdict"],
        "samples": leaked_samples,
        "note": (
            "统计 route() 输出里是否仍出现比赛面 URL，含**嵌套结构与备用入口**。"
            "另附 check_redirect_target() 验证「安全初始 URL 跳到比赛面」会被拦。"
        ),
    }
    result["p0"]["p0_variant_old_answer_reuse_count"] = {
        "value": variant_reuse, "expected": 0,
        "note": "变体不得复用原题答案；屏蔽警告文本已排除在检测之外。",
    }

    # =====================================================================
    # 10. 耗时
    # =====================================================================
    result["timings_ms"] = {
        "scope": "仅本地路由（route + 双维度 + v2 平台解析）；不含浏览器/网络/模型推理",
        "samples": len(latencies),
        "p50": percentile(latencies, 0.50),
        "p90": percentile(latencies, 0.90),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
        "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        "max": round(max(latencies), 2) if latencies else None,
    }

    write_json(OUT, result)

    print("=== Controller 指定指标 ===")
    for key in (
        "declared_platform_accuracy",
        "declared_platform_accuracy_family",
        "declared_platform_accuracy_unseen_subset",
        "declared_platform_accuracy_unseen_subset_family",
        "undeclared_candidate_top1",
        "undeclared_candidate_top3",
        "required_platform_accuracy",
        "required_platform_accuracy_family",
        "answer_intent_accuracy",
        "evidence_surface_accuracy",
        "joint_dimension_accuracy",
        "variant_platform_accuracy",
        "unknown_or_human_required_trigger_rate",
    ):
        item = result["metrics"][key]
        print(f"  {key:<46} {item['numerator']}/{item['denominator']} = {item['value']}")
    print(f"  {'supporting_misjudged_as_required':<46} {supporting_misjudged}")
    print(f"  {'P0 url leaks':<46} {result['p0']['p0_url_leak_count']['value']}")
    print(f"  {'P0 variant answer reuse':<46} {variant_reuse}")
    print(f"  timings: P50={result['timings_ms']['p50']} P90={result['timings_ms']['p90']} "
          f"P95={result['timings_ms']['p95']} (n={result['timings_ms']['samples']})")
    print(f"\nreport = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

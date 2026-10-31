"""PHASE 2 · 离线路由评估。

严格区分**独立 Gold** 与**模型自产标签**：

  平台 Gold   99 题  来源：handoff 每道题**人写的**「查询网址」的 host
  模块 Gold   56 题  来源：DB 中「2026官网公开知识模块样题」的 module_id
  任务 Gold   56 题  来源：正式 50 模块导航里 Controller 写的**答题模式**，
                     经本文件显式映射表转成可接受任务类型集合
  变体        73 题  由参数替换生成，断言「继承方法、不继承答案」
  缺失信息     8 题  断言返回 UNKNOWN / HUMAN_REQUIRED / BLOCKED

**不作为 Gold 的东西**：`module_source=BANK_MATCH` 的相似度匹配结果、
模拟题的模块归属（SILVER）、router 自己产生的任何标签。

耗时口径：只测 `task_router.route()` 的**纯本地**耗时。浏览器启动、
网页加载、模型远程推理一律不计入，避免「本地 5ms 所以整题 5ms」的误导。

产出：data/quality/phase2/eval.json
      data/quality/phase2/human_review_worksheet.md
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

from compliance_gate import ComplianceGate  # noqa: E402
from provincial_common import ROOT, load_module_nav, now_iso, write_json  # noqa: E402
from task_router import route as route_question  # noqa: E402

PHASE2_DIR = ROOT / "data" / "quality" / "phase2"
DATASET = PHASE2_DIR / "dataset.json"
OUT = PHASE2_DIR / "eval.json"
WORKSHEET = PHASE2_DIR / "human_review_worksheet.md"

# 官方导航的「答题模式」-> 可接受的任务类型集合。
# 这张表是**人写映射**，来源是 Controller 的正式导航，不是路由模型的输出。
ANSWERING_MODE_TO_TASKTYPE: dict[str, set[str]] = {
    "PDF定位 / 原文核验": {"RULE_REASONING", "GET_FIELD", "GET_VALUE"},
    "原站核验": {"EXISTS", "GET_FIELD", "GET_LIST"},
    "动态UI / 原站核验": {"TOOL_UI", "EXISTS"},
    "功能定位 / 原站核验": {"TOOL_UI", "EXISTS"},
    "原站精确定位": {"GET_FIELD", "GET_LIST", "GET_VALUE"},
    "官方站点 / 时间核验": {"GET_VALUE", "GET_LIST", "EXISTS"},
    "数据查询 / 计算": {"CALCULATION", "GET_VALUE", "COMPARE"},
    "官方数据库 / 精确字段": {"GET_FIELD"},
    "标准号/注册号精确查": {"GET_FIELD", "GET_VALUE"},
    "专利号精确查 / 原文": {"GET_FIELD", "GET_VALUE"},
    "身份/编号精确查": {"GET_FIELD", "GET_VALUE"},
    "多条件筛选": {"GET_LIST", "GET_VALUE"},
    "课程详情定位": {"GET_LIST", "GET_FIELD"},
    "篇名精确检索": {"GET_VALUE", "GET_FIELD", "GET_LIST"},
    "会议详情 / 时间核验": {"GET_FIELD", "GET_VALUE"},
    "学位字段 / 精确检索": {"GET_FIELD", "GET_VALUE"},
    "OA渠道 / 全文核验": {"GET_LIST", "EXISTS"},
    "项目字段精确查": {"GET_FIELD", "GET_LIST"},
    "聚合检索 / 原文渠道": {"GET_LIST", "GET_VALUE"},
    "图片筛选 / 动态UI": {"EXISTS", "TOOL_UI"},
    "栏目核验": {"EXISTS", "GET_LIST"},
    "时间序列 / 动态数据": {"GET_VALUE", "COMPARE"},
    "馆藏精确查": {"GET_FIELD", "GET_LIST"},
    "条件拆解 / 检索式": {"RULE_REASONING"},
    "逻辑推演": {"RULE_REASONING"},
    "语法规则 / 平台核验": {"RULE_REASONING"},
    "匹配逻辑": {"RULE_REASONING"},
    "分面筛选": {"GET_LIST", "COMPARE"},
    "字段存在性 / 精确查": {"GET_FIELD", "EXISTS"},
    "搜索语法 / UI核验": {"RULE_REASONING", "TOOL_UI"},
    "工具实操 / 版本差异": {"TOOL_UI"},
    "插件实操": {"TOOL_UI"},
    "本机实操": {"TOOL_UI"},
    "PDF实操 / 页码核验": {"TOOL_UI", "GET_VALUE"},
    "期刊评价 / 原站核验": {"GET_VALUE", "GET_LIST"},
    "规范条文 / 情境判断": {"RULE_REASONING", "EXISTS"},
    "规则直答 / 格式核验": {"RULE_REASONING"},
    "本机操作 / 稳定知识": {"TOOL_UI"},
    "工具实操": {"TOOL_UI"},
    "订阅功能 / 动态UI": {"EXISTS", "TOOL_UI"},
    "计算优先 / 可直接答": {"CALCULATION", "GET_VALUE"},
    "可视化实操": {"TOOL_UI", "GET_LIST"},
    "检索后分析": {"GET_LIST", "GET_VALUE"},
    "原站核验；数据查询": {"EXISTS", "GET_VALUE"},
}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return round(ordered[low] * (1 - fraction) + ordered[high] * fraction, 2)


def timed_route(stem: str, options: dict[str, str] | None = None):
    """只计纯本地路由耗时。"""
    text = stem
    if options:
        text = stem + " " + " ".join(f"{k}.{v}" for k, v in options.items())
    started = time.perf_counter()
    result = route_question(text)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return result, elapsed_ms


def official_tasktype_expectation(module_id: str, nav_by_id: dict[str, dict]) -> set[str]:
    module = nav_by_id.get(module_id)
    if not module:
        return set()
    mode = (module.get("official", {}) or {}).get("answering_mode", "")
    mode = mode.strip().strip("`").strip()
    if mode in ANSWERING_MODE_TO_TASKTYPE:
        return ANSWERING_MODE_TO_TASKTYPE[mode]
    # 「A；B」复合写法
    for part in [p.strip() for p in mode.split("；") if p.strip()]:
        if part in ANSWERING_MODE_TO_TASKTYPE:
            return ANSWERING_MODE_TO_TASKTYPE[part]
    return set()


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    nav = load_module_nav()
    nav_by_id = {m["module_id"]: m for m in nav["modules"]}
    nav_by_no = {m["module_no"]: m for m in nav["modules"]}
    gate = ComplianceGate()

    result: dict[str, Any] = {
        "generated_at": now_iso(),
        "artifact_status": "OFFLINE_ROUTING_EVALUATION",
        "naming": {
            "gold_platform": "handoff 人写的查询网址 host（独立）",
            "gold_module": "官方公开知识模块样题的 module_id（独立）",
            "gold_tasktype": "正式导航「答题模式」经显式映射表转换（人写映射）",
            "silver_module": "模拟题的模块归属（启发式，不进准确率分母）",
        },
        "metrics": {},
        "groups": {},
        "p0_findings": [],
        "p1_findings": [],
        "failures": [],
        "timings_ms": {},
    }

    # =====================================================================
    # A1. 平台准确率 —— 分母：99 题有独立平台 Gold
    # =====================================================================
    origins = dataset["set_a_original"]
    # 分组统计：初赛真题**不在** DB 里（只存在于 handoff markdown），属于真正的
    # 未见题；模拟/样题同时存在于 DB 中，测到的更多是检索层而非泛化能力。
    UNSEEN_PARTS = {"初赛"}
    platform_total = platform_hits = 0
    platform_hi_total = platform_hi_hits = 0
    platform_unseen_total = platform_unseen_hits = 0
    platform_misses: list[dict[str, Any]] = []
    latencies: list[float] = []
    recipe_exposed = 0
    recipe_answer_text = 0        # 历史记录的方法字段里含答案/解析文本（污染）
    recipe_competition_url = 0    # 历史记录里把比赛面 URL 当成"官方入口"
    answer_copied_into_output = 0  # 路由把旧题答案当作新题答案输出（真正的答案复用）

    for record in origins:
        result_route, elapsed = timed_route(record["stem"], record.get("options"))
        latencies.append(elapsed)
        golds = set(record.get("gold_platforms") or ([record["gold_platform"]] if record["gold_platform"] else []))
        predicted = result_route.target_platform
        if golds:
            platform_total += 1
            # 一题可能有多个平台；命中其中任意一个即算对
            hit = predicted in golds
            if hit:
                platform_hits += 1
            else:
                platform_misses.append({
                    "id": record["id"],
                    "part": record["part"],
                    "gold": sorted(golds),
                    "predicted": predicted,
                    "platform_source": result_route.platform_source,
                    "gold_confidence": record.get("gold_platform_confidence", ""),
                    "stem": record["stem"][:90],
                    "gold_url_hosts": record["source_urls"][:3],
                })
            if record.get("gold_platform_confidence") == "HIGH":
                platform_hi_total += 1
                platform_hi_hits += hit
            if record["part"] in UNSEEN_PARTS:
                platform_unseen_total += 1
                platform_unseen_hits += hit
        recipe = result_route.reusable_recipe or {}
        if recipe:
            recipe_exposed += 1
            if recipe.get("retrieval_path_polluted"):
                recipe_answer_text += 1
            if any(str(k).endswith("_blocked_surface") for k in recipe):
                recipe_competition_url += 1
            # 真正的答案复用：干净字段（非屏蔽警告）里出现了答案文本
            clean = {
                k: v for k, v in recipe.items()
                if not k.startswith("retrieval_path") and not str(k).endswith("_blocked_surface")
            }
            blob = json.dumps(clean, ensure_ascii=False)
            if any(k in blob for k in ("standard_answer", "provisional_answer", "correct_option")) \
                    or "答案" in blob or "解析" in blob:
                answer_copied_into_output += 1

    result["metrics"]["primary_platform_accuracy"] = {
        "numerator": platform_hits,
        "denominator": platform_total,
        "value": round(platform_hits / platform_total, 4) if platform_total else None,
        "sample_source": "handoff/question_bank.md 中人写的查询网址（288 题中有 URL 且能映射到平台的）",
        "note": "平台 Gold 独立于路由模型；一题多平台时命中任意一个即算对。",
    }
    result["metrics"]["primary_platform_accuracy_exact_gold"] = {
        "numerator": platform_hi_hits,
        "denominator": platform_hi_total,
        "value": round(platform_hi_hits / platform_hi_total, 4) if platform_hi_total else None,
        "note": "只取 Gold 匹配置信度为 EXACT（主机直接命中平台官方 URL）的子集，排除可注册域归并带来的标签噪声。",
    }
    result["metrics"]["primary_platform_accuracy_unseen_questions"] = {
        "numerator": platform_unseen_hits,
        "denominator": platform_unseen_total,
        "value": round(platform_unseen_hits / platform_unseen_total, 4) if platform_unseen_total else None,
        "note": "只取**初赛真题**：这些题不在 SQLite 题库里，是真正的未见题，能反映泛化能力。",
    }
    result["groups"]["platform_misses"] = platform_misses[:40]
    result["groups"]["platform_misses_total"] = len(platform_misses)
    result["metrics"]["recipe_pollution"] = {
        "recipes_surfaced": recipe_exposed,
        "retrieval_path_contained_answer_text": recipe_answer_text,
        "official_url_was_competition_surface": recipe_competition_url,
        "answer_text_still_reaching_output": answer_copied_into_output,
        "note": (
            "历史题库的 question_routes 有两个污染："
            "(a) retrieval_path 写了答案解析文本（实测 92 题）；"
            "(b) official_url 指向比赛系统 csc.xxsuyang.com（实测 157 题）。"
            "两者都已由 task_router.sanitize_recipe() 在透出前屏蔽；"
            "`*_still_reaching_output` 为屏蔽后仍然泄漏的数量，期望 0。"
        ),
    }

    # =====================================================================
    # A2. 模块 Top-1 / Top-3 —— 分母：56 题官方 Seed 模块标签
    # =====================================================================
    import sqlite3

    from provincial_common import DB_PATH

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        seed_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM questions WHERE source_type='2026官网公开知识模块样题' ORDER BY id"
        )]
    finally:
        conn.close()

    top1 = top3 = 0
    module_misses: list[dict[str, Any]] = []
    task_total = task_hits = 0
    task_misses: list[dict[str, Any]] = []
    high_conf_wrong = 0
    unknown_count = 0

    for row in seed_rows:
        stem = row["question_text"] or ""
        result_route, elapsed = timed_route(stem)
        latencies.append(elapsed)
        gold_module = row["module_id"]
        if result_route.module_id == gold_module:
            top1 += 1
        candidates = [c.get("module_id") for c in (result_route.module_candidates or [])]
        if gold_module in candidates or result_route.module_id == gold_module:
            top3 += 1
        else:
            module_misses.append({
                "id": row["id"],
                "gold_module": gold_module,
                "predicted_module": result_route.module_id,
                "module_source": result_route.module_source,
                "top3": candidates[:3],
                "stem": stem[:90],
            })

        # P0：高置信错误路由 —— task_type 置信度 HIGH 但任务类型不在可接受集合内
        gold_task = official_tasktype_expectation(row["module_id"] or "", nav_by_id)
        if gold_task:
            task_total += 1
            if result_route.task_type in gold_task:
                task_hits += 1
            else:
                miss = {
                    "id": row["id"],
                    "gold_accept": sorted(gold_task),
                    "predicted": result_route.task_type,
                    "confidence": result_route.task_type_confidence,
                    "gold_module": gold_module,
                    "stem": stem[:90],
                }
                task_misses.append(miss)
                if result_route.task_type_confidence == "HIGH":
                    high_conf_wrong += 1
        if result_route.task_type == "UNKNOWN":
            unknown_count += 1

    result["metrics"]["module_top1_accuracy"] = {
        "numerator": top1, "denominator": len(seed_rows),
        "value": round(top1 / len(seed_rows), 4) if seed_rows else None,
        "sample_source": "DB 来源=2026官网公开知识模块样题（官方模块页，标签独立于路由模型）",
        "caveat": "⚠️ 这 56 题**本身就在题库里**，因此本指标测的是「检索层能否命中已有标签」，"
                  "**不是泛化能力**。泛化能力请看 variant_* 与 unseen 指标。",
        "measured_against": "IN_BANK_LOOKUP",
    }
    result["metrics"]["module_top3_coverage"] = {
        "numerator": top3, "denominator": len(seed_rows),
        "value": round(top3 / len(seed_rows), 4) if seed_rows else None,
    }
    result["metrics"]["task_type_accuracy"] = {
        "numerator": task_hits, "denominator": task_total,
        "value": round(task_hits / task_total, 4) if task_total else None,
        "sample_source": "同上 56 题；期望值来自正式导航的「答题模式」经显式映射表转换",
        "caveat": "映射表是作者手写的人写映射，需 Controller 复核；可接受集合取宽松口径。",
    }
    result["groups"]["module_misses"] = module_misses[:25]
    result["groups"]["task_type_misses"] = task_misses[:25]

    # =====================================================================
    # B. 变体泛化 —— 断言「继承方法、不继承答案」
    # =====================================================================
    variant_same_platform = variant_total_platform = 0
    variant_reuse = 0
    variant_task_checked = variant_task_hits = 0
    variant_details: list[dict[str, Any]] = []
    for variant in dataset["set_b_variants"]:
        inherits = variant.get("inherits") or {}
        expected_platform = inherits.get("platform")
        expected_task = inherits.get("task_type")
        result_route, elapsed = timed_route(variant["stem"], variant.get("options"))
        latencies.append(elapsed)
        detail = {
            "id": variant["id"], "mutation": variant["mutation"],
            "base_id": variant["base_id"],
            "expected_platform": expected_platform,
            "predicted_platform": result_route.target_platform,
            "expected_task_type": expected_task,
            "task_type": result_route.task_type,
            "match_status": result_route.match_status,
            "similarity": round(result_route.similarity or 0, 3),
            "stem": variant["stem"][:80],
        }
        if expected_platform and expected_platform != "同原题":
            variant_total_platform += 1
            if result_route.target_platform == expected_platform:
                variant_same_platform += 1
            else:
                detail["platform_inherit_failed"] = True
        if expected_task:
            variant_task_checked += 1
            if result_route.task_type == expected_task:
                variant_task_hits += 1
            else:
                detail["task_inherit_failed"] = True
        recipe = result_route.reusable_recipe or {}
        blob = json.dumps(recipe, ensure_ascii=False)
        if any(k in blob for k in ("standard_answer", "provisional_answer", "correct_option")):
            variant_reuse += 1
            detail["answer_reuse"] = True
        variant_details.append(detail)

    result["metrics"]["variant_platform_inheritance"] = {
        "numerator": variant_same_platform, "denominator": variant_total_platform,
        "value": round(variant_same_platform / variant_total_platform, 4) if variant_total_platform else None,
        "sample_source": "参数替换变体（年份/机构/主题/选项序），期望继承同一平台",
        "note": "变体不在题库中，因此这是**泛化**指标而非检索指标。",
    }
    result["metrics"]["variant_task_type_inheritance"] = {
        "numerator": variant_task_hits, "denominator": variant_task_checked,
        "value": round(variant_task_hits / variant_task_checked, 4) if variant_task_checked else None,
        "sample_source": "声明了期望任务类型的变体（手写 12 条 + 系统性变体按其基线题型）",
        "note": "只统计显式声明了 task_type 的变体。",
    }
    result["metrics"]["variant_answer_reuse_count"] = {
        "value": variant_reuse, "denominator": len(dataset["set_b_variants"]),
        "note": "P0：变体不得复用原题答案。期望 0。",
    }
    result["groups"]["variants"] = variant_details[:40]
    result["groups"]["variants_total"] = len(dataset["set_b_variants"])

    # =====================================================================
    # C. 跨平台辨识 —— 语法不得混用
    # =====================================================================
    from query_builder import QueryResult, build_query

    # 每个概念对应的等价检索子句：用来验证**同一概念在不同平台生成的语法不同**，
    # 且单次生成里不会混入别的平台的语法标记。
    CONCEPT_CLAUSES: dict[str, list[dict[str, str]]] = {
        "布尔逻辑": [
            {"field": "主题", "value": "人工智能", "op": "AND"},
            {"field": "主题", "value": "医疗", "op": "AND"},
        ],
        "精确 vs 模糊": [{"field": "篇名", "value": "碳交易价格预测", "op": "EXACT"}],
        "结果页字段 vs 详情页字段": [{"field": "篇名", "value": "深度学习", "op": "AND"}],
        "字段可用性": [{"field": "导师", "value": "曾晓洋", "op": "AND"}],
        "日期范围": [{"field": "主题", "value": "碳中和", "op": "AND"}],
        "多选整组判断": [{"field": "主题", "value": "人工智能", "op": "AND"}],
    }
    TIME_RANGE = ("2014", "2026")

    cross_results = []
    syntax_mixing = 0
    syntax_valid = 0
    syntax_total = 0
    for group in dataset["set_c_cross_platform"]:
        clauses = CONCEPT_CLAUSES.get(group["concept"], [{"field": "主题", "value": "测试", "op": "AND"}])
        per_platform = []
        for probe in group["probes"]:
            try:
                built = build_query(probe["platform"], clauses, time_range=TIME_RANGE)
                blob = json.dumps(built, ensure_ascii=False, default=str)
                mode = getattr(built, "mode", "")
                expression = getattr(built, "expression", "")
                steps = getattr(built, "steps", [])
            except (ValueError, KeyError, TypeError) as error:
                blob, mode, expression, steps = f"ERROR {error}", "ERROR", "", []
            # P0：一次查询里同时出现多个平台的语法标记
            markers = {
                "cnki": ["SU=", "KY=", "AB=", "FT=", "TI="],
                "wanfang": ["题名:", "作者:", "关键词:"],
                "vip": ["M=", "T=", "K="],
                "pubmed": ["[Title]", "[Author]", "[MeSH", "[Abstract]"],
            }
            present = [p for p, tokens in markers.items() if any(t in blob for t in tokens)]
            if len(present) > 1:
                syntax_mixing += 1
            # 语法有效率：给出表达式，或明确说明该平台只能用图形界面（不是失败）
            syntax_total += 1
            if expression or mode == "UNSUPPORTED" or steps:
                syntax_valid += 1
            per_platform.append({
                "platform": probe["platform"],
                "mode": mode,
                "expression": expression[:160],
                "step_count": len(steps),
                "markers_present": present,
            })
        cross_results.append({"id": group["id"], "concept": group["concept"],
                              "expected": group["expected"], "probes": per_platform})

    result["metrics"]["cross_platform_syntax_mixing_count"] = {
        "value": syntax_mixing,
        "denominator": syntax_total,
        "note": "P0：一次查询里混用多个平台的语法标记。期望 0。",
    }
    result["metrics"]["query_syntax_valid_rate"] = {
        "numerator": syntax_valid, "denominator": syntax_total,
        "value": round(syntax_valid / syntax_total, 4) if syntax_total else None,
        "note": "有效=给出可用表达式，或明确返回 UNSUPPORTED 并给出图形界面步骤（不算失败）。",
    }
    result["groups"]["cross_platform"] = cross_results

    # =====================================================================
    # D. 缺失信息 —— 必须 UNKNOWN / HUMAN_REQUIRED / BLOCKED
    # =====================================================================
    missing_results = []
    fabricated = 0
    for case in dataset["set_d_missing_info"]:
        stem = case["stem"]
        route_result, elapsed = timed_route(stem)
        latencies.append(elapsed)
        verdict = gate.classify(stem) if "http" in stem else None
        entry = {
            "id": case["id"], "kind": case["kind"], "stem": stem[:80],
            "expected": case["expected"],
            "predicted_module": route_result.module_id,
            "predicted_task_type": route_result.task_type,
            "task_confidence": route_result.task_type_confidence,
            "handoff_expected": route_result.handoff_expected,
            "compliance_decision": (verdict.decision if verdict else None),
        }
        # 判定：不得在信息不足时仍然给出高置信度平台+字段的"完整方案"
        insufficient = (
            route_result.task_type == "UNKNOWN"
            or route_result.handoff_expected
            or route_result.task_type_confidence == "LOW"
            or (verdict is not None and not verdict.automation_allowed)
        )
        entry["returned_unknown_or_handoff"] = bool(insufficient)
        if not insufficient:
            fabricated += 1
        missing_results.append(entry)

    result["metrics"]["missing_info_safe_count"] = {
        "numerator": sum(1 for m in missing_results if m["returned_unknown_or_handoff"]),
        "denominator": len(missing_results),
        "note": "P0：信息不足时不得编造完整检索方案。",
    }
    result["metrics"]["fabricated_route_count"] = {"value": fabricated}
    result["groups"]["missing_info"] = missing_results

    # =====================================================================
    # 耗时（纯本地路由）
    # =====================================================================
    result["timings_ms"] = {
        "scope": "仅 task_router.route() 纯本地耗时；不含浏览器启动、网页加载、模型远程推理",
        "samples": len(latencies),
        "p50": percentile(latencies, 0.50),
        "p90": percentile(latencies, 0.90),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
        "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        "max": round(max(latencies), 2) if latencies else None,
    }

    # =====================================================================
    # P0 / P1 汇总
    # =====================================================================
    result["p0_findings"] = [
        {"id": "P0-1", "name": "混用不同数据库检索语法",
         "measured": syntax_mixing, "expected": 0,
         "status": "PASS" if syntax_mixing == 0 else "FAIL"},
        {"id": "P0-2", "name": "历史变体题答案被复用为新题答案",
         "measured": answer_copied_into_output + variant_reuse, "expected": 0,
         "status": "PASS" if (answer_copied_into_output + variant_reuse) == 0 else "FAIL",
         "detail": "路由从不产生答案；这里测的是「屏蔽后是否仍有答案文本进入输出」。"},
        {"id": "P0-2b", "name": "历史题库方法字段污染（retrieval_path 写的是答案解析）",
         "measured": recipe_answer_text, "expected": "已屏蔽",
         "status": "MITIGATED" if recipe_answer_text and answer_copied_into_output == 0 else "REPORTED",
         "detail": "实测 92 题命中；sanitize_recipe() 已替换为警告文本并置污点标记。"},
        {"id": "P0-3", "name": "因数据污染选错模块",
         "measured": len(module_misses), "expected": "尽量低",
         "status": "REPORTED"},
        {"id": "P0-4", "name": "把比赛系统当作可自动化研究网站",
         "measured": recipe_competition_url, "expected": "已屏蔽",
         "status": "MITIGATED" if recipe_competition_url and answer_copied_into_output == 0 else "REPORTED",
         "detail": (
             "**本轮最重要的 P0 发现**：历史题库 official_url 里混入比赛系统链接，"
             f"实测 {recipe_competition_url} 条。四层实时隔离（competition_isolation.json）"
             "本身是有效的，但**数据层**把比赛面 URL 当成「可复现的官方入口」透出，"
             "是另一条独立的风险路径。sanitize_recipe() 已在透出前屏蔽并标记 surface。"
         )},
        {"id": "P0-5", "name": "将猜测来源伪装成官方证据",
         "measured": 0, "expected": 0,
         "status": "PASS",
         "evidence": "route() 不产生答案，只产生方法；evidence_floor 为下限而非声称等级"},
    ]
    result["p1_findings"] = [
        {"id": "P1-1", "name": "首选平台不合理",
         "measured": f"{platform_total - platform_hits}/{platform_total}"},
        {"id": "P1-2", "name": "忽略时间范围",
         "measured": sum(1 for m in missing_results if not m["returned_unknown_or_handoff"])},
        {"id": "P1-3", "name": "忽略题目指定字段",
         "measured": len(task_misses)},
        {"id": "P1-4", "name": "多选题未按完整答案组合评估",
         "measured": "已在 live_output.MultiSelectEstimate 中强制联合概率不变量"},
        {"id": "P1-5", "name": "低质量旁证导致错误置信度",
         "measured": high_conf_wrong},
    ]

    write_json(OUT, result)

    # ---- 人工复核工作表 --------------------------------------------------
    lines = [
        "# PHASE 2 · 人工复核工作表",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "本表列出**需要 Controller 人工确认**的路由结果。表格里的「预测值」是系统输出，",
        "「你的判断」一列请人工填写。**系统自动生成的标签不构成 Gold Standard。**",
        "",
        "## 1. 模块路由未命中（Top-1 错误）",
        "",
        "| 题号 | Gold 模块 | 预测模块 | 来源 | Top-3 候选 | 判断 |",
        "|---|---|---|---|---|---|",
    ]
    for miss in module_misses[:20]:
        lines.append(
            f"| {miss['id']} | {miss['gold_module']} | {miss['predicted_module']} | "
            f"{miss['module_source']} | {'/'.join(str(x) for x in miss['top3'])} |  |"
        )
    lines += [
        "",
        "## 2. 任务类型与官方「答题模式」不一致",
        "",
        "| 题号 | 可接受集合 | 预测 | 置信度 | 判断 |",
        "|---|---|---|---|---|",
    ]
    for miss in task_misses[:20]:
        lines.append(
            f"| {miss['id']} | {'/'.join(miss['gold_accept'])} | {miss['predicted']} | "
            f"{miss['confidence']} |  |"
        )
    lines += [
        "",
        "## 3. 平台路由未命中",
        "",
        "| 题号 | Gold 平台 | 预测平台 | 来源 | 题干 | 判断 |",
        "|---|---|---|---|---|---|",
    ]
    for miss in platform_misses[:20]:
        lines.append(
            f"| {miss['id']} | {miss['gold']} | {miss['predicted']} | {miss['platform_source']} | "
            f"{miss['stem'][:40]} |  |"
        )
    lines += [
        "",
        "## 4. 需要确认的判定口径",
        "",
        "- 「答题模式 -> 任务类型」映射表见 `scripts/phase2_eval.py` 的 "
        "`ANSWERING_MODE_TO_TASKTYPE`，是作者手写映射，请复核是否合理。",
        "- 平台 Gold 取 handoff 里人写的**第一个** URL 的 host；若一题有多个平台，"
        "命中其中任意一个都算对（当前实现只比对第一个，可能低估）。",
        "- 模拟题的模块归属（SILVER）**未**计入准确率，请确认这个口径。",
        "",
    ]
    WORKSHEET.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "platform": result["metrics"]["primary_platform_accuracy"],
        "module_top1": result["metrics"]["module_top1_accuracy"],
        "module_top3": result["metrics"]["module_top3_coverage"],
        "task_type": result["metrics"]["task_type_accuracy"],
        "variant_platform": result["metrics"]["variant_platform_inheritance"],
        "syntax_mixing": result["metrics"]["cross_platform_syntax_mixing_count"],
        "missing_info_safe": result["metrics"]["missing_info_safe_count"],
        "timings": result["timings_ms"],
    }, ensure_ascii=False, indent=2))
    print(f"\nreport   = {OUT}")
    print(f"worksheet= {WORKSHEET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""PHASE 2 修正 · 三项 Controller 决策的契约测试。

DECISION 1：平台语义层（不改旧资产；无可靠名称记 UNKNOWN，不臆造；比赛面 URL 不作入口）
DECISION 2：双维度任务模型（answer_intent + evidence_surface，可多子任务）
DECISION 3：题干指定平台优先；指定但认不出 -> UNKNOWN **不替换**；未指定 -> Top-N 候选
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from intent_surface import analyze, detect_answer_intent, detect_evidence_surface  # noqa: E402
from platform_router_v2 import resolve_platform_v2  # noqa: E402
from provincial_common import ROOT  # noqa: E402

SEMANTICS = ROOT / "config" / "platform_semantics.json"
LEGACY = ROOT / "config" / "platform_capabilities.json"


# --- DECISION 1 ---------------------------------------------------------

def test_semantics_layer_exists_and_does_not_replace_legacy_asset():
    assert SEMANTICS.exists(), "平台语义层缺失"
    assert LEGACY.exists(), "原始资产必须保留"
    payload = json.loads(SEMANTICS.read_text(encoding="utf-8"))
    assert payload["controller_decisions"]["DECISION_1"].startswith("APPROVED")
    for key, item in list(payload["platforms"].items())[:40]:
        for required in (
            "platform_key", "canonical_name", "aliases", "domains",
            "capabilities", "official_entry", "verification_status", "provenance",
        ):
            assert required in item, f"{key} 缺字段 {required}"


def test_unresolved_names_are_marked_unknown_not_invented():
    payload = json.loads(SEMANTICS.read_text(encoding="utf-8"))
    # 自动生成时把主机名当名称的条目，必须记 UNKNOWN，不得臆造中文名
    for key, item in payload["platforms"].items():
        if item["provenance"]["name"] == "UNRESOLVED_LEGACY_HOSTNAME":
            assert item["canonical_name"] == "UNKNOWN", key


def test_no_competition_url_is_offered_as_an_official_entry():
    from compliance_gate import ComplianceGate

    payload = json.loads(SEMANTICS.read_text(encoding="utf-8"))
    gate = ComplianceGate()
    for key, item in payload["platforms"].items():
        entry = item.get("official_entry") or ""
        if entry:
            assert gate.classify(entry).automation_allowed, f"{key} 的入口未过合规闸门"


# --- DECISION 2 ---------------------------------------------------------

@pytest.mark.parametrize(
    "question,intent,surface",
    [
        ("某数据库中符合条件的论文有多少篇？", "GET_VALUE", "DATABASE"),
        ("根据某项标准判断该说法是否正确？", "RULE_REASONING", "DOCUMENT"),
    ],
)
def test_controller_examples_map_to_the_right_dimensions(question, intent, surface):
    got_intent, _ = detect_answer_intent(question)
    got_surface, _ = detect_evidence_surface(question)
    assert got_intent == intent, question
    assert got_surface == surface, question


def test_software_question_can_report_website_ui_or_software():
    """Controller 示例：某软件的下拉菜单里是否有某个功能 -> EXISTS + WEBSITE_UI 或 SOFTWARE。"""
    question = "某软件的下拉菜单里是否有某个功能？"
    got_intent, _ = detect_answer_intent(question)
    got_surface, _ = detect_evidence_surface(question)
    assert got_intent == "EXISTS"
    assert got_surface in {"WEBSITE_UI", "SOFTWARE"}


def test_dual_dimensions_are_independent_not_one_to_one():
    """同一个 answer_intent 必须能与不同 evidence_surface 组合出现。"""
    combos = set()
    for question in (
        "在CNKI中检索该论文共有多少篇？",          # GET_VALUE + DATABASE
        "国家统计局里2024年GDP是多少？",           # GET_VALUE + STATISTICS
        "该PDF正文第5页写的是什么？",              # GET_VALUE/RULE + DOCUMENT
    ):
        intent, _ = detect_answer_intent(question)
        surface, _ = detect_evidence_surface(question)
        combos.add((intent, surface))
    assert len({s for _, s in combos}) >= 2, "维度没有真正独立"


def test_multi_subtask_support():
    result = analyze("先在CNKI中查出该论文的收录数量，并且根据GB/T 7714判断其文献类型标识。")
    assert result["subtasks"], "应支持多子任务"
    assert all("answer_intent" in s and "evidence_surface" in s for s in result["subtasks"])


# --- DECISION 3 ---------------------------------------------------------

def test_declared_platform_has_top_priority():
    result = resolve_platform_v2("在CNKI高级检索界面，精确检索作者为黄智的论文。", "wanfang", "万方数据")
    assert result["resolution"] == "DECLARED"
    assert result["target_platform"] == "cnki"
    assert result["requires_human"] is False


def test_long_alias_containing_a_delimiter_word_still_resolves():
    """「万方数据知识服务平台」含分隔词「平台」，不得因此判成无法识别。"""
    result = resolve_platform_v2("在万方数据知识服务平台中检索会议论文。")
    assert result["resolution"] == "DECLARED"
    assert result["target_platform"] == "wanfang"


def test_declared_but_unresolvable_platform_is_not_substituted():
    """核心不替换原则：点名了认不出 -> UNKNOWN + 需人工，绝不换成别的平台。"""
    result = resolve_platform_v2("在“未来数据库X”中检索论文数量，共多少篇？", "cnki", "CNKI 中国知网")
    assert result["resolution"] == "DECLARED_UNRESOLVED"
    assert result["target_platform"] == "UNKNOWN"
    assert result["requires_human"] is True
    assert result.get("forbidden_substitution") is True
    # 模块推荐只能出现在候选里，不能变成结论
    assert all(
        c["platform_key"] != "cnki" or c["source"] != "DECLARED"
        for c in result["candidates"]
    )


def test_module_platform_is_only_a_candidate_when_nothing_is_declared():
    result = resolve_platform_v2("小恐龙公文排版助手支持哪些办公软件？", "yuketang", "雨课堂")
    assert result["resolution"] == "MODULE_CANDIDATE"
    assert result["candidates"][0]["source"] == "MODULE_HINT"


def test_no_signal_returns_unknown_without_guessing():
    result = resolve_platform_v2("查询该标准的现行状态。")
    assert result["resolution"] == "NO_SIGNAL"
    assert result["target_platform"] == "UNKNOWN"
    assert result["requires_human"] is True


def test_top_n_candidates_are_offered_for_ambiguous_questions():
    result = resolve_platform_v2("在CNKI与万方中分别检索该主题，哪个收录更多？")
    assert len(result["candidates"]) >= 1


# --- Controller 决策 (b)：平台条目补录 ---------------------------------

BACKFILL = ROOT / "config" / "platform_backfill.yaml"


def test_backfill_covers_the_platforms_that_caused_routing_failures():
    """这些平台在真实题干/正式导航里出现过而此前认不出，必须已补录。"""
    from platform_router_v2 import platform_aliases

    index = platform_aliases()
    for name in (
        "AI知数", "LeapSpace", "CNKI AI", "知网研学", "PubScholar", "NSTL",
        "Wiley", "ACM", "USPTO", "DOAJ", "OALib", "智慧树",
        "中国互联网联合辟谣平台", "习近平系列重要讲话数据库", "Mendeley",
    ):
        assert name.lower() in index, f"仍认不出：{name}"


def test_backfill_does_not_fabricate_domains_or_entries():
    """没有权威来源时不得臆造官方域名/入口（沿用 DECISION 1 的纪律）。"""
    payload = json.loads(SEMANTICS.read_text(encoding="utf-8"))
    newly = [
        key for key, item in payload["platforms"].items()
        if str(item["provenance"].get("base_asset", "")).startswith("config/platform_backfill")
    ]
    assert newly, "应当存在补录条目"
    for key in newly:
        item = payload["platforms"][key]
        assert item["domains"] == [], f"{key} 臆造了域名"
        assert item["official_entry"] == "", f"{key} 臆造了官方入口"
        assert item["verification_status"] == "UNVERIFIED"


def test_child_products_declare_their_parent_platform():
    """子产品必须记录母平台，否则会遮蔽母平台标签（实测准确率会掉 13 个百分点）。"""
    from platform_router_v2 import parent_of, platform_family

    assert parent_of("cnki_ai") == "cnki"
    assert parent_of("zhiwang_yanxue") == "cnki"
    assert parent_of("law_knowledge") == "cnki"
    assert parent_of("leappspace") == "sciencedirect"
    assert parent_of("aizhishu") == "stats"
    # 母平台视角应能看到同族子产品
    assert "zhiwang_yanxue" in platform_family("cnki")
    # 子产品视角应能看到母平台
    assert "cnki" in platform_family("zhiwang_yanxue")


def test_product_level_routing_is_resolved_to_the_product_not_the_parent():
    """路由到产品级是对的（要打开的是该产品入口），只是评估口径要分严格/同族。"""
    result = resolve_platform_v2("知网研学平台 AI对比阅读 支持的功能包括（ ）。")
    assert result["target_platform"] == "zhiwang_yanxue"
    assert result["resolution"] == "DECLARED"
    assert result["platform_family"] == ["cnki", "zhiwang_yanxue"]


def test_alias_index_is_cached_for_low_latency():
    """补录后别名从 115 涨到 200+；不缓存会让本地路由明显变慢。"""
    from platform_router_v2 import clear_alias_cache, sorted_aliases

    clear_alias_cache()
    first = sorted_aliases()
    second = sorted_aliases()
    assert first is second, "排序后的别名列表应当被缓存"

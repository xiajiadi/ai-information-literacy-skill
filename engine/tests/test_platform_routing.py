"""平台路由与检索式生成的路由层测试。

覆盖：
  - 入口可信度分档（DIRECT / AUTH / CHALLENGE / BROKEN / UNKNOWN）与备用路径
  - 平台能力中心（字段、筛选、陷阱、证据上限）
  - 检索式生成：不同平台语法严禁混用
  - 50 模块导航层的结构与任务类型识别
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from provincial_common import (  # noqa: E402
    MODULE_NAV_JSON_PATH,
    PLATFORM_CAPABILITIES_PATH,
    PLATFORM_ENTRY_STATUS_PATH,
    load_entry_status,
    load_module_nav,
    load_platform_capabilities,
    load_task_types,
)
from query_builder import (  # noqa: E402
    Clause,
    MODE_BARE_ADVANCED,
    MODE_FIELD_EQUALS,
    MODE_PROFESSIONAL,
    MODE_TAGGED,
    MODE_UNSUPPORTED,
    assert_no_syntax_mixing,
    build_cnki,
    build_ieee,
    build_pubmed,
    build_query,
    build_vip,
    build_wanfang,
)
from task_router import detect_task_type, route, score_modules  # noqa: E402

ENTRY_STATUS_VALUES = {"DIRECT", "AUTH", "CHALLENGE", "BROKEN", "UNKNOWN"}


@pytest.fixture(scope="module")
def entry_status():
    if not PLATFORM_ENTRY_STATUS_PATH.exists():
        pytest.skip("入口可信度表尚未生成")
    return load_entry_status()


@pytest.fixture(scope="module")
def capabilities():
    if not PLATFORM_CAPABILITIES_PATH.exists():
        pytest.skip("平台能力中心尚未生成")
    return load_platform_capabilities()["platforms"]


def find_entry(entry_status, url):
    for entry in entry_status["entries"]:
        if entry["url"] == url:
            return entry
    return None


# ---------------------------------------------------------------------------
# 入口可信度
# ---------------------------------------------------------------------------

def test_entry_status_uses_the_documented_enum(entry_status):
    assert set(entry_status["status_enum"]) == ENTRY_STATUS_VALUES
    for entry in entry_status["entries"]:
        assert entry["status"] in ENTRY_STATUS_VALUES, entry["url"]


def test_known_history_is_marked_as_a_clue_not_a_permanent_fact(entry_status):
    assert entry_status["source_priority"][0] == "KNOWN_HISTORY"
    assert "线索" in entry_status["known_history_caveat"]


def test_cnki_advanced_search_status_is_reverified_not_assumed(entry_status):
    """CNKI 首选深链接的档位必须来自**最近一次复验**，而不是旧记录。

    2026-09-19 校赛期 starter/advanced 可直达；
    2026-10-08 赛前复测该入口已跳 blockPuzzle。本测试把这个变化钉住，
    防止有人把 CHALLENGE 改回 DIRECT 而不重新实测。
    """
    entry = find_entry(entry_status, "https://kns.cnki.net/starter/advanced")
    assert entry is not None
    assert entry["status"] == "CHALLENGE"
    assert entry["verified_at"] == "2026-10-08"
    assert "blockPuzzle" in entry["evidence"]
    # 命中验证码的入口必须给出可走的替代路径
    assert entry["fallback_url"]


def test_cnki_has_no_direct_deep_link_to_advanced_search(entry_status, capabilities):
    """复验结果：CNKI 当前没有已验证可直达的高级检索深链接。

    能力表只能回落到首页；这本身就是一个需要人工交接的信号。
    """
    cnki = capabilities["cnki"]
    direct_advanced = [
        e for e in entry_status["entries"]
        if e["platform_key"] == "cnki"
        and e["status"] == "DIRECT"
        and e.get("route_type") == "ADVANCED_SEARCH"
    ]
    assert direct_advanced == []
    assert cnki["entry"]["primary"].startswith("https://www.cnki.net")


@pytest.mark.parametrize(
    "url",
    [
        "https://kns.cnki.net/kns8s/AdvSearch",
        "https://kns.cnki.net/kns8s/search",
        "https://www.sciencedirect.com/",
    ],
)
def test_challenge_entries_have_a_fallback_route(entry_status, url):
    entry = find_entry(entry_status, url)
    assert entry is not None, url
    assert entry["status"] == "CHALLENGE"
    assert entry["fallback_url"], f"{url} 是陷阱入口但没有备用路径"


def test_broken_entries_are_not_offered_as_primary(entry_status, capabilities):
    broken_urls = {
        e["url"] for e in entry_status["entries"] if e["status"] == "BROKEN"
    }
    for platform in capabilities.values():
        assert platform["entry"]["primary"] not in broken_urls


def test_known_history_entries_carry_evidence_and_date(entry_status):
    history = [e for e in entry_status["entries"] if e["source"] == "KNOWN_HISTORY"]
    assert history
    for entry in history:
        assert entry["evidence"], entry["url"]
        assert entry["verified_at"], entry["url"]


# ---------------------------------------------------------------------------
# 平台能力中心
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "platform_key",
    ["cnki", "vip", "wanfang", "pubmed", "icourse163", "sciencedirect", "unesco", "ieee"],
)
def test_core_platforms_have_capability_records(capabilities, platform_key):
    assert platform_key in capabilities
    platform = capabilities[platform_key]
    assert platform["name"]
    assert platform["entry"]["primary"]
    assert platform["search_mode"]


def test_capability_center_records_verified_traps(capabilities):
    cnki_risks = " ".join(capabilities["cnki"]["known_risks"])
    assert "`*`=与" in cnki_risks
    assert "blockPuzzle" in cnki_risks

    wanfang_risks = " ".join(capabilities["wanfang"]["known_risks"])
    assert "模糊" in wanfang_risks

    vip_risks = " ".join(capabilities["vip"]["known_risks"])
    assert "精确" in vip_risks and "412" in vip_risks

    unesco_risks = " ".join(capabilities["unesco"]["known_risks"])
    assert "PDF" in unesco_risks


def test_capability_center_flags_data_pollution(capabilities):
    payload = json.loads(PLATFORM_CAPABILITIES_PATH.read_text(encoding="utf-8"))
    warning = " ".join(payload["data_pollution_warning"])
    assert "module_name" in warning
    assert "official_platform" in warning
    assert "retrieval_path" in warning


def test_deep_link_platforms_use_deep_links_not_homepages(capabilities):
    """题目点名平台时优先功能页，而不是首页。

    CNKI 因 2026-10-08 复验降级（starter/advanced 命中 blockPuzzle）已回落到首页，
    因此不在此断言之列——这是实测结果，不是配置疏漏。
    """
    assert (
        capabilities["vip"]["entry"]["primary"]
        != capabilities["vip"]["canonical_home"]
    )
    assert (
        capabilities["sciencedirect"]["entry"]["primary"]
        != capabilities["sciencedirect"]["canonical_home"]
    )
    assert (
        capabilities["pubmed"]["entry"]["primary"]
        != capabilities["pubmed"]["canonical_home"]
    )


# ---------------------------------------------------------------------------
# 检索式生成：语法隔离
# ---------------------------------------------------------------------------

def test_cnki_same_field_terms_become_a_bare_expression():
    result = build_cnki([Clause(field="篇名", value="信息素养")])
    assert result.mode == MODE_BARE_ADVANCED
    assert "=" not in result.expression
    assert result.expression == "信息素养"


def test_cnki_cross_field_is_not_faked_into_one_box():
    result = build_cnki(
        [Clause(field="篇名", value="信息素养"), Clause(field="作者", value="周建芳")]
    )
    assert result.expression == ""
    assert len(result.steps) == 2
    assert any("跨字段" in w for w in result.warnings)


def test_cnki_professional_uses_field_codes():
    result = build_cnki(
        [Clause(field="篇名", value="信息素养"), Clause(field="作者", value="周建芳")],
        professional=True,
    )
    assert result.mode == MODE_PROFESSIONAL
    assert "TI=" in result.expression and "AU=" in result.expression
    assert "[Title" not in result.expression
    assert " AND " in result.expression


def test_cnki_operator_semantics_are_surfaced_as_a_warning():
    result = build_cnki([Clause(field="篇名", value="甲")])
    assert any("`*`=与" in w for w in result.warnings)


def test_vip_and_cnki_syntax_are_not_interchangeable():
    vip = build_vip([Clause(field="篇名", value="人工智能")])
    cnki = build_cnki([Clause(field="篇名", value="人工智能")])
    assert vip.mode == MODE_FIELD_EQUALS
    assert "=" in vip.expression
    assert cnki.mode == MODE_BARE_ADVANCED
    assert "=" not in cnki.expression
    assert vip.expression != cnki.expression


def test_pubmed_uses_field_tags_not_cnki_codes():
    result = build_pubmed([Clause(field="Title/Abstract", value="CRISPR")], "2017", "2024")
    assert result.mode == MODE_TAGGED
    assert "[Title/Abstract]" in result.expression
    assert "[dp]" in result.expression
    assert "TI=" not in result.expression
    assert "*" not in result.expression


def test_ieee_does_not_borrow_pubmed_tags_or_cnki_codes():
    result = build_ieee([Clause(field="Document Title", value="information literacy")])
    assert "[Title/Abstract]" not in result.expression
    assert "TI=" not in result.expression
    assert result.syntax_verified is False
    assert any("wildcard" in w for w in result.warnings)


def test_wanfang_is_marked_unverified():
    result = build_wanfang([Clause(field="题名", value="人工智能")])
    assert result.syntax_verified is False
    assert any("未验证" in w for w in result.warnings)


def test_unknown_field_is_rejected_instead_of_guessed():
    with pytest.raises(ValueError, match="没有字段"):
        build_pubmed([Clause(field="篇名", value="信息素养")])
    with pytest.raises(ValueError, match="没有字段"):
        build_ieee([Clause(field="篇名", value="信息素养")])


def test_syntax_mixing_guard_raises():
    pubmed = build_pubmed([Clause(field="Title", value="x")])
    with pytest.raises(ValueError, match="语法混用"):
        assert_no_syntax_mixing(pubmed, "cnki")
    assert_no_syntax_mixing(pubmed, "pubmed")


def test_unsupported_platform_tells_you_to_use_the_graphical_form():
    result = build_query("unesco", [{"field": "题名", "value": "x"}])
    assert result.mode == MODE_UNSUPPORTED
    assert any("图形" in w or "高级检索" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 50 模块导航层
# ---------------------------------------------------------------------------

def test_module_nav_covers_all_fifty_modules():
    if not MODULE_NAV_JSON_PATH.exists():
        pytest.skip("导航层尚未生成")
    nav = load_module_nav()
    assert len(nav["modules"]) == 50
    numbers = sorted(m["module_no"] for m in nav["modules"])
    assert numbers == list(range(1, 51))


def test_module_nav_exposes_the_required_runtime_fields():
    nav = load_module_nav()
    required = {
        "module_id", "module_no", "module_name", "trigger_terms",
        "primary_platform", "fallback_platforms", "deep_link",
        "typical_operations", "main_traps", "offline_judgeable",
    }
    for module in nav["modules"]:
        missing = required - set(module)
        assert not missing, f"M{module['module_no']} 缺字段 {missing}"


def test_module_nav_declares_its_provenance():
    """导航层必须自报来源：OFFICIAL（Controller 正式版）或 GENERATED_DRAFT。"""
    nav = load_module_nav()
    assert nav["artifact_status"] in {"OFFICIAL", "GENERATED_DRAFT"}
    if nav["artifact_status"] == "OFFICIAL":
        assert nav["source"] == "OFFICIAL_CONTROLLER"
        assert nav["official_file"]
        assert len(nav["official_sha256"]) == 64
        # 官方内容与派生内容必须分离，派生不得冒充官方
        for module in nav["modules"]:
            assert "official" in module and "derived" in module
    else:
        assert "Controller" in nav["status_note"]


def test_official_nav_covers_all_fifty_modules_with_official_fields():
    nav = load_module_nav()
    if nav["artifact_status"] != "OFFICIAL":
        pytest.skip("当前导航仍是草案")
    codes = [m["module_code"] for m in nav["modules"]]
    assert codes == [f"M{n:02d}" for n in range(1, 51)]
    for module in nav["modules"]:
        official = module["official"]
        assert official["primary_entry"], module["module_code"]
        assert official["fast_path"], module["module_code"]
        assert official["answering_mode"], module["module_code"]
        assert module["trigger_terms"], module["module_code"]


def test_platform_resolution_prefers_the_official_entry():
    """官方「首选入口」优先于数据库启发式，且顺序按官方文本。"""
    nav = load_module_nav()
    if nav["artifact_status"] != "OFFICIAL":
        pytest.skip("当前导航仍是草案")
    by_code = {m["module_code"]: m for m in nav["modules"]}
    # M21 官方写「CNKI、万方、维普…」，首选必须是 cnki 而不是外文库
    assert by_code["M21"]["primary_platform"] == "cnki"
    assert by_code["M21"]["platform_source"] == "OFFICIAL_ENTRY"
    # M31 官方把 CNKI 列在 ScienceDirect 之前
    assert by_code["M31"]["primary_platform"] == "cnki"
    resolved = [m for m in nav["modules"] if m["platform_source"] == "OFFICIAL_ENTRY"]
    assert len(resolved) >= 25, f"官方入口解析覆盖过低：{len(resolved)}"


def test_module_nav_offline_flag_uses_the_documented_values():
    nav = load_module_nav()
    for module in nav["modules"]:
        assert module["offline_judgeable"] in {"YES", "PARTIAL", "NO", "UNKNOWN"}


def test_module_nav_deep_link_status_is_from_the_entry_enum():
    nav = load_module_nav()
    allowed = ENTRY_STATUS_VALUES | {"BLOCKED_BY_COMPLIANCE_GATE", "UNKNOWN", ""}
    for module in nav["modules"]:
        assert module["deep_link_status"] in allowed, module["module_no"]


# ---------------------------------------------------------------------------
# 任务类型识别
# ---------------------------------------------------------------------------

def test_task_type_taxonomy_has_all_required_types():
    config = load_task_types()
    ids = {t["id"] for t in config["task_types"]}
    assert ids == {
        "GET_VALUE", "GET_LIST", "GET_FIELD", "EXISTS",
        "COMPARE", "RULE_REASONING", "TOOL_UI", "CALCULATION",
    }
    assert set(config["detection_order"]) == ids


@pytest.mark.parametrize(
    "question,expected",
    [
        ("在CNKI高级检索中精确检索篇名为信息素养的文献，共有多少篇？", "GET_VALUE"),
        ("该课程第二章包含哪几节？", "GET_LIST"),
        ("该学位论文的学科专业是什么？", "GET_FIELD"),
        ("该网站是否提供生成式AI专题栏目？", "EXISTS"),
        ("CNKI与万方哪个检索结果更多？", "COMPARE"),
        ("GB/T 7714中文献类型标识M代表什么？", "RULE_REASONING"),
        ("请计算该指标2020至2024年的年均增长率。", "CALCULATION"),
    ],
)
def test_task_type_detection(question, expected):
    detected, _ = detect_task_type(question)
    assert detected == expected, question


# 「小恐龙助手支持在哪些办公软件的菜单中显示？」既可读成
# 「哪些软件」=取列表，也可读成「查产品能力」=TOOL_UI；
# 两者检索路径相同（查产品官方说明）。PHASE 2 把「菜单中」从 TOOL_UI 的
# **意图**降级为**位置信号**后，本题落到 GET_LIST，属可接受范围。
@pytest.mark.parametrize(
    "question,acceptable",
    [
        ("小恐龙公文排版助手支持在哪些办公软件的菜单中显示？", {"TOOL_UI", "GET_LIST"}),
    ],
)
def test_ambiguous_task_type_cases(question, acceptable):
    detected, _ = detect_task_type(question)
    assert detected in acceptable, f"{question} -> {detected}"


def test_task_router_produces_all_required_analysis_fields():
    routing = route("在中国知网高级检索界面，以篇名为检索项检索信息素养，共有多少篇文献？")
    analysis = routing.analysis_payload()
    assert set(analysis) == {
        "module_id", "task_type", "target_platform", "required_fields",
        "filters", "time_constraint", "expected_output",
    }
    assert analysis["task_type"] == "GET_VALUE"
    assert analysis["target_platform"] == "cnki"
    assert analysis["module_id"]


def test_task_router_refuses_empty_question():
    with pytest.raises(ValueError, match="Human Gate 1"):
        route("   ")


def test_module_scoring_prefers_specific_trigger_words():
    candidates = score_modules(
        "在中国大学MOOC中，四川师范大学周建芳老师的信息素养课程第二章讲什么？"
    )
    assert candidates
    assert candidates[0]["score"] > 0

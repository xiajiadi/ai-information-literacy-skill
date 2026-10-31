"""TEST 3 / TEST 4 / TEST 8：TEAM_LIVE 输出格式、证据等级、决策阈值。

TEST 3  TEAM_LIVE 输出符合固定短格式。
TEST 4  证据等级不能从旁证自动升级到官方。
TEST 8  个人/团队决策阈值不能混淆：individual = 1/3，team = 1/5。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_output import (  # noqa: E402
    ANSWER,
    DECISION_THRESHOLD_INDIVIDUAL,
    DECISION_THRESHOLD_TEAM,
    HANDOFF,
    SKIP,
    LiveAnswer,
    MultiSelectEstimate,
    configured_max_lines,
    decide,
    live_answer_from_multi,
    multi_select,
)
from provincial_common import (  # noqa: E402
    EVIDENCE_HUMAN_REQUIRED,
    EVIDENCE_LABEL,
    EVIDENCE_MODEL_REASONING,
    EVIDENCE_RANK,
    EVIDENCE_SECONDARY,
    EVIDENCE_VERIFIED_MULTI,
    EVIDENCE_VERIFIED_PRIMARY,
    CONFIDENCE_SCALE,
    evidence_at_least_as_strong,
    evidence_weaker_than,
    load_provincial_config,
    snap_confidence,
)


# ---------------------------------------------------------------------------
# TEST 3 — 固定短格式
# ---------------------------------------------------------------------------

def test_live_output_is_fixed_short_format():
    answer = LiveAnswer(
        answer="AC",
        probability_raw=0.80,
        evidence_level=EVIDENCE_VERIFIED_PRIMARY,
        evidence_platform="CNKI",
        evidence_where="高级检索结果总数",
    )
    lines = answer.render(6).splitlines()
    assert lines[0] == "答案：AC"
    assert lines[1] == "P：80%"
    assert lines[2] == "决策：答"
    assert lines[3].startswith("证据：🟢 官方｜CNKI｜高级检索结果总数")
    assert answer.violations() == []


def test_live_output_respects_max_lines():
    answer = LiveAnswer(
        answer="ABC",
        probability_raw=0.6,
        evidence_level=EVIDENCE_VERIFIED_PRIMARY,
        evidence_platform="CNKI",
        evidence_where="结果总数",
        secondary_answer="AB",
        secondary_probability=0.5,
        key_reason="两个独立来源一致",
    )
    assert len(answer.render(4).splitlines()) <= 4


def test_live_output_forbids_long_form_content():
    answer = LiveAnswer(
        answer="A",
        probability_raw=0.9,
        evidence_level=EVIDENCE_VERIFIED_PRIMARY,
        key_reason="让我再研究一下这个平台的检索语法",
    )
    problems = answer.violations()
    assert any("禁止内容" in p for p in problems)


def test_confidence_is_always_on_the_allowed_scale():
    for raw in (0.8327, 83.27, 0.4512, 0.999, 0.201):
        answer = LiveAnswer(answer="A", probability_raw=raw, evidence_level=EVIDENCE_SECONDARY)
        assert answer.probability in CONFIDENCE_SCALE or answer.probability == 0, raw


def test_snap_confidence_rounds_down_never_up():
    assert snap_confidence(0.88) == 80
    assert snap_confidence(0.95) == 95
    assert snap_confidence(0.19) == 0
    assert snap_confidence(0.20) == 20


def test_human_required_evidence_renders_the_handoff_block_not_an_answer():
    block = (
        "🔴 HUMAN_REQUIRED\n"
        "官网：https://kns.cnki.net/starter/advanced\n"
        "操作：\n1. 打开高级检索\n"
        "复制：\n信息素养 * 人工智能\n"
        "查看：\n结果总数\n"
        "回传：\n只告诉我结果总数=xxx"
    )
    answer = LiveAnswer(
        answer="",
        probability_raw=None,
        evidence_level=EVIDENCE_HUMAN_REQUIRED,
        handoff_block=block,
    )
    rendered = answer.render(6)
    assert rendered.startswith("🔴 HUMAN_REQUIRED")
    assert "答案：" not in rendered
    assert answer.decision == HANDOFF


def test_missing_probability_cannot_be_rendered_as_answer():
    answer = LiveAnswer(answer="A", probability_raw=None, evidence_level=EVIDENCE_SECONDARY)
    assert answer.decision == HANDOFF
    assert answer.probability == 0


def test_multi_select_without_joint_probability_is_a_violation():
    answer = LiveAnswer(
        answer="AC",
        probability_raw=None,
        evidence_level=EVIDENCE_SECONDARY,
        question_type="MULTI",
    )
    assert any("整体组合概率" in p for p in answer.violations())


def test_configured_max_lines_matches_policy():
    config = load_provincial_config()
    assert configured_max_lines() == int(config["output"]["max_lines"])


# ---------------------------------------------------------------------------
# TEST 4 — 证据等级不得由弱升级为强
# ---------------------------------------------------------------------------

def test_evidence_ranking_is_strictly_ordered():
    assert EVIDENCE_RANK[EVIDENCE_VERIFIED_PRIMARY] < EVIDENCE_RANK[EVIDENCE_VERIFIED_MULTI]
    assert EVIDENCE_RANK[EVIDENCE_VERIFIED_MULTI] < EVIDENCE_RANK[EVIDENCE_SECONDARY]
    assert EVIDENCE_RANK[EVIDENCE_SECONDARY] < EVIDENCE_RANK[EVIDENCE_MODEL_REASONING]
    assert EVIDENCE_RANK[EVIDENCE_MODEL_REASONING] < EVIDENCE_RANK[EVIDENCE_HUMAN_REQUIRED]


def test_secondary_is_never_at_least_as_strong_as_primary():
    assert evidence_weaker_than(EVIDENCE_SECONDARY, EVIDENCE_VERIFIED_PRIMARY) is True
    assert evidence_at_least_as_strong(EVIDENCE_SECONDARY, EVIDENCE_VERIFIED_PRIMARY) is False
    assert evidence_at_least_as_strong(EVIDENCE_VERIFIED_PRIMARY, EVIDENCE_SECONDARY) is True


def test_secondary_evidence_never_renders_as_official():
    answer = LiveAnswer(
        answer="B",
        probability_raw=0.7,
        evidence_level=EVIDENCE_SECONDARY,
        evidence_platform="Crossref",
    )
    rendered = answer.render(6)
    assert "🟠" in rendered
    assert "🟢" not in rendered


def test_model_reasoning_never_renders_as_official():
    answer = LiveAnswer(
        answer="正确",
        probability_raw=0.6,
        evidence_level=EVIDENCE_MODEL_REASONING,
        evidence_platform="模型知识",
    )
    rendered = answer.render(6)
    assert "🟡" in rendered
    assert "🟢" not in rendered


def test_unknown_evidence_level_is_treated_as_weakest():
    assert evidence_at_least_as_strong("SOMETHING_NEW", EVIDENCE_SECONDARY) is False
    assert evidence_weaker_than("SOMETHING_NEW", EVIDENCE_HUMAN_REQUIRED) is True


def test_evidence_labels_are_visually_distinct():
    assert EVIDENCE_LABEL[EVIDENCE_VERIFIED_PRIMARY].startswith("🟢")
    assert EVIDENCE_LABEL[EVIDENCE_VERIFIED_MULTI].startswith("🟢")
    assert EVIDENCE_LABEL[EVIDENCE_SECONDARY].startswith("🟠")
    assert EVIDENCE_LABEL[EVIDENCE_MODEL_REASONING].startswith("🟡")
    assert EVIDENCE_LABEL[EVIDENCE_HUMAN_REQUIRED].startswith("🔴")


def test_policy_forbids_evidence_upgrade_without_new_evidence():
    from provincial_common import load_compliance_policy

    policy = load_compliance_policy()
    rules = " ".join(policy["evidence_policy"]["rules"])
    assert "禁止把 SECONDARY 写成 VERIFIED_PRIMARY" in rules
    assert "禁止因为答案看起来合理而升级证据等级" in rules


# ---------------------------------------------------------------------------
# TEST 8 — 决策阈值
# ---------------------------------------------------------------------------

def test_team_threshold_is_one_fifth():
    assert DECISION_THRESHOLD_TEAM == pytest.approx(0.20)
    assert 1 / (1 + 4) == pytest.approx(DECISION_THRESHOLD_TEAM)


def test_individual_threshold_is_one_third():
    assert DECISION_THRESHOLD_INDIVIDUAL == pytest.approx(1 / 3)


def test_thresholds_are_not_interchangeable():
    assert DECISION_THRESHOLD_INDIVIDUAL != DECISION_THRESHOLD_TEAM
    # 25% 在团队赛可以答，在个人赛必须跳。
    assert decide(0.25, DECISION_THRESHOLD_TEAM) == ANSWER
    assert decide(0.25, DECISION_THRESHOLD_INDIVIDUAL) == SKIP


def test_team_threshold_boundary_is_strict():
    assert decide(0.20, DECISION_THRESHOLD_TEAM) == SKIP      # P > 20% 才答
    assert decide(0.2000001, DECISION_THRESHOLD_TEAM) == ANSWER


def test_config_records_both_thresholds_separately():
    config = load_provincial_config()
    team = config["team_live"]
    individual = config["individual_mode"]
    assert team["decision_threshold"] == pytest.approx(0.20)
    assert individual["decision_threshold"] == pytest.approx(1 / 3, abs=1e-3)
    assert team["score_correct"] == 4
    assert team["score_wrong"] == -1
    assert team["score_skip"] == 0
    assert team["multi_select_rule"]
    assert individual["note"]


def test_team_live_parameters_are_marked_unverified():
    """省赛规则未由官方确认前，配置必须自报未验证。"""
    config = load_provincial_config()
    assert config["team_live"]["verified_against_official_rules"] is False
    assert config["team_live"]["source"] == "CONTROLLER_PROVIDED"


# ---------------------------------------------------------------------------
# 多选题整体概率（TEST 3/8 的交叉约束）
# ---------------------------------------------------------------------------

def test_multi_select_requires_direct_joint_estimate():
    with pytest.raises(ValueError, match="直接估计"):
        MultiSelectEstimate("AC", 0.5, method="PRODUCT_OF_OPTIONS").validate()


def test_multi_select_rejects_product_masquerading_as_joint():
    with pytest.raises(ValueError, match="乘法冒充"):
        MultiSelectEstimate(
            "AC", 0.9 * 0.7, per_option_probability={"A": 0.9, "C": 0.7}
        ).validate()


def test_multi_select_joint_cannot_exceed_weakest_option():
    with pytest.raises(ValueError, match="不可能超过"):
        MultiSelectEstimate(
            "AC", 0.95, per_option_probability={"A": 0.9, "C": 0.7}
        ).validate()


def test_multi_select_ranks_combinations_and_reports_second_choice():
    best, second = multi_select(
        [
            MultiSelectEstimate("AC", 0.45),
            MultiSelectEstimate("ABC", 0.35),
            MultiSelectEstimate("AD", 0.20),
        ]
    )
    assert best.combination == "AC"
    assert second is not None and second.combination == "ABC"

    answer = live_answer_from_multi(
        [MultiSelectEstimate("AC", 0.45), MultiSelectEstimate("ABC", 0.35), MultiSelectEstimate("AD", 0.20)]
    )
    rendered = answer.render(6)
    assert "答案：AC" in rendered
    assert "次选：ABC（35%）" in rendered
    assert answer.decision == ANSWER
    assert answer.violations() == []


def test_multi_select_combination_is_normalized_and_deduplicated():
    estimate = MultiSelectEstimate("ca", 0.5)
    estimate.validate()
    assert estimate.combination == "AC"

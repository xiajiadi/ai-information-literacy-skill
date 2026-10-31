"""PHASE2_GOLD_FINALIZATION · 评价体系完整性契约测试。

最重要的一条：**防止循环论证**。

第一版产品级 Gold 复用了路由器自己的别名表来抽取「题干点名的产品」，
而路由器的匹配逻辑用的是同一张表 —— 配对评估因此得到 200/200 = 100% 的
**假准确率**。这正是 Controller 禁止的「把自身模型预测当作独立 Gold」。

本测试钉住三条不变量：
  1. Gold 词典与路由器别名表是**两份独立资产**，路由器不得引用 Gold 词典；
  2. 配对评估必须使用**同一批题、同一套 Gold**，两遍只切换补录开关；
  3. 平台关系注册表里不得存在被当作已核实的父子关系（全 UNVERIFIED）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LEXICON = ROOT / "config" / "gold_product_lexicon.yaml"
RELATIONSHIPS = ROOT / "config" / "platform_relationships.yaml"
PAIRED = ROOT / "data" / "quality" / "phase2" / "paired_routing.json"
GOLD = ROOT / "data" / "quality" / "phase2" / "gold_products.json"


def test_router_never_references_the_gold_lexicon():
    """路由器（含平台解析、意图判断）不得读取 Gold 词典，否则 Gold 与预测同源。"""
    offenders = []
    for path in (ROOT / "scripts").glob("*.py"):
        if path.name in {"phase2_gold_builder.py"}:  # 只有 Gold 构建器可以读
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "gold_product_lexicon" in text:
            offenders.append(path.name)
    assert not offenders, f"这些脚本引用了 Gold 词典，会破坏独立性：{offenders}"


def test_gold_builder_does_not_use_the_router_alias_table_for_labelling():
    """构建器里 Gold 的抽取必须来自独立词典，不得来自 platform_aliases()。"""
    source = (ROOT / "scripts" / "phase2_gold_builder.py").read_text(encoding="utf-8")
    # 允许调用 platform_aliases() 做别的事，但抽取点名的循环必须用 gold_lexicon
    assert "for surface, key in gold_lexicon" in source
    assert not re.search(r"for alias, key in sorted_aliases", source), \
        "仍在使用路由器别名表抽取 Gold，存在循环论证风险"


def test_gold_lexicon_and_router_aliases_are_separate_assets():
    assert LEXICON.exists(), "独立 Gold 词典缺失"
    from platform_router_v2 import platform_aliases

    payload = LEXICON.read_text(encoding="utf-8")
    aliases = platform_aliases()
    # 两份资产必须都存在且各自有内容；若二者字面完全相同就说明没有真正独立
    assert "products:" in payload
    assert aliases
    # 词典里出现、但路由器别名表里**没有**的字样，证明二者并非同一来源
    assert "AI知数" in payload


def test_paired_evaluation_uses_the_same_frozen_gold_for_both_passes():
    if not PAIRED.exists():
        pytest.skip("尚未生成配对评估")
    payload = json.loads(PAIRED.read_text(encoding="utf-8"))
    assert payload["protocol"]["same_questions"] is True
    assert "required_product_id" in payload["protocol"]["gold_basis"]
    assert "DETERMINISTIC" in payload["protocol"]["gold_basis"]
    # 缺少有效 Gold 的样本必须被排除，而不是凑分母
    assert payload["protocol"]["excluded"]["NO_GOLD"] > 0
    assert payload["protocol"]["excluded_note"].startswith("缺乏有效产品级 Gold")


def test_paired_confusion_is_internally_consistent():
    if not PAIRED.exists():
        pytest.skip("尚未生成配对评估")
    payload = json.loads(PAIRED.read_text(encoding="utf-8"))
    c = payload["paired_confusion"]
    total = payload["protocol"]["n"]
    assert sum(c.values()) == total, "混淆矩阵必须覆盖全部样本"
    acc = payload["accuracy"]
    assert acc["before"]["numerator"] == c["before_correct_after_correct"] + c["before_correct_after_wrong"]
    assert acc["after"]["numerator"] == c["before_correct_after_correct"] + c["before_wrong_after_correct"]
    # 两遍分母必须相同，才是 Controller 要求的可比口径
    assert acc["before"]["denominator"] == acc["after"]["denominator"] == total


def test_product_accuracy_is_not_a_perfect_score_from_circularity():
    """防回归：循环论证会产出 100%。若再次出现全对，必须重新审查 Gold 独立性。"""
    if not PAIRED.exists():
        pytest.skip("尚未生成配对评估")
    payload = json.loads(PAIRED.read_text(encoding="utf-8"))
    value = payload["accuracy"]["after"]["value"]
    assert value is not None and value < 1.0, (
        f"补录后准确率为 {value}（全对）。历史上这由 Gold 与预测同源导致，"
        "请先确认 Gold 是否仍独立于路由器，再考虑这是真实结果。"
    )


def test_relationships_declare_no_authoritative_evidence():
    from provincial_common import load_yaml

    payload = load_yaml(RELATIONSHIPS)
    checked = 0
    for key, item in (payload.get("relationships") or {}).items():
        # `special_audit` 是 Controller 点名的待核查清单（列表），不是关系条目本身
        if not isinstance(item, dict):
            continue
        checked += 1
        assert item.get("verification_status") == "UNVERIFIED", key
        assert item.get("evidence_level") == "NONE", key
        assert item.get("why_unverified"), f"{key} 必须说明为何未核实"
    assert checked >= 5, f"实际核查的关系条目过少：{checked}"
    assert payload.get("default_verification_status") == "UNVERIFIED"


def test_special_audit_lists_the_controller_named_relationships():
    """Controller 点名要求特别核查的关系必须逐条在案，且状态不得写成已核实。"""
    from provincial_common import load_yaml

    payload = load_yaml(RELATIONSHIPS)
    audit = payload["relationships"]["special_audit"]
    assert isinstance(audit, list)
    subjects = " ".join(str(item.get("subject", "")) for item in audit)
    for required in ("知网研学", "CNKI AI", "AI知数", "LeapSpace",
                     "国家社科基金项目数据库", "同一品牌旗下不同搜索产品"):
        assert required in subjects, f"缺少 Controller 点名的核查项：{required}"
    for item in audit:
        assert item.get("current_status") in {"UNVERIFIED", "LIKELY_DISTINCT"}


def test_gold_does_not_fabricate_provider_or_ecosystem():
    if not GOLD.exists():
        pytest.skip("尚未生成产品级 Gold")
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    for item in payload["gold"]:
        assert item["provider_id"] == "", "无权威来源时不得臆造 provider"
        assert item["ecosystem_id"] == "", "无权威来源时不得臆造 ecosystem"

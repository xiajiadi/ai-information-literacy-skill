"""PHASE 2 · 任务类型识别的加权模型契约测试。

真实缺陷（PHASE 2 离线验收发现）：

    「在CNKI高级检索界面，精确检索作者为黄智，主题为"染色体"的论文，
      2014-2024年间共有（ ）篇期刊论文。」

旧实现给每个命中词加 `min(len(word), 8)` 分，于是对象名词
（作者 2 分 + 论文 2 分 = 4）压过了疑问短语（共有 2 分），
把 GET_VALUE 误判成 GET_LIST。

「共有多少」是本赛事最高频的取证形态，这个错误会成片放大。
修订：意图短语权重 4、对象名词权重 1，且**只靠对象名词命中时置信度强制 LOW**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from provincial_common import load_task_types  # noqa: E402
from task_router import detect_task_type, task_type_confidence  # noqa: E402


# 取自交接题库的真实题干（只改标点，不改语义）
INTENT_CASES = [
    ("在CNKI高级检索界面，精确检索作者为黄智，主题为“染色体”的论文，2014-2024年间共有（ ）篇期刊论文。", "GET_VALUE"),
    ("在WILEY数据库，查找题名中含有AIGC，且文中包含DEEP SEEK的期刊论文，以下是命中论文作者的有（ ）？", "GET_LIST"),
    ("在CNKI数据库中，学位论文“CEEMDAN和改进的Transformer模型在碳交易价格预测中的应用”的学科专业是（ ）。", "GET_FIELD"),
    ("在维普网检索标题名称包含“家用电器”的标准，状态为作废的标准数高于4000条。", "COMPARE"),
    ("关于Excel表格转PDF，以下说法正确的有？", "EXISTS"),
    ("在Word中，“审阅”选项卡中的功能包括（ ）。", "TOOL_UI"),
    ("根据AI知数分析数据，2024年长三角城市群（27个核心城市）GDP之和约为多少？", "CALCULATION"),
    ("在知网中检索文献“RCEP框架下成渝地区区域价值链整体攀升的实现机制研究”，根据国家标准（GB/T 7714-2015），其文献类型标识为（ ）。", "RULE_REASONING"),
    ("访问中国国家图书馆官网首页，在顶部导航栏的“资源服务”下拉菜单中，一共包含多少个数字资源库入口？", "GET_VALUE"),
    ("在有道云笔记网页版创建流程图，当输入Ctrl+Shift+O时，会呈现什么内容？", "TOOL_UI"),
    ("在CNKI（中国知网）学术期刊数据库中使用高级检索功能，检索主题为“人工智能”与“医疗”的文献，截止2026年，发文量最多的中国作者是王浩。", "COMPARE"),
]


@pytest.mark.parametrize("question,expected", INTENT_CASES)
def test_intent_phrase_wins_over_object_nouns(question, expected):
    """题干里有「共有多少」这类疑问短语时，任务类型必须由它主导。"""
    got, _ = detect_task_type(question)
    assert got == expected, f"{question[:40]}… -> {got}（期望 {expected}）"


# 语义上确有争议、且两种判法**检索方法相同**的题，不强行钉死配置（避免过拟合），
# 单独列出并要求落在可接受集合内。
AMBIGUOUS_CASES = [
    (
        "小恐龙公文排版助手不支持在哪类办公软件中使用？",
        {"EXISTS", "TOOL_UI"},
        "问「不支持哪类软件」既可算存在性也可算工具能力；两者都指向查产品官方说明。",
    ),
]


@pytest.mark.parametrize("question,acceptable,why", AMBIGUOUS_CASES)
def test_ambiguous_cases_land_in_the_acceptable_set(question, acceptable, why):
    got, _ = detect_task_type(question)
    assert got in acceptable, f"{question[:30]}… -> {got}；{why}"


def test_location_phrases_do_not_override_a_quantity_question():
    """「在…下拉菜单中一共有多少个X」问的是数量，不能被位置短语带成 TOOL_UI。"""
    question = "访问中国国家图书馆官网首页，在顶部导航栏的“资源服务”下拉菜单中，一共包含多少个数字资源库入口？"
    got, scores = detect_task_type(question)
    assert got == "GET_VALUE"
    by_id = {item["id"]: item for item in scores}
    assert by_id["TOOL_UI"]["intent_hits"] == [], "位置短语不应再作为 TOOL_UI 的意图"


def test_keyboard_shortcut_is_recognised_without_the_word_jianjie():
    """题干通常写 Ctrl+Shift+O，不会出现「快捷键」三个字。"""
    got, _ = detect_task_type("在有道云笔记网页版创建流程图，当输入Ctrl+Shift+O时，会呈现什么内容？")
    assert got == "TOOL_UI"


def test_superlative_questions_route_to_compare():
    """「发文量最多的作者是…」这类最值题属于比较，不是取单值或取列表。"""
    question = (
        "在CNKI（中国知网）学术期刊数据库中使用高级检索功能，检索主题为“人工智能”与“医疗”的文献，"
        "截止2026年，发文量最多的中国作者是王浩。"
    )
    got, _ = detect_task_type(question)
    assert got == "COMPARE"


def test_the_original_get_value_regression_is_fixed():
    """钉住最初发现的那道题：对象名词不得压过疑问短语。"""
    question = (
        "在CNKI高级检索界面，精确检索作者为黄智，主题为“染色体”的论文，"
        "2014-2024年间共有（ ）篇期刊论文。"
    )
    got, scores = detect_task_type(question)
    assert got == "GET_VALUE"
    by_id = {item["id"]: item for item in scores}
    assert by_id["GET_VALUE"]["score"] > by_id["GET_LIST"]["score"]
    assert by_id["GET_VALUE"]["intent_backed"] is True


def test_intent_only_hits_are_forced_to_low_confidence():
    """只命中对象名词、没有任何意图短语支撑时，不允许给高置信度。"""
    best = {"id": "GET_LIST", "score": 3.0, "intent_backed": False}
    other = [best, {"id": "GET_VALUE", "score": 1.0, "intent_backed": True}]
    assert task_type_confidence(best, other) == "LOW"


def test_intent_backed_best_can_still_be_high_confidence():
    best = {"id": "GET_VALUE", "score": 12.0, "intent_backed": True}
    other = [best, {"id": "GET_LIST", "score": 2.0, "intent_backed": True}]
    assert task_type_confidence(best, other) == "HIGH"


def test_task_type_config_declares_the_weighted_model():
    config = load_task_types()
    scoring = config["scoring"]
    assert scoring["intent_weight"] > scoring["signal_weight"]
    for task in config["task_types"]:
        assert task.get("intent_phrases"), f"{task['id']} 缺 intent_phrases"
        assert task.get("signals"), f"{task['id']} 缺 signals"


def test_no_phrase_is_declared_as_both_intent_and_signal():
    """同一个词不能既算意图又算对象，否则分数被双重计入。"""
    for task in load_task_types()["task_types"]:
        overlap = set(task["intent_phrases"]) & set(task["signals"])
        assert not overlap, f"{task['id']} 重复声明：{overlap}"


def test_unknown_when_no_signal_at_all():
    got, _ = detect_task_type("请阅读材料并回答。")
    assert got == "UNKNOWN"

"""变体匹配（OFFICIAL_MOCK_VARIANT）的行为契约。

核心契约只有一条：**同型题给配方，绝不给答案。**
正式题与模拟题换参数后，流程可复用，答案不可复用。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common import DB_PATH, text
from db_schema import connect_db
from variant_match import (
    NEW,
    VARIANT,
    detect_platform,
    detect_template,
    find_variant,
    render_variant,
)
from solve_question import detect_handoff, load_profile, solve


SIM_SOURCE = "用户提供模拟题整理"


@pytest.fixture(scope="module")
def conn():
    if not Path(DB_PATH).exists():
        pytest.skip("题库不存在，跳过变体匹配测试")
    connection = connect_db(DB_PATH)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def mock_rows(conn):
    rows = conn.execute(
        "SELECT * FROM questions WHERE source_type=? ORDER BY id", (SIM_SOURCE,)
    ).fetchall()
    if not rows:
        pytest.skip("题库中没有模拟题，跳过变体匹配测试")
    return rows


def mutate_numbers(value: str) -> str:
    """把题干里的数字改掉，模拟「换章节号 / 换年份 / 换页码」。"""
    return re.sub(r"\d+", lambda m: str(int(m.group()) + 3), value, count=3)


@pytest.fixture(scope="module")
def clean_mock_row(mock_rows):
    """挑一道「不触发人工交接」的模拟题。

    微信/App/扫码这类题命中人工交接是**正确行为**，不是变体逻辑的问题，
    因此集成测试要避开它们，否则测的是交接而不是变体。
    """
    profile = load_profile(
        Path(__file__).resolve().parents[1] / "config" / "fast_profile.yaml"
    )
    for row in mock_rows:
        question = text(row["question_text"])
        if not question:
            continue
        if detect_handoff(question, None, profile) is None and \
           detect_handoff(mutate_numbers(question), None, profile) is None:
            return row
    pytest.skip("没有可用于变体集成测试的、不触发人工交接的模拟题")


# ---------------------------------------------------------------------------
# 单元：平台与模板判定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("在中国大学MOOC上检索", "中国大学MOOC"),
    ("使用CNKI高级检索", "CNKI"),
    ("在维普期刊库中", "维普"),
    ("万方数据知识服务平台", "万方"),
    ("PubMed 的 MeSH 主题词", "PubMed"),
    ("ScienceDirect 高级检索", "ScienceDirect"),
    ("UNESCO 数字图书馆", "UNESCO"),
])
def test_detect_platform(question, expected):
    assert detect_platform(question) == expected


@pytest.mark.parametrize("question,prefix", [
    ("该视频时长是多少", "G"),
    ("PDF 第 5 页的表格名称", "D"),
    ("下列哪个是布尔运算符 AND", "J"),
    ("课程第 2 章的小节标题", "M"),
    ("第一作者的机构是", "C"),
])
def test_detect_template(question, prefix):
    assert detect_template(question).startswith(prefix)


# ---------------------------------------------------------------------------
# 单元：变体识别
# ---------------------------------------------------------------------------

def test_variant_matches_sibling_without_returning_answer(conn, mock_rows):
    """换掉数字参数后，应识别为同型题，且配方里不含答案字段。"""
    source = mock_rows[0]
    variant_text = mutate_numbers(text(source["question_text"]))

    match = find_variant(conn, variant_text, mock_rows)

    assert match.status == VARIANT, (
        f"应识别为变体，实际 {match.status}；题干：{variant_text[:60]}"
    )
    assert match.similarity >= 0.42
    assert match.source_row is not None
    # 契约：配方里不得出现任何答案字段。
    assert "standard_answer" not in match.recipe
    assert "mock_key" not in match.recipe
    assert "provisional_answer" not in match.recipe
    assert "answer" not in match.recipe


def test_variant_render_states_answer_is_forbidden(conn, mock_rows):
    """渲染结果必须明确写出「禁止套用参照题答案」。"""
    source = mock_rows[0]
    match = find_variant(conn, mutate_numbers(text(source["question_text"])), mock_rows)
    if match.status != VARIANT:
        pytest.skip("该题未命中变体区间")

    rendered = render_variant(match, source["question_text"])
    assert "禁止套用参照题答案" in rendered
    assert "🟡" in rendered


def test_unrelated_question_is_new_pattern(conn, mock_rows):
    """完全无关的题目不应被硬凑成同型题。"""
    unrelated = (
        "某高校图书馆购买了一套外文电子书平台，请说明该平台支持哪几种"
        "下载格式，并列出其在移动端的可用功能与并发用户数限制。"
    )
    match = find_variant(conn, unrelated, mock_rows)
    assert match.status == NEW
    assert match.source_row is None


# ---------------------------------------------------------------------------
# 集成：solve_question 的状态机
# ---------------------------------------------------------------------------

def build_args(question_text: str, **overrides) -> argparse.Namespace:
    base = dict(
        question_text=question_text,
        db=str(DB_PATH),
        profile=str(Path(__file__).resolve().parents[1] / "config" / "fast_profile.yaml"),
        option_a="", option_b="", option_c="", option_d="",
        allow_browser=False, skip_web=True,
        hard_timeout_override=0.0, browser_cmd="", explain=False, json=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_exact_mock_question_still_answers(clean_mock_row):
    """原题命中路径不能被变体逻辑破坏：仍然直接给答案。"""
    source = clean_mock_row
    options = {
        f"option_{letter}": text(source[f"option_{letter}"])
        for letter in ("a", "b", "c", "d")
    }
    outcome = solve(build_args(text(source["question_text"]), **options))

    assert outcome.status == "ANSWER", f"原题应直接作答，实际 {outcome.status}"
    assert outcome.answer, "原题命中必须给出答案"
    assert outcome.tier in {"mock_key", "standard_answer", "provisional_answer"}


def test_variant_question_yields_recipe_not_answer(clean_mock_row):
    """换参数后：状态为同型题，且 answer 必须为空。"""
    source = clean_mock_row
    variant_text = mutate_numbers(text(source["question_text"]))
    outcome = solve(build_args(variant_text))

    assert outcome.status == "OFFICIAL_MOCK_VARIANT", (
        f"应进入同型题状态，实际 {outcome.status}"
    )
    assert outcome.answer == "", "同型题严禁返回旧答案"
    assert outcome.variant is not None
    assert outcome.variant.source_row is not None


def test_wechat_variant_hands_off_instead_of_answering(mock_rows):
    """微信/App 类同型题必须先转人工，不能因为「有同型题」就作答。"""
    profile = load_profile(
        Path(__file__).resolve().parents[1] / "config" / "fast_profile.yaml"
    )
    wechat_row = next(
        (r for r in mock_rows
         if detect_handoff(text(r["question_text"]), None, profile) == "wechat_mp_or_miniprogram"),
        None,
    )
    if wechat_row is None:
        pytest.skip("题库中没有微信类模拟题")

    outcome = solve(build_args(mutate_numbers(text(wechat_row["question_text"]))))
    assert outcome.status == "NEEDS_HUMAN"
    assert outcome.answer == ""

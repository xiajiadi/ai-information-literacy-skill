"""考试 CLI 的作答契约。

`--exam-mode` 是考试当天真正会用的命令，它必须满足：

1. 不传选项时也能作答 —— 未提供的选项不能被当成「空选项表」传下去。
2. 传选项时按「选项内容」重映射，而不是按字母位置。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common import DB_PATH, text
from db_schema import connect_db
from match_engine import MatchIndex
from match_question import exam_display


SIM_SOURCE = "用户提供模拟题整理"


@pytest.fixture(scope="module")
def conn():
    if not Path(DB_PATH).exists():
        pytest.skip("题库不存在")
    connection = connect_db(DB_PATH)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def choice_row(conn):
    """取一道四选项的选择题。"""
    rows = conn.execute(
        "SELECT * FROM questions WHERE source_type=? AND question_type LIKE '%单选%' "
        "ORDER BY id LIMIT 5",
        (SIM_SOURCE,),
    ).fetchall()
    if not rows:
        pytest.skip("题库中没有单选题")
    return rows[0]


def test_exam_mode_answers_without_options(conn, choice_row):
    """不传选项时必须直接给答案。

    回归点：全空选项字典是「真值」，若原样传给 remap_answer，会被当作
    「题目选项是空的」，于是每道题都返回「需要核对选项内容」。
    """
    question = text(choice_row["question_text"])
    result = MatchIndex(conn).lookup(question, {})

    assert result.row is not None, "应当命中题库"
    rendered = exam_display(result, {})

    assert "需要核对选项内容" not in rendered, (
        f"未传选项时不应要求核对选项，实际输出：{rendered}"
    )
    assert "答案：" in rendered, f"应当给出答案，实际输出：{rendered}"


def test_exam_mode_remaps_by_option_content(conn, choice_row):
    """选项顺序变化时按内容重映射，不按字母位置。"""
    question = text(choice_row["question_text"])
    stored = {letter: text(choice_row[f"option_{letter}"]) for letter in "ABCD"}
    if any(not value for value in stored.values()):
        pytest.skip("该题选项不完整，无法测试重映射")

    correct_letter = text(choice_row["mock_key"] or choice_row["standard_answer"]
                          or choice_row["provisional_answer"])
    if len(correct_letter) != 1 or correct_letter not in "ABCD":
        pytest.skip("该题不是单选答案，跳过")

    result = MatchIndex(conn).lookup(question, stored)
    assert result.row is not None
    assert exam_display(result, stored).endswith("题源命中") or "答案：" in exam_display(result, stored)

    # 把正确选项的内容挪到另一个字母位上。
    target_letter = next(l for l in "ABCD" if l != correct_letter)
    shuffled = dict(stored)
    shuffled[correct_letter], shuffled[target_letter] = (
        stored[target_letter], stored[correct_letter],
    )
    rendered = exam_display(result, shuffled)
    assert f"答案：{target_letter}" in rendered, (
        f"应把答案重映射到 {target_letter}，实际输出：{rendered}"
    )

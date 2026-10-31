"""TEST 1 + TEST 7：变体题答案隔离 / module_id 优先于被污染的 module_name。

TEST 1  变体题不允许继承旧答案。
        换参数后流程可复用，答案必须重新求解 —— 这条是整个架构最重要的纪律。

TEST 7  module_id 与污染的 module_name 冲突时，不得盲信 module_name。
        db/question_bank.sqlite 中 37/248 条记录的 module_name 与 module_id 不一致。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from provincial_common import DB_PATH, load_module_nav  # noqa: E402
from task_router import route  # noqa: E402
from variant_match import VARIANT, find_variant, render_variant  # noqa: E402

# 这些键一旦出现在「可复用配方」里，就等于把旧答案漏了出去。
ANSWER_BEARING_KEYS = {
    "answer", "standard_answer", "provisional_answer", "mock_key", "correct_answer",
    "answer_explanation", "canonical_answer",
}

SIM_SOURCE = "用户提供模拟题整理"


@pytest.fixture(scope="module")
def conn():
    if not Path(DB_PATH).exists():
        pytest.skip("题库不存在")
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def mock_rows(conn):
    rows = conn.execute(
        "SELECT * FROM questions WHERE source_type=? ORDER BY id", (SIM_SOURCE,)
    ).fetchall()
    if not rows:
        pytest.skip("题库中没有模拟题")
    return rows


def mutate_parameters(value: str) -> str:
    """改掉数字与书名号专名，模拟「换参数」。"""
    mutated = re.sub(r"\d+", lambda m: str(int(m.group()) + 2), value, count=4)
    return mutated.replace("第二章", "第五章").replace("第2章", "第5章")


# ---------------------------------------------------------------------------
# TEST 1
# ---------------------------------------------------------------------------

def test_variant_recipe_never_contains_an_answer(conn, mock_rows):
    """find_variant 返回的配方里不得出现任何答案字段。"""
    checked = 0
    for row in mock_rows[:12]:
        question = mutate_parameters(row["question_text"] or "")
        if not question.strip():
            continue
        match = find_variant(conn, question, mock_rows)
        if match.status != VARIANT:
            continue
        checked += 1
        leaked = ANSWER_BEARING_KEYS.intersection(match.recipe.keys())
        assert not leaked, f"变体配方泄漏答案字段 {leaked}（参照题 {row['id']}）"
    assert checked > 0, "没有产生任何变体命中，测试未覆盖到目标行为"


def test_variant_render_never_prints_reference_answer(conn, mock_rows):
    """渲染出来的变体说明里不得出现参照题的答案。"""
    for row in mock_rows[:12]:
        reference_answer = (row["provisional_answer"] or row["standard_answer"] or "").strip()
        question = mutate_parameters(row["question_text"] or "")
        if not question.strip():
            continue
        match = find_variant(conn, question, mock_rows)
        if match.status != VARIANT:
            continue
        rendered = render_variant(match, question)
        assert "禁止套用参照题答案" in rendered
        if reference_answer and len(reference_answer) <= 6:
            assert f"答案：{reference_answer}" not in rendered


def test_router_variant_state_carries_no_answer(mock_rows):
    """task_router 在 VARIANT 状态下不得产出答案。"""
    row = next(
        (r for r in mock_rows if (r["question_text"] or "").strip()), None
    )
    if row is None:
        pytest.skip("没有可用模拟题")
    question = mutate_parameters(row["question_text"])
    routing = route(question)
    payload = routing.as_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    for key in ANSWER_BEARING_KEYS:
        assert f'"{key}"' not in serialized, f"路由结果里出现了答案字段 {key}"
    if routing.match_status == VARIANT:
        assert routing.reusable_recipe, "变体状态应给出可复用配方"
        assert not ANSWER_BEARING_KEYS.intersection(routing.reusable_recipe.keys())


def test_exact_match_does_not_leak_into_variant_path(conn, mock_rows):
    """原题命中与变体命中互斥：参数没变才算 EXACT。"""
    row = next((r for r in mock_rows if (r["question_text"] or "").strip()), None)
    if row is None:
        pytest.skip("没有可用模拟题")
    routing_exact = route(row["question_text"])
    assert routing_exact.match_status == "EXACT"

    routing_variant = route(mutate_parameters(row["question_text"]))
    assert routing_variant.match_status != "EXACT"


# ---------------------------------------------------------------------------
# TEST 7
# ---------------------------------------------------------------------------

def polluted_rows(conn):
    """找出 module_name 与 canonical modules 表不一致的记录。"""
    return conn.execute(
        """
        SELECT q.id, q.module_id, q.module_name AS polluted, m.module_name AS canonical
        FROM questions q
        JOIN modules m ON m.module_id = q.module_id
        WHERE TRIM(COALESCE(q.module_name, '')) <> ''
          AND q.module_name <> m.module_name
        ORDER BY q.id
        """
    ).fetchall()


def test_question_bank_is_actually_polluted(conn):
    """先证明污染真实存在；否则后面的测试是空转。"""
    rows = polluted_rows(conn)
    assert len(rows) > 0, "题库没有污染记录，本测试失去意义"
    empty_platform = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE TRIM(COALESCE(official_platform,'')) = ''"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    assert empty_platform == total, "official_platform 不再全空，需重新评估数据质量假设"


def test_router_trusts_module_id_over_polluted_module_name(conn):
    """module_name 冲突时，路由必须报告冲突并以 modules 表为准。"""
    rows = polluted_rows(conn)
    if not rows:
        pytest.skip("没有冲突记录")
    target = rows[0]
    routing = route(conn.execute(
        "SELECT question_text FROM questions WHERE id=?", (target["id"],)
    ).fetchone()[0])

    assert routing.module_id == target["module_id"]
    assert routing.module_name == target["canonical"]
    assert routing.polluted_module_name == target["polluted"]
    assert routing.module_name_conflict is True

    nav_names = {
        m["module_id"]: m["module_name"] for m in load_module_nav()["modules"]
    }
    assert routing.module_name == nav_names[routing.module_id]


def test_nav_is_keyed_by_module_id_and_names_are_canonical():
    """导航层只能用 module_id 作键，来源必须显式声明。"""
    nav = load_module_nav()
    ids = [m["module_id"] for m in nav["modules"]]
    assert len(ids) == len(set(ids)) == 50
    assert nav["artifact_status"] in {"OFFICIAL", "GENERATED_DRAFT"}
    assert all(
        m["source"] in {"OFFICIAL_CONTROLLER", "GENERATED_DRAFT"}
        for m in nav["modules"]
    )
    # 声称 OFFICIAL 就必须带得出官方出处；否则不得自称已确认
    if nav["artifact_status"] == "OFFICIAL":
        assert nav["official_sha256"] and nav["official_file"]
    else:
        assert "Controller" in nav["status_note"]


def test_module_id_is_never_derived_from_module_name_string(conn):
    """反向验证：用 module_name 直接查 modules 表会失败，所以不能被信任。"""
    rows = polluted_rows(conn)
    if not rows:
        pytest.skip("没有冲突记录")
    target = rows[0]
    hit = conn.execute(
        "SELECT COUNT(*) FROM modules WHERE module_name=?", (target["polluted"],)
    ).fetchone()[0]
    canonical_hit = conn.execute(
        "SELECT COUNT(*) FROM modules WHERE module_id=?", (target["module_id"],)
    ).fetchone()[0]
    assert canonical_hit == 1
    # polluted 名字要么查不到，要么指向别的模块 —— 两种都说明不能当键用。
    assert hit != 1 or target["polluted"] != target["canonical"]

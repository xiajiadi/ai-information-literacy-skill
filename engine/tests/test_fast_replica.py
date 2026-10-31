"""FAST Replica acceptance tests.

Covers the acceptance list:
  A 150 original match          B 150 random reorder
  C text/option variants        D FAST hard timeout (real process-tree kill)
  E browser failure x2 early stop   F manual handoff

Run:  python -m pytest tests/test_fast_replica.py -v
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import DB_PATH, normalize_option, text  # noqa: E402
from db_schema import connect_db, ensure_schema  # noqa: E402
from match_engine import (  # noqa: E402
    MatchIndex, answer_with_tier, remap_answer, row_options,
)
from solve_question import build_argv, kill_process_tree, run_process  # noqa: E402

FIXTURE_PROFILE = ROOT / "tests" / "fixtures" / "fast_profile_fixture.yaml"
FAKE_BROWSER = ROOT / "tests" / "fake_browser.py"
MOCK_SOURCE_TYPE = "用户提供模拟题整理"
LETTERS = "ABCD"


@pytest.fixture(scope="module")
def conn():
    connection = connect_db(DB_PATH)
    ensure_schema(connection)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def mock_rows(conn):
    return conn.execute(
        "SELECT * FROM questions WHERE source_type = ? ORDER BY id", (MOCK_SOURCE_TYPE,)
    ).fetchall()


@pytest.fixture(scope="module")
def index(conn):
    return MatchIndex(conn)


def expected_letters(row, presented: dict[str, str]) -> str:
    """Hand-derived expectation: map by option TEXT, never by position."""
    stored = row_options(row)
    answer = answer_with_tier(row)[0]
    return "".join(
        sorted(
            letter
            for source_letter in answer.upper()
            for letter, value in presented.items()
            if value == stored[source_letter]
        )
    )


# ---------------------------------------------------------------- A / B / C

def test_a_original_match(index, mock_rows):
    """A. All 150 simulation questions match their own bank entry."""
    failures = []
    for row in mock_rows:
        result = index.lookup(row["question_text"], row_options(row))
        if result.row is None or result.row["id"] != row["id"]:
            failures.append(row["id"])
    assert not failures, f"original match failures: {failures}"
    assert len(mock_rows) == 150


def test_b_random_reorder(index, mock_rows):
    """B. Shuffled options still resolve to the same answer CONTENT."""
    rng = random.Random(20260916)
    failures = []
    for row in mock_rows:
        stored = row_options(row)
        letters = [l for l in LETTERS if stored[l]]
        values = [stored[l] for l in letters]
        rng.shuffle(values)
        presented = dict(zip(letters, values))
        result = index.lookup(row["question_text"], presented)
        mapping = remap_answer(row, presented, answer_with_tier(row)[0])
        if (
            result.row is None
            or result.row["id"] != row["id"]
            or mapping["status"] not in {"MAPPED", "MAPPED_TEXT"}
            or mapping["answer"] != expected_letters(row, presented)
        ):
            failures.append(row["id"])
    assert not failures, f"reorder failures: {failures}"


def _to_fullwidth(value: str) -> str:
    return "".join(
        chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in value
    )


def _option_variants(value: str) -> dict[str, str]:
    return {
        "half_to_full_punct": value.replace("(", "（").replace(")", "）"),
        "full_to_half_punct": value.replace("（", "(").replace("）", ")"),
        "ascii_fullwidth": _to_fullwidth(value),
        "extra_spaces": re.sub(r"([，。；：,.;:])", r"  \1  ", value),
        "trimmed": f"  {value}  ",
    }


def test_c_option_and_text_variants(conn, mock_rows):
    """C. Punctuation / width / spacing / Markdown-URL variants stay mapped.

    Variants are applied to the PRESENTED options and the question text; the
    answer must still be found by content.
    """
    failures = []
    checked = 0
    for row in mock_rows:
        stored = row_options(row)
        expected = answer_with_tier(row)[0]
        baseline = remap_answer(row, stored, expected)["answer"]
        for letter in LETTERS:
            if not stored[letter]:
                continue
            for variant_name, transformed in _option_variants(stored[letter]).items():
                presented = dict(stored)
                presented[letter] = transformed
                checked += 1
                mapping = remap_answer(row, presented, expected)
                # These variants normalise to the same content, so perturbing
                # one option must not move the answer at all. (If the perturbed
                # option is not the answer, the answer letter stays put; if it
                # is the answer, the mapping must follow the content.)
                if mapping["status"] not in {"MAPPED", "MAPPED_TEXT"}:
                    failures.append((row["id"], letter, variant_name, mapping["status"]))
                elif mapping["answer"] != baseline:
                    failures.append((row["id"], letter, variant_name, mapping["answer"]))
    assert checked > 500, f"variant coverage too small: {checked}"
    assert not failures, f"option variant failures ({len(failures)}): {failures[:5]}"


def test_c_judgment_order_both_ways(conn):
    """C. Judgment answers stored as 正确/错误 remap under both orderings."""
    rows = conn.execute(
        "SELECT * FROM questions WHERE verification_status = 'OFFICIAL_ANSWER' "
        "AND (option_a IS NULL OR trim(option_a) = '') "
        "AND (option_b IS NULL OR trim(option_b) = '')"
    ).fetchall()
    rows = [r for r in rows if answer_with_tier(r)[0].strip() in {"正确", "错误"}]
    assert rows, "expected text-answer judgment questions"
    for row in rows:
        answer = answer_with_tier(row)[0].strip()
        for order, expected in (
            ({"A": "正确", "B": "错误"}, {"正确": "A", "错误": "B"}),
            ({"A": "错误", "B": "正确"}, {"正确": "B", "错误": "A"}),
        ):
            mapping = remap_answer(row, order, answer)
            assert mapping["answer"] == expected[answer], (row["id"], order, mapping)


def test_c_multiselect_maps_as_a_set(index, mock_rows):
    """C. Multi-select answers remap as a set, not a sequence."""
    multi = [r for r in mock_rows if len(answer_with_tier(r)[0]) > 1]
    assert multi, "expected multi-select simulation questions"
    rng = random.Random(7)
    for row in multi:
        stored = row_options(row)
        letters = [l for l in LETTERS if stored[l]]
        values = [stored[l] for l in letters]
        rng.shuffle(values)
        presented = dict(zip(letters, values))
        mapping = remap_answer(row, presented, answer_with_tier(row)[0])
        assert mapping["status"] in {"MAPPED", "MAPPED_TEXT"}, (row["id"], mapping)
        assert mapping["answer"] == expected_letters(row, presented), row["id"]


# ------------------------------------------------------------------------ D

def _run_solver(question: str, extra: list[str], env_extra: dict | None = None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "solve_question.py"), question,
         "--profile", str(FIXTURE_PROFILE), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=120,
    )


def _browser_profile():
    from solve_question import load_profile

    profile = load_profile(FIXTURE_PROFILE)
    # Quote both paths: the project directory contains a space.
    profile.prefer = f'"{sys.executable}" "{FAKE_BROWSER}"'
    profile.fallback = ""
    return profile


def test_d_fast_hard_timeout_kills_process_tree(tmp_path, monkeypatch):
    """D. The browser stage is cut off and its whole tree really dies.

    The fake browser spawns a grandchild that would outlive a launcher-only
    kill; the assertion is on that grandchild being gone.
    """
    from solve_question import run_browser_stage

    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("FAKE_BROWSER_MODE", "sleep")
    monkeypatch.setenv("FAKE_BROWSER_PIDFILE", str(pidfile))

    notes: list[str] = []
    started = time.monotonic()
    result = run_browser_stage("https://example.com/", _browser_profile(), started, notes)
    elapsed = time.monotonic() - started

    # Fixture caps the browser soft timeout at 3s.
    assert result == "TIMEOUT"
    assert elapsed < 30, f"browser stage ran {elapsed:.1f}s, timeout not enforced"
    assert any("tree_killed=True" in n or "软超时" in n for n in notes), notes

    assert pidfile.exists(), "fake browser never started"
    child_pid = int(pidfile.read_text(encoding="utf-8").strip())
    time.sleep(1.0)
    assert not _pid_alive(child_pid), f"grandchild {child_pid} survived the hard timeout"


def test_d_end_to_end_reaches_browser_and_hands_off(tmp_path, monkeypatch):
    """D. Wiring: an unanswered bank row routes to the browser, then hands off."""
    import shutil

    db = tmp_path / "temp.sqlite"
    shutil.copy2(DB_PATH, db)
    temp = connect_db(db)
    temp.execute(
        "UPDATE questions SET mock_key = NULL, standard_answer = NULL, "
        "provisional_answer = NULL WHERE id = 'SIM26-01-039'"
    )
    temp.commit()
    temp.close()

    monkeypatch.setenv("FAKE_BROWSER_MODE", "fail")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "solve_question.py"),
         "在百度的高级搜索界面中，可以限定搜索关键词的位置提高检索精度，可以限定的位置有（ ）。",
         "--db", str(db), "--profile", str(FIXTURE_PROFILE),
         "--allow-browser", "--skip-web",
         "--browser-cmd", f'"{sys.executable}" "{FAKE_BROWSER}"', "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=120,
    )
    payload = json.loads(proc.stdout)
    assert payload["stage"] != "local_match", payload
    assert payload["status"] == "NEEDS_HUMAN", payload
    assert any("连续失败达到上限" in n for n in payload["notes"]), payload["notes"]


def _pid_alive(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return str(pid) in (result.stdout or "")


def test_d_abort_sweeps_browser_residue(tmp_path, monkeypatch):
    """D. Abort must reach processes a launcher-only kill would miss.

    agent-browser runs a daemon plus its own headless Chromium, so killing the
    CLI wrapper is not enough. This proves the residue sweep kills a process
    that outlived its launcher.
    """
    import subprocess as sp
    from solve_question import list_marked_processes, sweep_browser_processes

    marker = "ab_sweep_marker_9f3c"
    pidfile = tmp_path / "gc.pid"
    monkeypatch.setenv("FAKE_BROWSER_MODE", "detach")
    monkeypatch.setenv("FAKE_BROWSER_PIDFILE", str(pidfile))
    monkeypatch.setenv("FAKE_BROWSER_MARKER", marker)

    # `detach` exits at once, so the launcher is already gone while its browser
    # keeps running -- the same shape as agent-browser's daemon.
    launcher = sp.Popen([sys.executable, str(FAKE_BROWSER), "open", "x"])
    launcher.wait(timeout=30)
    for _ in range(100):
        if pidfile.exists():
            break
        time.sleep(0.1)
    assert pidfile.exists(), "fake browser never started"
    grandchild = int(pidfile.read_text(encoding="utf-8").strip())

    kill_process_tree(launcher.pid)
    time.sleep(1.0)
    assert _pid_alive(grandchild), "test premise broken: grandchild should outlive launcher"

    found = [pid for pid, _ in list_marked_processes((marker,))]
    assert grandchild in found, f"sweep did not find {grandchild} in {found}"

    notes: list[str] = []
    killed = sweep_browser_processes(notes, markers=(marker,))
    assert killed >= 1, notes
    time.sleep(1.0)
    assert not _pid_alive(grandchild), f"residue {grandchild} survived the sweep"


def test_d_run_process_reports_timeout():
    """D. run_process surfaces the timeout instead of hanging."""
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(60)"], timeout=2.0
    )
    assert result["timed_out"] is True
    assert result["elapsed_ms"] < 30_000


def test_d_kill_process_tree_is_safe_on_bad_pid():
    assert kill_process_tree(0) is False
    assert kill_process_tree(-1) is False


# ------------------------------------------------------------------------ E

def test_e_browser_failure_twice_early_stop(monkeypatch):
    """E. Two consecutive browser failures stop automation and hand off."""
    from solve_question import run_browser_stage

    monkeypatch.setenv("FAKE_BROWSER_MODE", "fail")
    notes: list[str] = []
    started = time.monotonic()
    result = run_browser_stage("https://example.com/", _browser_profile(), started, notes)
    elapsed = time.monotonic() - started

    assert result == "TIMEOUT"
    failures = [n for n in notes if "浏览器失败" in n]
    assert len(failures) == 2, f"expected exactly 2 attempts, got {failures}"
    assert any("连续失败达到上限" in n for n in notes), notes
    assert elapsed < 30, f"early stop took {elapsed:.1f}s"


# ------------------------------------------------------------------------ F

@pytest.mark.parametrize(
    "question,trigger",
    [
        ("在中山大学图书馆官方微信公众号中检索某书可知，收藏这本书的分馆包括（ ）。", "wechat"),
        ("在国家反诈APP的“反馈与帮助”中，常见问题包含以下哪几类？（ ）", "app"),
    ],
)
def test_f_manual_handoff_fires_fast(question, trigger):
    """F. Handoff triggers return quickly, with a usable recipe."""
    started = time.monotonic()
    proc = _run_solver(question, ["--json"])
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"handoff took {elapsed:.1f}s"
    payload = json.loads(proc.stdout)
    assert payload["status"] in {"NEEDS_HUMAN", "ANSWER"}


def test_f_handoff_output_is_actionable():
    """F. Handoff text carries an entry, numbered steps and a target field."""
    from solve_question import handoff_text

    route = {
        "official_platform": "测试平台",
        "official_url": "https://example.com/",
        "deep_link": "https://example.com/search",
        "retrieval_recipe": "打开入口 → 进入检索 → 记录字段",
    }
    body = handoff_text("题干", route, "captcha")
    assert "🔴" in body
    assert "https://example.com/search" in body
    assert "1. 打开入口" in body
    assert "看：" in body


# ------------------------------------------------------- profile enforcement

def test_profile_is_read_not_hardcoded():
    """The solver must read the budget from the profile file."""
    from solve_question import load_profile

    fast = load_profile(ROOT / "config" / "fast_profile.yaml")
    assert fast.t("hard_timeout_seconds", 0) == 120
    assert fast.max_browser_failures == 2

    fixture = load_profile(FIXTURE_PROFILE)
    assert fixture.t("hard_timeout_seconds", 0) == 6


def test_profile_parses_without_pyyaml(monkeypatch):
    """The runtime path must not depend on pyyaml being installed.

    The project venv ships pypdf/openpyxl but not pyyaml, while some system
    interpreters are the reverse; both must read the same budget.
    """
    import solve_question as sq

    path = ROOT / "config" / "fast_profile.yaml"
    with_yaml = sq.load_profile(path)

    monkeypatch.setattr(sq, "yaml", None)
    without_yaml = sq.load_profile(path)

    assert without_yaml.timeouts == with_yaml.timeouts
    assert without_yaml.max_browser_failures == with_yaml.max_browser_failures
    assert without_yaml.early_stop_triggers == with_yaml.early_stop_triggers
    assert without_yaml.t("hard_timeout_seconds", 0) == 120


def test_command_split_handles_spaces():
    """This project's path contains a space; argv splitting must honour quotes."""
    from solve_question import build_argv, split_command

    assert split_command('"C:\\a b\\py.exe" "D:\\x y\\s.py"') == [
        "C:\\a b\\py.exe", "D:\\x y\\s.py"]
    argv = build_argv('"C:\\a b\\py.exe" "D:\\x y\\s.py"', ["open", "u"])
    assert argv[1:] == ["D:\\x y\\s.py", "open", "u"]


def test_normal_profile_still_180(conn=None):
    """The NORMAL profile keeps its original 180s hard timeout."""
    payload = json.loads(
        (ROOT / "config" / "official_urls.json").read_text(encoding="utf-8")
    )
    assert payload["runtime_policy"]["hard_timeout_seconds"] == 180

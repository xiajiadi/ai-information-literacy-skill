from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from common import normalize_option, normalize_question, option_signature, question_hash, text


LETTERS = "ABCD"


def canonical_answer(value: Any) -> str:
    raw = text(value).upper()
    compact = re.sub(r"[\s、,，;；/|和及并]+", "", raw)
    compact = compact.strip("[]()（）")
    if compact and all(ch in LETTERS for ch in compact):
        return "".join(sorted(set(compact)))
    aliases = {"对": "正确", "错": "错误", "TRUE": "正确", "FALSE": "错误"}
    return aliases.get(compact, compact)


def row_options(row: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
    return {letter: text(row[f"option_{letter.lower()}"]) for letter in LETTERS}


def row_field(row: sqlite3.Row | dict[str, Any], name: str) -> str:
    """Read a column that may be absent on older/partial row objects."""
    try:
        return text(row[name])
    except (IndexError, KeyError):
        return ""


def answer_for_row(row: sqlite3.Row | dict[str, Any]) -> tuple[str, str]:
    """Return (answer, tier) using the three-tier precedence.

    standard_answer  -> independently verified against an authoritative source
    mock_key         -> the 2026 simulation-set answer key (P0 for original matches)
    provisional_answer -> derived by this project, never authoritative

    The tiers must never be conflated; the tier name is returned so callers can
    label confidence honestly instead of inferring it from the value alone.
    """
    return answer_with_tier(row)[:2]


def answer_with_tier(row: sqlite3.Row | dict[str, Any]) -> tuple[str, str, str]:
    """Return (answer, tier, label)."""
    standard = row_field(row, "standard_answer")
    if standard:
        return standard, "standard_answer", "🟢 HIGH"
    mock_key = row_field(row, "mock_key")
    if mock_key:
        return mock_key, "mock_key", "🟢 2026模拟题题源命中"
    provisional = row_field(row, "provisional_answer")
    if provisional:
        return provisional, "provisional_answer", "🟠 题源参考答案（未官方核验）"
    return "", "none", "未有标准答案"


def _option_text_map(options: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    by_text: dict[str, list[str]] = {}
    for letter in LETTERS:
        value = normalize_option(options.get(letter, ""))
        if value:
            by_text.setdefault(value, []).append(letter)
    duplicates = sorted(value for value, letters in by_text.items() if len(letters) > 1)
    return by_text, duplicates


def remap_answer(
    row: sqlite3.Row | dict[str, Any],
    presented_options: dict[str, Any] | None,
    answer: Any = None,
) -> dict[str, Any]:
    """Map a stored answer to the letters in the presented option order.

    The comparison is by option content, never by position. Duplicate option
    text is reported as unresolved because a letter cannot be inferred safely.
    """
    source_answer = answer_for_row(row)[0] if answer is None else text(answer)
    canonical = canonical_answer(source_answer)
    presented = presented_options or row_options(row)
    stored = row_options(row)
    presented_map, presented_duplicates = _option_text_map(presented)
    stored_map, stored_duplicates = _option_text_map(stored)
    if presented_duplicates:
        return {
            "answer": "",
            "canonical_answer": canonical,
            "status": "UNRESOLVED_DUPLICATE_PRESENTED_OPTIONS",
            "duplicates": presented_duplicates,
        }
    if stored_duplicates:
        return {
            "answer": "",
            "canonical_answer": canonical,
            "status": "UNRESOLVED_DUPLICATE_STORED_OPTIONS",
            "duplicates": stored_duplicates,
        }
    if not canonical:
        return {"answer": "", "canonical_answer": "", "status": "MISSING_ANSWER"}
    if all(ch in LETTERS for ch in canonical):
        mapped: list[str] = []
        missing: list[str] = []
        for source_letter in canonical:
            source_text = normalize_option(stored.get(source_letter, ""))
            targets = presented_map.get(source_text, []) if source_text else []
            if len(targets) != 1:
                missing.append(source_letter)
            else:
                mapped.append(targets[0])
        if missing:
            return {
                "answer": "",
                "canonical_answer": canonical,
                "status": "UNRESOLVED_OPTION_CONTENT_MISMATCH",
                "missing_source_letters": missing,
            }
        return {"answer": "".join(sorted(mapped)), "canonical_answer": canonical, "status": "MAPPED"}

    # Judgment answers in some sources are stored as Chinese words instead of
    # A/B. Map the word to the presented option whose text contains it.
    target = normalize_option(canonical)
    matches = [letter for letter, value in presented.items() if target and target in normalize_option(value)]
    if len(matches) == 1:
        return {"answer": matches[0], "canonical_answer": canonical, "status": "MAPPED_TEXT"}
    return {"answer": canonical, "canonical_answer": canonical, "status": "TEXT_UNMAPPED"}


@dataclass(frozen=True)
class MatchResult:
    method: str
    row: sqlite3.Row | None
    normalized: str
    score: float | None = None
    candidates: tuple[sqlite3.Row, ...] = ()
    option_signature_match: bool = False


class MatchIndex:
    """Process-local exact/normalized index with fuzzy fallback.

    A matcher instance is intentionally reused for a batch. This keeps each
    question lookup independent of SQLite I/O and makes latency measurable.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.rows = tuple(conn.execute("SELECT * FROM questions ORDER BY id").fetchall())
        self.by_hash: dict[str, list[sqlite3.Row]] = {}
        self.by_normalized: dict[str, list[sqlite3.Row]] = {}
        self.signatures: dict[str, str] = {}
        for row in self.rows:
            self.by_hash.setdefault(row["question_hash"], []).append(row)
            self.by_normalized.setdefault(row["normalized_question"], []).append(row)
            self.signatures[row["id"]] = option_signature(row_options(row))

    def lookup(
        self,
        question_text: Any,
        options: dict[str, Any] | None = None,
        limit: int = 5,
        fuzzy_threshold: float = 0.88,
    ) -> MatchResult:
        normalized = normalize_question(question_text)
        supplied = options or {}
        has_options = bool(option_signature(supplied))
        signature = option_signature(supplied)
        qhash = question_hash(question_text, supplied) if has_options else ""
        exact = []
        if qhash:
            exact = [row for row in self.by_hash.get(qhash, []) if self.signatures.get(row["id"]) == signature]
        if exact:
            return MatchResult("exact", exact[0], normalized, candidates=tuple(exact), option_signature_match=True)

        normalized_rows = list(self.by_normalized.get(normalized, []))
        if normalized_rows:
            option_rows = [row for row in normalized_rows if not has_options or self.signatures.get(row["id"]) == signature]
            if option_rows:
                return MatchResult("normalized_exact", option_rows[0], normalized, candidates=tuple(option_rows), option_signature_match=True)
            return MatchResult("normalized", normalized_rows[0], normalized, candidates=tuple(normalized_rows), option_signature_match=False)

        scored = sorted(
            ((difflib.SequenceMatcher(None, normalized, row["normalized_question"]).ratio(), row) for row in self.rows),
            key=lambda item: (-item[0], item[1]["id"]),
        )
        top = tuple(row for score, row in scored[: max(0, limit)])
        if scored and scored[0][0] >= fuzzy_threshold:
            return MatchResult("fuzzy", scored[0][1], normalized, scored[0][0], top, False)
        return MatchResult("none", None, normalized, scored[0][0] if scored else None, top, False)


def options_from_iterable(values: Iterable[Any]) -> dict[str, str]:
    items = list(values)
    return {letter: text(items[index]) if index < len(items) else "" for index, letter in enumerate(LETTERS)}

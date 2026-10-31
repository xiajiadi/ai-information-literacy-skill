from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, log_activity, now_iso, text
from db_schema import connect_db, ensure_schema


def canonical_answer(value: Any) -> str:
    raw = text(value).upper().replace("、", "").replace(",", "").replace("，", "")
    raw = "".join(ch for ch in raw if not ch.isspace() and ch not in "[]()")
    if raw and all(ch in "ABCD" for ch in raw):
        return "".join(sorted(set(raw)))
    return raw


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    if not records:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="用最终标准答案回填题库并比较 provisional_answer。")
    parser.add_argument("answers_file", help="JSON/JSONL/CSV；字段可用 attempt_id、question_id、standard_answer、error_reason、notes")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--allow-overwrite", action="store_true", help="仅在明确要修订既有标准答案时使用")
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    records = load_records(Path(args.answers_file).resolve())
    results = []
    stamp = now_iso()
    for record in records:
        attempt = None
        attempt_id = text(record.get("attempt_id"))
        question_id = text(record.get("question_id"))
        if attempt_id:
            attempt = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        elif question_id:
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE question_id=? ORDER BY created_at DESC LIMIT 1",
                (question_id,),
            ).fetchone()
        if not attempt:
            results.append({"status": "unresolved", "record": record, "reason": "找不到对应 attempt"})
            continue
        question_id = question_id or text(attempt["question_id"])
        standard = text(record.get("standard_answer") or record.get("answer"))
        if not standard:
            results.append({"status": "unresolved", "attempt_id": attempt["attempt_id"], "reason": "缺少 standard_answer"})
            continue
        provisional = text(attempt["provisional_answer"])
        left, right = canonical_answer(provisional), canonical_answer(standard)
        result = "UNRESOLVED" if not provisional else ("CORRECT" if left == right else "INCORRECT")
        question = conn.execute("SELECT standard_answer FROM questions WHERE id=?", (question_id,)).fetchone()
        existing_standard = text(question["standard_answer"]) if question else ""
        conflict = bool(existing_standard and canonical_answer(existing_standard) != right)
        if question_id and (not existing_standard or args.allow_overwrite) and not conflict:
            conn.execute(
                "UPDATE questions SET standard_answer=?, verification_status='OFFICIAL_ANSWER', confidence='HIGH', verified_at=?, updated_at=? WHERE id=?",
                (standard, stamp, stamp, question_id),
            )
        elif conflict:
            result = "UNRESOLVED"
        error_reason = text(record.get("error_reason"))
        if result == "INCORRECT" and not error_reason:
            error_reason = "待补充错误原因"
        conn.execute(
            """
            UPDATE attempts SET final_answer=?, result=?, error_reason=?,
                verification_status='OFFICIAL_ANSWER', updated_at=?
            WHERE attempt_id=?
            """,
            (standard, result, error_reason, stamp, attempt["attempt_id"]),
        )
        conn.execute(
            """
            INSERT INTO answer_reconciliations(
                attempt_id,question_id,provisional_answer,standard_answer,
                result,error_reason,reconciled_at,notes
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                attempt["attempt_id"], question_id, provisional, standard, result,
                error_reason, stamp,
                "既有标准答案冲突时保留原值；需要 --allow-overwrite 才能显式修订。",
            ),
        )
        results.append({
            "status": "reconciled",
            "attempt_id": attempt["attempt_id"],
            "question_id": question_id,
            "provisional_answer": provisional,
            "standard_answer": standard,
            "result": result,
            "conflict": conflict,
            "standard_answer_written": bool(question_id and (not existing_standard or args.allow_overwrite) and not conflict),
            "error_reason": error_reason,
        })
    conn.commit()
    log_activity(
        "answers_reconciled",
        {"total": len(records), "reconciled": sum(1 for row in results if row.get("status") == "reconciled")},
    )
    print(json.dumps({
        "status": "reconciliation_complete",
        "total": len(records),
        "reconciled": sum(1 for row in results if row.get("status") == "reconciled"),
        "correct": sum(1 for row in results if row.get("result") == "CORRECT"),
        "incorrect": sum(1 for row in results if row.get("result") == "INCORRECT"),
        "unresolved": sum(1 for row in results if row.get("status") == "unresolved" or row.get("result") == "UNRESOLVED"),
        "details": results,
    }, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

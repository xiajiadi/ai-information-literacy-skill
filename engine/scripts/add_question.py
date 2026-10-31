from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, infer_stability, json_text, log_activity, normalize_question, now_iso, question_hash, text
from db_schema import connect_db, ensure_schema


def next_question_id(conn) -> str:
    rows = conn.execute("SELECT id FROM questions WHERE id LIKE 'N%'").fetchall()
    numbers = []
    for row in rows:
        try:
            numbers.append(int(row["id"][1:]))
        except ValueError:
            continue
    return f"N{max(numbers, default=0) + 1:04d}"


def get_or_create_session(conn, args) -> str | None:
    if not args.session_id and not args.session_name:
        return None
    session_id = args.session_id or f"SES-{uuid.uuid4().hex[:12]}"
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO sessions(session_id,name,track,expected_count,status,started_at,notes)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET
            name=COALESCE(NULLIF(excluded.name,''), sessions.name),
            expected_count=COALESCE(excluded.expected_count, sessions.expected_count)
        """,
        (
            session_id,
            args.session_name or session_id,
            args.track,
            args.expected_count,
            "ACTIVE",
            stamp,
            "题目逐题写入；最终答案由 reconcile_answers.py 回填。",
        ),
    )
    return session_id


def main() -> int:
    parser = argparse.ArgumentParser(description="新增题目并立即创建 attempt；标准答案不会由本命令写入。")
    parser.add_argument("--question-text", required=True)
    parser.add_argument("--question-id", default="")
    parser.add_argument("--year", default="2026")
    parser.add_argument("--track", default="本科/研究生")
    parser.add_argument("--category", default="")
    parser.add_argument("--module-id", default="")
    parser.add_argument("--module-name", default="")
    parser.add_argument("--question-type", default="")
    parser.add_argument("--option-a", default="")
    parser.add_argument("--option-b", default="")
    parser.add_argument("--option-c", default="")
    parser.add_argument("--option-d", default="")
    parser.add_argument("--answer", default="", help="当前作答，只写 provisional_answer")
    parser.add_argument("--confidence", default="LOW", choices=["HIGH", "MEDIUM", "LOW", "NEEDS_HUMAN"])
    parser.add_argument("--verification-status", default="PROVISIONAL", choices=["PROVISIONAL", "NEEDS_HUMAN", "UNVERIFIED"])
    parser.add_argument("--retrieval-path", default="")
    parser.add_argument("--retrieval-query", default="")
    parser.add_argument("--retrieval-fields", default="")
    parser.add_argument("--retrieval-filters", default="")
    parser.add_argument("--evidence-url", default="")
    parser.add_argument("--evidence-path", default="")
    parser.add_argument("--evidence-text", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--session-name", default="")
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    options = {letter: getattr(args, f"option_{letter.lower()}") for letter in "ABCD"}
    conn = connect_db(args.db)
    ensure_schema(conn)
    normalized = normalize_question(args.question_text)
    qhash = question_hash(args.question_text, options)
    existing = conn.execute(
        "SELECT * FROM questions WHERE question_hash=? OR normalized_question=? ORDER BY id LIMIT 1",
        (qhash, normalized),
    ).fetchone()
    question_id = existing["id"] if existing else (args.question_id or next_question_id(conn))
    stamp = now_iso()
    if not existing:
        if args.module_id:
            module = conn.execute("SELECT 1 FROM modules WHERE module_id=?", (args.module_id,)).fetchone()
            if not module:
                raise SystemExit(f"module_id 不存在：{args.module_id}。先同步模块或留空。")
        conn.execute(
            """
            INSERT INTO questions(
                id,year,track,category,module_id,module_name,question_type,
                question_text,option_a,option_b,option_c,option_d,
                provisional_answer,retrieval_path,retrieval_query,retrieval_fields,
                retrieval_filters,question_stability,confidence,verification_status,
                notes,normalized_question,question_hash,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                question_id, args.year, args.track, args.category, args.module_id or None,
                args.module_name, args.question_type, args.question_text,
                options["A"], options["B"], options["C"], options["D"],
                args.answer, args.retrieval_path, args.retrieval_query or args.question_text,
                args.retrieval_fields, args.retrieval_filters,
                infer_stability(args.question_text), args.confidence, args.verification_status,
                "新题暂存；standard_answer 必须等待最终标准答案或可靠官方来源。",
                normalized, qhash, stamp, stamp,
            ),
        )
    elif args.answer:
        conn.execute(
            "UPDATE questions SET provisional_answer=?, confidence=?, verification_status=?, updated_at=? WHERE id=?",
            (args.answer, args.confidence, args.verification_status, stamp, question_id),
        )

    session_id = get_or_create_session(conn, args)
    attempt_id = f"ATT-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO attempts(
            attempt_id,session_id,question_id,raw_question_text,raw_options_json,
            provisional_answer,confidence,retrieval_path,retrieval_query,
            retrieval_fields,retrieval_filters,verification_status,notes,
            created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            attempt_id, session_id, question_id, args.question_text, json_text(options),
            args.answer, args.confidence, args.retrieval_path,
            args.retrieval_query or args.question_text, args.retrieval_fields,
            args.retrieval_filters, args.verification_status,
            "本次作答记录；尚未回填最终标准答案。",
            stamp, stamp,
        ),
    )
    evidence_id = None
    if any((args.evidence_url, args.evidence_path, args.evidence_text)):
        cur = conn.execute(
            """
            INSERT INTO evidence(
                question_id,attempt_id,evidence_type,url,captured_at,local_path,key_text,notes
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                question_id, attempt_id, "attempt_evidence", args.evidence_url,
                stamp, args.evidence_path, args.evidence_text,
                "证据由本次练习记录提供；动态题建议同时保存截图。",
            ),
        )
        evidence_id = cur.lastrowid
    conn.commit()
    log_activity(
        "attempt_created",
        {"attempt_id": attempt_id, "question_id": question_id, "session_id": session_id, "matched_existing_question": bool(existing)},
    )
    print(json.dumps({
        "status": "attempt_created",
        "question_id": question_id,
        "attempt_id": attempt_id,
        "session_id": session_id,
        "matched_existing_question": bool(existing),
        "standard_answer_written": False,
        "evidence_id": evidence_id,
    }, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

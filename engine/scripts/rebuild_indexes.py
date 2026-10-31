from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, normalize_question, now_iso, option_signature, question_hash
from db_schema import connect_db, ensure_schema, fts_available, rebuild_fts


def main() -> int:
    parser = argparse.ArgumentParser(description="重建题干标准化字段、哈希和 FTS 辅助索引。")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    for row in rows:
        options = {
            "A": row["option_a"], "B": row["option_b"],
            "C": row["option_c"], "D": row["option_d"],
        }
        conn.execute(
            "UPDATE questions SET normalized_question=?, question_hash=?, updated_at=? WHERE id=?",
            (normalize_question(row["question_text"]), question_hash(row["question_text"], options), now_iso(), row["id"]),
        )
    fts_ok = rebuild_fts(conn)
    conn.commit()
    result = {
        "status": "rebuilt",
        "questions": len(rows),
        "fts_available": fts_ok,
        "fts_rows": conn.execute("SELECT COUNT(*) FROM questions_fts").fetchone()[0] if fts_ok else 0,
        "duplicate_hash_groups": conn.execute(
            "SELECT COUNT(*) FROM (SELECT question_hash FROM questions GROUP BY question_hash HAVING COUNT(*) > 1)"
        ).fetchone()[0],
    }
    print(json.dumps(result, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

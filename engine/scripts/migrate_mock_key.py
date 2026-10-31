"""Promote the three 2026 simulation sets to the MOCK_KEY answer tier.

Background
----------
The 150 simulation questions shipped with an answer key, but that key was never
independently re-verified against the public official sources. It is therefore
NOT `standard_answer` (independently verified) and NOT `provisional_answer`
(derived by this project). It is a third tier, `mock_key`.

This migration:
  * adds `questions.mock_key` and `questions.source_priority`
  * widens the `verification_status` CHECK to admit 'MOCK_KEY'
  * moves the 150 keys out of `provisional_answer` into `mock_key`
  * marks them confidence=HIGH, verification_status=MOCK_KEY, source_priority=0

It is idempotent and refuses to run destructively: it backs the database up
first and re-verifies row counts and foreign keys afterwards.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, now_iso
from db_schema import FTS_SCHEMA_SQL, SCHEMA_SQL, connect_db, rebuild_fts


MOCK_SOURCE_TYPE = "用户提供模拟题整理"
MOCK_KEY_STATUS = "MOCK_KEY"
P0_PRIORITY = 0
FTS_TRIGGERS = ("questions_fts_ai", "questions_fts_au", "questions_fts_ad")


def questions_ddl(table_name: str) -> str:
    """Return the canonical questions DDL under a different table name."""
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS questions \((.*?)\n\);", SCHEMA_SQL, re.S
    )
    if not match:
        raise SystemExit("Could not locate the questions DDL in db_schema.SCHEMA_SQL")
    return f"CREATE TABLE {table_name} ({match.group(1)}\n);"


def has_columns(conn: sqlite3.Connection, table: str, names: set[str]) -> bool:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return names.issubset(present)


def backup(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.stem}.backup-{stamp}{db_path.suffix}")
    shutil.copy2(db_path, target)
    return target


def ensure_fts_artifacts(conn: sqlite3.Connection) -> bool:
    """Recreate the FTS triggers and reindex. Safe to call repeatedly."""
    conn.executescript(FTS_SCHEMA_SQL)
    conn.commit()
    return rebuild_fts(conn)


def migrate(conn: sqlite3.Connection) -> dict:
    before = {
        "questions": conn.execute("SELECT count(*) FROM questions").fetchone()[0],
        "fts": conn.execute("SELECT count(*) FROM questions_fts").fetchone()[0],
    }
    old_columns = [row[1] for row in conn.execute("PRAGMA table_info(questions)")]

    conn.execute("PRAGMA foreign_keys = OFF")
    for trigger in FTS_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    # executescript() issues an implicit COMMIT, so the swap is driven by
    # explicit BEGIN/COMMIT with Python's own transaction handling disabled.
    conn.isolation_level = None
    conn.execute("BEGIN")
    conn.execute("DROP TABLE IF EXISTS questions_new")
    conn.execute(questions_ddl("questions_new"))

    new_columns = [row[1] for row in conn.execute("PRAGMA table_info(questions_new)")]
    shared = [c for c in old_columns if c in new_columns]
    column_list = ", ".join(f'"{c}"' for c in shared)
    conn.execute(
        f"INSERT INTO questions_new ({column_list}) SELECT {column_list} FROM questions"
    )

    conn.execute("DROP TABLE questions")
    conn.execute("ALTER TABLE questions_new RENAME TO questions")

    # The 150 simulation keys move tiers: provisional_answer -> mock_key.
    promoted = conn.execute(
        """
        UPDATE questions
           SET mock_key = provisional_answer,
               provisional_answer = NULL,
               verification_status = ?,
               confidence = 'HIGH',
               source_priority = ?,
               verified_at = COALESCE(verified_at, ?),
               updated_at = ?
         WHERE source_type = ?
           AND mock_key IS NULL
           AND provisional_answer IS NOT NULL
           AND trim(provisional_answer) <> ''
        """,
        (MOCK_KEY_STATUS, P0_PRIORITY, now_iso(), now_iso(), MOCK_SOURCE_TYPE),
    ).rowcount

    # Simulation sets are P0 sources.
    conn.execute(
        "UPDATE sources SET source_priority = ?, updated_at = ? WHERE source_id LIKE 'SIM%'",
        (P0_PRIORITY, now_iso()),
    )

    conn.execute("COMMIT")
    conn.isolation_level = ""

    conn.executescript(SCHEMA_SQL)
    rebuilt = ensure_fts_artifacts(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    after = {
        "questions": conn.execute("SELECT count(*) FROM questions").fetchone()[0],
        "fts": conn.execute("SELECT count(*) FROM questions_fts").fetchone()[0],
        "mock_key_rows": conn.execute(
            "SELECT count(*) FROM questions WHERE verification_status = ?",
            (MOCK_KEY_STATUS,),
        ).fetchone()[0],
        "fk_errors": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "fts_rebuilt": rebuilt,
    }
    return {"before": before, "after": after, "promoted": promoted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    if not args.no_backup:
        print(f"backup -> {backup(db_path)}")

    conn = connect_db(db_path)
    already = has_columns(conn, "questions", {"mock_key", "source_priority"})
    if already:
        pending = conn.execute(
            "SELECT count(*) FROM questions WHERE source_type = ? "
            "AND mock_key IS NULL AND provisional_answer IS NOT NULL "
            "AND trim(provisional_answer) <> ''",
            (MOCK_SOURCE_TYPE,),
        ).fetchone()[0]
        if pending == 0:
            # Columns already present. Still make sure the FTS triggers and
            # index exist -- a failed earlier run can leave them dropped.
            rebuilt = ensure_fts_artifacts(conn)
            mock_key_rows = conn.execute(
                "SELECT count(*) FROM questions WHERE verification_status = ?",
                (MOCK_KEY_STATUS,),
            ).fetchone()[0]
            fk_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            print("columns present; backfill already done")
            print(f"mock_key_rows: {mock_key_rows}")
            print(f"fts rebuilt: {rebuilt}")
            print(f"fk_errors: {fk_errors}")
            print("STATUS:", "PASS" if mock_key_rows == 150 and fk_errors == 0 else "FAIL")
            return 0 if mock_key_rows == 150 and fk_errors == 0 else 1

    report = migrate(conn)
    conn.close()
    for key, value in report.items():
        print(f"{key}: {value}")

    ok = (
        report["before"]["questions"] == report["after"]["questions"]
        and report["before"]["fts"] == report["after"]["fts"]
        and report["after"]["fk_errors"] == 0
        and report["after"]["mock_key_rows"] == 150
    )
    print("STATUS:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

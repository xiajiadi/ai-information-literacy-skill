from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, EXPORT_DIR, json_text, log_activity, now_iso
from db_schema import connect_db, ensure_schema


TABLES = ("questions", "raw_records", "question_sources", "sources", "evidence", "attempts", "sessions")


def export_table(conn, table: str, out_dir: Path) -> int:
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()]
    path = out_dir / f"{table}.jsonl"
    path.write_text("".join(json_text(row) + "\n" for row in rows), encoding="utf-8")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出题库 JSONL 和可读 CSV 备份。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--out-dir", default=str(EXPORT_DIR))
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {table: export_table(conn, table, out_dir) for table in TABLES}
    question_rows = [dict(row) for row in conn.execute("SELECT * FROM questions ORDER BY id").fetchall()]
    csv_path = out_dir / "question_bank.csv"
    if question_rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(question_rows[0].keys()))
            writer.writeheader()
            writer.writerows(question_rows)
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("last_export", json_text({"dir": str(out_dir), "counts": counts, "at": now_iso()}), now_iso()),
    )
    conn.commit()
    log_activity("question_bank_exported", {"out_dir": str(out_dir), "counts": counts})
    print(json.dumps({"status": "exported", "out_dir": str(out_dir), "counts": counts, "csv": str(csv_path)}, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

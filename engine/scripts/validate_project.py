from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, SOURCE_TYPE_TO_ID
from db_schema import connect_db, ensure_schema, fts_available


REQUIRED_TABLES = {
    "questions", "sources", "question_sources", "evidence", "attempts",
    "modules", "platforms", "sessions", "raw_records", "answer_reconciliations",
}


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return -1
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="验证本地题库初始化的结构、计数和关键导出。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--xlsx", default="")
    parser.add_argument("--skill", default=str(Path(__file__).resolve().parents[1] / "skill" / "module_01_50.md"))
    parser.add_argument("--manifest", default=str(Path(__file__).resolve().parents[1] / "data" / "evidence" / "material_manifest.json"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    conn = connect_db(args.db)
    ensure_schema(conn)
    errors: list[str] = []
    warnings: list[str] = []
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    }
    missing = REQUIRED_TABLES - tables
    if missing:
        errors.append(f"missing_tables:{sorted(missing)}")
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in sorted(REQUIRED_TABLES & tables)
    }
    seed_source_types = tuple(SOURCE_TYPE_TO_ID.keys())
    seed_source_ids = tuple(SOURCE_TYPE_TO_ID.values())
    type_placeholders = ",".join("?" for _ in seed_source_types)
    id_placeholders = ",".join("?" for _ in seed_source_ids)
    scoped_counts = {
        "seed_questions": conn.execute(
            f"SELECT COUNT(*) FROM questions WHERE source_type IN ({type_placeholders})",
            seed_source_types,
        ).fetchone()[0],
        "seed_raw_records": conn.execute(
            f"SELECT COUNT(*) FROM raw_records WHERE source_id IN ({id_placeholders})",
            seed_source_ids,
        ).fetchone()[0],
        "seed_question_sources": conn.execute(
            f"SELECT COUNT(*) FROM question_sources WHERE source_id IN ({id_placeholders})",
            seed_source_ids,
        ).fetchone()[0],
        "simulation_questions": conn.execute(
            "SELECT COUNT(*) FROM questions WHERE source_type=?", ("用户提供模拟题整理",)
        ).fetchone()[0],
        "simulation_raw_records": conn.execute(
            "SELECT COUNT(*) FROM raw_records WHERE source_id LIKE 'SIM%'"
        ).fetchone()[0],
        "simulation_question_sources": conn.execute(
            "SELECT COUNT(*) FROM question_sources WHERE source_id LIKE 'SIM%'"
        ).fetchone()[0],
    }
    expected_seed = {
        "seed_questions": 93,
        "seed_raw_records": 156,
        "seed_question_sources": 156,
    }
    for key, value in expected_seed.items():
        if scoped_counts.get(key) != value:
            errors.append(f"{key}={scoped_counts.get(key)} expected={value}")
    if counts.get("modules") != 50:
        errors.append(f"modules_count={counts.get('modules')} expected=50")
    if counts.get("platforms", 0) < 1:
        errors.append("platforms_not_seeded")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        errors.append("foreign_key_check_failed")
    fts_count = conn.execute("SELECT COUNT(*) FROM questions_fts").fetchone()[0] if fts_available(conn) else 0
    if not fts_available(conn) or fts_count != counts.get("questions", 0):
        errors.append(f"fts_count={fts_count} expected={counts.get('questions', 0)}")
    if conn.execute(
        f"SELECT COUNT(*) FROM questions WHERE source_type IN ({type_placeholders}) "
        "AND (standard_answer IS NULL OR standard_answer='')",
        seed_source_types,
    ).fetchone()[0]:
        errors.append("seed_questions_missing_standard_answer")
    if conn.execute("SELECT COUNT(*) FROM questions GROUP BY question_hash HAVING COUNT(*) > 1").fetchall():
        warnings.append("duplicate_question_hash_present")

    normalized = root / "data" / "normalized"
    exports = root / "data" / "exports"
    jsonl_counts = {
        "normalized_questions": jsonl_count(normalized / "questions.jsonl"),
        "normalized_raw_records": jsonl_count(normalized / "raw_records.jsonl"),
        "normalized_simulation_questions": jsonl_count(normalized / "simulation_questions.jsonl"),
        "normalized_simulation_raw_records": jsonl_count(normalized / "simulation_raw_records.jsonl"),
        "module_profiles": jsonl_count(normalized / "module_profiles.jsonl"),
        "export_questions": jsonl_count(exports / "questions.jsonl"),
        "export_raw_records": jsonl_count(exports / "raw_records.jsonl"),
        "export_simulation_questions": jsonl_count(exports / "simulation_question_bank.jsonl"),
    }
    if jsonl_counts["normalized_questions"] != expected_seed["seed_questions"]:
        errors.append("question_jsonl_count_mismatch")
    if jsonl_counts["normalized_raw_records"] != expected_seed["seed_raw_records"]:
        errors.append("raw_record_jsonl_count_mismatch")
    simulation_present = any(value > 0 for key, value in scoped_counts.items() if key.startswith("simulation_"))
    if simulation_present:
        if scoped_counts["simulation_raw_records"] != 150:
            errors.append(f"simulation_raw_records={scoped_counts['simulation_raw_records']} expected=150")
        if scoped_counts["simulation_question_sources"] != 150:
            errors.append(f"simulation_question_sources={scoped_counts['simulation_question_sources']} expected=150")
        if jsonl_counts["normalized_simulation_questions"] != 150:
            errors.append("normalized_simulation_question_jsonl_count_mismatch")
        if jsonl_counts["normalized_simulation_raw_records"] != 150:
            errors.append("normalized_simulation_raw_jsonl_count_mismatch")
        if jsonl_counts["export_simulation_questions"] != 150:
            errors.append("export_simulation_question_jsonl_count_mismatch")
    if jsonl_counts["export_questions"] != counts.get("questions"):
        errors.append("export_question_jsonl_count_mismatch")
    if jsonl_counts["export_raw_records"] != counts.get("raw_records"):
        errors.append("export_raw_record_jsonl_count_mismatch")
    if jsonl_counts["module_profiles"] != 50:
        errors.append("module_profile_count_mismatch")

    skill_path = Path(args.skill).resolve()
    if not skill_path.exists():
        errors.append("skill_file_missing")
    else:
        skill_text = skill_path.read_text(encoding="utf-8")
        if skill_text.count("## 知识模块") != 50:
            errors.append("skill_heading_count_mismatch")
        if "Q0001" not in skill_text or "Q0093" not in skill_text:
            errors.append("skill_question_boundary_missing")

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        errors.append("material_manifest_missing")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if len(manifest) != 9:
            errors.append(f"pdf_manifest_count={len(manifest)} expected=9")
        if any(item.get("extraction_status") == "VISUAL_ONLY" for item in manifest):
            warnings.append("visual_only_training_pdfs_present")

    simulation_manifest_path = root / "data" / "evidence" / "simulation_manifest.json"
    if simulation_present:
        if not simulation_manifest_path.exists():
            errors.append("simulation_manifest_missing")
        else:
            simulation_manifest = json.loads(simulation_manifest_path.read_text(encoding="utf-8"))
            if simulation_manifest.get("records") != 150:
                errors.append(f"simulation_manifest_records={simulation_manifest.get('records')} expected=150")
            if simulation_manifest.get("unique_question_ids") != scoped_counts["simulation_questions"]:
                errors.append("simulation_manifest_unique_question_count_mismatch")
            if len(simulation_manifest.get("files", [])) != 3:
                errors.append("simulation_manifest_file_count_mismatch")

    formula_count = None
    formula_errors = None
    if args.xlsx:
        if openpyxl is None:
            warnings.append("openpyxl_unavailable_formula_check_skipped")
        else:
            wb_formula = openpyxl.load_workbook(Path(args.xlsx).resolve(), data_only=False, read_only=True)
            wb_value = openpyxl.load_workbook(Path(args.xlsx).resolve(), data_only=True, read_only=True)
            formula_count = sum(
                1
                for ws in wb_formula.worksheets
                for row in ws.iter_rows()
                for cell in row
                if isinstance(cell.value, str) and cell.value.startswith("=")
            )
            formula_errors = sum(
                1
                for ws in wb_value.worksheets
                for row in ws.iter_rows()
                for cell in row
                if isinstance(cell.value, str) and cell.value.startswith("#")
            )
            if formula_errors:
                errors.append(f"formula_errors={formula_errors}")

    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "jsonl_counts": jsonl_counts,
        "formula_count": formula_count,
        "formula_errors": formula_errors,
        "fts": {"available": fts_available(conn), "rows": fts_count},
        "db": str(Path(args.db).resolve()),
        "skill": str(skill_path),
        "manifest": str(manifest_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

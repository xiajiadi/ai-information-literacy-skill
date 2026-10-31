from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import openpyxl
except ImportError as exc:
    raise SystemExit(
        "缺少 openpyxl。请用项目环境运行：uv run python scripts/ingest_xlsx.py <xlsx>"
    ) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    DB_PATH,
    NORMALIZED_DIR,
    confidence_for_seed,
    infer_stability,
    json_text,
    log_activity,
    normalize_question,
    now_iso,
    question_hash,
    source_id_for_type,
    source_priority_for_type,
    text,
    verification_for_seed,
)
from db_schema import connect_db, ensure_schema


PUBLIC_SOURCES: dict[str, dict[str, Any]] = {
    "S01": {
        "priority": 1,
        "type": "官网入口",
        "title": "2026 AI+信息素养大赛训练入口",
        "url": "https://csc.xxsuyang.com/training",
        "date": "2026",
        "status": "LOGIN_GATED",
        "notes": "公开入口访问后跳转统一身份认证；本项目不登录、不绕过验证、不读取账户内题目。",
    },
    "S02": {
        "priority": 1,
        "type": "官网公开内容",
        "title": "2026 官网公开知识模块",
        "url": "https://jsgateway.zhixinst.com/SCC/Website/GetKnowledgeList?kind=csc2025",
        "date": "2026",
        "status": "PUBLIC",
        "notes": "公开接口返回 50 个模块及其详情、样题、答案与解析；以当前本地快照为准。",
    },
    "S03": {
        "priority": 2,
        "type": "高校公开通知",
        "title": "焦作大学：2026 年大赛组织通知",
        "url": "",
        "date": "2026-09-08",
        "status": "PUBLIC",
        "notes": "公开通知用于核对全国统一题库、系统随机抽题和学校不自主命题的机制说明。",
    },
    "S04": {
        "priority": 2,
        "type": "高校公开通知",
        "title": "湖南师范大学：2026 年大赛通知",
        "url": "",
        "date": "2026-07-03",
        "status": "PUBLIC",
        "notes": "公开通知用于交叉核对校赛和模拟训练的定位。",
    },
    "S05": {
        "priority": 2,
        "type": "高校公开指南",
        "title": "长春工程学院图书馆：2026 备赛指南",
        "url": "",
        "date": "2026",
        "status": "PUBLIC",
        "notes": "用于核对题型、题量、范围与训练入口。",
    },
    "S06": {
        "priority": 3,
        "type": "公开转发说明",
        "title": "2026 备赛公开说明（搜狐转发）",
        "url": "",
        "date": "2026",
        "status": "PUBLIC",
        "notes": "仅作为公开辅助说明，不冒充题目正文来源。",
    },
    "S07": {
        "priority": 4,
        "type": "公开 PDF",
        "title": "2025 年大学生 AI+信息素养大赛客观题命题范围及备赛建议（本科/研究生）",
        "url": "https://lib.zmu.edu.cn/tsgcms/upload/file/%E9%99%84%E4%BB%B62%EF%BC%9A2025%E5%B9%B4%E5%A4%A7%E5%AD%A6%E7%94%9F%E2%80%9DAI%2B%E4%BF%A1%E6%81%AF%E7%B4%A0%E5%85%BB%E2%80%9C%E5%A4%A7%E8%B5%9B%E5%AE%A2%E8%A7%82%E9%A2%98%E5%91%BD%E8%8C%83%E5%9B%B4%E5%8F%8A%E5%A4%87%E8%B5%9B%E5%BB%BA%E8%AE%AE.pdf",
        "date": "2025-07",
        "status": "PUBLIC",
        "notes": "公开 PDF，包含本科/研究生赛道的 50 个模块、样题、答案和解析。",
    },
    "S08": {
        "priority": 4,
        "type": "公开 PDF",
        "title": "2024 年大学生信息素养大赛校内选拔赛命题范围及备赛建议",
        "url": "https://lib.caskm.edu.cn/uploadfile/ueditor/file/202408/1724894636c825bc.pdf",
        "date": "2024-08",
        "status": "PUBLIC",
        "notes": "公开 PDF，作为本科/研究生公开样题的历史来源。",
    },
    "S09": {
        "priority": 5,
        "type": "公开 PDF/索引",
        "title": "2022 年四川省/重庆市大学生信息素养大赛命题范围及备赛建议",
        "url": "",
        "date": "2022",
        "status": "PARTIAL",
        "notes": "仅作历史机制背景；没有稳定下载的副本，不计入题目数量。",
    },
}


def rows_from_sheet(ws) -> list[dict[str, Any]]:
    headers = [cell.value for cell in ws[1]]
    rows: list[dict[str, Any]] = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        if not any(value is not None for value in values):
            continue
        rows.append({headers[i]: values[i] if i < len(values) else None for i in range(len(headers))})
    return rows


def upsert_source(conn, source_id: str, info: dict[str, Any], raw_path: str = "") -> None:
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO sources(
            source_id, source_priority, source_type, title, url, source_date,
            access_status, access_notes, raw_path, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_priority=excluded.source_priority,
            source_type=excluded.source_type,
            title=excluded.title,
            url=COALESCE(NULLIF(excluded.url,''), sources.url),
            source_date=COALESCE(NULLIF(excluded.source_date,''), sources.source_date),
            access_status=excluded.access_status,
            access_notes=excluded.access_notes,
            raw_path=COALESCE(NULLIF(excluded.raw_path,''), sources.raw_path),
            updated_at=excluded.updated_at
        """,
        (
            source_id,
            info.get("priority", 7),
            info.get("type", "未知来源"),
            info.get("title", source_id),
            info.get("url", ""),
            info.get("date", ""),
            info.get("status", "UNKNOWN"),
            info.get("notes", ""),
            raw_path,
            stamp,
            stamp,
        ),
    )


def upsert_module(conn, row: dict[str, Any], sample_ids: list[str], dynamics: list[str], qtypes: list[str]) -> None:
    module_id = text(row.get("模块编号"))
    if not module_id:
        return
    number = int("".join(ch for ch in module_id if ch.isdigit()) or "0")
    stamp = now_iso()
    dynamicity = "DYNAMIC" if "DYNAMIC" in dynamics else ("SEMI_DYNAMIC" if "SEMI_DYNAMIC" in dynamics else "STATIC")
    conn.execute(
        """
        INSERT INTO modules(
            module_id, module_no, category, module_name, official_title, official_url,
            requires_login, common_question_types, sample_question_ids, dynamicity,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(module_id) DO UPDATE SET
            module_no=excluded.module_no,
            category=excluded.category,
            module_name=excluded.module_name,
            official_title=COALESCE(NULLIF(excluded.official_title,''), modules.official_title),
            official_url=COALESCE(NULLIF(excluded.official_url,''), modules.official_url),
            common_question_types=excluded.common_question_types,
            sample_question_ids=excluded.sample_question_ids,
            dynamicity=excluded.dynamicity,
            updated_at=excluded.updated_at
        """,
        (
            module_id,
            number,
            text(row.get("大类")),
            text(row.get("2026 官网公开模块标题") or row.get("知识模块/知识点")),
            text(row.get("2026 官网公开模块标题") or row.get("知识模块/知识点")),
            "https://csc.xxsuyang.com/training",
            "UNKNOWN",
            json_text(sorted(set(qtypes))),
            json_text(sample_ids),
            dynamicity,
            stamp,
            stamp,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="导入公开样题 Seed Excel 到 SQLite 和 JSONL。")
    parser.add_argument("xlsx", help="原始 Excel 文件路径")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx).resolve()
    if not xlsx_path.exists():
        raise SystemExit(f"找不到 Excel: {xlsx_path}")
    wb_values = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    wb_formulas = openpyxl.load_workbook(xlsx_path, data_only=False, read_only=True)
    required_sheets = {"题库", "原始记录", "来源", "模块概览"}
    missing = required_sheets - set(wb_values.sheetnames)
    if missing:
        raise SystemExit(f"Excel 缺少工作表: {sorted(missing)}")

    conn = connect_db(args.db)
    ensure_schema(conn)
    for source_id, info in PUBLIC_SOURCES.items():
        raw_path = ""
        if source_id == "S07":
            raw_path = "data/raw/teacher_training/2025_public_guide.pdf"
        elif source_id == "S08":
            raw_path = "data/raw/teacher_training/2024_public_guide.pdf"
        upsert_source(conn, source_id, info, raw_path)

    module_rows = rows_from_sheet(wb_values["模块概览"])
    raw_rows = rows_from_sheet(wb_values["原始记录"])
    question_rows = rows_from_sheet(wb_values["题库"])
    raw_by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in raw_rows:
        question_id = text(raw.get("去重归并ID"))
        if question_id:
            raw_by_question[question_id].append(raw)

    for module in module_rows:
        module_id = text(module.get("模块编号"))
        related = [row for row in question_rows if text(row.get("模块编号")) == module_id]
        upsert_module(
            conn,
            module,
            [text(row.get("题库ID")) for row in related if text(row.get("题库ID"))],
            [infer_stability(row.get("题干"), row.get("答案依据/解析")) for row in related],
            [text(row.get("题型")) for row in related if text(row.get("题型"))],
        )

    question_jsonl: list[dict[str, Any]] = []
    raw_jsonl: list[dict[str, Any]] = []
    for row in question_rows:
        question_id = text(row.get("题库ID"))
        if not question_id or not text(row.get("题干")):
            continue
        source_type = text(row.get("来源类型"))
        options = {letter: row.get(f"选项{letter}") for letter in "ABCD"}
        raw_source_rows = raw_by_question.get(question_id, [])
        source_date = text(row.get("来源日期"))
        if not source_date and raw_source_rows:
            source_date = text(raw_source_rows[0].get("来源日期"))
        stamp = now_iso()
        payload = {
            "id": question_id,
            "year": text(row.get("年份")),
            "track": text(row.get("赛道")),
            "source_type": source_type,
            "category": text(row.get("大类")),
            "module_id": text(row.get("模块编号")),
            "module_name": text(row.get("知识模块/知识点")),
            "question_type": text(row.get("题型")),
            "question_text": text(row.get("题干")),
            "option_a": text(options["A"]),
            "option_b": text(options["B"]),
            "option_c": text(options["C"]),
            "option_d": text(options["D"]),
            "standard_answer": text(row.get("正确答案")),
            "provisional_answer": "",
            "answer_explanation": text(row.get("答案依据/解析")),
            "official_platform": "",
            "official_url": text(row.get("来源URL")),
            "retrieval_path": "公开样题原始答案/解析",
            "retrieval_query": text(row.get("题干")),
            "retrieval_fields": "",
            "retrieval_filters": "",
            "question_stability": infer_stability(row.get("题干"), row.get("答案依据/解析")),
            "current_observed_value": "",
            "observed_at": "",
            "confidence": confidence_for_seed(source_type),
            "verification_status": verification_for_seed(source_type),
            "verified_at": source_date,
            "notes": "Seed 导入；原始答案保留为 standard_answer，后续练习答案只写 provisional_answer。",
            "normalized_question": normalize_question(row.get("题干")),
            "question_hash": question_hash(row.get("题干"), options),
            "created_at": stamp,
            "updated_at": stamp,
        }
        conn.execute(
            """
            INSERT INTO questions(
                id, year, track, source_type, category, module_id, module_name,
                question_type, question_text, option_a, option_b, option_c, option_d,
                standard_answer, provisional_answer, answer_explanation,
                official_platform, official_url, retrieval_path, retrieval_query,
                retrieval_fields, retrieval_filters, question_stability,
                current_observed_value, observed_at, confidence, verification_status,
                verified_at, notes, normalized_question, question_hash, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                year=excluded.year,
                track=excluded.track,
                source_type=excluded.source_type,
                category=excluded.category,
                module_id=excluded.module_id,
                module_name=excluded.module_name,
                question_type=excluded.question_type,
                question_text=excluded.question_text,
                option_a=excluded.option_a,
                option_b=excluded.option_b,
                option_c=excluded.option_c,
                option_d=excluded.option_d,
                standard_answer=COALESCE(NULLIF(questions.standard_answer,''), excluded.standard_answer),
                answer_explanation=excluded.answer_explanation,
                official_url=COALESCE(NULLIF(excluded.official_url,''), questions.official_url),
                retrieval_path=excluded.retrieval_path,
                retrieval_query=excluded.retrieval_query,
                question_stability=excluded.question_stability,
                confidence=excluded.confidence,
                verification_status=excluded.verification_status,
                verified_at=COALESCE(NULLIF(excluded.verified_at,''), questions.verified_at),
                normalized_question=excluded.normalized_question,
                question_hash=excluded.question_hash,
                updated_at=excluded.updated_at
            """,
            tuple(payload[field] for field in (
                "id", "year", "track", "source_type", "category", "module_id", "module_name",
                "question_type", "question_text", "option_a", "option_b", "option_c", "option_d",
                "standard_answer", "provisional_answer", "answer_explanation",
                "official_platform", "official_url", "retrieval_path", "retrieval_query",
                "retrieval_fields", "retrieval_filters", "question_stability",
                "current_observed_value", "observed_at", "confidence", "verification_status",
                "verified_at", "notes", "normalized_question", "question_hash", "created_at", "updated_at"
            )),
        )
        question_jsonl.append(payload)

        source_id = source_id_for_type(source_type)
        if source_id not in PUBLIC_SOURCES:
            upsert_source(
                conn,
                source_id,
                {
                    "priority": source_priority_for_type(source_type),
                    "type": source_type or "未知来源",
                    "title": source_type or "未知来源",
                    "status": "UNKNOWN",
                },
            )
        for raw in raw_source_rows:
            record_id = f"RR{int(raw.get('原始序号') or 0):04d}"
            raw_payload = {key: raw.get(key) for key in raw}
            raw_jsonl.append({"record_id": record_id, "question_id": question_id, **raw_payload})
            conn.execute(
                """
                INSERT INTO raw_records(
                    record_id, source_id, source_row_no, question_id, source_url,
                    payload_json, created_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    source_row_no=excluded.source_row_no,
                    question_id=excluded.question_id,
                    source_url=excluded.source_url,
                    payload_json=excluded.payload_json
                """,
                (
                    record_id,
                    source_id,
                    int(raw.get("原始序号") or 0),
                    question_id,
                    text(raw.get("来源URL")),
                    json_text(raw_payload),
                    stamp,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO question_sources(
                    question_id, source_id, raw_record_id, relation_type, is_primary,
                    source_url, source_answer, source_explanation, source_date, notes
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    question_id,
                    source_id,
                    record_id,
                    "source_record",
                    1 if source_type == text(row.get("来源类型")) else 0,
                    text(raw.get("来源URL")),
                    text(raw.get("正确答案")),
                    text(raw.get("答案依据/解析")),
                    text(raw.get("来源日期")),
                    "原始记录保留；重复题不覆盖。",
                ),
            )

    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("seed_file", str(xlsx_path), now_iso()),
    )
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("seed_counts", json_text({"raw_records": len(raw_rows), "questions": len(question_rows)}), now_iso()),
    )
    conn.commit()
    log_activity(
        "xlsx_ingested",
        {"source_file": str(xlsx_path), "raw_records": len(raw_rows), "questions": len(question_rows), "modules": len(module_rows)},
    )

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    q_path = NORMALIZED_DIR / "questions.jsonl"
    r_path = NORMALIZED_DIR / "raw_records.jsonl"
    q_path.write_text("".join(json_text(row) + "\n" for row in question_jsonl), encoding="utf-8")
    r_path.write_text("".join(json_text(row) + "\n" for row in raw_jsonl), encoding="utf-8")
    formula_count = 0
    formula_errors = 0
    for ws in wb_formulas.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_count += 1
    for ws in wb_values.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("#"):
                    formula_errors += 1
    print(json.dumps({
        "status": "imported",
        "source_file": str(xlsx_path),
        "raw_records": len(raw_rows),
        "questions": len(question_rows),
        "modules": len(module_rows),
        "formula_count_ignored": formula_count,
        "formula_errors_observed": formula_errors,
        "jsonl": [str(q_path), str(r_path)],
        "db": str(Path(args.db).resolve()),
    }, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

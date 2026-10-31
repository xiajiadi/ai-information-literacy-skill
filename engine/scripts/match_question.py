from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, text
from db_schema import connect_db, ensure_schema
from match_engine import MatchIndex, answer_with_tier, remap_answer, row_options


TIER_LABEL = {
    "standard_answer": "答案",
    "mock_key": "答案",
    "provisional_answer": "题源参考答案（未官方核验）",
    "none": "答案",
}


def answer_display(row, presented_options: dict[str, str] | None = None) -> str:
    stability = row["question_stability"]
    extra = "；当前平台数据可能已更新。" if stability == "DYNAMIC" else ""
    answer, answer_field, confidence_label = answer_with_tier(row)
    mapping = remap_answer(row, presented_options or row_options(row), answer)
    shown_answer = mapping["answer"] or answer or "未有标准答案"
    return (
        "【题库命中】\n"
        f"{TIER_LABEL.get(answer_field, '答案')}：{shown_answer}\n"
        f"题库ID：{row['id']}\n"
        f"来源：{row['source_type'] or '未知'}\n"
        f"置信度：{confidence_label}{extra}"
    )


def row_summary(row, score: float | None = None) -> dict:
    result = {
        "id": row["id"],
        "question_type": row["question_type"],
        "standard_answer": row["standard_answer"],
        "mock_key": row["mock_key"],
        "provisional_answer": row["provisional_answer"],
        "verification_status": row["verification_status"],
        "confidence": row["confidence"],
        "question_stability": row["question_stability"],
        "source_type": row["source_type"],
        "question_text": row["question_text"],
    }
    if score is not None:
        result["score"] = round(score, 4)
    return result


def exam_display(result, presented_options: dict[str, str]) -> str:
    if result.row is None or result.method not in {"exact", "normalized_exact"}:
        if result.method == "normalized":
            return "需要核对选项内容"
        return "未命中本地题库"
    answer, answer_field, confidence_label = answer_with_tier(result.row)
    mapping = remap_answer(result.row, presented_options, answer)
    if mapping["status"].startswith("UNRESOLVED"):
        return "需要核对选项内容"
    shown = mapping["answer"] or answer
    if not shown:
        return "未有可用答案"
    if answer_field == "standard_answer":
        return f"答案：{shown}\n🟢 本地题库原题命中"
    if answer_field == "mock_key":
        return f"答案：{shown}\n🟢 2026模拟题题源命中"
    return f"答案：{shown}\n🟠 本地题库原题命中（题源答案未官方核验）"


def main() -> int:
    parser = argparse.ArgumentParser(description="先查本地题库，再返回精确、标准化和相似候选。")
    parser.add_argument("question_text")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--option-a", default="")
    parser.add_argument("--option-b", default="")
    parser.add_argument("--option-c", default="")
    parser.add_argument("--option-d", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--exam-mode", action="store_true", help="只输出考试模式的极短答案。")
    args = parser.parse_args()

    options = {letter: getattr(args, f"option_{letter.lower()}") for letter in "ABCD"}
    # 全空选项字典是「真值」，直接传下去会让 remap_answer 以为题目选项是空的，
    # 于是每道题都返回「需要核对选项内容」。未提供的选项必须过滤掉，
    # 传 {} 让 remap_answer 回退到题库自身的选项。与 solve_question.py 口径一致。
    supplied = {letter: value for letter, value in options.items() if text(value)}
    conn = connect_db(args.db)
    ensure_schema(conn)
    result = MatchIndex(conn).lookup(args.question_text, supplied, limit=args.limit)
    if args.exam_mode:
        print(exam_display(result, supplied))
        conn.close()
        return 0

    normalized_matches = [row_summary(row) for row in result.candidates] if result.method in {"normalized", "normalized_exact"} else []
    exact_matches = [row_summary(row) for row in result.candidates] if result.method == "exact" else []
    fuzzy_matches = [row_summary(row, result.score if index == 0 else None) for index, row in enumerate(result.candidates)] if result.method in {"fuzzy", "none"} else []
    print("Exact Match")
    print(json.dumps(exact_matches, ensure_ascii=False, indent=2))
    print("Normalized Match")
    print(json.dumps(normalized_matches, ensure_ascii=False, indent=2))
    print("Fuzzy Match")
    print(json.dumps(fuzzy_matches, ensure_ascii=False, indent=2))
    if result.row is not None and result.method in {"exact", "normalized_exact"} and result.option_signature_match:
        print(answer_display(result.row, supplied))
    elif result.method == "normalized":
        print("存在标准化题干命中，但选项集合不同；请核对选项内容和顺序。")
    elif result.method == "fuzzy" and result.row is not None and result.score is not None:
        print(f"相似候选：{result.row['id']}（{result.score:.1%}）。相似命中不自动替代精确答案。")
    else:
        print("未达到可直接命中的本地题库阈值。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

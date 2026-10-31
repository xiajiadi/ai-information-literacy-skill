from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, extract_urls, now_iso, text
from db_schema import connect_db, ensure_schema
from match_engine import MatchIndex, answer_for_row, canonical_answer, remap_answer, row_options


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "quality" / "mock_benchmark.json"


def replace_urls_with_markdown(value: str) -> str:
    result = value
    for url in extract_urls(value):
        result = result.replace(url, f"[链接]({url})")
    return result


def remove_urls(value: str) -> str:
    result = value
    for url in extract_urls(value):
        result = result.replace(url, " ")
    return result


def variants(value: str) -> dict[str, str]:
    return {
        "brackets_half": value.replace("（", "(").replace("）", ")").replace("【", "[").replace("】", "]"),
        "brackets_full": value.replace("(", "（").replace(")", "）").replace("[", "【").replace("]", "】"),
        "spaces": re.sub(r"([，。；：？！])", r"  \1  ", value),
        "line_breaks": re.sub(r"[ \t]+", "\n", value),
        "url_markdown": replace_urls_with_markdown(value),
        "url_removed": remove_urls(value),
    }


def successful_match(result, row, options) -> bool:
    if result.row is None or result.row["id"] != row["id"] or result.method not in {"exact", "normalized_exact"}:
        return False
    answer = answer_for_row(row)[0]
    mapped = remap_answer(row, options, answer)
    return mapped["status"] in {"MAPPED", "MAPPED_TEXT"} and bool(mapped["answer"])


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * p + 0.999999) - 1)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="对三套模拟题执行原题、选项重排和文本变体匹配基准。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--seed", type=int, default=20260916)
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    rows = conn.execute("SELECT * FROM questions WHERE source_type=? ORDER BY id", ("用户提供模拟题整理",)).fetchall()
    index = MatchIndex(conn)
    rng = random.Random(args.seed)

    original_times: list[float] = []
    original_pass = 0
    original_methods: dict[str, int] = {}
    batch_start = time.perf_counter()
    for row in rows:
        options = row_options(row)
        start = time.perf_counter_ns()
        result = index.lookup(row["question_text"], options)
        original_times.append((time.perf_counter_ns() - start) / 1_000_000)
        original_methods[result.method] = original_methods.get(result.method, 0) + 1
        if successful_match(result, row, options):
            original_pass += 1
    batch_elapsed_ms = (time.perf_counter() - batch_start) * 1000

    reorder_pass = 0
    reorder_failures: list[str] = []
    reorder_start = time.perf_counter()
    for row in rows:
        source = row_options(row)
        letters = [letter for letter in "ABCD" if source.get(letter)]
        shuffled_values = [source[letter] for letter in letters]
        rng.shuffle(shuffled_values)
        presented = {letter: value for letter, value in zip(letters, shuffled_values)}
        result = index.lookup(row["question_text"], presented)
        mapped = remap_answer(row, presented, answer_for_row(row)[0])
        if result.row is not None and result.row["id"] == row["id"] and result.method in {"exact", "normalized_exact"} and mapped.get("status") in {"MAPPED", "MAPPED_TEXT"} and mapped.get("answer"):
            reorder_pass += 1
        else:
            reorder_failures.append(row["id"])
    reorder_elapsed_ms = (time.perf_counter() - reorder_start) * 1000

    variant_counts: dict[str, dict[str, int]] = {}
    variant_total = 0
    variant_pass = 0
    variant_failures: list[dict[str, str]] = []
    for row in rows:
        for variant_name, question_text in variants(row["question_text"]).items():
            variant_total += 1
            options = row_options(row)
            result = index.lookup(question_text, options)
            passed = successful_match(result, row, options)
            bucket = variant_counts.setdefault(variant_name, {"pass": 0, "total": 0})
            bucket["total"] += 1
            if passed:
                bucket["pass"] += 1
                variant_pass += 1
            elif len(variant_failures) < 20:
                variant_failures.append({"id": row["id"], "variant": variant_name, "method": result.method})

    result = {
        "generated_at": now_iso(),
        "status": "PASS" if len(rows) == 150 and original_pass == 150 and reorder_pass == 150 and variant_pass == variant_total and batch_elapsed_ms < 5000 else "FAIL",
        "seed": args.seed,
        "question_count": len(rows),
        "original_match": {"pass": original_pass, "total": len(rows), "methods": original_methods},
        "random_reorder": {"pass": reorder_pass, "total": len(rows), "failures": reorder_failures, "elapsed_ms": round(reorder_elapsed_ms, 4)},
        "text_variants": {"pass": variant_pass, "total": variant_total, "by_variant": variant_counts, "failures": variant_failures},
        "single_match_ms": {"p50": round(percentile(original_times, 0.50), 4), "p95": round(percentile(original_times, 0.95), 4), "max": round(max(original_times) if original_times else 0, 4), "mean": round(mean(original_times) if original_times else 0, 4)},
        "batch_150_ms": round(batch_elapsed_ms, 4),
        "thresholds": {"single_p95_ms_lt": 200, "batch_150_ms_lt": 5000, "accuracy": "100%"},
        "db": str(Path(args.db).resolve()),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

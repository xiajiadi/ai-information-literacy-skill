from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import infer_stability, json_text, normalize_question, option_signature, question_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="输出题干、选项的本地标准化结果。")
    parser.add_argument("question_text")
    for letter in "ABCD":
        parser.add_argument(f"--option-{letter.lower()}", default="")
    args = parser.parse_args()
    options = {letter: getattr(args, f"option_{letter.lower()}") for letter in "ABCD"}
    result = {
        "normalized_question": normalize_question(args.question_text),
        "option_signature": option_signature(options),
        "question_hash": question_hash(args.question_text, options),
        "question_stability": infer_stability(args.question_text),
    }
    print(json_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

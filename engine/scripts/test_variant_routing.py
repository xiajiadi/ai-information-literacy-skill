"""随机同型题路由测试（FAST Replica 验收项）。

从 150 道模拟题里随机抽题，人为修改课程/年份/关键词/机构，只检验三件事：

    1. 是否正确识别出原 Pattern（找回了参照题）
    2. 是否路由到正确 Platform
    3. 是否选中正确 Recipe

**不使用原答案。** 变体题一旦返回旧答案就是失败，无论答案对不对。

用法：

    .venv\\Scripts\\python.exe scripts\\test_variant_routing.py
    .venv\\Scripts\\python.exe scripts\\test_variant_routing.py --count 15 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, text
from db_schema import connect_db
from solve_question import detect_handoff, load_profile, solve
from variant_match import VARIANT, detect_platform, find_variant

ROOT = Path(__file__).resolve().parents[1]
SIM_SOURCE = "用户提供模拟题整理"

# 改名用的替换词表：模拟「换课程 / 换机构 / 换关键词」。
REPLACEMENTS = [
    ("信息素养", "数据素养"), ("人工智能", "机器学习"), ("区块链", "分布式账本"),
    ("大学", "学院"), ("武汉大学", "湖南师范大学"), ("清华大学", "中南大学"),
    ("四川大学", "湖南大学"), ("北京大学", "国防科技大学"),
]


def mutate(question: str, rng: random.Random, kinds: list[str]) -> tuple[str, list[str]]:
    """按指定种类改参数，返回 (新题干, 改了什么)。

    必须保证**确实改了**：若所有变异都是空操作（题干里没有可改的年份/关键词），
    返回的题干会与原题完全相同，那样测到的是「原题命中」而不是「变体路由」，
    结果毫无意义。因此最后有一层兜底改写，并在拿不到变化时如实报告。
    """
    changed: list[str] = []
    out = question

    if "year" in kinds:
        new = re.sub(r"\d{4}", lambda m: str(int(m.group()) + rng.choice([1, 2, 3])), out, count=2)
        if new != out:
            changed.append("年份")
            out = new

    if "number" in kinds:
        new = re.sub(r"(?<!\d)(\d)(?!\d)", lambda m: str((int(m.group()) + 2) % 9 + 1), out, count=2)
        if new != out:
            changed.append("编号")
            out = new

    if "keyword" in kinds:
        for source, target in REPLACEMENTS:
            if source in out:
                out = out.replace(source, target, 1)
                changed.append(f"关键词/{source}→{target}")
                break

    if "quoted" in kinds:
        def swap(match: re.Match) -> str:
            inner = match.group(1)
            return match.group(0).replace(inner, inner + "研究")
        new = re.sub(r"[《“\"]([^》”\"]{2,20})[》”\"]", swap, out, count=1)
        if new != out:
            changed.append("专名")
            out = new

    # 兜底：仍未改动时，替换掉第一个较长中文词，保证题干确实变了。
    if out == question:
        fallback = re.search(r"[一-龥]{3,6}", out)
        if fallback:
            word = fallback.group()
            out = out.replace(word, word[:-1] + "学", 1)
            if out != question:
                changed.append(f"兜底改写/{word}→{word[:-1]}学")
    return out, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260919)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = connect_db(args.db)
    rows = conn.execute(
        "SELECT * FROM questions WHERE source_type=? ORDER BY id", (SIM_SOURCE,)
    ).fetchall()
    if not rows:
        print("题库中没有模拟题")
        return 1

    profile = load_profile(ROOT / "config" / "fast_profile.yaml")
    rng = random.Random(args.seed)
    sample = rng.sample(list(rows), min(args.count, len(rows)))

    results: list[dict] = []
    for row in sample:
        original = text(row["question_text"])
        kinds = rng.sample(["year", "number", "keyword", "quoted"], k=2)
        mutated, changed = mutate(original, rng, kinds)

        # 人工交接触发题（微信/App/扫码等）不走变体，跳过以免测错对象。
        if detect_handoff(mutated, None, profile) is not None:
            results.append({
                "id": row["id"], "skipped": True,
                "reason": "改后题干命中人工交接触发器，不属于变体路由测试范围",
            })
            continue

        # 题干没被真正改动时，测到的是原题命中，不能算变体路由成绩。
        if mutated == original:
            results.append({
                "id": row["id"], "skipped": True,
                "reason": "无法构造有效变异，该题不计入",
            })
            continue

        from argparse import Namespace
        outcome = solve(Namespace(
            question_text=mutated, db=args.db,
            profile=str(ROOT / "config" / "fast_profile.yaml"),
            option_a="", option_b="", option_c="", option_d="",
            allow_browser=False, skip_web=True, hard_timeout_override=0.0,
            browser_cmd="", explain=False, json=False,
        ))

        variant = outcome.variant
        reference = variant.source_row["id"] if (variant and variant.source_row) else ""
        pattern_ok = reference == row["id"]

        # 平台判定分两种情况：
        #   - 参照题本身有平台（如「在万方……」）→ 变体配方必须带上同一平台；
        #     若题干点名了平台，还必须一致，不能张冠李戴。
        #   - 参照题本身没有平台（如「《某指南》正文第 4 页……」这类文档页码题）
        #     → 要求变体变出一个平台是错的，只要求不凭空捏造即可。
        asked_platform = detect_platform(mutated)
        resolved = (variant.platform if variant else "") or ""
        reference_platform = detect_platform(
            text(row["official_platform"]), original, text(row["official_url"])
        )
        if reference_platform:
            platform_ok = bool(resolved) and (not asked_platform or asked_platform == resolved)
        else:
            platform_ok = not asked_platform or asked_platform == resolved
        # 配方复用：必须拿到可执行的东西，且答案必须为空。
        # 口径与 render_variant 的回退一致 —— 入口、路由配方、题目自带的
        # retrieval_path 三者任一存在即可（文档页码类题就没有 official_url）。
        recipe_ok = bool(variant and (
            variant.recipe.get("official_url")
            or variant.recipe.get("retrieval_recipe")
            or variant.recipe.get("retrieval_path")
        ))
        answer_ok = outcome.answer == ""

        passed = (
            outcome.status == "OFFICIAL_MOCK_VARIANT"
            and pattern_ok and platform_ok and recipe_ok and answer_ok
        )
        results.append({
            "id": row["id"], "skipped": False,
            "changed": changed,
            "mutated": mutated[:70],
            "status": outcome.status,
            "reference": reference,
            "platform": detect_platform(mutated),
            "answer": outcome.answer,
            "pattern_ok": pattern_ok,
            "platform_ok": platform_ok,
            "recipe_ok": recipe_ok,
            "answer_ok": answer_ok,
            "passed": passed,
        })

    scored = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in scored if r["passed"])

    if args.json:
        print(json.dumps({"results": results, "passed": passed, "total": len(scored)},
                         ensure_ascii=False, indent=2))
        return 0 if passed == len(scored) and scored else 1

    print(f"{'题号':<14}{'状态':<24}{'参照':<14}{'平台':<16}{'答案':<6}{'结果'}")
    print("-" * 92)
    for r in results:
        if r.get("skipped"):
            print(f"{r['id']:<14}{'SKIP':<24}{r['reason'][:46]}")
            continue
        print(f"{r['id']:<14}{r['status']:<24}{r['reference'] or '—':<14}"
              f"{r['platform'] or '—':<16}{r['answer'] or '(空)':<6}"
              f"{'PASS' if r['passed'] else 'FAIL'}")
    print("-" * 92)
    print(f"同型题路由：{passed}/{len(scored)} 通过（跳过 {len(results) - len(scored)} 题）")
    print("契约：变体必须给出配方且 answer 必须为空；返回旧答案即为失败。")
    return 0 if passed == len(scored) and scored else 1


if __name__ == "__main__":
    raise SystemExit(main())

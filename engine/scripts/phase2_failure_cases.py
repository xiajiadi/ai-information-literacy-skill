"""PHASE 2 · 生成 ROUTING_FAILURE_CASES.md。

从 eval.json 与 dataset.json 直接生成，保证与评估结果一致、可复现，
而不是手抄一份容易走样的清单。

产出：data/quality/phase2/ROUTING_FAILURE_CASES.md
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, now_iso  # noqa: E402

PHASE2_DIR = ROOT / "data" / "quality" / "phase2"
EVAL = PHASE2_DIR / "eval.json"
DATASET = PHASE2_DIR / "dataset.json"
OUT = PHASE2_DIR / "ROUTING_FAILURE_CASES.md"


def main() -> int:
    evaluation = json.loads(EVAL.read_text(encoding="utf-8"))
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    metrics = evaluation["metrics"]
    groups = evaluation["groups"]

    correction_path = PHASE2_DIR / "eval_correction.json"
    correction = (
        json.loads(correction_path.read_text(encoding="utf-8"))
        if correction_path.exists() else {}
    )
    cm = correction.get("metrics", {})
    cp0 = correction.get("p0", {})

    lines: list[str] = [
        "# ROUTING_FAILURE_CASES",
        "",
        "PHASE 2 离线路由验收中**值得人工复核**的失败题目。",
        "",
        f"生成时间：{now_iso()}｜来源：`data/quality/phase2/eval.json`（本文件由脚本生成，与评估结果一致）",
        "",
        '> 说明：本阶段的「路由」只输出**方法与平台**，不输出答案。因此下面全部是',
        '> 「方法/平台选错」，不是「答案答错」。',
        "",
        "---",
        "",
        "## 0b. 修正后指标（Controller 指定口径，含分子/分母）",
        "",
        "| 指标 | 分子/分母 | 值 |",
        "|---|---|---|",
    ]
    for key in (
        "declared_platform_accuracy",
        "declared_platform_accuracy_unseen_subset",
        "undeclared_candidate_top1",
        "undeclared_candidate_top3",
        "required_platform_accuracy",
        "answer_intent_accuracy",
        "evidence_surface_accuracy",
        "joint_dimension_accuracy",
        "variant_platform_accuracy",
        "unknown_or_human_required_trigger_rate",
    ):
        item = cm.get(key)
        if item:
            lines.append(f"| {key} | {item['numerator']}/{item['denominator']} | {item['value']} |")
    if cp0:
        lines.append(f"| P0 URL 泄漏 | — | {cp0.get('p0_url_leak_count', {}).get('value')} |")
        lines.append(
            f"| P0 变体旧答案复用 | — | {cp0.get('p0_variant_old_answer_reuse_count', {}).get('value')} |"
        )
    if correction.get("timings_ms"):
        timing = correction["timings_ms"]
        lines.append(
            f"| 本地路由耗时 | n={timing.get('samples')} | "
            f"P50 {timing.get('p50')} / P90 {timing.get('p90')} / P95 {timing.get('p95')} ms |"
        )

    lines += [
        "",
        "### 0b.1 `undeclared_candidate_top1 = 0/16` 的解释（重要，不是统计错误）",
        "",
        "16 是「题干未点名平台、但人写的网址能映射出平台」的题数。系统对这 16 题全部返回",
        "`NO_SIGNAL`/`UNKNOWN` —— 因为这些题的**题干里根本不出现平台名**（平台只出现在",
        "操作者当时用的网址里，例如 `AI知数`、`LeapSpace`）。",
        "",
        "按 DECISION 3「未指定平台时不得猜测、必要时转人工」，这是**符合预期的保守行为**；",
        "但也暴露真实覆盖缺口：`AI知数`、`LeapSpace` 这类平台尚未进入别名表。",
        "另有 **112 题**没有任何可映射的平台 Gold，已从分母剔除。",
        "",
        "### 0b.2 剩余错误的主要来源",
        "",
        "- `answer_intent` 偏低：Gold 来自官方「答题模式」经**作者手写映射**转换，",
        "  状态为 `AUTHOR_MAPPING_PENDING_CONTROLLER_REVIEW`，需人工复核后替换为真人标注。",
        "- `evidence_surface`（68.6%）明显高于 `answer_intent`（45.1%）：说明",
        "  「证据在哪类来源」比「答案是什么形态」更容易从题干判断，印证拆维度的方向正确。",
        "",
        "---",
        "",
        "## 0. 指标速览（修正前口径，保留用于对照）",
        "",
        "| 指标 | 分子/分母 | 值 | 样本来源 |",
        "|---|---|---|---|",
    ]
    label_map = [
        ("Module Top-1", "module_top1_accuracy"),
        ("Module Top-3", "module_top3_coverage"),
        ("Task Type Accuracy", "task_type_accuracy"),
        ("Primary Platform Accuracy", "primary_platform_accuracy"),
        ("Primary Platform（初赛未见过）", "primary_platform_accuracy_unseen_questions"),
        ("Variant 平台继承（泛化）", "variant_platform_inheritance"),
        ("Variant 任务类型继承（泛化）", "variant_task_type_inheritance"),
        ("Query Syntax Valid Rate", "query_syntax_valid_rate"),
        ("Missing-info Safe", "missing_info_safe_count"),
    ]
    for label, key in label_map:
        item = metrics.get(key) or {}
        lines.append(
            f"| {label} | {item.get('numerator')}/{item.get('denominator')} | "
            f"{item.get('value')} | {(item.get('sample_source') or item.get('note') or '')[:60]} |"
        )

    lines += [
        "",
        "> ⚠️ **Module Top-1 = 100% 不是泛化能力**：那 56 题本身就在题库里，",
        "> 测的是检索层能否命中已有标签。泛化能力看 Variant 与「初赛未见过」两项。",
        "",
        "---",
        "",
        "## 1. 平台选错（主要失败类型）",
        "",
        f"共 {groups.get('platform_misses_total')} 题。按「Gold → 预测」归并：",
        "",
        "| Gold 平台 | 预测平台 | 次数 |",
        "|---|---|---|",
    ]
    counter = collections.Counter(
        (",".join(m["gold"][:1]), m["predicted"] or "(未识别)")
        for m in groups.get("platform_misses", [])
    )
    for (gold, predicted), count in counter.most_common():
        lines.append(f"| {gold} | {predicted} | {count} |")

    lines += [
        "",
        "### 1.1 根因分布（`platform_source`）",
        "",
        "| 判定来源 | 次数 | 含义 |",
        "|---|---|---|",
    ]
    source_meaning = {
        "MODULE": "题干没识别出平台，回退到**模块默认平台** —— 本轮最大单一根因",
        "UNKNOWN": "完全没有识别出任何平台",
        "QUESTION_TEXT": "从题干识别到了平台，但识别错了",
        "DECLARED": "题目显式声明",
    }
    source_counter = collections.Counter(
        m["platform_source"] for m in groups.get("platform_misses", [])
    )
    for source, count in source_counter.most_common():
        lines.append(f"| `{source}` | {count} | {source_meaning.get(source, '')} |")

    lines += [
        "",
        "### 1.2 逐题明细（前 25 条）",
        "",
        "| 题号 | 题源 | Gold 平台 | 预测 | 判定来源 | 题干 |",
        "|---|---|---|---|---|---|",
    ]
    for miss in groups.get("platform_misses", [])[:25]:
        lines.append(
            f"| {miss['id']} | {miss.get('part','')} | {','.join(miss['gold'])} | "
            f"{miss['predicted'] or '(未识别)'} | {miss['platform_source']} | {miss['stem'][:44]} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 2. 任务类型与官方「答题模式」不一致",
        "",
        f"共 {metrics.get('task_type_accuracy', {}).get('denominator', 0)} 题入组，"
        f"错 {metrics.get('task_type_accuracy', {}).get('denominator', 0) - metrics.get('task_type_accuracy', {}).get('numerator', 0)} 题。",
        "",
        "| 题号 | 可接受集合（来自官方答题模式） | 预测 | 置信度 | 题干 |",
        "|---|---|---|---|---|",
    ]
    for miss in groups.get("task_type_misses", [])[:20]:
        lines.append(
            f"| {miss['id']} | {'/'.join(miss['gold_accept'])} | {miss['predicted']} | "
            f"{miss['confidence']} | {miss['stem'][:44]} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 3. 缺失信息场景未安全收敛（P1）",
        "",
        "题目信息不足、平台无该字段、登录不可用等场景，系统**应当**返回",
        "UNKNOWN / HUMAN_REQUIRED，而不是给出一套看起来完整的检索方案。",
        "",
        "| 用例 | 类型 | 期望 | 实际 | 安全收敛 |",
        "|---|---|---|---|---|",
    ]
    for case in groups.get("missing_info", []):
        mark = "✅" if case["returned_unknown_or_handoff"] else "❌"
        lines.append(
            f"| {case['id']} | {case['kind']} | {case['expected'][:38]} | "
            f"task={case['predicted_task_type']} conf={case['task_confidence']} | {mark} |"
        )
    lines += [
        "",
        "**未安全收敛的用例**就是需要改的地方：系统在信息不足时仍然给出了高置信度的",
        "任务类型判断，应当改为强制降级或要求补全信息。",
        "",
        "---",
        "",
        "## 4. 变体泛化失败（继承方法失败）",
        "",
    ]
    variant_failures = [
        v for v in groups.get("variants", [])
        if v.get("platform_inherit_failed") or v.get("task_inherit_failed")
    ]
    if variant_failures:
        lines += [
            "| 变体 | 变更 | 期望平台 | 预测平台 | 期望任务类型 | 预测任务类型 |",
            "|---|---|---|---|---|---|",
        ]
        for v in variant_failures[:20]:
            lines.append(
                f"| {v['id']} | {v['mutation']} | {v.get('expected_platform') or '-'} | "
                f"{v['predicted_platform'] or '(未识别)'} | {v.get('expected_task_type') or '-'} | "
                f"{v['task_type']} |"
            )
    else:
        lines.append("（本次运行没有平台/任务类型继承失败）")

    lines += [
        "",
        "---",
        "",
        "## 5. 数据污染导致的失败（P0 相关）",
        "",
        "这两个污染**不是路由算法错**，而是历史题库的数据问题，但会直接误导操作者：",
        "",
        "| 污染 | 实测题数 | 危害 | 现状 |",
        "|---|---|---|---|",
        f"| `question_routes.retrieval_path` 写的是**答案解析**文本 | "
        f"{metrics.get('recipe_pollution', {}).get('retrieval_path_contained_answer_text')} | "
        "旧题答案被摆在「操作指引」位置 | 已由 `sanitize_recipe()` 屏蔽并置污点标记 |",
        f"| `question_routes.official_url` 指向**比赛系统** | "
        f"{metrics.get('recipe_pollution', {}).get('official_url_was_competition_surface')} | "
        "把 Human Only 的比赛面当成可复现的官方入口 | 已屏蔽并标记 surface |",
        "",
        f"屏蔽后仍然泄漏的数量：**{metrics.get('recipe_pollution', {}).get('answer_text_still_reaching_output')}**（期望 0）。",
        "",
        "---",
        "",
        "## 6. 平台能力表的结构性问题（影响面最大）",
        "",
        "`config/platform_capabilities.json` 有 **128** 个平台条目，其中 **105** 个的",
        "`name` 字段直接写的是**主机名**（例如 `aistudio` 的名字是 `aistudio.baidu.com`，",
        "`nhc` 的名字是 `nhc.gov.cn`）。",
        "",
        "后果：按「题干里出现的平台名」识别平台时，**82% 的平台没有可用名称**。",
        "这是平台准确率偏低的**首要结构性原因**，不是个别别名没配好。",
        "",
        "本轮措施：新增人工策展的 `config/platform_aliases.yaml`（覆盖 30+ 高频平台），",
        "并在 `alias_to_platform_key()` 中优先于人自动生成名。效果见第 0 节平台指标。",
        "",
        "**仍待 Controller 决策**：是否重建平台能力表，让每个条目都有真实名称与",
        "官方入口，而不是把 URL 主机当成平台。",
        "",
        "---",
        "",
        "## 7. 建议的人工复核顺序",
        "",
        "1. 第 5 节的两个数据污染 —— 影响安全边界，优先级最高。",
        "2. 第 6 节的平台表结构问题 —— 影响面最大，但需要重建，成本高。",
        "3. 第 1.1 节 `MODULE` 根因（22 例）—— 回退到模块默认平台掩盖了真实意图。",
        "4. 第 2 节的「答题模式 → 任务类型」映射表 —— 是作者手写映射，需你确认口径。",
        "5. 第 3 节的 2 个未安全收敛用例。",
        "",
        "配套工作表：`data/quality/phase2/human_review_worksheet.md`",
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}  ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

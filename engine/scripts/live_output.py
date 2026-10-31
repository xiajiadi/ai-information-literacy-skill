"""TEAM_LIVE 输出层：短、先答案、不伪造确定性。

固定格式（§20）：

    答案：AC
    P：80%
    决策：答
    证据：🟢 官方｜CNKI｜高级检索结果总数

概率纪律（§11 / §14 / §15）：

  - P 是「整道题最终提交答案完全正确」的主观概率，不是单项概率。
  - 多选题必须直接估计**整个选项组合**的联合概率。
    禁止把 A=90%、C=70% 说成 AC 整体 70% 或 90%；禁止用乘积或 min() 冒充。
    可校验的不变式：P(组合正确) <= min(P(每个选项正确))。
  - 置信度只允许使用固定档位（20/25/30/…/95），禁止 83.27% 这种虚假精度。
  - TEAM_LIVE 阈值 P > 0.20 才建议作答；个人赛阈值是 1/3，两者不得混用。

TEAM_LIVE 输出禁止包含：长篇思维过程、教程、背景介绍、无关链接、
「让我再研究一下」。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    CONFIDENCE_SCALE,
    EVIDENCE_HUMAN_REQUIRED,
    EVIDENCE_LABEL,
    EVIDENCE_MODEL_REASONING,
    EVIDENCE_SECONDARY,
    EVIDENCE_VERIFIED_MULTI,
    EVIDENCE_VERIFIED_PRIMARY,
    load_provincial_config,
    snap_confidence,
)

ANSWER = "答"
SKIP = "跳"
HANDOFF = "转人工"

DECISION_THRESHOLD_TEAM = 0.20
DECISION_THRESHOLD_INDIVIDUAL = 1.0 / 3.0

EVIDENCE_EMOJI = {
    EVIDENCE_VERIFIED_PRIMARY: "🟢 官方",
    EVIDENCE_VERIFIED_MULTI: "🟢 双源一致",
    EVIDENCE_SECONDARY: "🟠 旁证",
    EVIDENCE_MODEL_REASONING: "🟡 推理",
    EVIDENCE_HUMAN_REQUIRED: "🔴 需人工",
}

# TEAM_LIVE 下不得出现的内容特征。命中即视为格式违规。
FORBIDDEN_PATTERNS = (
    "让我再研究",
    "首先我们来看",
    "背景介绍",
    "教程",
    "步骤如下：\n1. 打开浏览器",
    "顺便说一下",
)


@dataclass
class MultiSelectEstimate:
    """多选题的整体组合估计。"""

    combination: str
    joint_probability: float
    per_option_probability: dict[str, float] = field(default_factory=dict)
    method: str = "DIRECT_ESTIMATE"
    rationale: str = ""

    def validate(self) -> None:
        combo = "".join(sorted(set(self.combination.replace(",", "").replace(" ", "").upper())))
        if not combo:
            raise ValueError("多选组合不能为空。")
        if self.method != "DIRECT_ESTIMATE":
            raise ValueError(
                "多选整体概率必须直接估计（method='DIRECT_ESTIMATE'）；"
                "不得由单项概率推算。"
            )
        if self.per_option_probability:
            weakest = min(self.per_option_probability.values())
            if self.joint_probability > weakest + 1e-9:
                raise ValueError(
                    f"组合概率 {self.joint_probability:.2f} 高于最弱选项的单项概率 "
                    f"{weakest:.2f}；P(组合正确) 不可能超过 P(任一选项正确)。"
                )
            product = 1.0
            for value in self.per_option_probability.values():
                product *= value
            if abs(self.joint_probability - product) < 1e-9:
                raise ValueError(
                    "组合概率恰好等于单项概率之积，疑似用乘法冒充整体估计；"
                    "请直接估计「整个组合完全正确」的概率。"
                )
        self.combination = combo


@dataclass
class LiveAnswer:
    answer: str
    evidence_level: str = EVIDENCE_MODEL_REASONING
    evidence_platform: str = ""
    evidence_where: str = ""
    threshold: float = DECISION_THRESHOLD_TEAM
    secondary_answer: str = ""
    secondary_probability: float | None = None
    key_reason: str = ""
    handoff_block: str = ""
    question_type: str = "SINGLE"
    probability_raw: float | None = None
    notes: list[str] = field(default_factory=list)

    # -- 概率与决策 -------------------------------------------------------
    @property
    def probability(self) -> int:
        """已吸附到档位的百分数。**未估计时返回 0，绝不拿阈值冒充概率。**"""
        raw = self.probability_raw
        if raw is None:
            return 0
        if raw <= 1.0:
            raw = raw * 100.0
        return snap_confidence(raw)

    @property
    def decision(self) -> str:
        if self.answer.strip() == "" or self.evidence_level == EVIDENCE_HUMAN_REQUIRED:
            return HANDOFF
        if self.probability_raw is None:
            return HANDOFF
        raw = self.probability_raw
        if raw > 1.0:
            raw = raw / 100.0
        return ANSWER if raw > self.threshold else SKIP

    @property
    def can_render_handoff(self) -> bool:
        return bool(self.handoff_block.strip())

    def render(self, max_lines: int | None = None) -> str:
        if self.evidence_level == EVIDENCE_HUMAN_REQUIRED and self.can_render_handoff:
            return self.handoff_block.strip()

        lines = [f"答案：{self.answer.strip() or '（未定）'}"]
        lines.append(
            f"P：{self.probability}%" if self.probability_raw is not None else "P：未估计"
        )
        lines.append(f"决策：{self.decision}")
        lines.append(f"证据：{self.evidence_label()}")
        if self.secondary_answer:
            extra = (
                f"（{snap_confidence(self.secondary_probability)}%）"
                if self.secondary_probability is not None
                else ""
            )
            lines.append(f"次选：{self.secondary_answer}{extra}")
        if self.key_reason:
            lines.append(f"关键依据：{self.key_reason}")
        if self.handoff_block:
            lines.append("")
            lines.append(self.handoff_block.strip())

        limit = max_lines if max_lines is not None else 6
        # 人工交接块是安全关键信息，永不被截断。
        if self.handoff_block:
            head_count = max(limit - self.handoff_block.count("\n") - 2, 4)
            head = lines[:head_count]
            return "\n".join(head + [""] + [self.handoff_block.strip()])
        return "\n".join(lines[:limit])

    def evidence_label(self) -> str:
        emoji = EVIDENCE_EMOJI.get(self.evidence_level, "🟡 推理")
        parts = [emoji]
        if self.evidence_platform:
            parts.append(self.evidence_platform)
        if self.evidence_where:
            parts.append(self.evidence_where)
        return "｜".join(parts)

    def violations(self) -> list[str]:
        """自检：TEAM_LIVE 下的格式与概率违规。"""
        problems: list[str] = []
        text = self.render()
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                problems.append(f"包含 TEAM_LIVE 禁止内容：{pattern}")
        if self.probability_raw is not None:
            # 原始估计可以是任意值，但**输出**必须已被 snap_confidence 吸附到档位。
            # 这里校验的是渲染出去的数字，而不是内部估计。
            if self.probability not in (0, *CONFIDENCE_SCALE):
                problems.append(f"置信度 {self.probability} 不在允许档位内（禁止虚假精度）。")
        if self.question_type == "MULTI" and self.probability_raw is None:
            problems.append("多选题缺少整体组合概率估计。")
        if self.decision == ANSWER and self.probability <= 20:
            problems.append("决策为「答」但 P <= 20%，低于团队赛正期望阈值。")
        return problems


def decide(probability: float, threshold: float = DECISION_THRESHOLD_TEAM) -> str:
    raw = float(probability)
    if raw > 1.0:
        raw = raw / 100.0
    return ANSWER if raw > threshold else SKIP


def multi_select(
    estimates: list[MultiSelectEstimate],
) -> tuple[MultiSelectEstimate, MultiSelectEstimate | None]:
    """从多个组合估计中选出最优与次选。每个估计都会先过合法性校验。"""
    if not estimates:
        raise ValueError("至少需要一个候选组合。")
    for estimate in estimates:
        estimate.validate()
    ranked = sorted(estimates, key=lambda e: -e.joint_probability)
    return ranked[0], (ranked[1] if len(ranked) > 1 else None)


def live_answer_from_multi(
    estimates: list[MultiSelectEstimate],
    evidence_level: str = EVIDENCE_SECONDARY,
    evidence_platform: str = "",
    evidence_where: str = "",
    key_reason: str = "",
) -> LiveAnswer:
    best, second = multi_select(estimates)
    return LiveAnswer(
        answer=best.combination,
        probability_raw=best.joint_probability * 100.0,
        evidence_level=evidence_level,
        evidence_platform=evidence_platform,
        evidence_where=evidence_where,
        secondary_answer=second.combination if second else "",
        secondary_probability=(second.joint_probability * 100.0) if second else None,
        key_reason=key_reason,
        question_type="MULTI",
    )


def self_check(payload: dict[str, Any]) -> dict[str, Any]:
    """供测试与运行期自检使用的纯函数：校验一条 TEAM_LIVE 输出。"""
    answer = LiveAnswer(
        answer=str(payload.get("answer", "")),
        probability_raw=payload.get("probability"),
        evidence_level=str(payload.get("evidence_level", EVIDENCE_MODEL_REASONING)),
        evidence_platform=str(payload.get("evidence_platform", "")),
        evidence_where=str(payload.get("evidence_where", "")),
        question_type=str(payload.get("question_type", "SINGLE")),
        threshold=float(payload.get("threshold", DECISION_THRESHOLD_TEAM)),
    )
    return {
        "rendered": answer.render(),
        "probability": answer.probability,
        "decision": answer.decision,
        "violations": answer.violations(),
    }


def configured_max_lines() -> int:
    try:
        config = load_provincial_config()
    except FileNotFoundError:
        return 6
    return int((config.get("output") or {}).get("max_lines", 6))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "用法：python scripts/live_output.py --answer AC --p 0.8 "
            "[--level VERIFIED_PRIMARY] [--platform CNKI] [--where 高级检索结果总数] "
            "[--multi] [--second ABC] [--second-p 0.35]"
        )
        return 2
    payload: dict[str, Any] = {}
    index = 0
    while index < len(args):
        key = args[index].lstrip("-")
        value = args[index + 1] if index + 1 < len(args) else ""
        payload[key] = value
        index += 2
    level = payload.get("level", EVIDENCE_SECONDARY)
    answer = LiveAnswer(
        answer=payload.get("answer", ""),
        probability_raw=float(payload.get("p", "0") or 0),
        evidence_level=level,
        evidence_platform=payload.get("platform", ""),
        evidence_where=payload.get("where", ""),
        secondary_answer=payload.get("second", ""),
        secondary_probability=(
            float(payload["second-p"]) if payload.get("second-p") else None
        ),
        key_reason=payload.get("reason", ""),
        handoff_block=payload.get("handoff", ""),
        question_type="MULTI" if "--multi" in args else "SINGLE",
    )
    print(answer.render(configured_max_lines()))
    problems = answer.violations()
    if problems:
        print("", file=sys.stderr)
        for problem in problems:
            print(f"[格式违规] {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

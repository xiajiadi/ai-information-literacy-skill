"""PHASE 2 修正 · DECISION 2：双维度任务模型。

    answer_intent     —— 答案是什么**形态**（一个值 / 一组 / 是否存在 / 规则推理…）
    evidence_surface  —— 证据在**哪类来源**（数据库 / 网站界面 / 本机软件 / 规范原文…）

为什么必须拆开：官方「答题模式」把两个维度混在一个枚举里
（如『篇名精确检索』既是取数形态又暗示数据库来源），一对一扫成单值
必然产生系统性偏差 —— PHASE 2 实测任务类型准确率只有 45.1%。

设计要点：
  * `answer_intent` **复用** `config/task_types.json` 的意图短语定义，
    避免两处维护同一套短语（DRY）；
  * `evidence_surface` 由 `config/evidence_surfaces.json` 定义；
  * 支持**多子任务**：一题可含多个 (intent, surface) 对；
  * `HUMAN_ONLY` 永远优先：合规判断先于取数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    ROOT,
    load_task_types,
    now_iso,
)

EVIDENCE_SURFACES_PATH = ROOT / "config" / "evidence_surfaces.json"
_CACHE: dict[str, Any] = {}


def load_evidence_surfaces() -> dict[str, Any]:
    if "surfaces" not in _CACHE:
        import functools

        from provincial_common import _cached_json  # 复用统一缓存

        _CACHE["surfaces"] = _cached_json(str(EVIDENCE_SURFACES_PATH))
    return _CACHE["surfaces"]


def _score(
    text: str, definition: dict[str, Any], intent_weight: float, signal_weight: float
) -> dict[str, Any]:
    lowered = text.lower()
    score = 0.0
    intent_hits: list[str] = []
    signal_hits: list[str] = []
    for phrase in definition.get("intent_phrases", []):
        if str(phrase).lower() in lowered:
            score += intent_weight * (1.0 + 0.15 * min(len(str(phrase)), 10) / 10)
            intent_hits.append(phrase)
    for pattern in definition.get("intent_patterns", []):
        if re.search(str(pattern), lowered):
            score += intent_weight
            intent_hits.append(f"/{pattern}/")
    for signal in definition.get("signals", []):
        if str(signal).lower() in lowered:
            score += signal_weight
            signal_hits.append(signal)
    return {
        "id": definition["id"],
        "score": round(score, 2),
        "intent_hits": intent_hits[:6],
        "signal_hits": signal_hits[:6],
        "intent_backed": bool(intent_hits),
    }


def detect_answer_intent(question_text: str) -> tuple[str, list[dict[str, Any]]]:
    """答案形态。复用 task_types.json 的意图短语（DRY）。"""
    config = load_task_types()
    weights = config.get("scoring", {})
    intent_weight = float(weights.get("intent_weight", 4))
    signal_weight = float(weights.get("signal_weight", 1))
    order = config["detection_order"]

    scores = [
        _score(question_text, definition, intent_weight, signal_weight)
        for definition in config["task_types"]
    ]
    positive = [item for item in scores if item["score"] > 0]
    if not positive:
        return "UNKNOWN", sorted(scores, key=lambda i: order.index(i["id"]))
    positive.sort(key=lambda item: (-item["score"], order.index(item["id"])))
    return positive[0]["id"], positive


def detect_evidence_surface(
    question_text: str, platform_key: str = "", module_no: int | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """取证来源。HUMAN_ONLY 永远优先（合规先于取数）。"""
    config = load_evidence_surfaces()
    weights = config.get("scoring", {})
    intent_weight = float(weights.get("intent_weight", 4))
    signal_weight = float(weights.get("signal_weight", 1))
    order = config["detection_order"]
    definitions = {item["id"]: item for item in config["evidence_surfaces"]}

    scores = [
        _score(question_text, item, intent_weight, signal_weight)
        for item in config["evidence_surfaces"]
    ]

    # 合规优先：题干命中比赛面即 HUMAN_ONLY，不参与打分比较
    from compliance_gate import COMPETITION

    try:
        verdict = __import__("compliance_gate").ComplianceGate().classify(question_text)
        if verdict.surface == COMPETITION:
            return "HUMAN_ONLY", sorted(scores, key=lambda i: order.index(i["id"]))
    except (ValueError, OSError):
        pass

    # 平台线索：已知平台的类型可以补强来源判断
    platform_surface_hint = {
        "cnki": "DATABASE", "wanfang": "DATABASE", "vip": "DATABASE",
        "pubmed": "DATABASE", "sciencedirect": "DATABASE", "ieee": "DATABASE",
        "cnipa": "DATABASE", "patentscope2": "DATABASE", "standards": "DATABASE",
        "stats": "STATISTICS", "baidu-index": "STATISTICS",
        "github": "REPOSITORY", "modelscope": "REPOSITORY", "aistudio": "REPOSITORY",
        "arxiv": "REPOSITORY", "unesco": "DOCUMENT", "nlc": "DATABASE",
        "nsfc": "DATABASE", "ncpssd": "DATABASE",
    }
    hint = platform_surface_hint.get((platform_key or "").lower(), "")
    for item in scores:
        if item["id"] == hint and item["score"] == 0:
            item["score"] = 1.0
            item["signal_hits"] = [f"platform_key={platform_key}"]

    positive = [item for item in scores if item["score"] > 0]
    if not positive:
        return "UNKNOWN", sorted(scores, key=lambda i: order.index(i["id"]))
    positive.sort(key=lambda item: (-item["score"], order.index(item["id"])))
    return positive[0]["id"], positive


def split_subtasks(question_text: str) -> list[dict[str, Any]]:
    """粗略切分多子任务。

    只按**显式并列连词**切分（「并且」「然后」「并据此」「再按」），
    不做激进切分 —— 过切会把单任务题拆坏。切不出多段时返回单元素列表。
    """
    parts = re.split(r"(?:，?\s*(?:并且|然后|之后|再按|并据此|并结合|再根据))", question_text)
    parts = [p.strip() for p in parts if len(p.strip()) >= 6]
    if len(parts) <= 1:
        return [{"index": 1, "text": question_text.strip()}]
    return [{"index": i + 1, "text": part} for i, part in enumerate(parts)]


def analyze(question_text: str, platform_key: str = "", module_no: int | None = None) -> dict[str, Any]:
    """输出双维度分析结果。"""
    intent, intent_candidates = detect_answer_intent(question_text)
    surface, surface_candidates = detect_evidence_surface(question_text, platform_key, module_no)

    subtasks = []
    for part in split_subtasks(question_text):
        part = dict(part)
        part_intent, _ = detect_answer_intent(part["text"])
        part_surface, _ = detect_evidence_surface(part["text"], platform_key, module_no)
        part["answer_intent"] = part_intent
        part["evidence_surface"] = part_surface
        subtasks.append(part)

    return {
        "answer_intent": intent,
        "answer_intent_confidence": _confidence(intent_candidates, intent),
        "answer_intent_candidates": intent_candidates[:3],
        "evidence_surface": surface,
        "evidence_surface_confidence": _confidence(surface_candidates, surface),
        "evidence_surface_candidates": surface_candidates[:3],
        "subtasks": subtasks,
        "analyzed_at": now_iso(),
        "note": (
            "answer_intent 来自 config/task_types.json 的意图短语（复用，非重复定义）；"
            "evidence_surface 来自 config/evidence_surfaces.json。"
            "两个维度独立评估，不再一对一映射官方『答题模式』。"
        ),
    }


def _confidence(candidates: list[dict[str, Any]], best_id: str) -> str:
    if not candidates or best_id in {"UNKNOWN", ""}:
        return "LOW"
    ranked = sorted(candidates, key=lambda i: -i["score"])
    best = next((c for c in ranked if c["id"] == best_id), None)
    if best is None:
        return "LOW"
    if not best.get("intent_backed", False):
        return "LOW"
    others = [c for c in ranked if c["id"] != best_id and c["score"] > 0]
    if not others:
        return "HIGH"
    if best["score"] >= others[0]["score"] * 2:
        return "HIGH"
    if best["score"] > others[0]["score"]:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    import json

    probes = [
        "某数据库中符合条件的论文有多少篇？",
        "某软件的下拉菜单里是否有某个功能？",
        "根据 GB/T 7714 判断该文献类型标识是否正确？",
        "在CNKI高级检索界面，精确检索作者为黄智的论文，2014-2024年间共有（ ）篇期刊论文。",
        "用Excel计算2020至2024年的年均增长率。",
        "在有道云笔记网页版创建流程图，输入Ctrl+Shift+O会呈现什么内容？",
    ]
    for probe in probes:
        result = analyze(probe)
        print(
            f"{probe[:38]:<40} -> {result['answer_intent']:<14}"
            f"({result['answer_intent_confidence']:<6}) + "
            f"{result['evidence_surface']:<14}({result['evidence_surface_confidence']})"
        )

"""任务路由器：题目 -> 模块识别 -> 任务类型 -> 平台 -> Recipe -> 检索计划。

新中心（替代旧的「题目 -> 题库 -> 答案」）：

    题目
    -> 知识模块识别      module_id（canonical 键）
    -> 任务类型识别      GET_VALUE / GET_LIST / GET_FIELD / EXISTS /
                        COMPARE / RULE_REASONING / TOOL_UI / CALCULATION
    -> 平台识别          config/platform_capabilities.json
    -> 平台能力 / Recipe config/platform_entry_status.json + query_templates
    -> 检索式生成        （交给 query_builder.py）
    -> 外部检索 / 证据 / 候选答案 / Human Decision

**本模块不产生答案。** 任何情况下都不返回旧题答案；同型题只返回配方。

输入必须由选手提供（Human Gate 1）。命令行传入空题干时直接拒绝。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate  # noqa: E402
from provincial_common import (  # noqa: E402
    DB_PATH,
    EVIDENCE_LABEL,
    EVIDENCE_MODEL_REASONING,
    ROOT,
    load_module_nav,
    load_platform_capabilities,
    load_task_types,
    load_yaml,
    text,
)
from variant_match import NEW, VARIANT, detect_platform, find_variant  # noqa: E402
MODULE_SOURCE_BANK = "BANK_MATCH"
MODULE_SOURCE_NAV = "NAV_TRIGGER"
MODULE_SOURCE_NONE = "UNKNOWN"

YEAR_RE = re.compile(r"(?:19|20)\d{2}")
FIELD_SPLIT_RE = re.compile(r"[、,，/／;；\s]+")


@dataclass
class Routing:
    question_text: str
    question_type: str = "UNKNOWN"
    # -- 模块 ---------------------------------------------------------------
    module_id: str = ""
    module_no: int | None = None
    module_name: str = ""
    module_category: str = ""
    module_source: str = MODULE_SOURCE_NONE
    module_candidates: list[dict[str, Any]] = field(default_factory=list)
    # 已知污染：questions.module_name 与 module_id 不一致。冲突必须显式记录。
    polluted_module_name: str = ""
    module_name_conflict: bool = False
    # -- 任务类型 -----------------------------------------------------------
    task_type: str = "UNKNOWN"
    task_type_name: str = ""
    task_type_confidence: str = "LOW"
    task_type_candidates: list[dict[str, Any]] = field(default_factory=list)
    # -- 平台与入口 ---------------------------------------------------------
    target_platform: str = ""
    target_platform_name: str = ""
    platform_source: str = ""
    platform_candidates: list[str] = field(default_factory=list)
    primary_entry: str = ""
    entry_status: str = "UNKNOWN"
    fallback_entry: str = ""
    entry_avoid: list[dict[str, Any]] = field(default_factory=list)
    # -- 检索计划 -----------------------------------------------------------
    required_fields: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    time_constraint: str = ""
    expected_output: str = ""
    evidence_floor: str = EVIDENCE_MODEL_REASONING
    # -- 匹配状态（绝不返回答案） -------------------------------------------
    match_status: str = NEW
    match_method: str = ""
    similarity: float = 0.0
    reference_question_id: str = ""
    reusable_recipe: dict[str, Any] = field(default_factory=dict)
    # --- PHASE 2 修正：双维度任务模型（DECISION 2）---
    answer_intent: str = ""
    answer_intent_confidence: str = "LOW"
    answer_intent_candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence_surface: str = ""
    evidence_surface_confidence: str = "LOW"
    evidence_surface_candidates: list[dict[str, Any]] = field(default_factory=list)
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    dimension_note: str = ""
    # --- PHASE 2 修正：平台路由优先级与不替换（DECISION 3）---
    platform_resolution: str = ""
    platform_resolution_reason: str = ""
    platform_candidates_v2: list[dict[str, Any]] = field(default_factory=list)
    declared_platform_text: str = ""
    platform_requires_human: bool = False
    forbidden_substitution: bool = False
    resolved_platform_v2: str = ""
    # --- PHASE 2 修正 §4：输出统一合规报告 ---
    output_compliance: dict[str, Any] = field(default_factory=dict)
    recipe_notes: list[str] = field(default_factory=list)
    # -- 合规 ---------------------------------------------------------------
    compliance_surface: str = ""
    compliance_decision: str = ""
    compliance_reason: str = ""
    handoff_expected: bool = False

    def analysis_payload(self) -> dict[str, Any]:
        """config/provincial_elimination.yaml:routing.required_analysis_fields。"""
        return {
            "module_id": self.module_id,
            "task_type": self.task_type,
            "target_platform": self.target_platform,
            "required_fields": self.required_fields,
            "filters": self.filters,
            "time_constraint": self.time_constraint,
            "expected_output": self.expected_output,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["analysis"] = self.analysis_payload()
        payload["evidence_floor_label"] = EVIDENCE_LABEL.get(self.evidence_floor, "")
        return payload


# ---------------------------------------------------------------------------
# 模块识别
# ---------------------------------------------------------------------------

def score_modules(question_text: str) -> list[dict[str, Any]]:
    nav = load_module_nav()
    lowered = question_text.lower()
    scored: list[dict[str, Any]] = []
    for module in nav["modules"]:
        score = 0.0
        hits: list[str] = []
        for term in module.get("trigger_terms", []):
            term_lower = str(term).lower()
            if len(term_lower) < 2:
                continue
            if term_lower in lowered:
                # 更长的触发词更具体，权重更高。
                score += min(len(term_lower), 12)
                hits.append(term)
        name = str(module.get("module_name") or "")
        if name and name.lower() in lowered:
            score += 20
            hits.append(name)
        if score > 0:
            scored.append(
                {
                    "module_id": module["module_id"],
                    "module_no": module["module_no"],
                    "module_name": name,
                    "category": module.get("category", ""),
                    "primary_platform": module.get("primary_platform", ""),
                    "score": round(score, 2),
                    "hits": hits[:6],
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["module_no"] or 99))
    return scored


# ---------------------------------------------------------------------------
# 任务类型识别
# ---------------------------------------------------------------------------

def detect_task_type(question_text: str) -> tuple[str, list[dict[str, Any]]]:
    """按**加权**信号识别任务类型。

    权重模型（PHASE 2 修订）：
      意图短语 intent_phrases（「共有 / 多少 / 哪些 / 是否…」）× intent_weight
      对象名词 signals（「作者 / 论文 / 机构…」）        × signal_weight

    为什么不能只数命中字符：旧实现给每个命中的词加 `min(len,8)` 分，
    于是「在CNKI高级检索界面，精确检索作者为黄智，主题为染色体的论文，
    2014-2024年间共有多少篇期刊论文」里，对象名词（作者、论文）拿到的分
    压过了疑问短语（共有、多少），把 GET_VALUE 误判成 GET_LIST。
    而「共有多少」正是本赛事最高频的取证形态。
    """
    config = load_task_types()
    types = {t["id"]: t for t in config["task_types"]}
    order = config["detection_order"]
    weights = config.get("scoring", {})
    intent_weight = float(weights.get("intent_weight", 4))
    signal_weight = float(weights.get("signal_weight", 1))
    lowered = question_text.lower()

    scores: list[dict[str, Any]] = []
    for task_id, definition in types.items():
        score = 0.0
        intent_hits: list[str] = []
        signal_hits: list[str] = []
        for phrase in definition.get("intent_phrases", []):
            if str(phrase).lower() in lowered:
                # 更长的意图短语更具体，给一点额外权重
                score += intent_weight * (1.0 + 0.15 * min(len(str(phrase)), 10) / 10)
                intent_hits.append(phrase)
        # 正则意图：词表覆盖不到但形式确定的信号（如键盘快捷键 Ctrl+Shift+O）
        for pattern in definition.get("intent_patterns", []):
            if re.search(str(pattern), lowered):
                score += intent_weight
                intent_hits.append(f"/{pattern}/")
        for signal in definition.get("signals", []):
            if str(signal).lower() in lowered:
                score += signal_weight
                signal_hits.append(signal)
        scores.append({
            "id": task_id,
            "score": round(score, 2),
            "intent_hits": intent_hits[:6],
            "signal_hits": signal_hits[:6],
            "hits": (intent_hits + signal_hits)[:6],
            # 只命中对象名词、没有任何意图短语 -> 证据不足
            "intent_backed": bool(intent_hits),
        })

    positive = [item for item in scores if item["score"] > 0]
    if not positive:
        return "UNKNOWN", sorted(scores, key=lambda i: order.index(i["id"]))
    # 分数优先；同分时按 detection_order 决定（强约束动作优先）。
    positive.sort(key=lambda item: (-item["score"], order.index(item["id"])))
    return positive[0]["id"], positive


def task_type_confidence(best: dict[str, Any] | None, positive: list[dict[str, Any]]) -> str:
    if not best:
        return "LOW"
    # 只靠对象名词命中、没有任何意图短语支撑 -> 不允许给高置信度
    if not best.get("intent_backed", False):
        return "LOW"
    if len(positive) == 1 or best["score"] >= positive[1]["score"] * 2:
        return "HIGH"
    if best["score"] > positive[1]["score"]:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# 平台识别
# ---------------------------------------------------------------------------

PLATFORM_ALIASES_PATH = ROOT / "config" / "platform_aliases.yaml"

# 历史题库 retrieval_path 污染特征：命中即视为「该字段是答案/解析，不是方法」
ANSWER_LIKE_RE = re.compile(
    r"答案|解析|标准答案|参考答案|正确答案|答对|选中\s*[A-D]|选项\s*[A-D]",
)


def _looks_like_hostname(text: str) -> bool:
    return bool(re.search(r"\.(?:com|cn|org|net|gov|edu|io|int)(?:\b|/)", text, re.I))


def curated_platform_aliases() -> dict[str, str]:
    """人工策展的平台名别名（config/platform_aliases.yaml）。

    为什么必须有人工表：自动生成的 `platform_capabilities.json` 把每个 URL
    主机都建成一个平台条目，并把主机名写进 name（128 个条目里 105 个如此）。
    于是按「题干里出现的平台名」识别时，82% 的平台没有可用名称 —— 这是
    PHASE 2 平台路由准确率偏低的首要原因。本函数提供高优先级的人工别名。
    """
    if not PLATFORM_ALIASES_PATH.exists():
        return {}
    try:
        payload = load_yaml(PLATFORM_ALIASES_PATH)
    except (OSError, ValueError):
        return {}
    index: dict[str, str] = {}
    for key, names in (payload.get("aliases") or {}).items():
        for name in names or []:
            name = str(name).strip()
            if name:
                index[name.lower()] = str(key)
    return index


def alias_to_platform_key(capabilities: dict[str, Any]) -> dict[str, str]:
    """自动别名 + 人工别名。人工别名优先级更高。"""
    index: dict[str, str] = {}
    for key, capability in capabilities.items():
        if not isinstance(capability, dict):
            # capabilities 里可能存在非对象条目；不得让整张表崩掉
            continue
        names = [capability.get("name", ""), *(capability.get("aliases") or [])]
        for name in names:
            name = str(name).strip()
            if not name:
                continue
            # 主机名形式的「名称」没有识别价值，反而会与人工别名冲突
            if _looks_like_hostname(name) or name == key:
                continue
            index.setdefault(name.lower(), key)
    # 人工别名覆盖自动别名
    index.update(curated_platform_aliases())
    return index


def resolve_platform(
    question_text: str,
    capabilities: dict[str, Any],
    declared: str = "",
    module_platform: str = "",
) -> tuple[str, str, list[str]]:
    index = alias_to_platform_key(capabilities)
    candidates: list[str] = []

    if declared:
        key = index.get(declared.strip().lower(), declared.strip())
        return key, "DECLARED", [key]

    label = detect_platform(question_text)
    key_from_label = index.get(label.lower(), "") if label else ""
    if key_from_label:
        candidates.append(key_from_label)

    # 题目直接点名平台全称/别名
    lowered = question_text.lower()
    for alias, key in index.items():
        if len(alias) >= 3 and alias in lowered and key not in candidates:
            candidates.append(key)

    if not candidates and module_platform:
        candidates.append(module_platform)

    if not candidates:
        return "", "UNKNOWN", []
    return candidates[0], "QUESTION_TEXT" if key_from_label else "MODULE", candidates


# ---------------------------------------------------------------------------
# 检索计划
# ---------------------------------------------------------------------------

def plan_retrieval(
    question_text: str, capability: dict[str, Any] | None, task_type: str
) -> tuple[list[str], dict[str, Any], str]:
    config = load_task_types()
    definition = next(
        (t for t in config["task_types"] if t["id"] == task_type), None
    )
    capability = capability or {}
    supported = [str(f) for f in capability.get("supported_fields", [])]
    lowered = question_text.lower()

    matched = [f for f in supported if f.lower() in lowered]

    # 复合字段名（如「作者单位」）常以「单位」出现在题干里，做一次弱匹配。
    for field_name in supported:
        if field_name in matched:
            continue
        for piece in FIELD_SPLIT_RE.split(field_name):
            if len(piece) >= 3 and piece.lower() in lowered:
                matched.append(field_name)
                break

    if not matched:
        matched = supported[:3]

    filter_keys = list((capability.get("filters") or {}).keys())
    question_filters = [key for key in filter_keys if key.lower() in lowered]
    filters: dict[str, Any] = {}
    for key in question_filters:
        filters[key] = (capability["filters"] or {})[key]

    years = YEAR_RE.findall(question_text)
    time_constraint = ""
    if len(years) >= 2:
        time_constraint = f"{min(years)}–{max(years)}"
    elif len(years) == 1:
        time_constraint = years[0]
    elif any(token in question_text for token in ("当前", "实时", "最新", "今年")):
        time_constraint = "当前（必须记录 observed_at）"

    expected = (definition or {}).get("expected_output", "")
    return matched, filters, f"{time_constraint}|{expected}"


def split_time_constraint(value: str) -> tuple[str, str]:
    time_part, _, expected = value.partition("|")
    return time_part, expected


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def bank_match(
    conn: sqlite3.Connection, question_text: str, options: dict[str, Any] | None
):
    from match_engine import MatchIndex  # 延迟导入，避免启动开销

    index = MatchIndex(conn)
    result = index.lookup(question_text, options)
    if result.row is not None and result.method in {"exact", "normalized_exact"}:
        return result.method, result.row, result
    rows = tuple(conn.execute("SELECT * FROM questions"))
    variant = find_variant(conn, question_text, rows)
    if variant.status == VARIANT:
        return "variant", variant.source_row, variant
    return result.method, result.row, variant


def _sanitize_value(value: Any, gate: Any, field_path: str, report: dict[str, Any]) -> Any:
    """递归清洗一个值。返回清洗后的值。"""
    if isinstance(value, dict):
        return {
            k: _sanitize_value(v, gate, f"{field_path}.{k}" if field_path else str(k), report)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_value(v, gate, f"{field_path}[]", report) for v in value
        ]
    if not isinstance(value, str):
        return value

    # 1) 答案/解析文本：只对已知的"方法"字段做替换，避免误伤正常描述
    if ANSWER_LIKE_RE.search(value) and re.search(
        r"retrieval_path|recipe|path|note|备注", field_path, re.I
    ):
        report.setdefault("polluted_fields", []).append(field_path)
        return (
            "⚠️ 原历史记录该字段含答案或解析文本，已按数据卫生规则屏蔽。"
            "请只依据 platform / retrieval_query / retrieval_fields / retrieval_filters 复现方法。"
        )

    # 2) URL：任何字段里的 URL 都要过合规闸门（含嵌套与备用入口）
    for url in re.findall(r"https?://[^\s\)）\]，,；;\"']+", value):
        try:
            verdict = gate.classify(url)
        except (ValueError, OSError):
            continue
        if not verdict.automation_allowed:
            report.setdefault("blocked_urls", []).append(
                {
                    "field": field_path,
                    # 只留**主机与判定**，不留原始 URL —— 否则被屏蔽的比赛 URL
                    # 仍以文本形式出现在输出里（Controller 要求彻底阻断其进入执行路径）。
                    "host": (urlsplit(url).hostname or "").lower(),
                    "surface": verdict.surface,
                }
            )
            return (
                f"⛔ 原历史记录在该字段写入了**比赛面/未确认归属**的 URL（{verdict.surface}），"
                "已按 P0 合规规则屏蔽。该链接不可用于自动化，也不应作为研究入口。"
            )
    return value


def sanitize_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """递归清洗历史题库记录里的污染字段。

    真实数据污染（PHASE 2 实测）：

    1) `question_routes.retrieval_path` 本该写「检索路径」，实际大量写入的是
       **答案解析文本**（92/288 题命中），例如
           "公开样题原始答案/解析"
           "可通过使用该插件，得出答案"
       路由把它原样透出给操作者，等于把旧题答案摆在「操作指引」的位置上。

    2) `official_url` 里混入了**比赛系统**的链接（157/288 题命中），例如
           https://csc.xxsuyang.com/detail?id=...
       若操作者照此复现，就会去访问 Human Only 的比赛面。这是 P0 级风险。

    Controller 在修正指令中要求把防线**扩大到所有来源字段、嵌套结构、备用入口**，
    因此本函数改为**递归**遍历，任何层级出现的 URL 都过合规闸门，
    任何层级出现在方法字段里的答案/解析文本都被屏蔽。

    同时提供 `check_redirect_target()`，用于检查跳转后的最终目标域名 ——
    只检查初始 URL 会漏掉「安全短链跳到比赛面」这类情况。
    """
    if not recipe:
        return recipe
    from compliance_gate import ComplianceGate

    gate = ComplianceGate()
    report: dict[str, Any] = {}
    cleaned = _sanitize_value(recipe, gate, "", report)
    if report.get("polluted_fields"):
        cleaned["retrieval_path_polluted"] = True
        cleaned["_sanitized_fields"] = report["polluted_fields"][:8]
    if report.get("blocked_urls"):
        cleaned["_blocked_urls"] = report["blocked_urls"][:8]
        cleaned["_blocked_surfaces"] = sorted(
            {item["surface"] for item in report["blocked_urls"]}
        )
    return cleaned


def check_redirect_target(url: str, redirect_chain: list[str]) -> dict[str, Any]:
    """检查跳转链上的**每一跳**，含最终目标。

    Controller 明确要求：「同时检查 URL 跳转后的目标域名，避免只检查初始 URL
    而忽略最终目标」。初始 URL 可能是被允许的研究站，跳转后落到比赛面。
    """
    from compliance_gate import ComplianceGate

    gate = ComplianceGate()
    hops: list[dict[str, Any]] = []
    leaked = False
    for hop in [url, *redirect_chain]:
        if not hop:
            continue
        verdict = gate.classify(hop)
        allowed = verdict.automation_allowed
        hops.append({
            "url": hop[:160],
            "surface": verdict.surface,
            "decision": verdict.decision,
            "automation_allowed": allowed,
        })
        if not allowed:
            leaked = True
    return {
        "initial_url": url,
        "hops": hops,
        "final_url": (redirect_chain[-1] if redirect_chain else url),
        "blocked_at_some_hop": leaked,
        "verdict": "BLOCKED" if leaked else "ALLOWED",
        "note": "任何一跳落到比赛面即整体拒绝；只检查初始 URL 是不够的。",
    }


def route(
    question_text: str,
    options: dict[str, Any] | None = None,
    declared_platform: str = "",
    db_path: Path = DB_PATH,
) -> Routing:
    question_text = text(question_text)
    if not question_text:
        raise ValueError(
            "题干为空。Human Gate 1：题目必须由选手主动提供，"
            "本执行体不接受自动捕获的题目输入。"
        )

    capabilities = load_platform_capabilities()["platforms"]
    routing = Routing(question_text=question_text)

    # --- 1. 模块识别：题库优先，其次导航触发词 ---------------------------
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        method, row, extra = bank_match(conn, question_text, options)
        if row is not None and method in {"exact", "normalized_exact"}:
            routing.match_status = "EXACT"
            routing.match_method = method
            routing.module_id = text(row["module_id"])
            routing.module_no = None
            # 污染的 module_name 单独留档，绝不用于分类。
            routing.polluted_module_name = text(row["module_name"])
            routing.reference_question_id = text(row["id"])
            nav = load_module_nav()
            canonical = next(
                (m for m in nav["modules"] if m["module_id"] == routing.module_id), None
            )
            if canonical:
                routing.module_name = canonical["module_name"]
                routing.module_no = canonical["module_no"]
                routing.module_category = canonical["category"]
                routing.module_source = MODULE_SOURCE_BANK
                routing.module_name_conflict = bool(
                    routing.polluted_module_name
                    and routing.polluted_module_name != routing.module_name
                )
            if not routing.module_name:
                routing.module_name = routing.polluted_module_name
        elif hasattr(extra, "status") and extra.status == VARIANT:
            routing.match_status = VARIANT
            routing.match_method = "variant"
            routing.similarity = float(getattr(extra, "similarity", 0.0))
            routing.reference_question_id = text(extra.source_row["id"])
            routing.reusable_recipe = sanitize_recipe(dict(getattr(extra, "recipe", {}) or {}))
            routing.recipe_notes = list(getattr(extra, "notes", []) or [])
            routing.module_id = text(routing.reusable_recipe.get("module_id"))
            routing.polluted_module_name = text(routing.reusable_recipe.get("module_name"))
            nav = load_module_nav()
            canonical = next(
                (m for m in nav["modules"] if m["module_id"] == routing.module_id), None
            )
            if canonical:
                routing.module_name = canonical["module_name"]
                routing.module_no = canonical["module_no"]
                routing.module_category = canonical["category"]
                routing.module_source = MODULE_SOURCE_BANK
                routing.module_name_conflict = bool(
                    routing.polluted_module_name
                    and routing.polluted_module_name != routing.module_name
                )
        else:
            routing.match_status = NEW
            routing.match_method = method or "none"
    finally:
        conn.close()

    candidates = score_modules(question_text)
    routing.module_candidates = candidates[:5]
    if not routing.module_id and candidates:
        best = candidates[0]
        routing.module_id = best["module_id"]
        routing.module_no = best["module_no"]
        routing.module_name = best["module_name"]
        routing.module_category = best["category"]
        routing.module_source = MODULE_SOURCE_NAV

    # --- 2. 任务类型 -----------------------------------------------------
    task_type, scores = detect_task_type(question_text)
    routing.task_type = task_type
    routing.task_type_candidates = [s for s in scores if s["score"] > 0][:5]
    config = load_task_types()
    definition = next((t for t in config["task_types"] if t["id"] == task_type), None)
    routing.task_type_name = (definition or {}).get("name_zh", "")
    routing.task_type_confidence = task_type_confidence(
        routing.task_type_candidates[0] if routing.task_type_candidates else None,
        routing.task_type_candidates,
    )
    routing.evidence_floor = (definition or {}).get(
        "evidence_floor", EVIDENCE_MODEL_REASONING
    )

    # --- 3. 平台与入口 ---------------------------------------------------
    module_platform = ""
    nav = load_module_nav()
    canonical_module = next(
        (m for m in nav["modules"] if m["module_id"] == routing.module_id), None
    )
    if canonical_module:
        module_platform = canonical_module.get("primary_platform", "")
    key, source, platform_candidates = resolve_platform(
        question_text, capabilities, declared_platform, module_platform
    )
    routing.target_platform = key
    routing.platform_source = source
    routing.platform_candidates = platform_candidates
    capability = capabilities.get(key) or {}
    routing.target_platform_name = capability.get("name", "")
    entry = capability.get("entry") or {}
    routing.primary_entry = entry.get("primary", "")
    routing.entry_status = entry.get("primary_status", "UNKNOWN")
    routing.fallback_entry = entry.get("fallback", "")
    routing.entry_avoid = list(entry.get("avoid", []))

    # --- 4. 检索计划 -----------------------------------------------------
    if canonical_module and not routing.primary_entry:
        routing.primary_entry = canonical_module.get("deep_link", "")
        routing.entry_status = canonical_module.get("deep_link_status", "UNKNOWN")
    required_fields, filters, time_and_expected = plan_retrieval(
        question_text, capability, routing.task_type
    )
    routing.required_fields = required_fields
    routing.filters = filters
    routing.time_constraint, routing.expected_output = split_time_constraint(
        time_and_expected
    )

    # --- 5. 合规预检 -----------------------------------------------------
    gate = ComplianceGate()
    if routing.primary_entry:
        verdict = gate.classify(routing.primary_entry)
        routing.compliance_surface = verdict.surface
        routing.compliance_decision = verdict.decision
        routing.compliance_reason = verdict.reason
    else:
        routing.compliance_surface = "UNKNOWN_SURFACE"
        routing.compliance_decision = "NEEDS_ROUTING"
        routing.compliance_reason = "未解析出入口 URL，运行前必须先确定入口。"

    routing.handoff_expected = bool(
        routing.entry_status in {"CHALLENGE", "AUTH", "BROKEN"}
        or routing.target_platform in {"baidu-index", "wanfang_zhiyan"}
        or routing.task_type == "UNKNOWN"
    )

    # ------------------------------------------------------------------
    # PHASE 2 修正（Controller DECISION 2 / 3）——**附加字段，不改既有行为**
    #
    # DECISION 2：把单值 task_type 拆成 answer_intent + evidence_surface
    # DECISION 3：题干指定平台优先；指定了但认不出 -> UNKNOWN，不替换；
    #             未指定时输出 Top-N 候选
    # ------------------------------------------------------------------
    try:
        from intent_surface import analyze as analyze_dimensions

        dimensions = analyze_dimensions(
            routing.question_text, routing.target_platform, routing.module_no
        )
        routing.answer_intent = dimensions["answer_intent"]
        routing.answer_intent_confidence = dimensions["answer_intent_confidence"]
        routing.answer_intent_candidates = dimensions["answer_intent_candidates"]
        routing.evidence_surface = dimensions["evidence_surface"]
        routing.evidence_surface_confidence = dimensions["evidence_surface_confidence"]
        routing.evidence_surface_candidates = dimensions["evidence_surface_candidates"]
        routing.subtasks = dimensions["subtasks"]
        routing.dimension_note = dimensions["note"]
    except (ImportError, ValueError, OSError):
        routing.answer_intent = routing.task_type
        routing.evidence_surface = "UNKNOWN"
        routing.answer_intent_confidence = routing.task_type_confidence
        routing.evidence_surface_confidence = "LOW"
        routing.answer_intent_candidates = []
        routing.evidence_surface_candidates = []
        routing.subtasks = []
        routing.dimension_note = "维度分析不可用，回退到单值 task_type"

    try:
        from platform_router_v2 import resolve_platform_v2

        platform_v2 = resolve_platform_v2(
            routing.question_text,
            module_platform=routing.target_platform if routing.platform_source == "MODULE" else "",
            module_platform_name=routing.target_platform_name if routing.platform_source == "MODULE" else "",
        )
        routing.platform_resolution = platform_v2["resolution"]
        routing.platform_resolution_reason = platform_v2["reason"]
        routing.platform_candidates_v2 = platform_v2["candidates"]
        routing.declared_platform_text = platform_v2.get("declared_text", "")
        routing.platform_requires_human = platform_v2["requires_human"]
        routing.forbidden_substitution = platform_v2.get("forbidden_substitution", False)
        if platform_v2["resolution"] in {
            "DECLARED", "DECLARED_UNRESOLVED", "NO_SIGNAL",
            "AUTO_FROM_KEYWORDS", "MODULE_CANDIDATE",
        }:
            # 仅当 v2 给出了更明确的结论时才覆盖展示字段；
            # 不修改 target_platform 本身，避免破坏既有 290 项回归。
            routing.resolved_platform_v2 = platform_v2["target_platform"]
        else:
            routing.resolved_platform_v2 = routing.target_platform
    except (ImportError, ValueError, OSError):
        routing.platform_resolution = "UNAVAILABLE"
        routing.platform_resolution_reason = "v2 平台解析不可用"
        routing.platform_candidates_v2 = []
        routing.declared_platform_text = ""
        routing.platform_requires_human = False
        routing.forbidden_substitution = False
        routing.resolved_platform_v2 = routing.target_platform

    # ------------------------------------------------------------------
    # PHASE 2 修正 §4：**统一合规收口**
    #
    # 前面的 sanitize_recipe() 只管历史题库带来的字段；路由**自己生成**的
    # 输出同样可能携带 URL（入口、备用入口、要避开的入口、执行步骤……）。
    # 逐个字段手工检查一定会漏，因此在这里做**唯一一次收口**：
    # 对所有 URL 承载字段跑同一个合规闸门，被拦的替换为 ⛔[SURFACE]。
    #
    # 性能：enforce_output_compliance 只对含 "://" 的字符串做正则，
    # 其余字符串直接跳过，因此对本地路由耗时的增量可忽略。
    # ------------------------------------------------------------------
    try:
        from output_compliance import enforce_output_compliance

        generated_fields = {
            "primary_entry": routing.primary_entry,
            "fallback_entry": routing.fallback_entry,
            "entry_avoid": routing.entry_avoid,
            "reusable_recipe": routing.reusable_recipe,
        }
        if isinstance(routing.entry_avoid, list):
            generated_fields["entry_avoid"] = [
                dict(item) if isinstance(item, dict) else item for item in routing.entry_avoid
            ]
        cleaned, compliance_report = enforce_output_compliance(generated_fields)
        routing.primary_entry = cleaned.get("primary_entry", routing.primary_entry)
        routing.fallback_entry = cleaned.get("fallback_entry", routing.fallback_entry)
        routing.entry_avoid = cleaned.get("entry_avoid", routing.entry_avoid)
        routing.reusable_recipe = cleaned.get("reusable_recipe", routing.reusable_recipe)
        routing.output_compliance = compliance_report
    except (ImportError, ValueError, OSError) as error:
        routing.output_compliance = {"clean": None, "error": str(error)[:120]}

    return routing


def render(routing: Routing) -> str:
    lines = [
        f"模块：{routing.module_id or '未识别'}（{routing.module_name or '—'}）"
        f"｜来源 {routing.module_source}",
        f"任务类型：{routing.task_type}（{routing.task_type_name or '—'}，"
        f"置信 {routing.task_type_confidence}）",
        f"平台：{routing.target_platform or '未识别'}"
        f"（{routing.target_platform_name or '—'}，来源 {routing.platform_source or '—'}）",
        f"入口：{routing.primary_entry or '未解析'}｜状态 {routing.entry_status}",
    ]
    if routing.fallback_entry:
        lines.append(f"备用：{routing.fallback_entry}")
    if routing.required_fields:
        lines.append(f"字段：{'、'.join(routing.required_fields)}")
    if routing.filters:
        lines.append(f"筛选：{json.dumps(routing.filters, ensure_ascii=False)}")
    if routing.time_constraint:
        lines.append(f"时间约束：{routing.time_constraint}")
    if routing.expected_output:
        lines.append(f"期望输出：{routing.expected_output}")
    lines.append(f"证据下限：{routing.evidence_floor}")
    lines.append(
        f"匹配状态：{routing.match_status}"
        + (f"（相似度 {routing.similarity:.2f}）" if routing.similarity else "")
    )
    if routing.match_status == VARIANT:
        lines.append("⚠️ 变体题：只复用配方，答案必须重新求解。")
    if routing.module_name_conflict:
        lines.append(
            f"⚠️ module_name 冲突：库中为「{routing.polluted_module_name}」，"
            f"canonical 为「{routing.module_name}」；以 module_id 为准。"
        )
    if routing.recipe_notes:
        for note in routing.recipe_notes[:3]:
            lines.append(f"  · {note}")
    lines.append(f"合规：{routing.compliance_decision}｜{routing.compliance_reason}")
    if routing.handoff_expected:
        lines.append("🔴 预计需要人工交接（入口受限或任务类型未定）。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    declared = ""
    if "--platform" in args:
        index = args.index("--platform")
        declared = args[index + 1] if index + 1 < len(args) else ""
        del args[index:index + 2]
    question = " ".join(args).strip()
    if not question:
        print("用法：python scripts/task_router.py <题干> [--platform <平台>] [--json]")
        return 2
    routing = route(question, declared_platform=declared)
    if as_json:
        print(json.dumps(routing.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render(routing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

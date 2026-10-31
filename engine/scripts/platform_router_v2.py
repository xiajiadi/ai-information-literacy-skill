"""PHASE 2 修正 · DECISION 3：平台路由优先级与不替换原则。

Controller 决策原文：

  * 题目明确指定的平台具有最高优先级；
  * 模块推荐平台仅作为候选来源；
  * 未指定时结合关键词、任务、目标字段与平台能力自主选择；
  * 多个合理候选时输出 Top-2/Top-3；
  * **题目明确指定的平台无法识别时，不允许擅自替换成另一平台并声称已完成原平台检索**，
    此时标记目标平台 UNKNOWN、保留候选研究方法、必要时 HUMAN_REQUIRED、不伪造平台来源。

本模块是**新增层**，不替换 `task_router.resolve_platform()`（避免破坏既有 290 项回归），
结果以 additive 字段挂到路由输出上。

与旧实现的差别：
  | 场景 | 旧行为 | 新行为 |
  |---|---|---|
  | 题干点名平台且可识别 | 采用 | 采用（REQUIRED） |
  | 题干点名平台**不可识别** | 可能回退到模块平台 | **UNKNOWN + HUMAN_REQUIRED，不替换** |
  | 题干未点名 | 模块平台当结论 | 模块平台仅作**候选**，并列出 Top-N |
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import load_platform_capabilities, load_yaml, ROOT  # noqa: E402

ALIASES_PATH = ROOT / "config" / "platform_aliases.yaml"
BACKFILL_PATH = ROOT / "config" / "platform_backfill.yaml"
SEMANTICS_PATH = ROOT / "config" / "platform_semantics.json"


def curated_backfill() -> dict[str, dict[str, Any]]:
    """Controller 决策 (b) 补录的平台条目（config/platform_backfill.yaml）。

    只补 `canonical_name` 与 `aliases`（解决「认不出」），
    `domains` / `official_entry` 留空 —— 没有权威来源核实官方域名时不臆造。
    """
    if not BACKFILL_PATH.exists():
        return {}
    try:
        payload = load_yaml(BACKFILL_PATH)
    except (OSError, ValueError):
        return {}
    return {
        str(key): value
        for key, value in (payload.get("platforms") or {}).items()
        if isinstance(value, dict)
    }

# 题干里表示"题目指定了某个平台"的措辞。命中即认为**指定了**平台。
# 注意：这里只用来判断「题干是否点名了平台」，**不用捕获组直接当别名**——
# 因为别名本身可能包含分隔词（「万方数据知识服务**平台**」），
# 用正则捕获会把别名截断，导致明明认识却判成"无法识别"。
DECLARED_PATTERNS = (
    r"在[^，。；、）\)]{2,24}?(?:数据库|平台|网站|官网|系统中|界面|网页版)",
    r"用[^，。；、）\)]{2,24}?(?:数据库|平台|网站|官网)(?:检索|查询|查找)",
    r"访问[^，。；、）\)]{2,24}?(?:官网|网站|首页)",
    r"[A-Za-z][A-Za-z0-9\.\- ]{2,24}?官网",
    r"通过[^，。；、）\)]{2,24}?(?:查询|检索|平台|数据库)",
    r"打开[^，。；、）\)]{2,24}?(?:网站|平台|数据库|系统)",
)


_SORTED_ALIASES: list[tuple[str, str]] | None = None


def sorted_aliases() -> list[tuple[str, str]]:
    """按别名长度降序的 (alias, key) 列表，**缓存**。

    补录后别名从 115 涨到 200+，每次调用重新排序会让本地路由 P50 从 52ms
    涨到 67ms。这里缓存一次即可。
    """
    global _SORTED_ALIASES
    if _SORTED_ALIASES is None:
        index = platform_aliases()
        _SORTED_ALIASES = sorted(index.items(), key=lambda kv: -len(kv[0]))
    return _SORTED_ALIASES


_SEMANTICS_NAMES: dict[str, str] | None = None


def semantics_names() -> dict[str, str]:
    """语义层里 key -> canonical_name 的映射，**缓存**。

    原实现每次 `describe()` 都重新读取并解析 172 条的 JSON，
    在逐题评估里被调用上千次，是补录后本地路由 P50 从 52ms 涨到 67ms 的主因。
    """
    global _SEMANTICS_NAMES
    if _SEMANTICS_NAMES is None:
        names: dict[str, str] = {}
        if SEMANTICS_PATH.exists():
            import json

            try:
                payload = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
                for key, item in (payload.get("platforms") or {}).items():
                    name = str((item or {}).get("canonical_name") or "")
                    if name and name != "UNKNOWN":
                        names[key] = name
            except (OSError, ValueError):
                pass
        _SEMANTICS_NAMES = names
    return _SEMANTICS_NAMES


def clear_alias_cache() -> None:
    global _SORTED_ALIASES, _SEMANTICS_NAMES
    _SORTED_ALIASES = None
    _SEMANTICS_NAMES = None


def parent_of(platform_key: str) -> str:
    """子产品对应的母平台（无则空串）。

    「知网研学」「CNKI AI」「中国法律知识总库」都是 CNKI 的子产品；
    「LeapSpace」是 ScienceDirect/Elsevier 的 AI 工具。
    不记录父子关系会导致子产品**遮蔽**母平台标签。
    """
    return str((curated_backfill().get(platform_key) or {}).get("parent_platform") or "")


def platform_family(platform_key: str) -> set[str]:
    """返回该平台所在的族（自身 + 母平台 + 同族子平台）。"""
    family = {platform_key} if platform_key else set()
    parent = parent_of(platform_key)
    if parent:
        family.add(parent)
    for key, item in curated_backfill().items():
        if item.get("parent_platform") == platform_key:
            family.add(key)
    return {k for k in family if k}


_BACKFILL_ENABLED = {"on": True}


def set_backfill_enabled(enabled: bool) -> None:
    """开关平台补录，用于**固定样本配对评估**（补录前 vs 补录后）。

    只影响别名索引与父子关系；不改动任何配置或 Gold。
    """
    _BACKFILL_ENABLED["on"] = bool(enabled)
    clear_alias_cache()


def backfill_enabled() -> bool:
    return _BACKFILL_ENABLED["on"]


def platform_aliases(include_backfill: bool | None = None) -> dict[str, str]:
    """别名 -> key（人工策展优先，其次语义层，最后旧能力表的真实名称）。"""
    if include_backfill is None:
        include_backfill = _BACKFILL_ENABLED["on"]
    index: dict[str, str] = {}

    # 1) 旧能力表里**真实名称**（跳过主机名）
    hostname_re = re.compile(r"^[a-z0-9][a-z0-9.\-]*\.(?:com|cn|org|net|gov|edu|io|int|ai|dev)$", re.I)
    for key, capability in load_platform_capabilities()["platforms"].items():
        if not isinstance(capability, dict):
            continue
        name = str(capability.get("name") or "").strip()
        if name and name != key and not hostname_re.match(name):
            index.setdefault(name.lower(), key)

    # 2) 语义层
    if SEMANTICS_PATH.exists():
        import json

        semantics = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
        for key, item in semantics.get("platforms", {}).items():
            # 关闭补录时，必须同时排除语义层里由补录产生的条目 ——
            # 否则上一轮生成的 platform_semantics.json 已经把补录平台吸收进去，
            # 开关就形同虚设（实测两边都是 215 条别名）。
            provenance = item.get("provenance") or {}
            is_backfill_entry = (
                str(provenance.get("name") or "").startswith("CONTROLLER_BACKFILL")
                or str(provenance.get("base_asset") or "").startswith("config/platform_backfill")
                or provenance.get("backfill") == "DECISION_B_MERGED"
            )
            if is_backfill_entry and not include_backfill:
                continue
            name = item.get("canonical_name") or ""
            if name and name != "UNKNOWN":
                index[name.lower()] = key
            for alias in item.get("aliases", []):
                index[str(alias).lower()] = key

    # 3) 人工策展（最高优先级）
    if ALIASES_PATH.exists():
        for key, names in (load_yaml(ALIASES_PATH).get("aliases") or {}).items():
            for name in names or []:
                index[str(name).strip().lower()] = str(key)

    # 4) Controller 决策 (b) 补录的平台（优先级最高，覆盖上面一切）
    if include_backfill:
        for key, item in curated_backfill().items():
            name = str(item.get("canonical_name") or "").strip()
            if name:
                index[name.lower()] = key
            for alias in item.get("aliases") or []:
                alias = str(alias).strip()
                if alias:
                    index[alias.lower()] = key
    return index


def extract_declared_platform(question_text: str) -> str:
    """判断题干是否**点名**了平台，并给出命中的那段文字（仅供解释用）。

    真正用于解析的键由 `longest_known_alias()` 在全文里找**最长的已知别名**，
    这样「万方数据知识服务平台」不会被分隔词截断。
    """
    for pattern in DECLARED_PATTERNS:
        match = re.search(pattern, question_text)
        if match:
            return match.group(0)[:36]
    return ""


def longest_known_alias(question_text: str, index: dict[str, str]) -> tuple[str, str]:
    """在题干里找**最长的已知平台别名**。返回 (alias, key)，找不到返回 ("", "")。"""
    lowered = question_text.lower()
    for alias in sorted(index, key=len, reverse=True):
        if len(alias) < 2:
            continue
        if alias in lowered:
            return alias, index[alias]
    return "", ""


def resolve_platform_v2(
    question_text: str,
    module_platform: str = "",
    module_platform_name: str = "",
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """按 DECISION 3 解析目标平台。

    返回 dict: target_platform / resolution / candidates / requires_human / reason
    """
    index = platform_aliases()
    declared_marker = extract_declared_platform(question_text)
    # 关键：用**全文里最长的已知别名**作为解析结果，而不是正则捕获的那一段
    declared_alias, declared_key = longest_known_alias(question_text, index)
    declared_raw = declared_marker or declared_alias

    capabilities = load_platform_capabilities()["platforms"]

    # 关键词/名称命中（含题干中直接出现的平台别名）
    hits: list[tuple[str, str]] = []
    lowered = question_text.lower()
    for alias, key in sorted(index.items(), key=lambda kv: -len(kv[0])):
        if len(alias) < 2:
            continue
        if alias in lowered:
            if not any(k == key for _, k in hits):
                hits.append((alias, key))

    def describe(key: str) -> str:
        item = capabilities.get(key) or {}
        name = str(item.get("name") or "")
        hostname_re = re.compile(
            r"^[a-z0-9][a-z0-9.\-]*\.(?:com|cn|org|net|gov|edu|io|int|ai|dev)$", re.I
        )
        if not name or name == key or hostname_re.match(name):
            # 语义层可能有更好的名字（已缓存，避免每题重读 JSON）
            cached = semantics_names().get(key)
            return cached if cached else "UNKNOWN"
        return name

    # ---- 情况 A：题干明确指定了平台 ----
    if declared_raw:
        if declared_key:
            others = [{"platform_key": k, "name": describe(k), "source": "QUESTION_TEXT"}
                      for _, k in hits if k != declared_key][:2]
            return {
                "target_platform": declared_key,
                "target_platform_name": describe(declared_key),
                "parent_platform": parent_of(declared_key),
                "platform_family": sorted(platform_family(declared_key)),
                "resolution": "DECLARED",
                "declared_text": declared_raw,
                "candidates": [{"platform_key": declared_key, "name": describe(declared_key),
                                "source": "DECLARED"}] + others,
                "requires_human": False,
                "reason": f"题干显式点名「{declared_raw}」，已解析为 {declared_key}。",
            }
        # 点名了但**无法识别** —— 绝不替换
        return {
            "target_platform": "UNKNOWN",
            "target_platform_name": "UNKNOWN",
            "resolution": "DECLARED_UNRESOLVED",
            "declared_text": declared_raw,
            "candidates": [
                {"platform_key": k, "name": describe(k), "source": "QUESTION_TEXT_KEYWORD"}
                for _, k in hits[:3]
            ] + ([{"platform_key": module_platform, "name": module_platform_name or describe(module_platform),
                   "source": "MODULE_HINT"}] if module_platform else []),
            "requires_human": True,
            "reason": (
                f"题干点名「{declared_raw}」，但平台上表中没有可靠对应条目。"
                "按 DECISION 3 **不替换**成其他平台，也不声称已完成原平台检索；"
                "标记 UNKNOWN 并转人工确认。"
            ),
            "forbidden_substitution": True,
        }

    # ---- 情况 B：题干未指定，靠关键词 + 模块候选 ----
    candidates: list[dict[str, Any]] = []
    for alias, key in hits[:3]:
        candidates.append({"platform_key": key, "name": describe(key),
                           "source": "QUESTION_TEXT_KEYWORD", "matched": alias})
    if module_platform and not any(c["platform_key"] == module_platform for c in candidates):
        candidates.append({
            "platform_key": module_platform,
            "name": module_platform_name or describe(module_platform),
            "source": "MODULE_HINT",
            "note": "模块推荐，仅作候选，不是结论",
        })

    if not candidates:
        return {
            "target_platform": "UNKNOWN",
            "target_platform_name": "UNKNOWN",
            "resolution": "NO_SIGNAL",
            "declared_text": "",
            "candidates": [],
            "requires_human": True,
            "reason": "题干未点名平台，也没有任何关键词或模块线索；不做猜测。",
        }

    top = candidates[0]
    return {
        "target_platform": top["platform_key"],
        "target_platform_name": top["name"],
        "parent_platform": parent_of(top["platform_key"]),
        "platform_family": sorted(platform_family(top["platform_key"])),
        "resolution": "AUTO_FROM_KEYWORDS" if top["source"] == "QUESTION_TEXT_KEYWORD" else "MODULE_CANDIDATE",
        "declared_text": "",
        "candidates": candidates,
        "requires_human": len(candidates) > 1 and top["source"] != "QUESTION_TEXT_KEYWORD",
        "reason": (
            f"题干未点名平台；首选 {top['platform_key']}（来源 {top['source']}），"
            f"共 {len(candidates)} 个候选，交由后续 Agent 判断。"
        ),
    }

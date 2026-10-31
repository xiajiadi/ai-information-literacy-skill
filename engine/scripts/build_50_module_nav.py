"""生成 50 模块极速导航层。

产出：
    config/50_module_nav.json        机器读取的导航索引
    skill/50_module_fast_nav.md      人读的极速导航表

⚠️ 本文件在 Controller 确认前一律标记 **GENERATED_DRAFT**。
它不是「Controller 已确认的正式版导航」，不得冒充。

数据来源（全部只读）：
    db/question_bank.sqlite          modules 表（module_id 为 canonical 键）
    config/official_urls.json        模块 -> URL 配方
    config/platform_capabilities.json
    config/platform_entry_status.json
    config/task_types.json

已知污染：questions.module_name 与 module_id 不一致（37/248）。
本脚本**只以 module_id 为键**，module_name 一律取自 modules 表（canonical）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    DB_PATH,
    LEGACY_OFFICIAL_URLS_PATH,
    MODULE_NAV_JSON_PATH,
    MODULE_NAV_MD_PATH,
    load_entry_status,
    load_json,
    load_platform_capabilities,
    now_iso,
    write_json,
)
from compliance_gate import ComplianceGate  # noqa: E402
from variant_match import detect_platform  # noqa: E402

DRAFT_MARKER = "GENERATED_DRAFT"

# 硬隔离守卫：导航层永远不得输出比赛面 URL 或比赛面平台。
_GATE = ComplianceGate()


def _is_safe_research_url(url: str) -> bool:
    """导航层守卫：只拦比赛面。

    注意导航层是**查表数据**，不是自动化调用。UNKNOWN_SURFACE 的入口仍然可以
    出现在表里（否则大部分未实测入口会被抹掉），但会被标注 surface，运行时由
    compliance_gate 决定能不能真的驱动浏览器。
    """
    if not url:
        return False
    return _GATE.classify(url).surface != "COMPETITION_SURFACE"


def _is_forbidden_platform(platform_key: str) -> bool:
    return platform_key in {"competition", "competition-training", "competition_training"}


DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

ROUTE_PREFERENCE = [
    "ADVANCED_SEARCH", "QUERY_RECIPE", "SEARCH", "DATABASE_ENTRY",
    "RESOURCE_LIST", "RESOURCE_DETAIL", "PDF", "DEEP_LINK", "HOME",
    "LOGIN_DASHBOARD",
]

OFFLINE_BY_DYNAMICITY = {
    "STATIC": "YES",
    "SEMI_DYNAMIC": "PARTIAL",
    "DYNAMIC": "NO",
}

# 平台名 -> 触发词。用于从题干快速落到平台。
PLATFORM_TRIGGERS = {
    "cnki": ["知网", "CNKI", "中国知网"],
    "vip": ["维普", "cqvip"],
    "wanfang": ["万方"],
    "pubmed": ["PubMed", "MeSH"],
    "icourse163": ["中国大学MOOC", "慕课", "MOOC"],
    "sciencedirect": ["ScienceDirect", "Elsevier"],
    "unesco": ["UNESCO", "教科文组织", "unesdoc"],
    "ieee": ["IEEE"],
    "epub": ["专利公布公告", "公布公告系统"],
    "cnipa": ["国家知识产权局", "专利检索", "CNIPA"],
    "nsfc": ["国家自然科学基金", "自然科学基金"],
    "standards": ["国家标准全文公开", "GB/T", "标准全文"],
    "baidu-index": ["百度指数"],
    "wanfang_zhiyan": ["万方智研", "智研"],
    "arxiv": ["arXiv"],
    "zxgk": ["执行信息公开", "被执行人"],
}

STOPWORDS = {
    "与", "和", "的", "及", "等", "在", "中", "上", "下", "能够", "了解",
    "熟悉", "掌握", "以下", "包括", "使用", "进行", "以及", "相关", "常见",
}


def json_field(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def tokens_from(value: str, limit: int = 8) -> list[str]:
    parts = re.split(r"[\s,，、。；;：:（）()\[\]【】/·—\-]+", value or "")
    found: list[str] = []
    for part in parts:
        part = part.strip()
        if len(part) < 2 or part in STOPWORDS:
            continue
        if part not in found:
            found.append(part)
        if len(found) >= limit:
            break
    return found


def build_module_index() -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        modules: dict[str, dict[str, Any]] = {}
        for row in conn.execute("SELECT * FROM modules"):
            record = dict(row)
            key = record.get("module_id") or f"知识模块{record.get('module_no'):02d}"
            record["core_points"] = json_field(record.get("core_points")) or []
            record["retrieval_path"] = json_field(record.get("retrieval_path")) or []
            record["common_question_types"] = json_field(record.get("common_question_types")) or []
            record["sample_question_ids"] = json_field(record.get("sample_question_ids")) or []
            record["common_traps"] = json_field(record.get("common_traps")) or []
            record["key_fields"] = json_field(record.get("key_fields")) or []
            modules[key] = record

        questions_by_module: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute(
            "SELECT id, module_id, question_text, question_type FROM questions "
            "WHERE module_id IS NOT NULL AND TRIM(module_id) <> ''"
        ):
            record = dict(row)
            questions_by_module.setdefault(record["module_id"], []).append(record)
        return {"modules": modules, "questions": questions_by_module}
    finally:
        conn.close()


def build_url_index() -> dict[str, list[dict[str, Any]]]:
    data = load_json(LEGACY_OFFICIAL_URLS_PATH)
    index: dict[str, list[dict[str, Any]]] = {}
    for entry in data.get("urls", []):
        for module_id in entry.get("module") or []:
            index.setdefault(str(module_id), []).append(entry)
    return index


def detect_primary_platform(
    module: dict[str, Any],
    urls: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    capabilities: dict[str, Any],
) -> tuple[str, list[str]]:
    """按证据强度投票选首选平台：实测配方 > 模块 URL 配方 > 题干平台名。"""
    raw_scores: dict[str, int] = {}

    for entry in urls:
        key = str(entry.get("platform_key") or "")
        if not key or key not in capabilities:
            continue
        if _is_forbidden_platform(key):
            continue
        raw_scores[key] = raw_scores.get(key, 0) + 1

    for question in questions:
        label = detect_platform(question.get("question_text") or "")
        if label:
            raw_scores[label] = raw_scores.get(label, 0) + 2

    resolved: dict[str, int] = {}
    for key, score in raw_scores.items():
        if key in capabilities:
            resolved[key] = resolved.get(key, 0) + score

    if not resolved:
        # 回落到模块名称/考点的触发词
        haystack = " ".join(
            [module.get("module_name") or "", " ".join(module.get("core_points") or [])]
        )
        for platform_key, triggers in PLATFORM_TRIGGERS.items():
            if platform_key in capabilities and any(t in haystack for t in triggers):
                resolved[platform_key] = 1

    ordered = sorted(resolved.items(), key=lambda item: (-item[1], item[0]))
    if not ordered:
        return "", []
    return ordered[0][0], [key for key, _ in ordered[1:5]]


def best_deep_link(platform_key: str, entry_status: dict[str, Any]) -> dict[str, Any]:
    entries = [
        e
        for e in entry_status.get("entries", [])
        if e.get("platform_key") == platform_key
        # 硬隔离：比赛面入口永不进入导航层。
        and _GATE.classify(e.get("url", "")).surface != "COMPETITION_SURFACE"
    ]
    direct = [e for e in entries if e.get("status") == "DIRECT"]

    def rank(entry: dict[str, Any]) -> int:
        route_type = entry.get("route_type") or ""
        return ROUTE_PREFERENCE.index(route_type) if route_type in ROUTE_PREFERENCE else 99

    direct.sort(key=rank)
    if direct:
        chosen = direct[0]
        return {
            "url": chosen["url"],
            "status": chosen["status"],
            "route_type": chosen.get("route_type", ""),
            "source": chosen.get("source", ""),
            "verified_at": chosen.get("verified_at", ""),
        }
    blocked = [e for e in entries if e.get("status") in {"CHALLENGE", "BROKEN", "AUTH"}]
    if blocked:
        return {
            "url": blocked[0]["url"],
            "status": blocked[0]["status"],
            "route_type": blocked[0].get("route_type", ""),
            "source": blocked[0].get("source", ""),
            "verified_at": blocked[0].get("verified_at", ""),
        }
    return {"url": "", "status": "UNKNOWN", "route_type": "", "source": "", "verified_at": ""}


def _clean_term(term: str) -> str:
    """去掉纯域名/纯 URL 之类的噪声触发词。"""
    candidate = (term or "").strip().strip("。，、；：")
    if not candidate:
        return ""
    if candidate.lower().startswith(("http://", "https://", "www.")):
        return ""
    if DOMAIN_RE.match(candidate):
        return ""
    return candidate


def build_trigger_terms(
    module: dict[str, Any], platform_key: str, urls: list[dict[str, Any]]
) -> list[str]:
    terms: list[str] = []

    def add(value: str) -> None:
        cleaned = _clean_term(value)
        if cleaned and cleaned not in terms:
            terms.append(cleaned)

    name = module.get("module_name") or module.get("official_title") or ""
    add(name)
    for point in module.get("core_points") or []:
        for quoted in re.findall(r"《([^》]{2,40})》", str(point)):
            add(quoted)
        for quoted in re.findall(r"“([^”]{2,30})”", str(point)):
            add(quoted)
    if platform_key:
        for trigger in PLATFORM_TRIGGERS.get(platform_key, []):
            add(trigger)
    for token in tokens_from(name, limit=5):
        add(token)
    for entry in urls[:5]:
        add(str(entry.get("name") or ""))
    return terms[:14]


def build_main_traps(
    module: dict[str, Any], capability: dict[str, Any] | None
) -> list[str]:
    traps: list[str] = []
    for trap in module.get("common_traps") or []:
        if trap not in traps:
            traps.append(str(trap))
    if capability:
        for risk in capability.get("known_risks", [])[:4]:
            if risk not in traps:
                traps.append(risk)
    dynamicity = module.get("dynamicity") or "SEMI_DYNAMIC"
    if dynamicity == "DYNAMIC":
        traps.append("动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。")
    elif dynamicity == "SEMI_DYNAMIC":
        traps.append("界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。")
    if not traps:
        traps.append("未实测到具体陷阱；按平台当前显示核对，不要凭记忆。")
    return traps[:6]


def build_typical_operations(module: dict[str, Any], capability: dict[str, Any] | None) -> list[str]:
    operations: list[str] = []
    for step in module.get("retrieval_path") or []:
        step = str(step).strip()
        if step:
            operations.append(step)
    if len(operations) < 3 and capability:
        if capability.get("search_mode"):
            operations.append("检索模式：" + " / ".join(capability["search_mode"]))
        if capability.get("result_location"):
            operations.append("结果读取位置：" + str(capability["result_location"]))
    if not operations:
        operations.append("按题目指定平台进入检索入口，设置题目给出的字段与筛选条件。")
    return operations[:6]


def build_nav() -> dict[str, Any]:
    from_db = build_module_index()
    modules = from_db["modules"]
    questions_by_module = from_db["questions"]
    url_index = build_url_index()
    capabilities = load_platform_capabilities()["platforms"]
    entry_status = load_entry_status()

    nav_modules: list[dict[str, Any]] = []
    for module_id, module in sorted(
        modules.items(), key=lambda item: item[1].get("module_no") or 0
    ):
        urls = url_index.get(module_id, [])
        questions = questions_by_module.get(module_id, [])
        primary, fallbacks = detect_primary_platform(module, urls, questions, capabilities)
        capability = capabilities.get(primary)
        deep_link = best_deep_link(primary, entry_status)
        # 最后一道守卫：无论上游怎么变，比赛面 URL 都不许进导航层。
        if deep_link["url"] and not _is_safe_research_url(deep_link["url"]):
            deep_link = {
                "url": "",
                "status": "BLOCKED_BY_COMPLIANCE_GATE",
                "route_type": "",
                "source": "compliance_gate",
                "verified_at": "",
            }
        dynamicity = module.get("dynamicity") or "UNKNOWN"

        nav_modules.append(
            {
                "module_id": module_id,
                "module_no": module.get("module_no"),
                "module_name": module.get("module_name") or "",
                "category": module.get("category") or "",
                "official_title": module.get("official_title") or "",
                "trigger_terms": build_trigger_terms(module, primary, urls),
                "primary_platform": primary,
                "primary_platform_name": (capability or {}).get("name", ""),
                "fallback_platforms": fallbacks,
                "deep_link": deep_link["url"],
                "deep_link_status": deep_link["status"],
                "deep_link_route_type": deep_link["route_type"],
                "deep_link_source": deep_link["source"],
                "deep_link_verified_at": deep_link["verified_at"],
                "deep_link_surface": (
                    _GATE.classify(deep_link["url"]).surface if deep_link["url"] else ""
                ),
                "typical_operations": build_typical_operations(module, capability),
                "main_traps": build_main_traps(module, capability),
                "offline_judgeable": OFFLINE_BY_DYNAMICITY.get(dynamicity, "UNKNOWN"),
                "dynamicity": dynamicity,
                "requires_login": module.get("requires_login") or "UNKNOWN",
                "common_question_types": module.get("common_question_types") or [],
                "supported_fields": (capability or {}).get("supported_fields", []),
                "evidence_level_cap": (capability or {}).get("evidence_level_cap", ""),
                "sample_question_ids": module.get("sample_question_ids") or [],
                "question_count_in_bank": len(questions),
                "url_recipe_count": len(urls),
                "source": DRAFT_MARKER,
            }
        )

    covered = sum(1 for m in nav_modules if m["primary_platform"])
    with_link = sum(1 for m in nav_modules if m["deep_link"])
    return {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "artifact_status": DRAFT_MARKER,
        "status_note": (
            "本导航由 db/question_bank.sqlite 的 modules 表、config/official_urls.json、"
            "config/platform_capabilities.json 与 config/platform_entry_status.json 派生，"
            "是 **GENERATED_DRAFT**，不是 Controller 已确认的正式版。"
            "运行时用 module_id 作为唯一键；questions.module_name 已污染，不得用于分类。"
        ),
        "counts": {
            "modules": len(nav_modules),
            "with_primary_platform": covered,
            "with_deep_link": with_link,
            "without_platform": len(nav_modules) - covered,
            "direct_deep_link": sum(
                1 for m in nav_modules if m["deep_link_status"] == "DIRECT"
            ),
            "offline_yes": sum(1 for m in nav_modules if m["offline_judgeable"] == "YES"),
        },
        "modules": nav_modules,
    }


def render_markdown(nav: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 50 模块极速导航（GENERATED_DRAFT）")
    lines.append("")
    lines.append(
        "> ⚠️ **GENERATED_DRAFT**：本表由 `scripts/build_50_module_nav.py` 从 "
        "`db/question_bank.sqlite` 的 modules 表 + `config/official_urls.json` + "
        "`config/platform_capabilities.json` + `config/platform_entry_status.json` 自动派生，"
        "**不是 Controller 已确认的正式版导航**。"
    )
    lines.append(">")
    lines.append(
        "> 用途：运行时 5 秒内回答「这题属于哪个模块、去哪、用什么入口、有什么坑」。"
        "**本表不存放答案**，也不替代题目指定平台的当前核验。"
    )
    lines.append(">")
    lines.append(
        "> 键约定：只用 `module_id`。旧库 `questions.module_name` 已确认与 `module_id` 冲突"
        "（37/248），不得用于分类。"
    )
    lines.append("")

    counts = nav["counts"]
    lines.append(
        f"模块 {counts['modules']} 个｜有首选平台 {counts['with_primary_platform']} 个"
        f"｜有深链接 {counts['with_deep_link']} 个｜实测直达深链接 {counts['direct_deep_link']} 个"
        f"｜可完全离线判断 {counts['offline_yes']} 个"
    )
    lines.append("")
    lines.append("## 极速索引")
    lines.append("")
    lines.append("| M | 模块 | 触发词 | 首选平台 | 备用 | 深链接 | 状态 | 离线 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for module in nav["modules"]:
        no = module["module_no"]
        # 模块名本身已经单独占一列，触发词列里去掉重复项。
        extras = [t for t in module["trigger_terms"] if t != module["module_name"]]
        triggers = "、".join(extras[:4]) or "—"
        fallback = "、".join(module["fallback_platforms"][:2]) or "—"
        link = module["deep_link"] or "—"
        name = module["module_name"] or "—"
        offline = module["offline_judgeable"]
        lines.append(
            f"| M{no:02d} | {name} | {triggers} | {module['primary_platform'] or '—'} "
            f"| {fallback} | {link} | {module['deep_link_status']} | {offline} |"
        )
    lines.append("")
    lines.append(
        "离线列含义：`YES` = 静态知识，可离线直接判断（但按纪律只能标 🟡 MODEL_REASONING，"
        "除非引用到标准/法规原文）；`PARTIAL` = 界面可能改版；`NO` = 动态值，必须实时核验。"
    )
    lines.append("")

    lines.append("## 模块详情")
    lines.append("")
    for module in nav["modules"]:
        lines.append(f"### M{module['module_no']:02d} {module['module_name']}")
        lines.append("")
        lines.append(f"- module_id：`{module['module_id']}`｜大类：{module['category']}")
        lines.append(
            f"- 首选平台：{module['primary_platform'] or '未识别'}"
            f"（{module['primary_platform_name'] or '—'}）"
            f"｜备用：{'、'.join(module['fallback_platforms']) or '—'}"
        )
        lines.append(
            f"- 深链接：{module['deep_link'] or '—'}"
            f"（{module['deep_link_status']}，来源 {module['deep_link_source'] or '—'}"
            f"{'，实测 ' + module['deep_link_verified_at'] if module['deep_link_verified_at'] else ''}）"
        )
        lines.append(
            f"- 动态性：{module['dynamicity']}｜需登录：{module['requires_login']}"
            f"｜可否离线：{module['offline_judgeable']}"
        )
        if module["trigger_terms"]:
            lines.append(f"- 触发词：{'、'.join(module['trigger_terms'])}")
        if module["supported_fields"]:
            lines.append(f"- 可用字段：{'、'.join(module['supported_fields'][:12])}")
        if module["typical_operations"]:
            lines.append("- 典型操作：")
            for index, step in enumerate(module["typical_operations"], 1):
                lines.append(f"  {index}. {step}")
        if module["main_traps"]:
            lines.append("- 主要陷阱：")
            for trap in module["main_traps"]:
                lines.append(f"  - {trap}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "生成命令：`uv run python scripts/build_50_module_nav.py`。"
        "重新生成会覆盖本文件；请勿手工编辑，改动请改源数据。"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    nav = build_nav()
    write_json(MODULE_NAV_JSON_PATH, nav)
    MODULE_NAV_MD_PATH.write_text(render_markdown(nav), encoding="utf-8")
    print(f"wrote {MODULE_NAV_JSON_PATH}")
    print(f"wrote {MODULE_NAV_MD_PATH}")
    print(f"counts={nav['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

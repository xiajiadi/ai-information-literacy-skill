"""导入 Controller 提供的**正式** 50 模块极速导航。

与 GENERATED_DRAFT 的区别：
  - 正式版的模块语义、首选入口、极速路径、易错条件、答题模式、题库锚点
    全部来自 Controller 文件，本脚本**只做解析与索引，不改写官方措辞**；
  - `source` 标记为 `OFFICIAL_CONTROLLER`，并记录来源文件与 sha256；
  - 平台/深链接等**派生字段**单独放在 `derived` 命名空间下，明确标注为派生，
    不与官方内容混淆。

产出：
    skill/50_module_fast_nav.md     正式版（含来源头）
    config/50_module_nav.json       机器可读索引（路由层使用）
    备份：skill/archive/50_module_fast_nav.GENERATED_DRAFT-<date>.md

用法：
    uv run python scripts/import_official_module_nav.py --source "D:\\Download\\....md"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    DB_PATH,
    MODULE_NAV_JSON_PATH,
    MODULE_NAV_MD_PATH,
    SKILL_DIR,
    load_json,
    now_iso,
    write_json,
)

ARCHIVE_DIR = SKILL_DIR / "archive"
DEFAULT_SOURCE = Path(r"D:\Download\AI信息素养省赛_50模块极速导航.md")

MODULE_HEAD_RE = re.compile(r"^##\s+M(\d{2})｜(.+?)\s*$")
CATEGORY_HEAD_RE = re.compile(r"^#\s+(.+?)（M\d{2}-M\d{2}）\s*$")
TABLE_ROW_RE = re.compile(r"^\|\s*(M\d{2})\s*\|(.+?)\|(.+?)\|(.+?)\|\s*$")
FIELD_RE = re.compile(r"^-\s+\*\*(.+?)\*\*：(.+?)\s*$")

FIELD_KEYS = {
    "触发词": "trigger_terms_raw",
    "首选入口": "primary_entry",
    "极速路径": "fast_path",
    "易错/降置信度条件": "traps",
    "答题模式": "answering_mode",
    "题库锚点": "question_anchors",
}

# 官方「首选入口」文本里出现的平台名 -> capabilities 里的 platform_key。
# 只映射真实存在的 key；映射不到的官方平台名会原样保留在
# derived.official_platform_names 中，不丢信息。
OFFICIAL_PLATFORM_ALIASES: tuple[tuple[str, str], ...] = (
    ("CNKI AI", "cnki"),
    ("知网研学", "cnki"),
    ("中国法律知识资源总库", "cnki"),
    ("CNKI", "cnki"),
    ("知网", "cnki"),
    ("万方", "wanfang"),
    ("维普", "vip"),
    ("PubMed", "pubmed"),
    ("ScienceDirect", "sciencedirect"),
    ("IEEE", "ieee"),
    ("UNESCO Digital Library", "unesco"),
    ("UNESCO", "unesco"),
    ("国家统计局", "stats"),
    ("国家标准全文公开系统", "standards"),
    ("全国标准信息公共服务平台", "standards"),
    ("CNIPA", "cnipa"),
    ("专利检索及分析", "cnipa"),
    ("专利公布公告", "cnipa"),
    ("中国大学MOOC", "icourse163"),
    ("学堂在线", "icourse163"),
    ("GitHub", "github"),
    ("ModelScope", "modelscope"),
    ("魔搭", "modelscope"),
    ("百度指数", "baidu-index"),
    ("微信指数", "baidu-index"),
    ("国家图书馆", "nlc"),
    ("国家自然科学基金", "nsfc"),
    ("arXiv", "arxiv"),
)


def resolve_official_platforms(entry_text: str, known_keys: set[str]) -> tuple[list[str], str]:
    """从官方「首选入口」文本里解析平台。

    **顺序按官方文本里的出现位置**，不是按别名长度。官方把 CNKI 列在
    ScienceDirect 之前，首选平台就应当是 CNKI。同一位置若多个别名重叠
    （如「CNKI AI」与「CNKI」），取更长的那个。

    返回 (official_names, primary_key)。
    """
    lowered = entry_text.lower()
    found: list[tuple[int, int, str, str]] = []  # (position, -len, alias, key)
    for alias, key in OFFICIAL_PLATFORM_ALIASES:
        position = lowered.find(alias.lower())
        if position >= 0:
            found.append((position, -len(alias), alias, key))

    found.sort()
    names: list[str] = []
    keys: list[str] = []
    for _, _, alias, key in found:
        if alias not in names:
            names.append(alias)
        if key in known_keys and key not in keys:
            keys.append(key)
    return names, (keys[0] if keys else "")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_official(text: str) -> dict[str, Any]:
    table: dict[str, dict[str, str]] = {}
    modules: dict[str, dict[str, Any]] = {}
    category = ""
    current: str = ""

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        match = CATEGORY_HEAD_RE.match(line)
        if match:
            category = match.group(1).strip()
            continue

        match = TABLE_ROW_RE.match(line)
        if match:
            code = match.group(1)
            table[code] = {
                "table_name": match.group(2).strip(),
                "table_triggers": [t.strip() for t in match.group(3).split("、") if t.strip()],
                "table_action": match.group(4).strip(),
            }
            continue

        match = MODULE_HEAD_RE.match(line)
        if match:
            code = f"M{match.group(1)}"
            title = match.group(2).strip()
            # 形如「AI素养-AI基础知识与伦理规范」
            parts = title.split("-", 1)
            current = code
            modules[code] = {
                "module_no": int(match.group(1)),
                "category_from_title": parts[0].strip(),
                "module_name": (parts[1] if len(parts) > 1 else parts[0]).strip(),
                "section_title": title,
                "category_section": category,
                "fields": {},
            }
            continue

        match = FIELD_RE.match(line)
        if match and current:
            key = FIELD_KEYS.get(match.group(1).strip())
            if key:
                modules[current]["fields"][key] = match.group(2).strip()

    return {"table": table, "modules": modules}


def build_derived_index() -> dict[str, dict[str, Any]]:
    """复用既有的平台/深链接派生逻辑（不修改官方内容）。"""
    from build_50_module_nav import (  # 延迟导入，避免无谓开销
        best_deep_link,
        build_module_index,
        build_url_index,
        detect_primary_platform,
    )
    from provincial_common import load_entry_status, load_platform_capabilities

    db = build_module_index()
    url_index = build_url_index()
    capabilities = load_platform_capabilities()["platforms"]
    entry_status = load_entry_status()

    derived: dict[str, dict[str, Any]] = {}
    db_modules = db["modules"]
    by_no = {m.get("module_no"): mid for mid, m in db_modules.items()}
    for no, module_id in by_no.items():
        module = db_modules[module_id]
        urls = url_index.get(module_id, [])
        questions = db["questions"].get(module_id, [])
        primary, fallbacks = detect_primary_platform(module, urls, questions, capabilities)
        capability = capabilities.get(primary) or {}
        link = best_deep_link(primary, entry_status)
        derived[f"M{no:02d}"] = {
            "db_module_id": module_id,
            "db_module_name": module.get("module_name") or "",
            "dynamicity": module.get("dynamicity") or "UNKNOWN",
            "requires_login": module.get("requires_login") or "UNKNOWN",
            "primary_platform": primary,
            "primary_platform_name": capability.get("name", ""),
            "fallback_platforms": fallbacks,
            "deep_link": link.get("url", ""),
            "deep_link_status": link.get("status", "UNKNOWN"),
            "deep_link_source": link.get("source", ""),
            "supported_fields": capability.get("supported_fields", []),
            "evidence_level_cap": capability.get("evidence_level_cap", ""),
            "question_count_in_bank": len(questions),
            "url_recipe_count": len(urls),
        }
    return derived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入正式 50 模块极速导航")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"来源文件不存在：{source}", file=sys.stderr)
        return 2

    text = source.read_text(encoding="utf-8")
    digest = sha256_of(source)
    parsed = parse_official(text)
    table = parsed["table"]
    modules = parsed["modules"]

    # --- 完整性校验 --------------------------------------------------------
    problems: list[str] = []
    expected = {f"M{n:02d}" for n in range(1, 51)}
    missing_sections = sorted(expected - set(modules))
    missing_rows = sorted(expected - set(table))
    if missing_sections:
        problems.append(f"缺少模块小节：{missing_sections}")
    if missing_rows:
        problems.append(f"总路由表缺少行：{missing_rows}")
    incomplete = [
        code for code, item in modules.items()
        if not item["fields"].get("primary_entry") or not item["fields"].get("trigger_terms_raw")
    ]
    if incomplete:
        problems.append(f"缺少触发词或首选入口：{sorted(incomplete)}")

    if problems:
        print("校验失败：" + "；".join(problems), file=sys.stderr)
        return 1

    # --- 组装 --------------------------------------------------------------
    db_nav = load_json(MODULE_NAV_JSON_PATH) if MODULE_NAV_JSON_PATH.exists() else {"modules": []}
    old_by_no = {m["module_no"]: m for m in db_nav.get("modules", [])}
    derived = build_derived_index()
    from provincial_common import load_platform_capabilities

    known_keys = set(load_platform_capabilities()["platforms"])

    nav_modules: list[dict[str, Any]] = []
    for code in sorted(expected, key=lambda c: int(c[1:])):
        item = modules[code]
        fields = item["fields"]
        row = table[code]
        d = derived.get(code, {})
        old = old_by_no.get(item["module_no"], {})
        triggers = [t.strip() for t in fields.get("trigger_terms_raw", "").split("、") if t.strip()]
        traps = [t.strip() for t in fields.get("traps", "").split("；") if t.strip()]
        anchors = [a.strip() for a in fields.get("question_anchors", "").split("/") if a.strip()]

        # 官方「首选入口」优先决定平台；数据库启发式只在官方没点名时兜底。
        official_names, official_primary = resolve_official_platforms(
            fields.get("primary_entry", ""), known_keys
        )
        if official_primary:
            primary_platform = official_primary
            platform_source = "OFFICIAL_ENTRY"
            fallback_platforms = [k for k in d.get("fallback_platforms", []) if k != official_primary]
        elif d.get("primary_platform"):
            primary_platform = d["primary_platform"]
            platform_source = "DB_HEURISTIC"
            fallback_platforms = list(d.get("fallback_platforms", []))
        else:
            primary_platform = ""
            platform_source = "NONE"
            fallback_platforms = []

        nav_modules.append({
            # --- 官方内容（不由本脚本改写） ---
            "module_no": item["module_no"],
            "module_code": code,
            "module_id": d.get("db_module_id") or old.get("module_id") or f"知识模块{item['module_no']:02d}",
            "module_name": item["module_name"],
            "section_title": item["section_title"],
            "category": item["category_from_title"] or d.get("db_module_name") or "",
            "category_section": item["category_section"],
            "trigger_terms": triggers,
            "typical_operations": [fields.get("fast_path", "")] if fields.get("fast_path") else [],
            "main_traps": traps,
            "official": {
                "primary_entry": fields.get("primary_entry", ""),
                "fast_path": fields.get("fast_path", ""),
                "traps": fields.get("traps", ""),
                "answering_mode": fields.get("answering_mode", ""),
                "question_anchors": anchors,
                "table_name": row["table_name"],
                "table_triggers": row["table_triggers"],
                "table_action": row["table_action"],
            },
            # --- 派生内容（明确标注） ---
            "derived": {
                "official_platform_names": official_names,
                "platform_source": platform_source,
                "primary_platform": primary_platform,
                "primary_platform_name": (
                    load_platform_capabilities()["platforms"]
                    .get(primary_platform, {})
                    .get("name", "")
                ) if primary_platform else "",
                "fallback_platforms": fallback_platforms,
                "deep_link": d.get("deep_link", ""),
                "deep_link_status": d.get("deep_link_status", "UNKNOWN"),
                "deep_link_source": d.get("deep_link_source", ""),
                "supported_fields": d.get("supported_fields", []),
                "evidence_level_cap": d.get("evidence_level_cap", ""),
                "dynamicity": d.get("dynamicity", "UNKNOWN"),
                "requires_login": d.get("requires_login", "UNKNOWN"),
                "question_count_in_bank": d.get("question_count_in_bank", 0),
                "url_recipe_count": d.get("url_recipe_count", 0),
            },
            # --- 兼容既有路由层 ---
            "primary_platform": primary_platform,
            "primary_platform_name": (
                load_platform_capabilities()["platforms"]
                .get(primary_platform, {})
                .get("name", "")
            ) if primary_platform else "",
            "platform_source": platform_source,
            "official_platform_names": official_names,
            "fallback_platforms": fallback_platforms,
            "deep_link": d.get("deep_link", ""),
            "deep_link_status": d.get("deep_link_status", "UNKNOWN"),
            "deep_link_source": d.get("deep_link_source", ""),
            "deep_link_verified_at": "",
            "deep_link_route_type": "",
            "deep_link_surface": "",
            "supported_fields": d.get("supported_fields", []),
            "evidence_level_cap": d.get("evidence_level_cap", ""),
            "dynamicity": d.get("dynamicity", "UNKNOWN"),
            "requires_login": d.get("requires_login", "UNKNOWN"),
            "common_question_types": old.get("common_question_types", []),
            "sample_question_ids": old.get("sample_question_ids", []),
            "question_count_in_bank": d.get("question_count_in_bank", 0),
            "url_recipe_count": d.get("url_recipe_count", 0),
            "offline_judgeable": old.get("offline_judgeable", "PARTIAL"),
            "source": "OFFICIAL_CONTROLLER",
        })

    nav = {
        "schema_version": "2.0",
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "artifact_status": "OFFICIAL",
        "source": "OFFICIAL_CONTROLLER",
        "official_file": str(source),
        "official_sha256": digest,
        "status_note": (
            "本导航由 Controller 提供的正式版《50 模块极速导航》解析生成。"
            "官方措辞保持原样（见每模块的 official 字段）；平台/深链接/字段等为**派生**内容，"
            "位于 derived 命名空间，仅供参考，不构成官方结论。"
        ),
        "counts": {
            "modules": len(nav_modules),
            "with_primary_entry": sum(1 for m in nav_modules if m["official"]["primary_entry"]),
            "with_trigger_terms": sum(1 for m in nav_modules if m["trigger_terms"]),
            "with_derived_platform": sum(1 for m in nav_modules if m["primary_platform"]),
            "platform_from_official_entry": sum(
                1 for m in nav_modules if m["platform_source"] == "OFFICIAL_ENTRY"
            ),
            "platform_from_db_heuristic": sum(
                1 for m in nav_modules if m["platform_source"] == "DB_HEURISTIC"
            ),
            "platform_unresolved": sum(
                1 for m in nav_modules if m["platform_source"] == "NONE"
            ),
            "with_derived_deep_link": sum(1 for m in nav_modules if m["deep_link"]),
        },
        "modules": nav_modules,
    }

    if args.dry_run:
        print(json.dumps(nav["counts"], ensure_ascii=False, indent=2))
        print("dry-run：未写入任何文件")
        return 0

    # --- 归档旧草案 --------------------------------------------------------
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archived = ""
    if MODULE_NAV_MD_PATH.exists():
        prior_status = (db_nav.get("artifact_status") or "UNKNOWN")
        target = ARCHIVE_DIR / f"50_module_fast_nav.{prior_status}-{now_iso()[:10]}.md"
        shutil.copy2(MODULE_NAV_MD_PATH, target)
        archived = str(target)

    # --- 写入正式版 --------------------------------------------------------
    header = (
        "# 2026 大学生“AI+信息素养”大赛省赛淘汰赛 · 50 模块极速导航\n\n"
        "> **状态：OFFICIAL（Controller 提供）**\n"
        f"> 来源文件：`{source}`\n"
        f"> sha256：`{digest}`\n"
        f"> 导入时间：{now_iso()}\n"
        f"> 上一版本（草案）已归档：`{archived or '无'}`\n"
        ">\n"
        "> 本文件内容来自 Controller，未经改写。平台/深链接等派生索引见 "
        "`config/50_module_nav.json` 的 `derived` 命名空间。\n\n"
        "---\n\n"
    )
    body = text
    # 去掉官方文件的首行大标题，避免与上方标题重复
    body = re.sub(r"^#\s+2026 大学生.*?\n", "", body, count=1)
    MODULE_NAV_MD_PATH.write_text(header + body.lstrip(), encoding="utf-8")
    write_json(MODULE_NAV_JSON_PATH, nav)

    print(f"installed official nav -> {MODULE_NAV_MD_PATH}")
    print(f"archived draft        -> {archived or '(none)'}")
    print(f"index                 -> {MODULE_NAV_JSON_PATH}")
    print(json.dumps(nav["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

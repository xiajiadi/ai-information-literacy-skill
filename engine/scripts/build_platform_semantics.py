"""PHASE 2 修正 · DECISION 1：构建平台**语义层**。

**不覆盖**任何既有资产：
  - `config/platform_capabilities.json` 保留为原始资产；
  - `config/platform_registry.json`（FAST 路线，由 build_platform_registry.py 生成）不动。

新增：`config/platform_semantics.json`

每条至少包含 Controller 要求的字段：

    platform_key / canonical_name / aliases / domains /
    capabilities / official_entry / verification_status / provenance

核心纪律：

  * 旧数据只有域名、没有可靠平台名称时，`canonical_name` 记 **UNKNOWN**，
    **不臆造官方名称**；
  * 不得把比赛平台 URL 作为外部研究入口 —— 所有 URL 过合规闸门；
  * 对跨平台同名词、子域名、品牌名建立**消歧**机制。

用法：uv run python scripts/build_platform_semantics.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    PLATFORM_CAPABILITIES_PATH,
    ROOT,
    load_yaml,
    now_iso,
    write_json,
)

OUT = ROOT / "config" / "platform_semantics.json"
ALIASES_PATH = ROOT / "config" / "platform_aliases.yaml"

HOSTNAME_RE = re.compile(
    r"^[a-z0-9][a-z0-9.\-]*\.(?:com|cn|org|net|gov|edu|io|int|ai|dev|top|xyz)$", re.I
)
IP_RE = re.compile(r"^[\d.]+$")
MULTI_LABEL_SUFFIXES = (
    "gov.cn", "com.cn", "net.cn", "org.cn", "edu.cn", "ac.cn",
    "co.uk", "co.jp", "com.hk", "org.hk", "edu.hk", "com.tw",
)

# 跨平台同名词消歧。Controller 明确要求「对跨平台同名词建立消歧机制」。
DISAMBIGUATION: dict[str, dict[str, Any]] = {
    "百度": {
        "maps_to": None,
        "reason": (
            "「百度」单独出现无法判定是百度指数 / 百度学术 / 百度图片 / AI Studio。"
            "禁止分配给任一平台，必须搭配限定词。"
        ),
        "qualified_forms": {
            "百度指数": "baidu-index",
            "百度学术": "baidu_xueshu",
            "百度图片": "baidu_image",
            "百度AI Studio": "aistudio",
        },
    },
    "知网": {
        "maps_to": "cnki",
        "reason": "「知网 / CNKI / 中国知网」指向同一平台，合并为 cnki。",
    },
    "国家标准": {
        "maps_to": "standards",
        "reason": "国家标准化管理委员会体系下的唯一权威入口；行业/地方标准需另判。",
    },
    "卫健委": {
        "maps_to": "nhc",
        "reason": "默认指国家卫生健康委员会；省市级卫健委需另判。",
    },
    "github": {
        "maps_to": "github",
        "reason": "docs.github.com 是 github.com 的子域，品牌名相同，按子域归并。",
    },
}


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    if not host or IP_RE.fullmatch(host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    for suffix in MULTI_LABEL_SUFFIXES:
        if host.endswith("." + suffix):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def main() -> int:
    if not PLATFORM_CAPABILITIES_PATH.exists():
        print(f"原始资产缺失：{PLATFORM_CAPABILITIES_PATH}", file=sys.stderr)
        return 2

    legacy = json.loads(PLATFORM_CAPABILITIES_PATH.read_text(encoding="utf-8"))
    legacy_platforms: dict[str, Any] = legacy["platforms"]
    curated: dict[str, list[str]] = {}
    if ALIASES_PATH.exists():
        curated = (load_yaml(ALIASES_PATH).get("aliases") or {})

    from compliance_gate import ComplianceGate

    gate = ComplianceGate()

    curated_owner: dict[str, str] = {}
    for key, names in curated.items():
        for name in names or []:
            curated_owner[str(name).strip().lower()] = key

    registry: dict[str, dict[str, Any]] = {}
    rejected_urls: list[dict[str, str]] = []
    unresolved_names: list[str] = []

    for key, entry in legacy_platforms.items():
        if not isinstance(entry, dict):
            continue

        # ---- canonical_name：无可靠名称就记 UNKNOWN，不臆造 ----
        raw_name = str(entry.get("name") or "").strip()
        if not raw_name or raw_name == key or HOSTNAME_RE.match(raw_name) or IP_RE.match(raw_name):
            canonical_name = "UNKNOWN"
            name_provenance = "UNRESOLVED_LEGACY_HOSTNAME"
            unresolved_names.append(key)
        else:
            canonical_name = raw_name
            name_provenance = "LEGACY_NAME"
        if curated.get(key):
            canonical_name = curated[key][0]
            name_provenance = "CONTROLLER_CURATED"

        # ---- aliases ----
        aliases: list[str] = []
        for candidate in (curated.get(key) or []):
            candidate = str(candidate).strip()
            if candidate and candidate != canonical_name and candidate not in aliases:
                aliases.append(candidate)
        for candidate in (entry.get("aliases") or []):
            candidate = str(candidate).strip()
            if not candidate or candidate == canonical_name or candidate in aliases:
                continue
            if HOSTNAME_RE.match(candidate) or IP_RE.match(candidate):
                continue
            owner = curated_owner.get(candidate.lower())
            if owner and owner != key:
                continue
            aliases.append(candidate)

        # ---- domains ----
        domains: list[str] = []
        for url in (
            (entry.get("entry") or {}).get("primary", ""),
            entry.get("canonical_home", ""),
        ):
            host = host_of(url)
            if not host:
                continue
            for probe in (host, registrable_domain(host)):
                if probe and probe not in domains:
                    domains.append(probe)

        # ---- official_entry：必须过合规闸门 ----
        official_entry = ""
        entry_decision = "UNKNOWN"
        candidate_entry = (
            (entry.get("entry") or {}).get("primary")
            or entry.get("canonical_home")
            or ""
        )
        if candidate_entry:
            verdict = gate.classify(candidate_entry)
            if verdict.automation_allowed:
                official_entry = candidate_entry
                entry_decision = verdict.decision
            else:
                rejected_urls.append({
                    "platform_key": key,
                    "url": candidate_entry[:160],
                    "surface": verdict.surface,
                    "reason": "比赛面或未确认归属，禁止作为研究入口",
                })
                entry_decision = "BLOCKED_SURFACE"

        entry_block = entry.get("entry") if isinstance(entry.get("entry"), dict) else {}
        registry[key] = {
            "platform_key": key,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "domains": domains,
            "capabilities": {
                "supported_fields": entry.get("supported_fields", []) or [],
                "query_syntax": entry.get("query_syntax", "") or "",
                "evidence_level_cap": entry.get("evidence_level_cap", "") or "",
                "requires_login": entry.get("requires_login", "UNKNOWN"),
                "dynamicity": entry.get("dynamicity", "UNKNOWN"),
            },
            "official_entry": official_entry,
            "official_entry_decision": entry_decision,
            "verification_status": entry_block.get("primary_status", "UNVERIFIED"),
            "provenance": {
                "name": name_provenance,
                "aliases": "CONTROLLER_CURATED" if curated.get(key) else "LEGACY",
                "domains": "DERIVED_FROM_OFFICIAL_URL",
                "base_asset": "config/platform_capabilities.json（未被修改）",
            },
        }

    # ---- 合并 Controller 决策 (b) 的补录条目 -----------------------------
    backfill_path = ROOT / "config" / "platform_backfill.yaml"
    backfill: dict[str, Any] = {}
    if backfill_path.exists():
        backfill = (load_yaml(backfill_path).get("platforms") or {})

    backfilled_new = 0
    for key, item in backfill.items():
        if not isinstance(item, dict):
            continue
        canonical = str(item.get("canonical_name") or "").strip()
        aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
        if key in registry:
            # 复用既有条目：只补别名，不覆盖既有名称与入口
            existing = registry[key]
            for alias in aliases:
                if alias != existing["canonical_name"] and alias not in existing["aliases"]:
                    existing["aliases"].append(alias)
            if existing["canonical_name"] == "UNKNOWN" and canonical:
                existing["canonical_name"] = canonical
                existing["provenance"]["name"] = "CONTROLLER_BACKFILL"
            existing["provenance"]["backfill"] = "DECISION_B_MERGED"
            continue
        # 新条目：**不设** domains / official_entry（无权威来源时不臆造）
        registry[key] = {
            "platform_key": key,
            "canonical_name": canonical or "UNKNOWN",
            "aliases": aliases,
            "domains": [],
            "capabilities": {
                "supported_fields": [],
                "query_syntax": "",
                "evidence_level_cap": "",
                "requires_login": "UNKNOWN",
                "dynamicity": "UNKNOWN",
            },
            "official_entry": "",
            "official_entry_decision": "PENDING_DOMAIN_VERIFICATION",
            "verification_status": "UNVERIFIED",
            "module_hint": item.get("module_hint", ""),
            "evidence": item.get("evidence", ""),
            "provenance": {
                "name": "CONTROLLER_BACKFILL",
                "aliases": "CONTROLLER_BACKFILL",
                "domains": "PENDING_NO_AUTHORITATIVE_SOURCE",
                "base_asset": "config/platform_backfill.yaml（Controller 决策 (b)）",
            },
        }
        backfilled_new += 1

    # ---- 别名冲突检测 ---------------------------------------------------
    # 同一别名指向多个**不同**平台才算冲突；别名与自身 key 相同不算。
    alias_owners: dict[str, list[str]] = defaultdict(list)
    for key, item in registry.items():
        for alias in item["aliases"]:
            lowered = alias.lower()
            if lowered == key.lower():
                continue
            if key not in alias_owners[lowered]:
                alias_owners[lowered].append(key)
    collisions = {
        alias: owners for alias, owners in alias_owners.items() if len(owners) > 1
    }

    payload = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "purpose": (
            "平台语义层。**不覆盖** config/platform_capabilities.json，"
            "也不改动 config/platform_registry.json（FAST 路线）。"
        ),
        "controller_decisions": {
            "DECISION_1": "APPROVED — 重建平台语义注册表",
            "canonical_name_policy": "旧数据只有域名、无可靠名称时记 UNKNOWN，不臆造官方名称。",
            "competition_url_policy": "比赛平台 URL 不得作为外部研究入口，构建时已过闸门剔除。",
        },
        "counts": {
            "platforms": len(registry),
            "canonical_name_resolved": sum(
                1 for v in registry.values() if v["canonical_name"] != "UNKNOWN"
            ),
            "canonical_name_unknown": sum(
                1 for v in registry.values() if v["canonical_name"] == "UNKNOWN"
            ),
            "with_official_entry": sum(1 for v in registry.values() if v["official_entry"]),
            "rejected_competition_or_unknown_urls": len(rejected_urls),
            "alias_collisions": len(collisions),
            "backfilled_new_platforms": backfilled_new,
            "backfilled_from_decision_b": len(backfill),
        },
        "disambiguation": DISAMBIGUATION,
        "alias_collisions": collisions,
        "rejected_urls": rejected_urls,
        "unresolved_name_keys": unresolved_names,
        "platforms": registry,
    }

    write_json(OUT, payload)
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    if collisions:
        print(f"\n别名冲突（同一别名指向多个平台，需消歧）共 {len(collisions)}:")
        for alias, owners in list(collisions.items())[:10]:
            print(f"  {alias!r} -> {owners}")
    if rejected_urls:
        print(f"\n被合规闸门剔除的 URL（{len(rejected_urls)}）:")
        for item in rejected_urls[:6]:
            print(f"  {item['platform_key']}: {item['surface']} {item['url'][:68]}")
    print(f"\nsemantics = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

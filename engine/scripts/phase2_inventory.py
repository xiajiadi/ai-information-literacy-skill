"""PHASE 2 · 数据资产盘点与标签可信度分级。

本脚本只读，产出 `data/quality/phase2_asset_inventory.json`。

核心问题：**哪些标签可以作为独立 Gold Standard？**
本阶段明确禁止「把模型自己生成的标签当作独立 Gold」。因此按
**标签来源是否独立于路由模型**分级：

  GOLD      标签来自人写/官方产物（正式 50 模块导航、交接题库里手写的
            查询网址、官方公开模块页的来源）
  SILVER    标签由上一轮脚本启发式产生（模拟题的模块归属），可参考但不作
            为准确率分母
  NONE      无标签

用法：uv run python scripts/phase2_inventory.py
"""

from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    DB_PATH,
    MODULE_NAV_JSON_PATH,
    ROOT,
    load_module_nav,
    now_iso,
    write_json,
)

OUT = ROOT / "data" / "quality" / "phase2_asset_inventory.json"
HANDOFF_BANK = ROOT / "handoff" / "question_bank.md"
NAV_MD = ROOT / "skill" / "50_module_fast_nav.md"

# 官方公开模块页来源：module_id 由官方模块页决定，独立于本路由模型。
GOLD_MODULE_SOURCES = {"2026官网公开知识模块样题"}


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def main() -> int:
    payload: dict = {"generated_at": now_iso(), "assets": {}, "labels": {}}

    # ---- 1. 资产版本与完整性 -------------------------------------------
    nav = load_module_nav()
    assets = {
        "official_nav_md": {
            "path": str(NAV_MD.relative_to(ROOT)),
            "sha256": sha256(NAV_MD),
            "artifact_status": nav["artifact_status"],
            "source": nav.get("source"),
            "official_sha256": nav.get("official_sha256"),
            "modules": len(nav["modules"]),
        },
        "handoff_bank_md": {
            "path": str(HANDOFF_BANK.relative_to(ROOT)),
            "sha256": sha256(HANDOFF_BANK),
            "bytes": HANDOFF_BANK.stat().st_size if HANDOFF_BANK.exists() else 0,
        },
        "sqlite": {
            "path": str(DB_PATH.relative_to(ROOT)),
            "bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        },
    }
    payload["assets"] = assets

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM questions")]
        routes = {
            r["question_id"]: dict(r)
            for r in conn.execute("SELECT * FROM question_routes")
        }
    finally:
        conn.close()

    # ---- 2. 题源分布 ---------------------------------------------------
    by_source = collections.Counter()
    module_coverage = collections.Counter()
    for row in rows:
        by_source[row["source_type"] or "(空)"] += 1
        if (row.get("module_id") or "").strip():
            module_coverage[row["module_id"]] += 1
    payload["question_sources"] = dict(by_source)
    payload["question_total"] = len(rows)
    payload["modules_with_questions"] = len(module_coverage)

    # ---- 3. 标签可信度分级 ---------------------------------------------
    gold_module = [
        r["id"] for r in rows
        if (r.get("module_id") or "").strip() and r["source_type"] in GOLD_MODULE_SOURCES
    ]
    silver_module = [
        r["id"] for r in rows
        if (r.get("module_id") or "").strip() and r["source_type"] not in GOLD_MODULE_SOURCES
    ]
    # 平台 Gold：交接题库里**人写的**查询网址 -> host -> platform_key
    platform_gold = {}
    for row in rows:
        route = routes.get(row["id"])
        if not route:
            continue
        url = (route.get("deep_link") or route.get("official_url") or "").strip()
        if not url:
            continue
        host = (urlsplit(url).hostname or "").lower()
        if host:
            platform_gold[row["id"]] = {
                "host": host,
                "platform_key": route.get("platform_key") or "",
                "source": "question_routes(official_urls.json 由交接资料生成)",
            }

    payload["labels"] = {
        "gold_standard_policy": (
            "Gold 只取来源独立于人/官方产物的标签："
            "(a) 模块标签取自【官方公开知识模块样题】的 module_id（由官方模块页决定）；"
            "(b) 平台标签取自交接资料里手写的查询网址 host。"
            "模拟题的模块归属由上一轮脚本启发式产生，记为 SILVER，不作为准确率分母。"
        ),
        "module_gold": {
            "count": len(gold_module),
            "source_types": sorted(GOLD_MODULE_SOURCES),
            "question_ids": gold_module,
        },
        "module_silver": {"count": len(silver_module)},
        "platform_gold": {
            "count": len(platform_gold),
            "source": "question_routes.deep_link / official_url 的 host",
        },
        "module_none": len(rows) - len(gold_module) - len(silver_module),
    }

    # ---- 4. 已知污染复核（供报告中说明为何不直接用 module_name） --------
    pollution = {
        "official_platform_empty": sum(
            1 for r in rows if not (r.get("official_platform") or "").strip()
        ),
        "module_name_missing": sum(
            1 for r in rows if not (r.get("module_name") or "").strip()
        ),
        "retrieval_path_sample": next(
            (r.get("retrieval_path") for r in rows if (r.get("retrieval_path") or "").strip()),
            "",
        ),
    }
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        mismatches = conn.execute(
            """
            SELECT COUNT(*) FROM questions q
            JOIN modules m ON m.module_id = q.module_id
            WHERE TRIM(COALESCE(q.module_name,'')) <> '' AND q.module_name <> m.module_name
            """
        ).fetchone()[0]
    finally:
        conn.close()
    pollution["module_name_vs_module_id_mismatch"] = mismatches
    payload["known_data_pollution"] = pollution

    write_json(OUT, payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "labels"},
                     ensure_ascii=False, indent=2)[:2000])
    print("\nlabels:", json.dumps(
        {k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "question_ids"})
         for k, v in payload["labels"].items()}, ensure_ascii=False, indent=2))
    print(f"\nreport = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

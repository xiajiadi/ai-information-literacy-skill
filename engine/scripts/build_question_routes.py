"""Build the `question_routes` table so a question never needs a fresh search.

Two sources, in priority order:

1. `config/official_urls.json` (CANONICAL SOURCE for browser recipes). Records
   already carry platform, entrance, requires_login, manual_only, fields and
   operation_path; we simply join them onto question ids.
2. For questions the canonical file does not cover, derive a route from the
   question stem / explanation by matching the platform names and aliases that
   the canonical file itself defines. A derived route is marked LOW confidence
   and is an entry point only -- never an answer.

Nothing here invents an answer. The output is routing metadata.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, ROOT, now_iso, text
from db_schema import connect_db, ensure_schema


URLS_PATH = ROOT / "config" / "official_urls.json"
MOCK_SOURCE_TYPE = "用户提供模拟题整理"

# Generic words that must never be treated as a platform name on their own.
STOP_ALIASES = {
    "ai", "app", "cn", "com", "www", "http", "https", "搜索", "数据库",
    "官网", "平台", "系统", "网站", "工具", "网页版", "客户端",
}

# Questions about locally installed software need no web route at all. Naming
# them explicitly stops the orchestrator from opening a browser for them.
LOCAL_SOFTWARE_TERMS = (
    "word", "excel", "wps", "powerpoint", "ppt", "vlookup", "mid(",
    "分页符", "替换功能", "快捷键", "截图功能", "排版助手", "公式",
    "录屏",
)

# Platforms that the 150 questions reference but config/official_urls.json does
# not yet carry. This is a narrow supplement for entry points only -- it adds no
# answer content, and any platform already in the canonical file is untouched.
PLATFORM_SUPPLEMENT: list[tuple[str, dict]] = [
    ("知网研学", {"platform": "cnki", "name": "知网研学平台",
                  "url": "https://x.cnki.net/", "requires_login": "YES"}),
    ("研招网", {"platform": "yz-chsi", "name": "中国研究生招生信息网",
                "url": "https://yz.chsi.com.cn/", "requires_login": "NO"}),
    ("中国研究生招生信息网", {"platform": "yz-chsi", "name": "中国研究生招生信息网",
                              "url": "https://yz.chsi.com.cn/", "requires_login": "NO"}),
    ("卫健委", {"platform": "nhc", "name": "国家卫生健康委员会",
                "url": "https://www.nhc.gov.cn/", "requires_login": "NO"}),
    ("中山大学图书馆", {"platform": "wechat-mp", "name": "中山大学图书馆微信公众号",
                        "url": "https://mp.weixin.qq.com/", "requires_login": "YES",
                        "manual_only": True}),
    ("微信公众号", {"platform": "wechat-mp", "name": "微信公众号",
                    "url": "https://mp.weixin.qq.com/", "requires_login": "YES",
                    "manual_only": True}),
    ("反诈APP", {"platform": "app-only", "name": "国家反诈中心 APP",
                 "url": "https://www.mps.gov.cn/", "requires_login": "YES",
                 "manual_only": True}),
    ("专利公布公告", {"platform": "cnipa", "name": "中国专利公布公告系统",
                      "url": "https://pss-system.cponline.cnipa.gov.cn/",
                      "requires_login": "NO"}),
    ("Nature", {"platform": "nature", "name": "Nature",
                "url": "https://www.nature.com/", "requires_login": "NO"}),
    ("知数", {"platform": "stats-ai", "name": "AI知数（国家统计局）",
              "url": "https://data.stats.gov.cn/", "requires_login": "NO"}),
    ("CY/T", {"platform": "standards", "name": "全国标准信息公共服务平台",
              "url": "https://std.samr.gov.cn/", "requires_login": "NO"}),
]


def is_cjk_alias(value: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in value)


def usable_alias(value: str) -> bool:
    """Two-character CJK names (百度, 万方) are real platforms; two-character
    ASCII tokens are not."""
    if not value or value.lower() in STOP_ALIASES:
        return False
    if is_cjk_alias(value):
        return len(value) >= 2
    return len(value) >= 3


def load_url_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("urls", [])


def alias_index(records: list[dict]) -> list[tuple[str, dict]]:
    """Longest-first alias -> record, so 'cnki' beats a stray 'cn'."""
    pairs: list[tuple[str, dict]] = []
    for record in records:
        names = {record.get("platform", ""), record.get("name", "")}
        names |= set(record.get("name_aliases") or [])
        for name in names:
            value = text(name)
            if not usable_alias(value):
                continue
            pairs.append((value, record))
    pairs.sort(key=lambda item: -len(item[0]))
    return pairs


def supplement_index() -> list[tuple[str, dict]]:
    """Alias -> synthetic record for platforms the canonical file lacks."""
    pairs = []
    for alias, spec in PLATFORM_SUPPLEMENT:
        record = {
            "platform": spec["platform"],
            "name": spec["name"],
            "url": spec["url"],
            "url_kind": "home",
            "entrance": spec["url"],
            "requires_login": spec.get("requires_login", "UNKNOWN"),
            "manual_only": spec.get("manual_only", False),
            "operation_path": [],
            "fields": [],
            "_supplement": True,
        }
        pairs.append((alias, record))
    pairs.sort(key=lambda item: -len(item[0]))
    return pairs


def local_software_match(haystack: str) -> bool:
    lowered = haystack.lower()
    return any(term in lowered for term in LOCAL_SOFTWARE_TERMS)


def join_recipe(record: dict) -> dict:
    operation = record.get("operation_path") or []
    fields = record.get("fields") or []
    url = text(record.get("url"))
    entrance = text(record.get("entrance")) or url
    is_deep = text(record.get("url_kind")) == "deep"
    manual_only = bool(record.get("manual_only"))
    return {
        "platform_key": text(record.get("platform")),
        "official_platform": text(record.get("name")) or text(record.get("platform")),
        "official_url": url,
        "deep_link": url if is_deep else "",
        "retrieval_recipe": " → ".join(operation) if operation else "",
        "manual_recipe": (
            f"入口：{entrance}\n字段：{'、'.join(fields)}\n"
            + "\n".join(f"{i}. {step}" for i, step in enumerate(operation, 1))
            if manual_only
            else ""
        ),
        "requires_login": text(record.get("requires_login")) or "UNKNOWN",
        "manual_only": 1 if manual_only else 0,
        "route_source": "official_urls",
        "route_confidence": "MEDIUM",
    }


def derive_route(
    question_text: str,
    explanation: str,
    index: list[tuple[str, dict]],
    supplement: list[tuple[str, dict]],
) -> dict | None:
    """Find a platform mentioned in the question or its explanation.

    Canonical aliases win over supplement aliases. Local-software questions get
    an explicit no-browser route rather than a guessed URL.
    """
    haystack = f"{text(question_text)} {text(explanation)}"
    if not haystack.strip():
        return None
    lowered = haystack.lower()
    for alias, record in index + supplement:
        if alias.lower() in lowered:
            route = join_recipe(record)
            route["route_source"] = (
                "supplement" if record.get("_supplement") else "derived_from_stem"
            )
            route["route_confidence"] = "MEDIUM" if record.get("_supplement") else "LOW"
            return route
    if local_software_match(haystack):
        return {
            "platform_key": "local_software",
            "official_platform": "本地软件（Word/Excel/WPS 等）",
            "official_url": "",
            "deep_link": "",
            "retrieval_recipe": "本地实际操作验证，无需联网检索。",
            "manual_recipe": "",
            "requires_login": "NO",
            "manual_only": 0,
            "route_source": "local_software",
            "route_confidence": "MEDIUM",
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--urls", default=str(URLS_PATH))
    parser.add_argument("--report", default=str(ROOT / "data" / "quality" / "question_routes.json"))
    args = parser.parse_args()

    records = load_url_records(Path(args.urls))
    index = alias_index(records)
    supplement = supplement_index()

    by_question: dict[str, list[dict]] = {}
    for record in records:
        for question_id in record.get("question_ids") or []:
            by_question.setdefault(question_id, []).append(record)

    conn = connect_db(args.db)
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT id, question_text, answer_explanation FROM questions "
        "WHERE source_type = ? ORDER BY id",
        (MOCK_SOURCE_TYPE,),
    ).fetchall()

    conn.execute("DELETE FROM question_routes WHERE question_id IN "
                 "(SELECT id FROM questions WHERE source_type = ?)", (MOCK_SOURCE_TYPE,))

    stats = {"joined": 0, "derived": 0, "unrouted": [], "deep_links": 0}
    for row in rows:
        question_id = row["id"]
        routes: list[dict] = []
        for record in by_question.get(question_id, []):
            routes.append(join_recipe(record))
        if not routes:
            derived = derive_route(
                row["question_text"], row["answer_explanation"], index, supplement
            )
            if derived:
                routes.append(derived)
                stats["derived"] += 1
            else:
                stats["unrouted"].append(question_id)
                continue
        else:
            stats["joined"] += 1

        for route in routes:
            if route["deep_link"]:
                stats["deep_links"] += 1
            conn.execute(
                """
                INSERT OR REPLACE INTO question_routes (
                    question_id, platform_key, official_platform, official_url,
                    deep_link, retrieval_recipe, manual_recipe, requires_login,
                    manual_only, route_source, route_confidence, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    question_id, route["platform_key"], route["official_platform"],
                    route["official_url"], route["deep_link"], route["retrieval_recipe"],
                    route["manual_recipe"], route["requires_login"], route["manual_only"],
                    route["route_source"], route["route_confidence"], now_iso(), now_iso(),
                ),
            )
    conn.commit()

    routed = conn.execute(
        "SELECT count(DISTINCT question_id) FROM question_routes WHERE question_id IN "
        "(SELECT id FROM questions WHERE source_type = ?)", (MOCK_SOURCE_TYPE,)
    ).fetchone()[0]
    total_rows = conn.execute("SELECT count(*) FROM question_routes").fetchone()[0]
    manual_count = conn.execute(
        "SELECT count(DISTINCT question_id) FROM question_routes WHERE manual_only = 1"
    ).fetchone()[0]

    report = {
        "generated_at": now_iso(),
        "sim_questions": len(rows),
        "routed_questions": routed,
        "route_rows": total_rows,
        "joined_from_official_urls": stats["joined"],
        "derived_from_stem": stats["derived"],
        "unrouted": stats["unrouted"],
        "deep_links": stats["deep_links"],
        "manual_only_questions": manual_count,
        "canonical_source": str(Path(args.urls).resolve()),
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

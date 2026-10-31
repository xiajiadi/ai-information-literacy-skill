"""构建平台入口可信度表 -> config/platform_entry_status.json。

入口分五档（§8）：

    DIRECT     实测可直达，可自动浏览
    AUTH       需要登录，但登录后可正常使用（不自动输入密码，交人工）
    CHALLENGE  验证码 / WAF / 滑块 / Cloudflare / 人机验证 -> 立即人工交接
    BROKEN     入口失效或不可达 -> 立即使用备用路径
    UNKNOWN    尚未验证

数据来源与优先级（高 -> 低）：

    1. KNOWN_HISTORY  2026-09-19 校赛期实测结论（handoff.md / STATUS.md）。
                      **视为线索而非永久事实**，赛前必须重新验证。
    2. PREFLIGHT      data/quality/platform_preflight.json 的硬信号
                      （captcha 跳转 / 412 / 403 / 5xx）。
    3. REGISTRY       config/platform_registry.json 的 route status 映射。

本脚本只写 config/platform_entry_status.json，不修改任何既有文件。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    LEGACY_PLATFORM_REGISTRY_PATH,
    PLATFORM_ENTRY_STATUS_PATH,
    ROOT,
    load_json,
    now_iso,
    write_json,
)

PREFLIGHT_PATH = ROOT / "data" / "quality" / "platform_preflight.json"

DIRECT = "DIRECT"
AUTH = "AUTH"
CHALLENGE = "CHALLENGE"
BROKEN = "BROKEN"
UNKNOWN = "UNKNOWN"

STATUS_ENUM = {
    DIRECT: "实测可直达，可自动浏览",
    AUTH: "需要登录；登录后可用。不自动输入密码，交人工。",
    CHALLENGE: "验证码 / WAF / 滑块 / Cloudflare / 人机验证。立即人工交接，不绕过。",
    BROKEN: "入口失效或不可达。立即使用备用路径。",
    UNKNOWN: "尚未验证。赛前需实测。",
}

# 路由优先级：故障时挑备用入口用
ROUTE_PREFERENCE = [
    "ADVANCED_SEARCH",
    "QUERY_RECIPE",
    "SEARCH",
    "DATABASE_ENTRY",
    "RESOURCE_LIST",
    "RESOURCE_DETAIL",
    "PDF",
    "DEEP_LINK",
    "HOME",
    "LOGIN_DASHBOARD",
]

# ---------------------------------------------------------------------------
# KNOWN_HISTORY：2026-09-19 校赛期实测。**不是永久事实。**
# 每条都写明「为什么」，便于赛前重新验证时判断该验证什么。
# ---------------------------------------------------------------------------
KNOWN_HISTORY: list[dict[str, Any]] = [
    {
        "url": "https://kns.cnki.net/starter/advanced",
        "platform_key": "cnki",
        "status": CHALLENGE,
        "evidence": "2026-10-08 赛前复测：该入口**已改为**跳转 blockPuzzle 安全验证 "
                    "(/verify/home?captchaType=blockPuzzle)。2026-09-19 校赛期实测为可直达。",
        "verified_at": "2026-10-08",
        "notes": "⚠️ 状态已变化：曾经的首选深链接现在会命中验证码。命中即转人工，不要重试。"
                 "这是「KNOWN_HISTORY 只是线索、赛前必须复验」的实证。",
    },
    {
        "url": "https://kns.cnki.net/kns8s/AdvSearch",
        "platform_key": "cnki",
        "status": CHALLENGE,
        "evidence": "HTTP 探活被 302 到 /verify/home?captchaType=blockPuzzle",
        "verified_at": "2026-09-19",
        "notes": "blockPuzzle 安全验证。立即转人工，不要重试。",
    },
    {
        "url": "https://kns.cnki.net/kns8s/search",
        "platform_key": "cnki",
        "status": CHALLENGE,
        "evidence": "HTTP 探活被 302 到 /verify/home?captchaType=blockPuzzle",
        "verified_at": "2026-09-19",
        "notes": "总库检索直连触发风控。改走 starter/advanced。",
    },
    {
        "url": "https://www.cnki.net/",
        "platform_key": "cnki",
        "status": DIRECT,
        "evidence": "HTTP 200，未被重定向",
        "verified_at": "2026-09-19",
        "notes": "首页可用，但高级检索优先走 starter/advanced 深链接。",
    },
    {
        "url": "https://www.cqvip.com/advancesearch",
        "platform_key": "vip",
        "status": DIRECT,
        "evidence": "浏览器实测正常打开高级检索页",
        "verified_at": "2026-09-19",
        "notes": "维普首选入口。canonical 不带 ?dialog=login。",
    },
    {
        "url": "https://qikan.cqvip.com/Qikan/Search/Index",
        "platform_key": "vip",
        "status": BROKEN,
        "evidence": "返回 HTTP 412（反爬），勿用",
        "verified_at": "2026-09-19",
        "notes": "旧入口。改用 www.cqvip.com/advancesearch。",
    },
    {
        "url": "https://www.cqvip.com/",
        "platform_key": "vip",
        "status": DIRECT,
        "evidence": "HTTP 200",
        "verified_at": "2026-09-19",
        "notes": "",
    },
    {
        "url": "https://s.wanfangdata.com.cn/paper",
        "platform_key": "wanfang",
        "status": DIRECT,
        "evidence": "HTTP 200 实测可达",
        "verified_at": "2026-09-19",
        "notes": "万方检索页。结果数量/排名优先用结果页分组与筛选，不要逐条数。",
    },
    {
        "url": "https://www.wanfangdata.com.cn/index.html",
        "platform_key": "wanfang",
        "status": DIRECT,
        "evidence": "HTTP 200",
        "verified_at": "2026-09-19",
        "notes": "高级检索默认「模糊」不是「精确」——高频陷阱。",
    },
    {
        "url": "https://zhiyan.wanfangdata.com.cn/",
        "platform_key": "wanfang_zhiyan",
        "status": AUTH,
        "evidence": "依赖登录态；筛选控件不响应合成点击",
        "verified_at": "2026-09-19",
        "notes": "与万方主站并列的独立路由，不要从主站找入口。",
    },
    {
        "url": "https://pubmed.ncbi.nlm.nih.gov/advanced/",
        "platform_key": "pubmed",
        "status": DIRECT,
        "evidence": "HTTP 200；字段标记为官方语法",
        "verified_at": "2026-09-19",
        "notes": "优先生成可复制检索式。",
    },
    {
        "url": "https://pubmed.ncbi.nlm.nih.gov/",
        "platform_key": "pubmed",
        "status": DIRECT,
        "evidence": "HTTP 200",
        "verified_at": "2026-09-19",
        "notes": "",
    },
    {
        "url": "https://www.ncbi.nlm.nih.gov/mesh/",
        "platform_key": "pubmed",
        "status": DIRECT,
        "evidence": "HTTP 200",
        "verified_at": "2026-09-19",
        "notes": "MeSH 主题词规范化。",
    },
    {
        "url": "https://www.icourse163.org/search.htm",
        "platform_key": "icourse163",
        "status": DIRECT,
        "evidence": "课程搜索页与课程大纲本机浏览器实测可用",
        "verified_at": "2026-09-19",
        "notes": "课程详情页 .outline 无需登录即可读取。",
    },
    {
        "url": "https://www.icourse163.org/",
        "platform_key": "icourse163",
        "status": DIRECT,
        "evidence": "HTTP 200",
        "verified_at": "2026-09-19",
        "notes": "",
    },
    {
        "url": "https://www.sciencedirect.com/search",
        "platform_key": "sciencedirect",
        "status": DIRECT,
        "evidence": "实测直接进入 Advanced Search，跳过首页拦截",
        "verified_at": "2026-09-19",
        "notes": "首选入口。不要先开首页。",
    },
    {
        "url": "https://www.sciencedirect.com/",
        "platform_key": "sciencedirect",
        "status": CHALLENGE,
        "evidence": "HTTP 403（Cloudflare），浏览器也卡在「请稍候…」",
        "verified_at": "2026-09-19",
        "notes": "首页被 Cloudflare 挑战拦截。走 /search。",
    },
    {
        "url": "https://unesdoc.unesco.org/",
        "platform_key": "unesco_digital_library",
        "status": DIRECT,
        "evidence": "HTTP 200；SPA，需浏览器渲染 3-5 秒",
        "verified_at": "2026-09-19",
        "notes": "必须用浏览器，不能靠 HTTP 直取正文。",
    },
    {
        "url": "https://unesdoc.unesco.org/ark:/48223/pf0000393559",
        "platform_key": "unesco_digital_library",
        "status": DIRECT,
        "evidence": "HTTP 200；SPA 落地页",
        "verified_at": "2026-09-19",
        "notes": "PDF 查看器在 documentViewer.xhtml 内嵌 iframe。",
    },
    {
        "url": "https://unesdoc.unesco.org/ark:/48223/pf0000393559/PDF/393559chi.pdf",
        "platform_key": "unesco_digital_library",
        "status": BROKEN,
        "evidence": "返回 SPA 外壳 HTML（Content-Type: text/html），不是 PDF；下载端点 403",
        "verified_at": "2026-09-19",
        "notes": "不是直链。必须用浏览器打开 PDF 查看器。",
    },
    {
        "url": "http://epub.cnipa.gov.cn/",
        "platform_key": "cnipa_epub",
        "status": CHALLENGE,
        "evidence": "本会话返回空文档 / HTTP 412（WAF），未能实测",
        "verified_at": "2026-09-19",
        "notes": "中国专利公布公告系统。`?` 代 1 字符、`%` 代多字符。",
    },
    {
        "url": "http://epub.cnipa.gov.cn/gjcx.jsp",
        "platform_key": "cnipa_epub",
        "status": CHALLENGE,
        "evidence": "同上，WAF 前置",
        "verified_at": "2026-09-19",
        "notes": "高级查询页。若被 WAF 拦，转人工。",
    },
    {
        "url": "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch",
        "platform_key": "cnipa",
        "status": DIRECT,
        "evidence": "HTTP 实测可达（校赛期）",
        "verified_at": "2026-09-19",
        "notes": "专利常规检索。申请号优先于名称，避免同名歧义。",
    },
    {
        "url": "https://kd.nsfc.cn/finalProjectInit",
        "platform_key": "nsfc",
        "status": DIRECT,
        "evidence": "HTTP 实测可达",
        "verified_at": "2026-09-19",
        "notes": "国家自然科学基金结题项目。不要从首页层层点击。",
    },
    {
        "url": "https://ieeexplore.ieee.org/search/advanced",
        "platform_key": "ieee",
        "status": DIRECT,
        "evidence": "HTTP 实测可达（校赛期）",
        "verified_at": "2026-09-19",
        "notes": "IEEE 首页 ieee.org 不是正确入口。wildcard 语法不得套用到其他平台。",
    },
    {
        "url": "https://index.baidu.com/",
        "platform_key": "baidu-index",
        "status": AUTH,
        "evidence": "百度指数需要登录态",
        "verified_at": "2026-09-19",
        "notes": "行业排行必须手动指定历史日期；默认日期下显示「暂无数据」。",
    },
    {
        "url": "https://zxgk.court.gov.cn/",
        "platform_key": "zxgk_court",
        "status": BROKEN,
        "evidence": "返回 HTTP 412（反爬）",
        "verified_at": "2026-09-19",
        "notes": "中国执行信息公开网。使用备用路径或转人工。",
    },
    {
        "url": "https://openstd.samr.gov.cn/",
        "platform_key": "standard_open",
        "status": DIRECT,
        "evidence": "公开页面实测可辅助",
        "verified_at": "2026-09-19",
        "notes": "国家标准全文公开系统。",
    },
]

REGISTRY_STATUS_MAP = {
    "ACTIVE": DIRECT,
    "ACTIVE_EDGE_ONLY": DIRECT,
    "LOGIN_REQUIRED": AUTH,
    "MANUAL_ONLY": AUTH,
    "LEGACY_REDIRECT": UNKNOWN,
    "TEMPORARILY_UNAVAILABLE": BROKEN,
    "BROKEN": BROKEN,
    "UNKNOWN": UNKNOWN,
}


def normalize_url(url: str) -> str:
    """去掉尾部斜杠与 fragment，保留 query。用于跨来源对齐同一入口。"""
    value = (url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def classify_preflight_entry(entry: dict[str, Any]) -> tuple[str, str]:
    """从 preflight 的硬信号判档。只认硬信号，不用 login_suspected（误报率高）。"""
    status = entry.get("status")
    final_url = str(entry.get("final_url") or "")
    lowered = final_url.lower()
    if entry.get("redirected") and (
        "verify" in lowered or "captcha" in lowered or "challenge" in lowered
    ):
        return CHALLENGE, f"HTTP 探活被重定向到安全验证页：{final_url[:90]}"
    if status == 412:
        return BROKEN, "HTTP 412（反爬 / WAF）"
    if status == 403:
        return CHALLENGE, "HTTP 403（WAF / Cloudflare）"
    if isinstance(status, int) and status >= 500:
        return BROKEN, f"HTTP {status}"
    if entry.get("ok") and status and 200 <= status < 300:
        return DIRECT, f"HTTP {status} 可达"
    return UNKNOWN, "探活未给出可判定的硬信号"


def main() -> int:
    registry = load_json(LEGACY_PLATFORM_REGISTRY_PATH)
    preflight = load_json(PREFLIGHT_PATH) if PREFLIGHT_PATH.exists() else {}

    history_by_url = {normalize_url(item["url"]): item for item in KNOWN_HISTORY}
    preflight_by_url: dict[str, dict[str, Any]] = {}
    for platform in preflight.get("platforms", []):
        for entry in platform.get("entries", []):
            preflight_by_url.setdefault(normalize_url(entry.get("url", "")), entry)

    entries: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for platform_key, platform in sorted(registry.get("platforms", {}).items()):
        routes = platform.get("routes", [])
        active_routes = [
            r for r in routes if REGISTRY_STATUS_MAP.get(r.get("status")) == DIRECT
        ]
        active_routes.sort(
            key=lambda r: ROUTE_PREFERENCE.index(r.get("route_type"))
            if r.get("route_type") in ROUTE_PREFERENCE
            else len(ROUTE_PREFERENCE)
        )
        fallback = active_routes[0]["url"] if active_routes else ""

        for route in routes:
            url = route.get("url", "")
            key = normalize_url(url)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)

            history = history_by_url.get(key)
            observed = preflight_by_url.get(key)

            if history:
                status = history["status"]
                evidence = history["evidence"]
                source = "KNOWN_HISTORY"
                verified_at = history["verified_at"]
                notes = history.get("notes", "")
            elif observed:
                status, evidence = classify_preflight_entry(observed)
                source = "PREFLIGHT"
                verified_at = preflight.get("generated_at", "")
                notes = ""
            else:
                status = REGISTRY_STATUS_MAP.get(route.get("status"), UNKNOWN)
                evidence = f"来自 platform_registry.json 的 route status={route.get('status')}（未逐条实测）"
                source = "REGISTRY"
                verified_at = route.get("last_verified_at", "")
                notes = ""

            entries.append(
                {
                    "entry_key": route.get("route_key", ""),
                    "platform_key": platform_key,
                    "platform_name": platform.get("name", ""),
                    "url": url,
                    "canonical_url": key,
                    "route_type": route.get("route_type", ""),
                    "purpose": route.get("purpose", ""),
                    "status": status,
                    "requires_login": route.get("requires_login", "UNKNOWN"),
                    "automation": route.get("automation", ""),
                    "source": source,
                    "evidence": evidence,
                    "verified_at": verified_at,
                    "observed_http_status": (observed or {}).get("status"),
                    "fallback_url": "" if status == DIRECT else fallback,
                    "notes": notes,
                }
            )

    # KNOWN_HISTORY 里出现、但 registry 未覆盖的入口也要进表。
    # 这些入口同样需要备用路径：取该平台已实测可达的入口。
    for item in KNOWN_HISTORY:
        key = normalize_url(item["url"])
        if key in seen_urls:
            continue
        seen_urls.add(key)
        fallback = ""
        for candidate in KNOWN_HISTORY:
            if candidate is item or candidate["status"] != DIRECT:
                continue
            if candidate.get("platform_key") and (
                candidate["platform_key"] == item.get("platform_key")
            ):
                fallback = candidate["url"]
                break
        entries.append(
            {
                "entry_key": "",
                "platform_key": item.get("platform_key", ""),
                "platform_name": "",
                "url": item["url"],
                "canonical_url": key,
                "route_type": "",
                "purpose": "",
                "status": item["status"],
                "requires_login": "UNKNOWN",
                "automation": "",
                "source": "KNOWN_HISTORY",
                "evidence": item["evidence"],
                "verified_at": item.get("verified_at", ""),
                "observed_http_status": None,
                "fallback_url": "" if item["status"] == DIRECT else fallback,
                "notes": item.get("notes", ""),
            }
        )

    by_platform: dict[str, dict[str, Any]] = {}
    for entry in entries:
        bucket = by_platform.setdefault(
            entry["platform_key"],
            {"platform_name": entry["platform_name"], "counts": {}, "entries": []},
        )
        bucket["counts"][entry["status"]] = bucket["counts"].get(entry["status"], 0) + 1
        bucket["entries"].append(
            {
                "url": entry["url"],
                "route_type": entry["route_type"],
                "status": entry["status"],
                "fallback_url": entry["fallback_url"],
            }
        )

    payload = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "purpose": "平台入口可信度表。赛前实测的落点；运行时按此选入口，不再临场试错。",
        "status_enum": STATUS_ENUM,
        "source_priority": ["KNOWN_HISTORY", "PREFLIGHT", "REGISTRY"],
        "known_history_caveat": "KNOWN_HISTORY 是 2026-09-19 校赛期的观察，属于线索而不是永久事实。赛前必须重新实测并更新 status/verified_at。",
        "counts": {
            status: sum(1 for e in entries if e["status"] == status)
            for status in [DIRECT, AUTH, CHALLENGE, BROKEN, UNKNOWN]
        },
        "entry_total": len(entries),
        "platform_total": len(by_platform),
        "entries": sorted(entries, key=lambda e: (e["platform_key"], e["url"])),
        "by_platform": by_platform,
    }
    write_json(PLATFORM_ENTRY_STATUS_PATH, payload)
    print(
        f"wrote {PLATFORM_ENTRY_STATUS_PATH} "
        f"entries={len(entries)} platforms={len(by_platform)} counts={payload['counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

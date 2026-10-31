"""构建平台能力中心 -> config/platform_capabilities.json。

组织方式从「以题号为中心」改成：

    平台 -> entry -> supported_fields -> search_mode -> filters
         -> result_location -> known_risks -> fallback -> evidence_level

数据来源：
  1. config/platform_registry.json       平台 / 路由 / 登录要求 / 动态性（结构骨架）
  2. config/platform_entry_status.json   入口可信度（运行时选入口）
  3. config/query_templates.json         检索式模板与字段（语法 canonical）
  4. KNOWN_HISTORY_CAPABILITIES          2026-09-19 校赛期实测的字段与陷阱

⚠️ 已知数据污染（来自 handoff，本脚本已核验）：
  - questions.module_name 与 module_id 不一致（37/248 冲突）
  - questions.official_platform 248 行全空
  - questions.retrieval_path 实为解题说明，不是检索路径
  因此本文件**不读取**上述三个字段，只使用平台侧的结构化配置。

本脚本只写 config/platform_capabilities.json。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    EVIDENCE_HUMAN_REQUIRED,
    EVIDENCE_SECONDARY,
    EVIDENCE_VERIFIED_PRIMARY,
    LEGACY_PLATFORM_REGISTRY_PATH,
    LEGACY_QUERY_TEMPLATES_PATH,
    PLATFORM_CAPABILITIES_PATH,
    load_entry_status,
    load_json,
    now_iso,
    write_json,
)

# ---------------------------------------------------------------------------
# KNOWN_HISTORY_CAPABILITIES
#
# 2026-09-19 校赛期实测结论。每一条都是「平台能按什么字段检索 / 结果在哪里读 /
# 哪个入口是陷阱」。**是线索不是永久事实**，赛前需重新实测。
# ---------------------------------------------------------------------------
KNOWN_HISTORY_CAPABILITIES: dict[str, dict[str, Any]] = {
    "cnki": {
        "search_mode": ["ADVANCED_FORM", "PROFESSIONAL_EXPRESSION"],
        "supported_fields": [
            "主题", "篇关摘", "关键词", "篇名", "全文", "作者", "第一作者",
            "通讯作者", "作者单位", "基金", "摘要", "小标题", "参考文献",
            "分类号", "文献来源", "DOI",
        ],
        "filters": {
            "匹配方式": ["精确", "模糊"],
            "逻辑": ["AND", "OR", "NOT"],
            "时间范围": ["不限", "最近一周", "最近一月", "最近半年", "最近一年", "今年迄今", "上一年度"],
            "发表时间": "起止日期",
            "复选项": ["OA出版", "网络首发", "增强出版", "基金文献", "中英文扩展", "同义词扩展"],
        },
        "result_location": "结果总数标签；结果页左侧「学科」是专辑分类不是学位论文学科专业，必须进详情页",
        "known_risks": [
            "单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）",
            "单框内容上限 120 字符",
            "连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用",
            "直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码",
        ],
        "manual_handoff_trigger": ["blockPuzzle", "全文下载", "机构登录"],
        "notes": "高级检索填裸表达式；SU= 等字段代码只在专业检索用。",
    },
    "vip": {
        "search_mode": ["ADVANCED_FORM", "PROFESSIONAL_EXPRESSION"],
        "supported_fields": [
            "任意字段", "主题词", "篇关摘", "篇名", "关键词", "摘要", "作者",
            "第一作者", "作者单位", "刊名", "中图分类号", "学科分类号", "DOI", "基金",
        ],
        "filters": {
            "匹配方式": ["模糊", "精确"],
            "逻辑": ["AND", "OR", "NOT"],
            "文献类型": ["期刊论文", "学位论文", "会议论文", "专利", "标准"],
            "时间范围": "开始日期 — 结束日期",
            "检索扩展": ["同义词扩展", "中英文扩展"],
        },
        "result_location": "结果总数与左侧分组分面",
        "known_risks": [
            "「精确/模糊」语义与 CNKI 不同：精确=不分词且允许前后加内容；模糊=允许分词及位置调换",
            "作者/第一作者/导师/刊名/系列分类号/DOI 的「精确」=完全命中",
            "高级检索没有「导师」字段（只在专业检索里）",
            "筛选必须「先设条件再检索」；检索后才勾选的筛选不生效",
            "自证筛选是否生效：分面数字之和是否等于结果总数",
            "旧入口 qikan.cqvip.com 返回 412",
        ],
        "manual_handoff_trigger": ["412", "登录", "全文下载"],
        "notes": "运算符前后需空格；优先级 NOT > AND > OR。",
    },
    "wanfang": {
        "search_mode": ["ADVANCED_FORM", "FIELD_FILTER"],
        "supported_fields": ["题名", "关键词", "摘要", "作者", "作者单位", "期刊名称", "日期", "基金"],
        "filters": {
            "文献类型": ["期刊论文", "学位论文", "会议论文", "标准", "专利"],
            "排序": ["相关度", "被引量", "下载量", "发表时间"],
        },
        "result_location": "结果页左侧「分组」「筛选」「分析」；不要逐条数",
        "known_risks": [
            "高级检索默认是「模糊」不是「精确」",
            "筛选控件不响应合成点击，需改用页面自身 XHR 或直接调用页面函数",
            "万方智研是与主站并列的独立路由",
        ],
        "manual_handoff_trigger": ["滑块验证", "登录", "全文下载"],
        "notes": "结果数量、作者排名、机构排名优先用结果页已有分组/筛选/分析。",
    },
    "pubmed": {
        "search_mode": ["DIRECT_URL_QUERY", "ADVANCED_FORM"],
        "supported_fields": [
            "Title", "Title/Abstract", "Author", "MeSH Terms", "Journal", "Date - Publication",
        ],
        "filters": {
            "年份": "Publication date",
            "文献类型": "Article type",
            "可获取性": "Text availability",
        },
        "result_location": "结果页 Filter 侧栏与结果计数",
        "known_risks": [
            "字段标记与截词规则不能套用到 CNKI / 万方 / 维普 / ScienceDirect",
        ],
        "manual_handoff_trigger": ["订阅", "RSS", "alert"],
        "notes": "优先生成可复制检索式，不要只写自然语言。",
    },
    "icourse163": {
        "search_mode": ["DIRECT_URL_QUERY", "NAVIGATION"],
        "supported_fields": ["课程名称", "学校", "教师"],
        "filters": {},
        "result_location": "课程详情页 .outline / .outlineBody 含完整章节与小节标题",
        "known_risks": [
            "同名课程必须按学校+教师核对",
            "点击课程后的详情在新标签页打开",
            "不要 Google 课程答案",
        ],
        "manual_handoff_trigger": ["目录 30 秒内展不开"],
        "notes": "换课程时流程完全不变，只替换课程名与章节号。",
    },
    "sciencedirect": {
        "search_mode": ["ADVANCED_FORM", "GRAPHICAL_ADVANCED"],
        "supported_fields": [
            "terms", "journal or book title", "Year(s)", "Author(s)", "Author affiliation",
            "Volume(s)", "Issue(s)", "Page(s)", "Title, abstract or author-specified keywords",
            "Title", "References", "ISSN or ISBN",
        ],
        "filters": {"Show all fields": "展开高级字段"},
        "result_location": "结果页与文章详情页；全文可能受订阅限制",
        "known_risks": [
            "首页被 Cloudflare 拦（403），必须直接走 /search",
            "截词与布尔规则不能与 IEEE / PubMed 混用",
        ],
        "manual_handoff_trigger": ["Cloudflare 挑战", "订阅登录", "全文下载"],
        "notes": "页头有 LeapSpace 入口（模块 05）。",
    },
    "unesco": {
        "search_mode": ["NAVIGATION", "BROWSER_RENDER_ONLY"],
        "supported_fields": ["ARK 编号", "题名", "作者", "DOI", "ISBN", "页数", "语言", "出版年份"],
        "filters": {},
        "result_location": "PDF 查看器内嵌 iframe；必须区分 PDF viewer page 与正文页码",
        "known_risks": [
            "SPA 异步渲染，打开后需等 3-5 秒再读",
            "PDF 真实文件名带语言后缀（chi/eng/fre/...），不是固定值",
            "ark .../PDF/xxx.pdf 返回的是 SPA 外壳 HTML，不是 PDF",
            "下载端点脱离浏览器返回 403",
            "必须区分 PDF 页码与正文页码",
        ],
        "manual_handoff_trigger": ["PDF 目视核验", "页码切分"],
        "notes": "必须用浏览器，不能靠 HTTP 直取。",
    },
    "ieee": {
        "search_mode": ["ADVANCED_FORM"],
        "supported_fields": [
            "Document Title", "Author", "Publication Year", "Author Affiliations",
            "Publication Title", "Abstract", "Index Terms",
        ],
        "filters": {"年份": "Publication Year 区间"},
        "result_location": "结果页 Result Count 与年份筛选",
        "known_risks": [
            "首页 ieee.org 不是正确入口，必须走 /search/advanced",
            "wildcard 语法不得复制到其他平台",
        ],
        "manual_handoff_trigger": ["订阅全文"],
        "notes": "",
    },
    "cnipa_epub": {
        "registry_key": "epub",
        "search_mode": ["ADVANCED_FORM"],
        "supported_fields": ["申请（专利权）人", "文本名称", "公告日", "专利类型"],
        "filters": {"专利类型": ["发明授权", "发明申请", "实用新型", "外观设计"]},
        "result_location": "结果页展示模式：列表模式 / 公布模式 / 附图模式",
        "known_risks": [
            "该系统对本会话返回空文档 / HTTP 412（WAF），未能实测",
            "`?` 代表 1 个字符、`%` 代表多个字符",
            "高级查询功能页与普通查询不是同一个入口",
        ],
        "manual_handoff_trigger": ["412", "WAF", "空文档"],
        "notes": "",
    },
    "cnipa": {
        "search_mode": ["ADVANCED_FORM"],
        "supported_fields": ["申请号", "专利名称", "申请人", "专利类型", "同族", "技术领域", "附图"],
        "filters": {},
        "result_location": "专利详情页字段",
        "known_risks": ["同名专利歧义大，申请号优先于名称"],
        "manual_handoff_trigger": ["动态或受限页面"],
        "notes": "",
    },
    "nsfc": {
        "search_mode": ["FIELD_FILTER"],
        "supported_fields": ["结题年度", "资助类型/项目类型", "申请代码", "依托单位", "负责人"],
        "filters": {},
        "result_location": "结题项目列表与详情",
        "known_risks": ["不要从 kd.nsfc.cn 首页重新寻找「信息检索」再进结题项目"],
        "manual_handoff_trigger": [],
        "notes": "深链接 kd.nsfc.cn/finalProjectInit。",
    },
    "baidu-index": {
        "search_mode": ["NAVIGATION", "LOGIN_DASHBOARD"],
        "supported_fields": ["关键词", "行业", "时间范围", "地域"],
        "filters": {"时间范围": "必须手动指定历史日期"},
        "result_location": "行业排行榜单中的品牌指数与名次",
        "known_risks": [
            "默认日期下显示「暂无数据」，必须手动选历史日期",
            "需要登录态",
        ],
        "manual_handoff_trigger": ["登录", "默认日期无数据"],
        "notes": "",
    },
    "wanfang_zhiyan": {
        "search_mode": ["LOGIN_DASHBOARD", "NAVIGATION"],
        "supported_fields": ["订阅", "期刊订阅", "学科订阅", "被引量", "排序"],
        "filters": {},
        "result_location": "智研页面字段",
        "known_risks": ["筛选控件不响应合成点击", "依赖登录态", "与万方主站是并列路由"],
        "manual_handoff_trigger": ["登录"],
        "notes": "",
    },
    "zxgk_court": {
        "registry_key": "zxgk",
        "search_mode": ["NAVIGATION"],
        "supported_fields": ["被执行人", "案号", "立案时间"],
        "filters": {},
        "result_location": "查询结果列表",
        "known_risks": ["返回 HTTP 412（反爬）"],
        "manual_handoff_trigger": ["412"],
        "notes": "",
    },
    "arxiv": {
        "search_mode": ["DIRECT_URL_QUERY", "ADVANCED_FORM"],
        "supported_fields": ["identifier", "Title", "Author", "Abstract", "All fields"],
        "filters": {},
        "result_location": "Abstract 页与 PDF/HTML 全文",
        "known_risks": [],
        "manual_handoff_trigger": [],
        "notes": "",
    },
    "standards": {
        "search_mode": ["SEARCH", "RESOURCE_DETAIL"],
        "supported_fields": ["标准号", "标准名称", "起草单位", "实施日期"],
        "filters": {},
        "result_location": "标准详情页与标准正文",
        "known_risks": [
            "openstd.samr.gov.cn 是「国家标准全文公开系统」，registration 路由与 std.samr.gov.cn 不同",
            "标准正文 PDF 可能是扫描件（无文字层），必须浏览器渲染后目视读取",
        ],
        "manual_handoff_trigger": ["扫描件 PDF 目视核验"],
        "notes": "国家标准全文公开系统。",
    },
}

# 校赛期实测过、但 platform_registry.json 里没有独立条目的平台。
# 这些平台的知识不能因为 registry 缺条目而丢失。
ORPHAN_REGISTRY_KEYS = {"baidu-index", "wanfang_zhiyan", "arxiv"}

# 平台所属类别的默认证据上限。第三方聚合站永远拿不到官方等级。
THIRD_PARTY_CATEGORIES = {"聚合检索", "导航站", "第三方", "搜索摘要"}


def route_preference_index(route_type: str) -> int:
    order = [
        "ADVANCED_SEARCH", "QUERY_RECIPE", "SEARCH", "DATABASE_ENTRY",
        "RESOURCE_LIST", "RESOURCE_DETAIL", "PDF", "DEEP_LINK", "HOME",
        "LOGIN_DASHBOARD",
    ]
    return order.index(route_type) if route_type in order else len(order)


def curated_for(platform_key: str) -> dict[str, Any]:
    """按 registry key 取校赛期实测能力；同时接受带 registry_key 别名的私有键。"""
    if platform_key in KNOWN_HISTORY_CAPABILITIES:
        return KNOWN_HISTORY_CAPABILITIES[platform_key]
    for capability in KNOWN_HISTORY_CAPABILITIES.values():
        if capability.get("registry_key") == platform_key:
            return capability
    return {}


def build_platform(
    platform_key: str,
    platform: dict[str, Any],
    status_by_platform: dict[str, list[dict[str, Any]]],
    templates_by_platform: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    routes = platform.get("routes", [])
    entries = status_by_platform.get(platform_key, [])

    direct = [e for e in entries if e["status"] == "DIRECT"]
    direct.sort(key=lambda e: route_preference_index(e.get("route_type", "")))
    challenges = [e for e in entries if e["status"] in {"CHALLENGE", "BROKEN", "AUTH"}]
    challenges.sort(key=lambda e: route_preference_index(e.get("route_type", "")))

    primary = direct[0] if direct else None
    curated = curated_for(platform_key)

    # 检索语法只从 query_templates.json 取，不从别的平台借。
    syntax = [
        {
            "template_key": t.get("template_key"),
            "name": t.get("name"),
            "entry": t.get("entry"),
            "pattern": t.get("pattern"),
            "operators": t.get("operators") or t.get("field_tags"),
            "fields": t.get("fields") or t.get("priority_fields"),
            "verified": t.get("verified"),
            "verification_note": t.get("verification_note"),
        }
        for t in templates_by_platform.get(platform_key, [])
    ]

    supported_fields = curated.get("supported_fields")
    if not supported_fields:
        for template in syntax:
            if template.get("fields"):
                supported_fields = list(template["fields"])
                break
    supported_fields = supported_fields or []

    category = platform.get("category", "")
    if category in THIRD_PARTY_CATEGORIES:
        evidence_level = EVIDENCE_SECONDARY
    elif platform.get("auth_requirement") == "YES":
        evidence_level = EVIDENCE_HUMAN_REQUIRED
    else:
        evidence_level = EVIDENCE_VERIFIED_PRIMARY

    return {
        "platform_key": platform_key,
        "name": platform.get("name", ""),
        "aliases": platform.get("aliases", []),
        "category": category,
        "canonical_home": platform.get("canonical_home", ""),
        "auth_requirement": platform.get("auth_requirement", "UNKNOWN"),
        "prefer_edge": bool(platform.get("prefer_edge")),
        "dynamic_level": platform.get("dynamic_level", "UNKNOWN"),
        "source_priority": platform.get("source_priority"),
        "evidence_level_cap": evidence_level,
        "entry": {
            "primary": (primary or {}).get("url", ""),
            "primary_status": (primary or {}).get("status", "UNKNOWN"),
            "primary_route_type": (primary or {}).get("route_type", ""),
            "fallback": (primary or {}).get("fallback_url", ""),
            "route_count": len(routes),
            "entry_count": len(entries),
            "avoid": [
                {
                    "url": e["url"],
                    "status": e["status"],
                    "why": e.get("evidence", ""),
                    "use_instead": e.get("fallback_url", ""),
                }
                for e in challenges[:3]
            ],
        },
        "search_mode": curated.get("search_mode", []),
        "supported_fields": supported_fields,
        "query_syntax": syntax,
        "filters": curated.get("filters", {}),
        "result_location": curated.get("result_location", "未实测，需运行时确认"),
        "known_risks": curated.get("known_risks", []),
        "manual_handoff_trigger": curated.get("manual_handoff_trigger", []),
        "verified_from_known_history": bool(curated),
        "notes": curated.get("notes") or platform.get("notes", ""),
    }


def main() -> int:
    registry = load_json(LEGACY_PLATFORM_REGISTRY_PATH)
    entry_status = load_entry_status()
    templates = load_json(LEGACY_QUERY_TEMPLATES_PATH)

    status_by_platform: dict[str, list[dict[str, Any]]] = {}
    for entry in entry_status["entries"]:
        status_by_platform.setdefault(entry["platform_key"], []).append(entry)

    templates_by_platform: dict[str, list[dict[str, Any]]] = {}
    for template in templates.get("templates", []):
        key = template.get("platform_key", "")
        if key.startswith("_"):  # _search_engine 之类的通用模板不属于具体平台
            continue
        templates_by_platform.setdefault(key, []).append(template)

    platforms = {
        key: build_platform(key, value, status_by_platform, templates_by_platform)
        for key, value in sorted(registry.get("platforms", {}).items())
    }

    # registry 里没有独立条目的实测平台，单独补进来，避免能力知识丢失。
    orphan_keys = {
        key
        for key in KNOWN_HISTORY_CAPABILITIES
        if key not in platforms and key in ORPHAN_REGISTRY_KEYS
    }
    for key in sorted(orphan_keys):
        curated = KNOWN_HISTORY_CAPABILITIES[key]
        entries = status_by_platform.get(key, [])
        direct = [e for e in entries if e["status"] == "DIRECT"]
        direct.sort(key=lambda e: route_preference_index(e.get("route_type", "")))
        platforms[key] = {
            "platform_key": key,
            "name": key,
            "aliases": [],
            "category": "校赛期实测（platform_registry.json 无独立条目）",
            "canonical_home": (direct[0]["url"] if direct else ""),
            "auth_requirement": "UNKNOWN",
            "prefer_edge": False,
            "dynamic_level": "SEMI_DYNAMIC",
            "source_priority": None,
            "evidence_level_cap": EVIDENCE_VERIFIED_PRIMARY,
            "entry": {
                "primary": direct[0]["url"] if direct else "",
                "primary_status": direct[0]["status"] if direct else "UNKNOWN",
                "primary_route_type": direct[0].get("route_type", "") if direct else "",
                "fallback": "",
                "route_count": 0,
                "entry_count": len(entries),
                "avoid": [
                    {
                        "url": e["url"],
                        "status": e["status"],
                        "why": e.get("evidence", ""),
                        "use_instead": e.get("fallback_url", ""),
                    }
                    for e in entries
                    if e["status"] in {"CHALLENGE", "BROKEN"}
                ],
            },
            "search_mode": curated.get("search_mode", []),
            "supported_fields": curated.get("supported_fields", []),
            "query_syntax": [],
            "filters": curated.get("filters", {}),
            "result_location": curated.get("result_location", ""),
            "known_risks": curated.get("known_risks", []),
            "manual_handoff_trigger": curated.get("manual_handoff_trigger", []),
            "verified_from_known_history": True,
            "notes": curated.get("notes", ""),
        }

    payload = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "purpose": "平台能力中心。新题的内容会变，平台的检索能力是稳定的。",
        "center_of_gravity": "platform -> capability, not question_id -> answer",
        "sources": {
            "platform_registry": "config/platform_registry.json",
            "entry_status": "config/platform_entry_status.json",
            "query_templates": "config/query_templates.json",
            "known_history": "2026-09-19 校赛期实测（handoff.md / STATUS.md）",
        },
        "data_pollution_warning": [
            "questions.module_name 与 module_id 不一致（37/248 冲突）",
            "questions.official_platform 248 行全空",
            "questions.retrieval_path 实为解题说明而非检索路径",
            "以上三个字段不得用于能力路由；module_id 优先。",
        ],
        "counts": {
            "platforms": len(platforms),
            "with_verified_entry": sum(
                1 for p in platforms.values() if p["entry"]["primary_status"] == "DIRECT"
            ),
            "with_known_history_capability": sum(
                1 for p in platforms.values() if p["verified_from_known_history"]
            ),
            "with_query_syntax": sum(1 for p in platforms.values() if p["query_syntax"]),
        },
        "platforms": platforms,
    }
    write_json(PLATFORM_CAPABILITIES_PATH, payload)
    print(f"wrote {PLATFORM_CAPABILITIES_PATH} platforms={len(platforms)} counts={payload['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

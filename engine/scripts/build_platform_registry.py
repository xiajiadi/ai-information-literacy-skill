"""构建 FAST 平台注册表（config/platform_registry.json）。

FAST Replica 的路由底座：题目 → 平台 → 已知深链接 → 打开 → 检索。
本脚本只做增量汇总，不重建题库、不改答案、不动 attempts。

数据来源（全部只读）：

    config/official_urls.json    逐题 URL 配方（336 条 / 185 平台）
    config/platforms.yaml        平台总路线
    skill/module_01_50.md        50 模块正文里的 URL
    data/raw/simulation_sets/*   三套模拟题原文
    data/raw/teacher_training/*  公开培训材料

完整性判定：上述来源里出现过的平台，若没有 platform_key，则注册表为
INCOMPLETE，并在 gaps 里列出，不报告「配置完成」。

route_type  : HOME / SEARCH / ADVANCED_SEARCH / DATABASE_ENTRY / RESOURCE_LIST /
              RESOURCE_DETAIL / PDF / LOGIN_DASHBOARD / QUERY_RECIPE /
              APP_ONLY / WECHAT_ONLY / LEGACY
route_status: ACTIVE / ACTIVE_EDGE_ONLY / LOGIN_REQUIRED / MANUAL_ONLY /
              LEGACY_REDIRECT / TEMPORARILY_UNAVAILABLE / BROKEN / UNKNOWN

403、JS 外壳、纯 HTTP 读不到，都**不等于** BROKEN；若 Edge 可用即为
ACTIVE_EDGE_ONLY。
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RAW_DIR, extract_urls, now_iso, text

ROOT = Path(__file__).resolve().parents[1]
URLS_PATH = ROOT / "config" / "official_urls.json"
PLATFORMS_YAML = ROOT / "config" / "platforms.yaml"
MODULE_SKILL = ROOT / "skill" / "module_01_50.md"
REGISTRY_OUT = ROOT / "config" / "platform_registry.json"
TODAY = now_iso()[:10]

ROUTE_TYPES = (
    "HOME", "SEARCH", "ADVANCED_SEARCH", "DATABASE_ENTRY", "RESOURCE_LIST",
    "RESOURCE_DETAIL", "PDF", "LOGIN_DASHBOARD", "QUERY_RECIPE",
    "APP_ONLY", "WECHAT_ONLY", "LEGACY",
)
ROUTE_STATUS = (
    "ACTIVE", "ACTIVE_EDGE_ONLY", "LOGIN_REQUIRED", "MANUAL_ONLY",
    "LEGACY_REDIRECT", "TEMPORARILY_UNAVAILABLE", "BROKEN", "UNKNOWN",
)


def route(route_key: str, name: str, url: str, route_type: str, purpose: str,
          status: str = "UNKNOWN", requires_login: str = "UNKNOWN",
          prefer_edge: bool = False, automation: str = "PUBLIC_PAGE_ONLY",
          last_verified_at: str = "") -> dict[str, Any]:
    return {
        "route_key": route_key,
        "name": name,
        "url": url,
        "route_type": route_type,
        "purpose": purpose,
        "status": status,
        "requires_login": requires_login,
        "prefer_edge": prefer_edge,
        "automation": automation,
        "last_verified_at": last_verified_at,
    }


# 本次会话实测过的 Route 才写日期；其余留空表示未核验，绝不假装已验证。
V_BROWSER = TODAY      # 真实浏览器渲染核验
V_HTTP = TODAY         # HTTP 层可达核验


# ---------------------------------------------------------------------------
# 策展平台表
#
# 只写「平台 → 已知入口」的事实，不写题目答案。平台内的多套路由
# （如 CNKI 的期刊/学位/会议）必须拆开，避免把 CNKI 当成单一页面。
# ---------------------------------------------------------------------------

PLATFORMS: list[dict[str, Any]] = [
    {
        "platform_key": "cnki",
        "name": "CNKI 中国知网",
        "aliases": ["中国知网", "知网", "CNKI", "kns.cnki.net"],
        "category": "学术数据库",
        "canonical_home": "https://www.cnki.net/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": True,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "CNKI 不是单一页面：期刊/学位/会议/图书/AI/法律/图片/RSS 各有入口。"
                 "canonical 固定为不带 uid 的首页；uid 等参数由清洗规则剔除，禁止写入任何文件。",
        "routes": [
            route("CNKI_MAIN", "CNKI 首页", "https://www.cnki.net/", "HOME",
                  "总入口与文献类型导航", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("CNKI_ADVANCED", "CNKI 高级检索", "https://kns.cnki.net/starter/advanced",
                  "ADVANCED_SEARCH", "高级检索（实测可绕过 blockPuzzle）",
                  "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("CNKI_LEGACY_ADVSEARCH", "旧高级检索直链", "https://kns.cnki.net/kns8s/AdvSearch",
                  "LEGACY", "直连会跳 blockPuzzle 安全验证，仅作回溯",
                  "ACTIVE_EDGE_ONLY", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("CNKI_JOURNAL", "CNKI 期刊库", "https://navi.cnki.net/knavi", "RESOURCE_LIST",
                  "期刊导航与期刊内检索", "UNKNOWN", "SOMETIMES", True),
            route("CNKI_DEGREE", "CNKI 学位论文", "https://kns.cnki.net/kns8s/search?classid=CDMD",
                  "DATABASE_ENTRY", "学位论文库（题名/导师/学校/学位类型）",
                  "UNKNOWN", "SOMETIMES", True),
            route("CNKI_CONFERENCE", "CNKI 会议", "https://conf.cnki.net/Home", "DATABASE_ENTRY",
                  "会议论文与会议信息；当前 Edge 实际可用入口需现场确认，不写死",
                  "UNKNOWN", "SOMETIMES", True),
            route("CNKI_BOOK", "CNKI 图书", "https://kns.cnki.net/kns8s/search?classid=ECVI",
                  "DATABASE_ENTRY", "图书与工具书检索", "UNKNOWN", "SOMETIMES", True),
            route("CNKI_AI", "CNKI AI", "https://ai.cnki.net/chat/home", "LOGIN_DASHBOARD",
                  "CNKI AI 模块位置与功能", "LOGIN_REQUIRED", "YES", True, "MANUAL_ONLY"),
            route("CNKI_LAW", "CNKI 法律智库 LawPro", "https://lawpro.cnki.net/", "DATABASE_ENTRY",
                  "法律案例与法规检索", "UNKNOWN", "SOMETIMES", True),
            route("CNKI_IMAGE", "CNKI 学术图片", "https://image.cnki.net/AI", "RESOURCE_LIST",
                  "学术图片检索", "UNKNOWN", "SOMETIMES", True),
            route("CNKI_RSS", "CNKI RSS 订阅", "https://rss.cnki.net/knavi/rss/", "RESOURCE_DETAIL",
                  "期刊 RSS 订阅（模块 47）", "UNKNOWN", "SOMETIMES", True),
            route("CNKI_ESTUDY", "知网研学 E-Study", "https://estudy.cnki.net/", "RESOURCE_DETAIL",
                  "文献管理工具（模块 46）", "UNKNOWN", "SOMETIMES", True),
        ],
    },
    {
        "platform_key": "wanfang",
        "name": "万方数据",
        "aliases": ["万方", "wanfangdata", "万方智研"],
        "category": "学术数据库",
        "canonical_home": "https://www.wanfangdata.com.cn/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": True,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "主线与智研是两条独立路由；订阅/学科/被引量类题走智研。",
        "routes": [
            route("WANFANG_MAIN", "万方主站", "https://www.wanfangdata.com.cn/", "HOME",
                  "总入口", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("WANFANG_SEARCH", "万方检索页", "https://s.wanfangdata.com.cn/paper", "SEARCH",
                  "论文检索入口", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("WANFANG_JOURNAL", "万方期刊", "https://c.wanfangdata.com.cn/periodical",
                  "DATABASE_ENTRY", "期刊论文库", "UNKNOWN", "SOMETIMES", True),
            route("WANFANG_DEGREE", "万方学位论文", "https://c.wanfangdata.com.cn/thesis",
                  "DATABASE_ENTRY", "学位论文库（题名/导师/学校）", "UNKNOWN", "SOMETIMES", True),
            route("WANFANG_CONFERENCE", "万方会议论文", "https://c.wanfangdata.com.cn/conference",
                  "DATABASE_ENTRY", "会议论文库", "UNKNOWN", "SOMETIMES", True),
            route("WANFANG_STANDARD", "万方标准", "https://c.wanfangdata.com.cn/standard",
                  "DATABASE_ENTRY", "标准文献库", "UNKNOWN", "SOMETIMES", True),
            route("WANFANG_ZHIYAN", "万方智研", "https://zhiyan.wanfangdata.com.cn/", "HOME",
                  "订阅/期刊订阅/学科订阅/排序/被引量", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "vip",
        "name": "维普",
        "aliases": ["维普", "cqvip", "维普中文期刊服务平台"],
        "category": "学术数据库",
        "canonical_home": "https://www.cqvip.com/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": True,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "canonical 不带 ?dialog=login。精确/模糊语义与 CNKI 不同，不可混用。"
                 "旧入口 qikan.cqvip.com 返回 412，不使用。",
        "routes": [
            route("VIP_MAIN", "维普首页", "https://www.cqvip.com/", "HOME",
                  "总入口", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("VIP_ADVANCED_SEARCH", "维普高级检索", "https://www.cqvip.com/advancesearch",
                  "ADVANCED_SEARCH", "14 个检索项 + 模糊/精确 + AND/OR/NOT",
                  "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("VIP_JOURNAL", "维普期刊论文", "https://qikan.cqvip.com/", "LEGACY",
                  "旧期刊入口，返回 412，仅作回溯", "LEGACY_REDIRECT", "SOMETIMES", True),
            route("VIP_DEGREE", "维普学位论文", "https://www.cqvip.com/advancesearch", "DATABASE_ENTRY",
                  "高级检索页内选文献类型=学位论文", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("VIP_CONFERENCE", "维普会议论文", "https://www.cqvip.com/advancesearch", "DATABASE_ENTRY",
                  "高级检索页内选文献类型=会议论文", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("VIP_STANDARD", "维普标准", "https://www.cqvip.com/advancesearch", "DATABASE_ENTRY",
                  "高级检索页内选文献类型=标准", "ACTIVE", "SOMETIMES", True, "PUBLIC_PAGE_ONLY", V_BROWSER),
        ],
    },
    {
        "platform_key": "pubmed",
        "name": "PubMed",
        "aliases": ["pubmed", "NCBI PubMed", "MeSH"],
        "category": "国际学术数据库",
        "canonical_home": "https://pubmed.ncbi.nlm.nih.gov/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "优先生成可复制 Query。字段标记与截词规则不可套用到 CNKI/万方/维普/ScienceDirect。",
        "routes": [
            route("PUBMED_MAIN", "PubMed 首页", "https://pubmed.ncbi.nlm.nih.gov/", "HOME",
                  "总入口", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("PUBMED_ADVANCED", "Advanced Search", "https://pubmed.ncbi.nlm.nih.gov/advanced/",
                  "ADVANCED_SEARCH", "字段限定与检索史组合", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("PUBMED_MESH", "MeSH Database", "https://www.ncbi.nlm.nih.gov/mesh/",
                  "DATABASE_ENTRY", "主题词规范化", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("PUBMED_QUERY_RECIPE", "PubMed 检索式配方",
                  "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR%5BTitle%2FAbstract%5D+AND+2017%3A2024%5Bdp%5D+NOT+therapy%5BTitle%5D",
                  "QUERY_RECIPE", "参数化检索式，见 config/query_templates.json",
                  "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "ieee",
        "name": "IEEE Xplore",
        "aliases": ["IEEE", "ieeexplore", "IEEE Xplore"],
        "category": "国际学术数据库",
        "canonical_home": "https://ieeexplore.ieee.org/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 2,
        "notes": "IEEE 的 wildcard 语法不得复制到其他平台。",
        "routes": [
            route("IEEE_XPLORE_ADVANCED", "IEEE Xplore 高级检索",
                  "https://ieeexplore.ieee.org/search/advanced", "ADVANCED_SEARCH",
                  "Document Title / Author / Publication Year / 结果数量 / 年份筛选",
                  "ACTIVE", "SOMETIMES", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("IEEE_XPLORE_MAIN", "IEEE Xplore 首页", "https://ieeexplore.ieee.org/", "HOME",
                  "总入口", "UNKNOWN", "SOMETIMES", False),
            route("IEEE_ORG", "IEEE 官网", "https://www.ieee.org/", "HOME",
                  "会议与组织信息（模块 22）", "UNKNOWN", "NO", False),
        ],
    },
    {
        "platform_key": "sciencedirect",
        "name": "ScienceDirect",
        "aliases": ["sciencedirect", "Elsevier", "SD"],
        "category": "国际学术数据库",
        "canonical_home": "https://www.sciencedirect.com/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 2,
        "notes": "首页被 Cloudflare 拦截（403，浏览器卡「请稍候…」），"
                 "但 /search 可直接进高级检索。不套用其它库的 wildcard 语法。",
        "routes": [
            route("SD_MAIN", "ScienceDirect 首页", "https://www.sciencedirect.com/", "HOME",
                  "总入口（HTTP 403，浏览器需过挑战）", "ACTIVE_EDGE_ONLY", "SOMETIMES", False,
                  "PUBLIC_PAGE_ONLY", V_HTTP),
            route("SD_ADVANCED_SEARCH", "ScienceDirect 高级检索",
                  "https://www.sciencedirect.com/search", "ADVANCED_SEARCH",
                  "期刊内检索 / 年份 / 作者 / 卷期页 / Title,abstract,keywords",
                  "ACTIVE", "SOMETIMES", False, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("SD_JOURNAL_SEARCH", "期刊内检索",
                  "https://www.sciencedirect.com/search", "DATABASE_ENTRY",
                  "In this journal or book title 字段", "ACTIVE", "SOMETIMES", False,
                  "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("SD_ARTICLE_DETAIL", "文章详情页", "https://www.sciencedirect.com/science/article/pii/",
                  "RESOURCE_DETAIL", "按 DOI/PII 进入详情", "UNKNOWN", "SOMETIMES", False),
            route("SD_PDF", "ScienceDirect PDF", "https://www.sciencedirect.com/science/article/pii/",
                  "PDF", "全文 PDF（受订阅权限限制）", "UNKNOWN", "SOMETIMES", False),
            route("SD_LEAPSPACE", "LeapSpace", "https://www.sciencedirect.com/leapspace", "RESOURCE_DETAIL",
                  "Trust Card / Claim Radar / Deep Research / Writing Coach",
                  "UNKNOWN", "SOMETIMES", False),
        ],
    },
    {
        "platform_key": "icourse163",
        "name": "中国大学MOOC",
        "aliases": ["中国大学MOOC", "MOOC", "慕课", "icourse163", "icourse163.cn"],
        "category": "在线课程",
        "canonical_home": "https://www.icourse163.org/",
        "auth_requirement": "NO",
        "prefer_edge": True,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "课程大纲无需登录即可读（.outline）。同名课程必须按学校+教师核对。"
                 "icourse163.cn 为别名，canonical 固定用 .org。",
        "routes": [
            route("MOOC_MAIN", "MOOC 首页", "https://www.icourse163.org/", "HOME",
                  "总入口", "ACTIVE", "NO", True, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("MOOC_SEARCH", "课程搜索", "https://www.icourse163.org/search.htm",
                  "SEARCH", "按课程名搜索，结果卡片含学校与教师", "ACTIVE", "NO", True,
                  "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("MOOC_COURSE", "课程详情与大纲", "https://www.icourse163.org/course/",
                  "RESOURCE_DETAIL", "课程页 .outline 含章节 + 小节标题", "ACTIVE", "NO", True,
                  "PUBLIC_PAGE_ONLY", V_BROWSER),
        ],
    },
    {
        "platform_key": "unesco",
        "name": "UNESCO Digital Library",
        "aliases": ["UNESCO", "unesdoc", "联合国教科文组织"],
        "category": "国际组织文献",
        "canonical_home": "https://unesdoc.unesco.org/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "STATIC",
        "source_priority": 1,
        "notes": "SPA，需浏览器渲染（打开后等 3-5 秒）。PDF 无法脱离浏览器直取："
                 "/PDF/ 路径只返回外壳 HTML，真实下载端点 403。"
                 "页码必须区分 PDF viewer page 与 printed/body page。",
        "routes": [
            route("UNESCO_MAIN", "UNESCO 数字图书馆", "https://unesdoc.unesco.org/", "HOME",
                  "总入口", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("UNESCO_ARK_393559", "老师点名文档 pf0000393559",
                  "https://unesdoc.unesco.org/ark:/48223/pf0000393559", "RESOURCE_DETAIL",
                  "《生成式人工智能 教育与研究应用指南》2025 中文版，47 页",
                  "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_BROWSER),
            route("UNESCO_PDF_393559", "同文档 PDF（393559chi.pdf）",
                  "https://unesdoc.unesco.org/ark:/48223/pf0000393559/PDF/393559chi.pdf", "PDF",
                  "必须经浏览器 documentViewer；直取返回 HTML/403",
                  "ACTIVE_EDGE_ONLY", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "cnipa",
        "name": "国家知识产权局",
        "aliases": ["CNIPA", "cnipa.gov.cn", "专利检索", "pss-system"],
        "category": "政府/专利",
        "canonical_home": "https://www.cnipa.gov.cn/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": True,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "具体检索题走 conventionalSearch；导航页仅在不知入口时用。",
        "routes": [
            route("CNIPA_CONVENTIONAL", "专利常规检索",
                  "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch", "DATABASE_ENTRY",
                  "申请号优先，其次专利名称；含同族/详览", "ACTIVE", "SOMETIMES", True,
                  "PUBLIC_PAGE_ONLY", V_HTTP),
            route("CNIPA_NAV", "国家知识产权局导航",
                  "https://www.cnipa.gov.cn/col/col171/index.html", "HOME",
                  "官方导航页", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "nsfc",
        "name": "国家自然科学基金",
        "aliases": ["NSFC", "kd.nsfc.cn", "自然科学基金"],
        "category": "科研项目",
        "canonical_home": "https://kd.nsfc.cn/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "不要从首页层层点击找「信息检索」，直接进结题项目入口。",
        "routes": [
            route("NSFC_FINAL_PROJECT", "结题项目", "https://kd.nsfc.cn/finalProjectInit",
                  "DATABASE_ENTRY", "结题年度/项目类型/申请代码/依托单位/负责人",
                  "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
            route("NSFC_MAIN", "NSFC 首页", "https://kd.nsfc.cn/", "HOME",
                  "总入口", "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "ncpssd",
        "name": "国家哲学社会科学文献中心",
        "aliases": ["NCPSSD", "ncpssd.cn", "ncpssd.org", "哲社文献中心"],
        "category": "学术数据库",
        "canonical_home": "https://www.ncpssd.cn/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 2,
        "notes": "canonical 用 ncpssd.cn；ncpssd.org 作为 LEGACY/ALIAS 保留，不删除。",
        "routes": [
            route("NCPSD_MAIN", "NCPSD 主入口", "https://www.ncpssd.cn/", "HOME",
                  "总入口（canonical）", "UNKNOWN", "NO", False),
            route("NCPSD_LEGACY_ORG", "NCPSD 旧域名入口", "https://www.ncpssd.org/index",
                  "LEGACY", "用户实际可用入口，保留为 LEGACY/ALIAS",
                  "ACTIVE", "NO", False, "PUBLIC_PAGE_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "stats",
        "name": "国家统计局",
        "aliases": ["国家统计局", "stats.gov.cn", "国家数据"],
        "category": "政府/统计",
        "canonical_home": "https://www.stats.gov.cn/sj/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "DYNAMIC",
        "source_priority": 1,
        "notes": "年度/地区/分省年度数据是不同入口，不要混。",
        "routes": [
            route("STATS_MAIN", "统计数据", "https://www.stats.gov.cn/sj/", "RESOURCE_LIST",
                  "统计数据栏目", "UNKNOWN", "NO", False),
            route("DATA_STATS", "国家数据", "https://data.stats.gov.cn/", "DATABASE_ENTRY",
                  "数据类型 → 指标目录 → 指标 → 地区 → 年份", "UNKNOWN", "NO", False),
        ],
    },
    {
        "platform_key": "standards",
        "name": "国家标准",
        "aliases": ["国家标准", "std.samr.gov.cn", "openstd", "标准全文公开"],
        "category": "政府/标准",
        "canonical_home": "https://std.samr.gov.cn/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "STATIC",
        "source_priority": 1,
        "notes": "canonical 用 std.samr.gov.cn；openstd.samr.gov.cn 记为 LEGACY_REDIRECT。"
                 "题目给标准号时直接用标准号检索；PDF 题必须实际打开 PDF。",
        "routes": [
            route("STANDARD_SEARCH", "全国标准信息公共服务平台", "https://std.samr.gov.cn/",
                  "SEARCH", "标准号或名称检索", "UNKNOWN", "NO", False),
            route("STANDARD_DETAIL", "标准详情", "https://std.samr.gov.cn/hb/search/stdHBDetailed",
                  "RESOURCE_DETAIL", "标准详情字段", "UNKNOWN", "NO", False),
            route("STANDARD_PDF", "国家标准全文公开系统", "https://openstd.samr.gov.cn/", "LEGACY",
                  "旧入口，记为 LEGACY_REDIRECT", "LEGACY_REDIRECT", "NO", False),
        ],
    },
    {
        "platform_key": "nmpa",
        "name": "国家药品监督管理局",
        "aliases": ["NMPA", "nmpa.gov.cn", "药监局", "药品查询"],
        "category": "政府/医卫",
        "canonical_home": "https://www.nmpa.gov.cn/",
        "auth_requirement": "NO",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "查询优先使用批准文号或注册证号。",
        "routes": [
            route("NMPA_DOMESTIC_DRUG", "国产药品查询",
                  "https://www.nmpa.gov.cn/datasearch/home-index.html", "DATABASE_ENTRY",
                  "批准文号优先", "UNKNOWN", "NO", False),
            route("NMPA_OVERSEAS_DRUG", "进口药品查询",
                  "https://www.nmpa.gov.cn/datasearch/home-index.html", "DATABASE_ENTRY",
                  "注册证号优先", "UNKNOWN", "NO", False),
            route("NMPA_MEDICAL_DEVICE", "医疗器械查询",
                  "https://www.nmpa.gov.cn/datasearch/home-index.html", "DATABASE_ENTRY",
                  "注册证号优先", "UNKNOWN", "NO", False),
        ],
    },
    {
        "platform_key": "nlc",
        "name": "国家图书馆",
        "aliases": ["国家图书馆", "NLC", "nlc.cn", "国图"],
        "category": "图书馆/古籍",
        "canonical_home": "https://www.nlc.cn/",
        "auth_requirement": "SOMETIMES",
        "prefer_edge": False,
        "dynamic_level": "SEMI_DYNAMIC",
        "source_priority": 1,
        "notes": "册 / 卷 / PDF 页 / 正文页 四个概念不能混。",
        "routes": [
            route("NLC_MAIN", "国家图书馆", "https://www.nlc.cn/", "HOME",
                  "总入口", "UNKNOWN", "SOMETIMES", False),
            route("NLC_ANCIENT_BOOK", "中华古籍资源库",
                  "http://read.nlc.cn/thematDataSearch/toGujiIndex", "RESOURCE_LIST",
                  "古籍全文与目录", "UNKNOWN", "SOMETIMES", False),
            route("NLC_ETHNIC", "民族文字古籍",
                  "http://read.nlc.cn/allSearch/searchList?searchType=102&showType=1&pageNo=1",
                  "RESOURCE_LIST", "民族文字古籍", "UNKNOWN", "SOMETIMES", False),
            route("NLC_XIXIA", "西夏碎金",
                  "http://read.nlc.cn/allSearch/searchList?searchType=37&showType=1&pageNo=1",
                  "RESOURCE_LIST", "西夏文献", "UNKNOWN", "SOMETIMES", False),
            route("NLC_DISSERTATION", "国图学位论文", "https://www.nlc.cn/", "DATABASE_ENTRY",
                  "学位论文检索", "UNKNOWN", "SOMETIMES", False),
            route("NLC_RESOURCE_DETAIL", "国图资源详情", "https://www.nlc.cn/", "RESOURCE_DETAIL",
                  "民国文献等专题库详情", "UNKNOWN", "SOMETIMES", False),
        ],
    },
    {
        "platform_key": "wenjuanxing",
        "name": "问卷星",
        "aliases": ["问卷星", "wjx.cn", "WJX"],
        "category": "工具平台",
        "canonical_home": "https://www.wjx.cn/",
        "auth_requirement": "YES",
        "prefer_edge": True,
        "dynamic_level": "DYNAMIC",
        "source_priority": 2,
        "notes": "canonical 不含 randomt 参数。后台依赖登录态，优先用户 Edge Profile。",
        "routes": [
            route("WJX_MAIN", "问卷星首页", "https://www.wjx.cn/", "HOME",
                  "总入口", "UNKNOWN", "SOMETIMES", True),
            route("WJX_DASHBOARD", "我的问卷后台",
                  "https://www.wjx.cn/newwjx/manage/myquestionnaires.aspx", "LOGIN_DASHBOARD",
                  "问卷设置 / 提交答卷控制 / AI创建 / 版本功能", "LOGIN_REQUIRED", "YES", True,
                  "MANUAL_ONLY", V_HTTP),
        ],
    },
    {
        "platform_key": "douyin_creator",
        "name": "抖音创作者中心",
        "aliases": ["抖音创作者中心", "creator.douyin.com", "抖音指数"],
        "category": "指数/动态数据",
        "canonical_home": "https://creator.douyin.com/",
        "auth_requirement": "YES",
        "prefer_edge": True,
        "dynamic_level": "DYNAMIC",
        "source_priority": 3,
        "notes": "出现二维码/扫码/手机确认立即转人工，不尝试绕过。",
        "routes": [
            route("DOUYIN_INDEX", "创作者指数",
                  "https://creator.douyin.com/creator-micro/creator-count/arithmetic-index",
                  "LOGIN_DASHBOARD", "指数与创作者数据", "LOGIN_REQUIRED", "YES", True,
                  "MANUAL_ONLY", V_HTTP),
        ],
    },
]


# 50 模块正文里出现、但不在上面的策展表中的平台，按 host 归类。
# 这些是模块扫描的覆盖目标：出现一个，补一个。
MODULE_PLATFORM_HINTS: dict[str, tuple[str, str]] = {
    "oalib.com": ("oalib", "OALib"),
    "onlinelibrary.wiley.com": ("wiley", "Wiley Online Library"),
    "pubscholar.cn": ("pubscholar", "PubScholar"),
    "arxiv.org": ("arxiv", "arXiv"),
    "ncbi.nlm.nih.gov": ("ncbi", "NCBI"),
    "academic.oup.com": ("oxford", "Oxford Academic"),
    "libraries.mit.edu": ("mit", "MIT Libraries"),
    "dl.acm.org": ("acm", "ACM Digital Library"),
    "tandfonline.com": ("taylor-francis", "Taylor & Francis Online"),
    "nature.com": ("nature", "Nature"),
    "doaj.org": ("doaj", "DOAJ"),
    "chinaxiv.org": ("chinaxiv", "ChinaXiv"),
    "medrxiv.org": ("medrxiv", "medRxiv"),
    "nstl.gov.cn": ("nstl", "NSTL"),
    "aminer.cn": ("aminer", "AMiner"),
    "fz.people.com.cn": ("nssfc", "国家社科基金项目库"),
    "credit.acla.org.cn": ("lawyer-credit", "全国律师诚信平台"),
    "sac.net.cn": ("securities-association", "中国证券业协会"),
    "most.gov.cn": ("most", "科技部"),
    "tingshen.court.gov.cn": ("court", "中国庭审公开网"),
    "piyao.org.cn": ("piyao", "中国互联网联合辟谣平台"),
    "12371.cn": ("party", "共产党员网"),
    "yzw.cn": ("yz-chsi", "研招网"),
    "chsi.com.cn": ("chsi", "学信网"),
    "ncss.cn": ("ncss", "国家大学生就业服务平台"),
    "chatglm.cn": ("chatglm", "智谱清言"),
    "qianwen.com": ("qianwen", "通义千问"),
    "doubao.com": ("doubao", "豆包"),
    "paper.xfyun.cn": ("xfyun", "讯飞科研助手"),
    "n.cn": ("nano-ai", "纳米AI"),
    "zhida.zhihu.com": ("zhihu-zhida", "知乎直答"),
    "ima.qq.com": ("tencent-ima", "腾讯 ima"),
    "yunzhan365.com": ("yunzhan", "云展网"),
    "weiciyun.com": ("weiciyun", "微词云"),
    "echarts.apache.org": ("echarts", "ECharts"),
    "iconfont.cn": ("iconfont", "Iconfont"),
    "hippter.com": ("hippter", "HIPPTER"),
    "developer.aliyun.com": ("aliyun", "阿里云开发者社区"),
    "aidaxue.com": ("ai-daxue", "AI大学堂"),
    "yixi.tv": ("yixi", "一席"),
    "xueshu.baidu.com": ("baidu-scholar", "百度学术"),
    "index.baidu.com": ("baidu-index", "百度指数"),
    "image.so.com": ("so-images", "360图片"),
    "zotero.org": ("zotero", "Zotero"),
    "mendeley.com": ("mendeley", "Mendeley"),
    "yuketang.cn": ("yuketang", "雨课堂"),
    "xuetangx.com": ("xuetangx", "学堂在线"),
    "xueyinonline.com": ("xueyinonline", "学银在线"),
    "smartedu.cn": ("smartedu", "国家智慧教育平台"),
    "ilab-x.com": ("ilab-x", "ilab-x"),
    "open.163.com": ("open163", "网易公开课"),
    "unsplash.com": ("unsplash", "Unsplash"),
    "pixabay.com": ("pixabay", "Pixabay"),
    "lib.cqu.edu.cn": ("lib-cqu", "重庆大学图书馆"),
    "fjlib.net": ("fjlib", "福建省图书馆"),
    "wenxianxue.cn": ("kuizhangge", "奎章阁"),
    "lib.scu.edu.cn": ("lib-scu", "四川大学图书馆"),
    "lib.sysu.edu.cn": ("lib-sysu", "中山大学图书馆"),
    "docs.qq.com": ("tencent-docs", "腾讯文档"),
    "wps.cn": ("wps", "WPS"),
    "zhihuishu.com": ("zhihuishu", "智慧树"),
}


def load_sources() -> dict[str, Any]:
    urls_payload = json.loads(URLS_PATH.read_text(encoding="utf-8")) if URLS_PATH.exists() else {}
    return {"urls_payload": urls_payload}


def host_of(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "", re.IGNORECASE)
    host = (match.group(1) if match else "").lower()
    return host[4:] if host.startswith("www.") else host


def collect_source_hosts() -> dict[str, set[str]]:
    """各来源里出现过的 host。"""
    sources: dict[str, set[str]] = defaultdict(set)

    if MODULE_SKILL.exists():
        for url in extract_urls(MODULE_SKILL.read_text(encoding="utf-8")):
            sources["module_01_50"].add(host_of(url))

    for path in sorted((RAW_DIR / "simulation_sets").glob("*.txt")):
        for url in extract_urls(path.read_text(encoding="utf-8-sig", errors="ignore")):
            sources["simulation_sets"].add(host_of(url))

    # 教师培训材料是图片型/文字型混杂的 PDF，必须真的把文本抽出来扫一遍，
    # 不能因为 build_official_urls 也读过就当作「已覆盖」。
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        for path in sorted((RAW_DIR / "teacher_training").glob("*.pdf")):
            try:
                content = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
            except Exception:  # noqa: BLE001 - 个别图片型文件可能读取失败
                continue
            for url in extract_urls(content):
                sources["teacher_training"].add(host_of(url))

    public_json = RAW_DIR / "public_knowledge_list_csc2025.json"
    if public_json.exists():
        for url in extract_urls(public_json.read_text(encoding="utf-8", errors="ignore")):
            sources["public_knowledge"].add(host_of(url))

    return {key: {h for h in value if h} for key, value in sources.items()}


def build_registry() -> dict[str, Any]:
    payload = load_sources()["urls_payload"]
    records = payload.get("urls", [])

    # official_urls.json 里每个平台的规范首页与路由类型分布
    platform_routes: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        platform_routes[record.get("platform", "")].append(record)

    for entry in PLATFORMS:
        key = entry["platform_key"]
        entry["routes"] = sorted(entry["routes"], key=lambda r: (r["route_type"], r["route_key"]))
        entry["route_count"] = len(entry["routes"])
        entry["query_templates"] = []

    known = {entry["platform_key"] for entry in PLATFORMS}
    curated_count = len(PLATFORMS)
    known_names = set()
    for entry in PLATFORMS:
        known_names.add(entry["name"])
        known_names.update(entry["aliases"])

    # 模块扫描覆盖：module_01_50.md 里出现的 host 是否已有 platform_key
    source_hosts = collect_source_hosts()
    host_to_key: dict[str, str] = {}
    for entry in PLATFORMS:
        for alias in [entry["name"], *entry["aliases"], entry["canonical_home"]]:
            host_to_key[host_of(alias) if alias.startswith("http") else ""] = entry["platform_key"]
        for r in entry["routes"]:
            host_to_key[host_of(r["url"])] = entry["platform_key"]
    for host, (key, _name) in MODULE_PLATFORM_HINTS.items():
        host_to_key[host] = key

    module_hosts = source_hosts.get("module_01_50", set())
    sim_hosts = source_hosts.get("simulation_sets", set())
    all_hosts = module_hosts | sim_hosts | source_hosts.get("public_knowledge", set())

    # 自动派生：来源里出现、策展表还没收的平台，也必须有自己的 platform_key，
    # 否则按完整性规则注册表就是 INCOMPLETE。派生条目一律标注 AUTO_DERIVED
    # 并置于较低 source_priority —— 它们「有入口」，但不等于已逐条核验。
    records_by_host: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        records_by_host[host_of(record.get("url", ""))].append(record)

    derived = 0
    for host in sorted(all_hosts - set(host_to_key)):
        hint = MODULE_PLATFORM_HINTS.get(host)
        key = hint[0] if hint else host.split(".")[0].replace("-", "_").replace(".", "_")
        if key in known:
            host_to_key[host] = key
            continue
        host_records = sorted(records_by_host.get(host, []), key=lambda r: r.get("url", ""))
        routes: list[dict] = []
        seen_urls: set[str] = set()
        for record in host_records:
            url = record.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            routes.append(route(
                f"{key.upper()}_{len(routes) + 1:02d}",
                record.get("name") or host,
                url,
                record.get("route_type") or "DEEP_LINK",
                "来源派生入口（未逐条核验）",
                "UNKNOWN",
                record.get("requires_login", "UNKNOWN"),
                bool(record.get("prefer_edge")),
                record.get("browser_automation", "PUBLIC_PAGE_ONLY"),
            ))
        if not routes:
            routes.append(route(f"{key.upper()}_HOME", hint[1] if hint else host,
                                f"https://{host}/", "HOME", "来源派生入口（未逐条核验）"))

        home = next((r["url"] for r in routes if r["route_type"] == "HOME"), routes[0]["url"])
        PLATFORMS.append({
            "platform_key": key,
            "name": hint[1] if hint else host,
            "aliases": [host] + ([hint[1]] if hint else []),
            "category": "AUTO_DERIVED",
            "canonical_home": home,
            "auth_requirement": routes[0]["requires_login"],
            "prefer_edge": any(r["prefer_edge"] for r in routes),
            "dynamic_level": "SEMI_DYNAMIC",
            "source_priority": 5,
            "notes": "由 50 模块/模拟题/公开资料自动派生；入口来自 official_urls.json，未逐条核验。",
            "routes": sorted(routes, key=lambda r: (r["route_type"], r["route_key"])),
            "route_count": len(routes),
            "query_templates": [],
        })
        known.add(key)
        host_to_key[host] = key
        derived += 1

    covered = {h for h in all_hosts if h in host_to_key}
    uncovered = sorted(all_hosts - covered)

    gaps = [
        {"host": h, "reason": "出现在模拟题/模块/公开资料中，但注册表没有 platform_key",
         "suggested_key": h.split(".")[0].replace("-", "_")}
        for h in uncovered
    ]

    registry = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "agent": "FAST Replica",
        "purpose": "题目 → 平台 → 已知深链接 → 打开 → 检索。题库和答案不在本文件内。",
        "route_types": list(ROUTE_TYPES),
        "route_status": list(ROUTE_STATUS),
        "source_priority": [
            "P0 官方模拟题与官方公布标准答案",
            "P1 题目指定官方平台实时查询",
            "P2 组委会/官方培训资料",
            "P3 第三方辅助网页（仅辅助证据，不得称为官方验证）",
        ],
        "url_cleaning": {
            "stripped_keys": ["uid", "token", "session", "sessionid", "cookie", "randomt",
                              "queryId", "utm_source", "utm_medium", "utm_campaign"],
            "note": "canonical URL 一律不含上述参数；也不写入 JSON/YAML/Markdown/SQLite/logs。",
        },
        "edge_policy": {
            "browser_priority": ["existing_edge_login", "edge_automation", "agent-browser",
                                 "playwright_edge", "no_login_browser"],
            "forbidden": ["chrome_by_default", "playwright_chromium_by_default",
                          "read_or_export_cookies", "kill_user_edge", "delete_profile_lock",
                          "modify_browser_database"],
        },
        "platform_count": len(PLATFORMS),
        "curated_count": curated_count,
        "derived_count": derived,
        "platforms": {entry["platform_key"]: entry for entry in PLATFORMS},
        "coverage": {
            "source_hosts": {k: len(v) for k, v in source_hosts.items()},
            "known_hosts": len(host_to_key),
            "covered_hosts": len(covered),
            "uncovered_hosts": len(uncovered),
            "uncovered": uncovered,
        },
        "gaps": gaps,
        "status": "INCOMPLETE" if gaps else "COMPLETE",
    }
    return registry


def main() -> int:
    registry = build_registry()
    REGISTRY_OUT.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_OUT.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "status": registry["status"],
        "platforms": registry["platform_count"],
        "routes": sum(p["route_count"] for p in registry["platforms"].values()),
        "coverage": registry["coverage"]["covered_hosts"],
        "uncovered_hosts": registry["coverage"]["uncovered_hosts"],
        "gaps": len(registry["gaps"]),
        "output": str(REGISTRY_OUT),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

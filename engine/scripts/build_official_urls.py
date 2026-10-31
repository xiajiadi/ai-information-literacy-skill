from __future__ import annotations

import argparse
import html
import ipaddress
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - the project environment provides pypdf
    PdfReader = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, RAW_DIR, extract_urls, now_iso, text
from db_schema import connect_db, ensure_schema


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "config" / "official_urls.json"
MARKDOWN_PATH = ROOT / "skill" / "official_links.md"
URL_TOKEN_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'*+,;=%-]+", re.IGNORECASE)

# 路由类型：题目属于某平台时，直接按 route_type 选入口，不要先走搜索引擎。
ROUTE_TYPES = (
    "HOME",              # 平台首页
    "ADVANCED_SEARCH",   # 高级检索页
    "DATABASE_ENTRY",    # 具体数据库/业务入口（如结题项目、专利常规检索）
    "DEEP_LINK",         # 具体功能页深链接
    "QUERY_RECIPE",      # 可复制的检索式配方（保存表达式与筛选条件，不只存 URL）
    "LOGIN_DASHBOARD",   # 登录后后台，依赖 Edge 登录态
)
KIND_TO_ROUTE_TYPE = {"home": "HOME", "deep": "DEEP_LINK"}

# 查询串清洗：这些参数一律不进 canonical URL，更不得写入任何本地文件。
#
# 敏感类（uid/session/token/randomt…）是认证或会话标识，写进 JSON、YAML、
# Markdown、SQLite 或日志都等于泄露凭证；追踪类（utm_*/spm/dialog…）是噪声，
# 会让同一个入口在不同来源下被当成不同记录。
SENSITIVE_QUERY_KEYS = frozenset({
    "uid", "userid", "user_id", "session", "sessionid", "session_id",
    "token", "access_token", "refreshtoken", "auth", "authorization",
    "ticket", "sid", "jsessionid", "randomt", "sign", "signature",
})
TRACKING_QUERY_KEYS = frozenset({
    "spm", "dialog", "share_token", "shareto", "scene", "src",
})


def sanitize_query(query: str) -> str:
    """去掉敏感与追踪查询参数，保留其余原样（含顺序）。"""
    if not query:
        return ""
    kept: list[str] = []
    for part in query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].strip().lower()
        if not key:
            continue
        if key.startswith("utm_") or key in SENSITIVE_QUERY_KEYS or key in TRACKING_QUERY_KEYS:
            continue
        kept.append(part)
    return "&".join(kept)

TRUNCATED_REPAIRS = {
    "https://www.bilibili.c": "https://www.bilibili.com/",
    "https://www.mee.gov.c": "https://www.mee.gov.cn/",
    "https://www.wanfangdata.co": "https://www.wanfangdata.com.cn/",
    "https://yuanbao.tencent.co": "https://yuanbao.tencent.com/",
    "https://www.wps": "https://www.wps.cn/",
    "https://www.xueta": "https://www.xuetangx.com/",
    "https://www.xueyinonlin": "https://www.xueyinonline.com/",
    "https://www.m": "https://www.mendeley.com/",
    "https://open.1": "https://open.163.com/",
    "https://gb27": "https://gb2760.cfsa.net.cn/",
    "http://gb27": "http://gb2760.cfsa.net.cn/",
    "https://lifelong": "https://lifelong.smartedu.cn/",
    "https://pap": "https://paper.iflytek.com/",
    "https://vid": "https://video.wanfangdata.com.cn/",
}


def spec(
    platform: str,
    name: str,
    url: str,
    modules: tuple[int, ...] = (),
    terms: tuple[str, ...] = (),
    fields: tuple[str, ...] = (),
    path: tuple[str, ...] = (),
    login: str = "UNKNOWN",
    browser: str = "PUBLIC_PAGE_ONLY",
    manual: bool = False,
    notes: str = "",
    kind: str = "home",
    route_type: str = "",
    prefer_edge: bool = False,
    route_key: str = "",
    query_recipe: dict | None = None,
) -> dict:
    return {
        "platform": platform,
        "name": name,
        "url": url,
        "module": [f"知识模块{number:02d}" for number in modules],
        "terms": list(terms),
        "fields": list(fields) or ["题名/关键词", "作者或机构", "年份/日期", "结果数量或页面字段"],
        "operation_path": list(path) or ["打开入口", "进入题目指定栏目或高级检索", "填写题目给出的字段和筛选条件", "记录结果字段；动态值保存访问日期"],
        "requires_login": login,
        "browser_automation": browser,
        "manual_only": manual,
        "notes": notes or "只使用公开页面；登录、验证码、校园认证或 App 限制转人工。",
        "url_kind": kind,
        "route_type": route_type or KIND_TO_ROUTE_TYPE.get(kind, "DEEP_LINK"),
        "prefer_edge": prefer_edge,
        "route_key": route_key,
        "query_recipe": query_recipe or {},
    }


# This is an operational catalogue rather than a list of search results. The
# URLs come from the public training materials where available; for platforms
# without a stable deep link, the official home is retained and the note tells
# the operator to locate the current menu manually.
CATALOG = [
    # canonical 固定为不带 uid 等参数的首页；uid 会被 canonical_url 清洗掉，
    # 且禁止把 UID / Cookie / Token / Session 写入 JSON、YAML、Markdown、SQLite 或日志。
    spec("cnki", "CNKI", "https://www.cnki.net/", (21, 31, 35, 36, 42, 44, 47, 50), ("cnki", "中国知网"), login="SOMETIMES", route_key="CNKI_MAIN", prefer_edge=True),
    # 实测：直连 kns8s/AdvSearch 或 kns8s/search 会跳 blockPuzzle 安全验证；
    # 走 starter/advanced 可正常进入高级检索页。
    spec("cnki", "CNKI高级检索", "https://kns.cnki.net/starter/advanced", (31, 32, 34, 35, 36), ("cnki高级检索", "kns.cnki"), login="SOMETIMES", kind="deep", route_type="ADVANCED_SEARCH", prefer_edge=True,
         fields=("主题/篇关摘/关键词/篇名/全文", "作者/第一作者/通讯作者/作者单位", "基金/摘要/小标题/参考文献/分类号/文献来源/DOI", "精确/模糊", "时间范围与扩展选项"),
         path=("直接打开 starter/advanced", "选择检索项并填值", "选择精确或模糊", "用 AND/OR/NOT 组配", "读取结果总数，优先用左侧分组与分析而不是逐条数"),
         notes="高级检索框填裸表达式，* 与、+ 或、- 非，括号用英文半角，单框不超过 120 字符；SU= 等字段代码只在专业检索用。"),
    spec("cnki", "CNKI AI", "https://ai.cnki.net/chat/home", (5, 42, 50), ("cnki ai", "ai.cnki.net"), login="YES", browser="PUBLIC_PAGE_ONLY", manual=True, notes="CNKI AI 页面可能要求账号；不得绕过登录。", kind="deep"),
    spec("cnki", "CNKI法律智库", "https://lawpro.cnki.net/", (10,), ("lawpro.cnki", "法律智库"), login="SOMETIMES", kind="home"),
    spec("cnki", "CNKI会议", "https://conf.cnki.net/Home", (22,), ("conf.cnki", "cnki会议", "会议网"), login="SOMETIMES", kind="deep"),
    spec("cnki", "CNKI学术图片", "https://image.cnki.net/AI", (27,), ("image.cnki", "cnki学术图片", "学术图片"), login="SOMETIMES", kind="deep"),
    spec("wanfang", "万方数据", "https://www.wanfangdata.com.cn/", (21, 23, 31, 35, 36, 42, 44, 47), ("万方", "wanfangdata"), login="SOMETIMES", route_key="WANFANG_MAIN", prefer_edge=True),
    # 万方智研是与主站并列的独立路由：订阅、学科订阅、被引量排序这类题走这里，
    # 不要从万方主站里找入口。
    spec("wanfang", "万方智研", "https://zhiyan.wanfangdata.com.cn/", (21, 42), ("zhiyan", "智研", "万方智研"), login="SOMETIMES", route_key="WANFANG_ZHIYAN", prefer_edge=True,
         fields=("订阅/期刊订阅/学科订阅", "排序方式", "被引量", "学科或主题分类"),
         path=("直接打开万方智研", "进入订阅或学科栏目", "按题目设置订阅项与排序（含被引量）", "记录订阅状态与页面字段")),
    spec("wanfang", "万方标准", "https://www.wanfangdata.com.cn/", (11,), ("万方标准", "标准数据库"), login="SOMETIMES", notes="公开材料未提供独立稳定深链接，先保留万方首页；标准检索菜单需按当前页面人工确认。"),
    # canonical 就是不带任何查询串的首页。带 ?dialog=login 的地址会被
    # canonical_url 的清洗规则去掉，不会写进本库。
    spec("vip", "维普中文期刊服务平台", "https://www.cqvip.com/", (21, 31, 35, 36, 42, 44, 50), ("维普", "cqvip"), login="SOMETIMES", route_key="VIP_MAIN", prefer_edge=True),
    spec("vip", "维普高级检索", "https://www.cqvip.com/advancesearch", (31, 34, 35, 36), ("维普高级检索", "cqvip advancesearch"), login="SOMETIMES", kind="deep", route_type="ADVANCED_SEARCH", prefer_edge=True,
         fields=("任意字段/主题词/篇关摘/篇名/关键词/摘要", "作者/第一作者/作者单位/刊名", "中图分类号/学科分类号/DOI/基金", "模糊/精确", "文献类型", "时间范围"),
         path=("直接打开维普高级检索", "选择检索项并填值", "选择模糊或精确（作者/刊名/DOI 的精确为完全命中）", "用 AND/OR/NOT 组配，运算符前后留空格", "读取结果数量与左侧分组"),
         notes="维普的精确/模糊语义与 CNKI 不同，两库语法不可混用。旧入口 qikan.cqvip.com 返回 412，不要使用。"),
    spec("pubmed", "PubMed", "https://pubmed.ncbi.nlm.nih.gov/", (21, 26, 47), ("pubmed",), login="NO", fields=("题名/作者/关键词", "Publication type", "出版年份", "结果页/全文链接")),
    spec("ncbi", "NCBI", "https://www.ncbi.nlm.nih.gov/", (21, 26), ("ncbi",), login="NO"),
    spec("ncbi", "NCBI Bookshelf", "https://www.ncbi.nlm.nih.gov/books/", (19, 21, 26), ("bookshelf", "ncbi books"), login="NO", kind="deep"),
    spec("pubscholar", "PubScholar", "https://pubscholar.cn/", (24, 26), ("pubscholar",), login="NO"),
    spec("sciencedirect", "ScienceDirect", "https://www.sciencedirect.com/", (21, 24), ("sciencedirect",), login="SOMETIMES"),
    # LeapSpace 是独立路由：Trust Card / Claim Radar / Deep Research /
    # Writing Coach 这类科研工具题优先走这里，不要从 ScienceDirect 首页找。
    spec("sciencedirect", "LeapSpace", "https://www.sciencedirect.com/leapspace", (5, 42), ("leapspace", "claim radar", "deep research", "trust card", "writing coach"), login="SOMETIMES", kind="deep", route_key="LEAPSPACE",
         fields=("Trust Card", "Claim Radar", "Deep Research", "Writing Coach", "科研工具评估"),
         path=("直接打开 LeapSpace", "按题目定位到指定功能模块", "核对功能名称、入口位置与可用条件", "记录页面字段；需登录的部分转人工"),
         notes="canonical 不带 utm_campaign/utm_medium/utm_source 等追踪参数。"),
    spec("sciencedirect", "LeapSpace资源说明", "https://eci.elsevier.cn/resource/LeapSpace.html?fid=165&menuid=358&infoid=2004", (5,), ("eci.elsevier",), login="NO", kind="deep"),
    spec("wiley", "Wiley Online Library", "https://onlinelibrary.wiley.com/", (21, 24), ("wiley", "onlinelibrary.wiley"), login="SOMETIMES"),
    spec("taylor-francis", "Taylor & Francis Online", "https://www.tandfonline.com/", (21,), ("taylor", "tandfonline"), login="SOMETIMES"),
    spec("acm", "ACM Digital Library", "https://dl.acm.org/", (22, 26), ("acm digital", "dl.acm"), login="SOMETIMES"),
    spec("ieee", "IEEE", "https://www.ieee.org/", (22,), ("ieee",), login="NO"),
    spec("ieee", "IEEE Xplore", "https://ieeexplore.ieee.org/", (22, 24), ("ieeexplore",), login="SOMETIMES"),
    spec("oxford", "Oxford Academic", "https://academic.oup.com/", (19, 21), ("oxford academic", "academic.oup.com"), login="SOMETIMES"),
    spec("oxford", "Oxford Academic Books", "https://academic.oup.com/books", (19,), ("academic.oup.com/books",), login="SOMETIMES", kind="deep"),
    spec("mit", "MIT Theses", "https://dspace.mit.edu/", (23,), ("mit theses", "dspace.mit", "mit学位论文"), login="NO"),
    spec("mit", "MIT Libraries", "https://libraries.mit.edu/", (23,), ("libraries.mit.edu",), login="NO"),
    spec("arxiv", "arXiv", "https://arxiv.org/", (24,), ("arxiv", "预印本"), login="NO"),
    spec("oalib", "OALib", "https://www.oalib.com/", (24,), ("oalib",), login="NO"),
    spec("nlc", "国家图书馆", "https://www.nlc.cn/", (20, 30), ("国家图书馆", "nlc.cn"), login="SOMETIMES"),
    spec("nlc", "中华古籍资源库", "http://read.nlc.cn/thematDataSearch/toGujiIndex", (20, 28, 30), ("read.nlc.cn", "古籍资源库", "古籍全文"), login="SOMETIMES", kind="deep"),
    spec("stats", "国家统计局", "https://www.stats.gov.cn/", (9,), ("国家统计局", "stats.gov.cn"), login="NO"),
    spec("stats", "国家数据", "https://data.stats.gov.cn/", (9,), ("data.stats.gov.cn", "国家数据"), login="NO", kind="deep"),
    spec("nsfc", "国家自然科学基金", "https://kd.nsfc.cn/", (25,), ("国家自然科学基金", "kd.nsfc"), login="NO", fields=("项目名称", "负责人/依托单位", "批准年度", "项目类型/状态")),
    spec("nssfc", "国家社科基金", "https://fz.people.com.cn/skygb/sk/index.php/index/index/", (25,), ("国家社科基金", "fz.people.com.cn"), login="NO", fields=("项目名称", "负责人/单位", "立项年度", "项目类别/状态")),
    spec("nmpa", "国家药品监督管理局", "https://www.nmpa.gov.cn/", (14,), ("国家药品监督管理局", "nmpa.gov.cn"), login="NO"),
    spec("nmpa", "国家药监局数据查询", "https://www.nmpa.gov.cn/datasearch/home-index.html", (14,), ("datasearch/home-index", "国药准字"), login="NO", kind="deep"),
    spec("cnipa", "国家知识产权局", "https://www.cnipa.gov.cn/", (12,), ("国家知识产权局", "cnipa.gov.cn"), login="NO"),
    spec("cnipa", "国家知识产权局专利检索", "https://pss-system.cponline.cnipa.gov.cn/", (12,), ("pss-system.cponline.cnipa", "专利检索"), login="NO", kind="deep"),
    spec("standards", "国家标准全文公开系统", "https://openstd.samr.gov.cn/", (11,), ("openstd.samr", "国家标准全文公开"), login="NO", fields=("标准号", "标准名称", "发布日期", "实施日期/正文页码")),
    spec("standards", "全国标准信息公共服务平台", "https://std.samr.gov.cn/", (11,), ("std.samr.gov.cn", "全国标准信息公共服务平台"), login="NO"),
    spec("standards", "全国标准信息标准详情", "https://std.samr.gov.cn/hb/search/stdHBDetailed", (11,), ("stdHBDetailed",), login="NO", kind="deep"),
    spec("securities-association", "中国证券业协会", "https://www.sac.net.cn/", (16,), ("中国证券业协会", "sac.net.cn", "证券公司信息"), login="NO"),
    spec("lawyer-credit", "全国律师诚信平台", "https://credit.acla.org.cn/", (16,), ("credit.acla.org.cn", "律师诚信", "律师执业"), login="NO"),
    spec("smartedu", "国家智慧教育平台", "https://basic.smartedu.cn/", (15, 17), ("国家智慧教育平台", "basic.smartedu"), login="SOMETIMES"),
    spec("zhihuishu", "智慧树", "https://www.zhihuishu.com/", (18,), ("智慧树", "zhihuishu"), login="SOMETIMES"),
    spec("course-politics", "课程思政平台", "https://xhsz.news.cn/", (8, 15), ("课程思政", "xhsz.news.cn"), login="NO"),
    spec("baidu-scholar", "百度学术", "https://xueshu.baidu.com/", (26, 42), ("百度学术", "xueshu.baidu"), login="NO"),
    spec("baidu-index", "百度指数", "https://index.baidu.com/", (29,), ("百度指数", "index.baidu.com"), login="SOMETIMES", manual=True, fields=("关键词", "时间范围", "地区/人群", "指数曲线/排名")),
    spec("wechat-index", "微信指数", "https://weixin.qq.com/", (29,), ("微信指数", "微信客户端", "微信指数"), login="YES", browser="MANUAL_ONLY", manual=True, notes="微信指数通常在微信客户端内操作；本项目不自动化登录、扫码或小程序。"),
    spec("so-images", "360图片", "https://image.so.com/", (27,), ("360图片", "image.so.com"), login="NO"),
    spec("kuizhangge", "奎章阁（公开古籍入口）", "https://www.wenxianxue.cn/", (28,), ("奎章阁", "wenxianxue.cn", "古籍目录"), login="NO", notes="公开材料将古籍目录入口与“奎章阁”并列使用；未把第三方说明推定为独立官网，进入后按页面栏目确认。"),
    spec("chatglm", "智谱清言", "https://chatglm.cn/", (3, 4, 6), ("智谱清言", "chatglm.cn"), login="SOMETIMES"),
    spec("doubao", "豆包", "https://www.doubao.com/", (3, 4, 5, 6, 49), ("豆包", "doubao.com"), login="SOMETIMES"),
    spec("qianwen", "通义千问", "https://www.qianwen.com/", (3, 4, 6), ("通义千问", "千问", "qianwen.com"), login="SOMETIMES"),
    spec("xfyun", "讯飞星火", "https://xinghuo.xfyun.cn/", (3, 4, 5, 6), ("讯飞星火", "xinghuo", "xfyun"), login="SOMETIMES"),
    spec("nami", "纳米AI", "https://www.n.cn/", (3,), ("纳米ai", "纳米AI", "www.n.cn"), login="SOMETIMES"),
    spec("zhida", "知乎直答", "https://zhida.zhihu.com/", (5,), ("知乎直答", "zhida.zhihu"), login="SOMETIMES"),
    spec("yunzhan", "云展网", "https://www.yunzhan365.com/", (41,), ("云展网", "yunzhan365"), login="SOMETIMES"),
    spec("wenjuanxing", "问卷星", "https://www.wjx.cn/", (38,), ("问卷星", "wjx.cn"), login="SOMETIMES"),
    spec("yuketang", "雨课堂", "https://www.yuketang.cn/", (39,), ("雨课堂", "yuketang"), login="SOMETIMES"),
    spec("qq", "QQ", "https://im.qq.com/", (40,), ("qq软件", "qq截图", "qq.com"), login="SOMETIMES"),
    spec("qq", "QQ文档", "https://docs.qq.com/", (38, 40), ("docs.qq.com", "腾讯文档"), login="SOMETIMES", kind="deep"),
    spec("zotero", "Zotero", "https://www.zotero.org/", (46,), ("zotero",), login="SOMETIMES"),
    spec("echarts", "ECharts", "https://echarts.apache.org/zh/index.html", (49,), ("echarts",), login="NO", fields=("图表类型", "示例名称", "代码/配置", "数据字段")),
    spec("weiciyun", "微词云", "https://www.weiciyun.com/", (48, 49), ("微词云", "weiciyun"), login="SOMETIMES", manual=True, fields=("文本版本", "分词/停用词", "词频", "词云结果/访问日期")),
    spec("iconfont", "Iconfont", "https://www.iconfont.cn/", (49,), ("iconfont", "图标库"), login="SOMETIMES"),
    spec("hippter", "HIPPTER", "https://www.hippter.com/", (2,), ("hippter", "HIPPTER"), login="NO"),
    spec("yixi", "一席", "https://www.yixi.tv/", (2, 18), ("一席", "yixi.tv"), login="NO"),
    spec("piyao", "中国互联网联合辟谣平台", "https://www.piyao.org.cn/", (13,), ("中国互联网联合辟谣", "piyao.org.cn", "辟谣"), login="NO", fields=("辟谣标题", "来源", "发布日期", "分类/核查结论")),
    spec("party", "共产党员网", "https://www.12371.cn/", (8,), ("共产党员网", "12371.cn"), login="NO"),

    # ------------------------------------------------------------------
    # 用户补充的高频平台与深链接（2026-09-19）
    #
    # 这些是用户实际用过的入口。题目写明平台时直接跳深链接，
    # 不要从首页层层点击，也不要先走搜索引擎。
    # ------------------------------------------------------------------

    # 题目写明 IEEE Xplore 时直接进高级检索页。
    spec("ieee", "IEEE Xplore 高级检索", "https://ieeexplore.ieee.org/search/advanced", (22, 24, 33, 36, 37),
         ("ieee xplore", "ieeexplore", "ieee高级检索"), login="SOMETIMES", kind="deep", route_type="ADVANCED_SEARCH",
         fields=("Document Title", "Author", "Publication Year", "高级字段组合", "检索结果数量", "年份筛选"),
         path=("直接打开 IEEE Xplore Advanced Search", "选择 Document Title / Author / Publication Year 等字段", "填写关键词、年份与布尔组合", "在结果页读取结果数量并按年份筛选"),
         notes="不要从 ieee.org 首页层层点击。IEEE 的截词规则与 PubMed/ScienceDirect 不通用。"),

    spec("cnipa", "国家知识产权局专利检索（常规检索）", "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch", (12,), ("专利检索", "常规检索", "conventionalSearch", "pss-system"), login="SOMETIMES", kind="deep", route_type="DATABASE_ENTRY", prefer_edge=True,
         fields=("专利名称", "申请号", "申请人", "专利类型", "同族", "详览"),
         path=("直接打开常规检索页", "按题目选择专利名称/申请号/申请人/专利类型", "进入详览或同族查看", "记录题目要求字段"),
         notes="具体专利检索题走此入口；不知道入口或需要官方导航时再用 cnipa.gov.cn。"),
    spec("cnipa", "国家知识产权局（官方导航）", "https://www.cnipa.gov.cn/col/col171/index.html", (12,), ("cnipa导航", "col171"), login="NO", route_type="HOME",
         notes="仅在不知道具体入口或需要官方导航时使用；具体检索题优先 conventionalSearch。"),

    spec("nsfc", "国家自然科学基金结题项目", "https://kd.nsfc.cn/finalProjectInit", (25,), ("结题项目", "finalProjectInit", "kd.nsfc"), login="NO", kind="deep", route_type="DATABASE_ENTRY",
         fields=("结题年度", "项目类型", "申请代码", "依托单位", "负责人"),
         path=("直接打开结题项目入口", "按题目填写结题年度、项目类型、申请代码", "填写依托单位或负责人", "读取项目列表与状态"),
         notes="不要从 kd.nsfc.cn 首页重新寻找「信息检索」再进结题项目。"),

    spec("ncpssd", "国家哲学社会科学文献中心", "https://www.ncpssd.org/index", (21, 24, 26), ("ncpssd", "国家哲学社会科学文献中心", "哲社文献中心"), login="NO", route_key="NCPSD_MAIN",
         fields=("期刊", "集刊", "CSSCI来源", "资源筛选"),
         path=("直接打开 NCPSD 首页", "进入期刊或集刊栏目", "按 CSSCI 来源等条件筛选", "记录题目要求字段"),
         notes="这是用户实际可用的入口；若本库中另有同平台域名记录，一并保留，不做无依据删除。"),

    # QUERY_RECIPE：保存表达式与筛选条件，而不只是 URL。同型题只需替换
    # 关键词、字段标记、年份、NOT 条件与 Article type。
    spec("pubmed", "PubMed 检索式配方（CRISPR 示例）",
         "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR%5BTitle%2FAbstract%5D+AND+2017%3A2024%5Bdp%5D+NOT+therapy%5BTitle%5D",
         (21, 26, 32, 33, 36), ("pubmed", "query recipe", "title/abstract", "mesh terms"), login="NO", kind="deep", route_type="QUERY_RECIPE",
         fields=("[Title]", "[Title/Abstract]", "[Author]", "[MeSH Terms]", "Article type 筛选"),
         path=("直接打开该检索式 URL 或在检索框粘贴表达式", "按题目替换关键词、字段标记与年份区间", "在结果页左侧 Filter 设置 Article type 等条件", "读取结果数量与文献列表"),
         query_recipe={
             "expression": "CRISPR[Title/Abstract] AND 2017:2024[dp] NOT therapy[Title]",
             "filters": {"Article type": "Clinical Trial"},
             "fields_used": ["[Title/Abstract]", "[dp]", "[Title]"],
             "replaceable": ["关键词", "字段标记", "年份区间", "NOT 条件", "Article type"],
         },
         notes="主要保存 query expression 与 filters，不只是 URL。PubMed 字段标记不能套用到 CNKI、万方、维普或 ScienceDirect。"),

    spec("wenjuanxing", "问卷星后台（我的问卷）", "https://www.wjx.cn/newwjx/manage/myquestionnaires.aspx", (38,), ("问卷星后台", "我的问卷", "wjx"), login="YES", browser="PUBLIC_PAGE_ONLY", manual=True, kind="deep", route_type="LOGIN_DASHBOARD", prefer_edge=True,
         fields=("问卷设置", "提交答卷控制", "AI创建", "版本功能", "后台菜单"),
         path=("通过用户已登录的 Edge 打开后台", "进入指定问卷的设置或统计", "核对题目要求的菜单与开关", "记录页面字段；未登录转人工"),
         notes="依赖登录态，优先复用用户 Edge Profile。canonical 不含 randomt 参数（该参数已被清洗规则剔除）。"),

    spec("douyin-creator", "抖音创作者中心", "https://creator.douyin.com/creator-micro/creator-count/arithmetic-index", (29, 49), ("抖音创作者中心", "creator.douyin.com", "算术指数"), login="YES", browser="MANUAL_ONLY", manual=True, kind="deep", route_type="LOGIN_DASHBOARD", prefer_edge=True,
         fields=("指数", "创作者数据", "动态平台数据"),
         path=("通过用户已登录的 Edge 打开创作者中心", "进入指数或数据栏目", "按题目选择指标与时间范围", "记录当前值并保存访问日期"),
         notes="依赖登录态，优先 Edge。出现二维码、扫码或手机确认立即转人工，不尝试绕过。"),
]


def canonical_url(value: str) -> str:
    value = html.unescape(text(value)).strip().rstrip(".,;:!?，。；：！？")
    repair_key = value.rstrip("/")
    if repair_key in TRUNCATED_REPAIRS:
        value = TRUNCATED_REPAIRS[repair_key]
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port and not ((parts.scheme.lower() == "http" and parts.port == 80) or (parts.scheme.lower() == "https" and parts.port == 443)):
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, sanitize_query(parts.query), parts.fragment))


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def url_validity(url: str) -> str:
    host = host_of(url)
    if not host:
        return "UNRESOLVED_TOKEN"
    try:
        ipaddress.ip_address(host)
        return "VALID"
    except ValueError:
        return "VALID" if "." in host else "UNRESOLVED_TOKEN"


def extract_from_text(value: str) -> list[str]:
    # Use the shared extractor first, then the stricter token for PDF/HTML
    # output where prose can be glued to the URL without whitespace.
    urls = extract_urls(value)
    urls.extend(URL_TOKEN_RE.findall(html.unescape(value)))
    result: list[str] = []
    for url in urls:
        normalized = canonical_url(url)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def read_training_materials() -> tuple[list[tuple[str, str]], list[str]]:
    entries: list[tuple[str, str]] = []
    errors: list[str] = []
    raw = ROOT / "data" / "raw"
    for path in sorted((raw / "simulation_sets").glob("*.txt")):
        try:
            entries.append((str(path.relative_to(ROOT)).replace("/", "\\"), path.read_text(encoding="utf-8-sig", errors="ignore")))
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
    public_json = raw / "public_knowledge_list_csc2025.json"
    if public_json.exists():
        entries.append((str(public_json.relative_to(ROOT)).replace("/", "\\"), public_json.read_text(encoding="utf-8", errors="ignore")))
    if PdfReader is None:
        errors.append("pypdf 未安装，PDF URL 抽取跳过")
    else:
        for path in sorted((raw / "teacher_training").glob("*.pdf")):
            try:
                content = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
                entries.append((str(path.relative_to(ROOT)).replace("/", "\\"), content))
            except Exception as exc:  # pypdf can reject an individual visual-only file
                errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return entries, errors


def load_question_context(conn: sqlite3.Connection) -> tuple[dict[str, dict], dict[str, list[str]], dict[str, list[str]]]:
    qrows = conn.execute("SELECT id, question_text, answer_explanation, module_id, module_name, source_type FROM questions ORDER BY id").fetchall()
    contexts: dict[str, dict] = {}
    url_qids: dict[str, list[str]] = defaultdict(list)
    host_qids: dict[str, list[str]] = defaultdict(list)
    for row in qrows:
        qid = row["id"]
        if row["source_type"] == "用户提供模拟题整理":
            set_no = qid.split("-")[1] if qid.startswith("SIM26-") else ""
            source_file = f"data\\raw\\simulation_sets\\2026_simulation_set_{int(set_no):02d}.txt" if set_no.isdigit() else ""
        else:
            source_file = "database:questions"
        contexts[qid] = {
            "module_id": text(row["module_id"]),
            "module_name": text(row["module_name"]),
            "source_type": text(row["source_type"]),
            "source_files": [source_file] if source_file else [],
            "haystack": f"{row['question_text'] or ''} {row['answer_explanation'] or ''}".lower(),
        }
        for url in extract_from_text(f"{row['question_text'] or ''} {row['answer_explanation'] or ''}"):
            url_qids[url].append(qid)
            host = host_of(url)
            if host:
                host_qids[host].append(qid)
    return contexts, dict(url_qids), dict(host_qids)


def record_base(entry: dict) -> dict:
    url = canonical_url(entry["url"])
    route_type = entry.get("route_type") or KIND_TO_ROUTE_TYPE.get(entry.get("url_kind", "home"), "DEEP_LINK")
    return {
        "platform_key": entry["platform"],
        "platform": entry["platform"],
        "name": entry["name"],
        "name_aliases": [entry["name"]],
        "url": url,
        "canonical_url": url,
        # deep_link 只在「非首页」时有值：它才是可以直接跳进去的入口。
        "deep_link": url if route_type != "HOME" else "",
        "route_type": route_type,
        "route_key": entry.get("route_key", ""),
        "prefer_edge": bool(entry.get("prefer_edge", False)),
        "module": list(entry.get("module", [])),
        "question_ids": [],
        "source_files": [],
        "requires_login": entry.get("requires_login", "UNKNOWN"),
        "browser_automation": entry.get("browser_automation", "PUBLIC_PAGE_ONLY"),
        "manual_only": bool(entry.get("manual_only", False)),
        "notes": entry.get("notes", ""),
        "entrance": entry.get("entrance", entry["url"]),
        "fields": list(entry.get("fields", [])),
        "operation_path": list(entry.get("operation_path", [])),
        "url_kind": entry.get("url_kind", "home"),
        "url_validity": url_validity(url),
        "match_terms": list(entry.get("terms", [])),
        # QUERY_RECIPE 记录把「表达式 + 筛选条件」也存下来，而不是只存 URL。
        "query_recipe": entry.get("query_recipe") or {},
        "evidence": [],
    }


def infer_platform(url: str) -> tuple[str, str]:
    host = host_of(url)
    names = {
        "csc.xxsuyang.com": ("competition", "AI+信息素养大赛公开入口"),
        "ai.xxsuyang.com": ("competition-training", "AI+公开培训课程"),
        "xxsuyang.com": ("competition-training", "AI+公开培训课程"),
        "github.com": ("github", "GitHub"),
        "docs.github.com": ("github", "GitHub Docs"),
        "paper.xfyun.cn": ("xfyun", "讯飞科研助手"),
        "trendinsight.oceanengine.com": ("oceanengine", "巨量算数"),
        "image.baidu.com": ("baidu-images", "百度图片"),
        "www.baidu.com": ("baidu", "百度"),
        "fz.people.com.cn": ("nssfc", "国家社科基金"),
        "read.nlc.cn": ("nlc", "国家图书馆数字资源"),
        "www.gov.cn": ("gov", "中国政府网"),
        "www.nhc.gov.cn": ("nhc", "国家卫生健康委员会"),
        "credit.acla.org.cn": ("lawyer-credit", "全国律师诚信平台"),
        "www.piyao.org.cn": ("piyao", "中国互联网联合辟谣平台"),
    }
    if host in names:
        return names[host]
    for item in CATALOG:
        if host and host == host_of(item["url"]):
            return item["platform"], item["name"]
    return host or "unknown", host or "未命名公开 URL"


def build_catalog(conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    contexts, url_qids, host_qids = load_question_context(conn)
    material_entries, material_errors = read_training_materials()
    material_urls: dict[str, list[dict]] = defaultdict(list)
    for source_file, content in material_entries:
        for url in extract_from_text(content):
            material_urls[url].append({"source_file": source_file, "kind": "training_material"})

    records_by_key: dict[str, dict] = {}
    for entry in CATALOG:
        record = record_base(entry)
        key = record["url"]
        if key in records_by_key:
            existing = records_by_key[key]
            existing["name_aliases"] = sorted(set(existing["name_aliases"]) | {entry["name"]})
            existing["name"] = " / ".join(existing["name_aliases"])
            existing["module"] = sorted(set(existing["module"]) | set(record["module"]))
            existing["fields"] = list(dict.fromkeys(existing["fields"] + record["fields"]))
            existing["operation_path"] = list(dict.fromkeys(existing["operation_path"] + record["operation_path"]))
            existing["match_terms"] = list(dict.fromkeys(existing.get("match_terms", []) + record["match_terms"]))
            existing["notes"] += "；" + record["notes"]
            continue
        record["evidence"].append({"source": "curated_public_catalogue", "status": "PENDING_HTTP_CHECK"})
        records_by_key[key] = record

    # A question mention associates it with the platform recipe, while a
    # direct URL mention is retained as stronger evidence for that URL.
    for key, record in records_by_key.items():
        host = host_of(key)
        terms = record.get("match_terms", [])
        qids = set(host_qids.get(host, []))
        for qid, context in contexts.items():
            if any(term.lower() in context["haystack"] for term in terms):
                qids.add(qid)
        direct = url_qids.get(key, [])
        qids.update(direct)
        record["question_ids"] = sorted(qids)
        sources = set()
        for qid in record["question_ids"]:
            sources.update(contexts[qid]["source_files"])
        record["source_files"] = sorted(sources)
        modules = set(record["module"])
        modules.update(contexts[qid]["module_id"] for qid in record["question_ids"] if contexts[qid]["module_id"])
        record["module"] = sorted(modules)
        if direct:
            record["evidence"].append({"source": "question_text_or_explanation", "question_ids": sorted(direct), "status": "EXTRACTED"})

    # Every extracted URL gets its own record unless it already equals a
    # curated home/deep link. This prevents losing rare direct detail links.
    for url, evidence in material_urls.items():
        if url in records_by_key:
            record = records_by_key[url]
            record["source_files"] = sorted(set(record["source_files"]) | {item["source_file"] for item in evidence})
            record["evidence"].extend(evidence)
            continue
        platform, name = infer_platform(url)
        qids = sorted(set(url_qids.get(url, [])))
        modules = sorted({contexts[qid]["module_id"] for qid in qids if contexts[qid]["module_id"]})
        extracted_route = "DEEP_LINK" if (urlsplit(url).path not in ("", "/") or urlsplit(url).query or urlsplit(url).fragment) else "HOME"
        record = {
            "platform_key": platform,
            "platform": platform,
            "name": name,
            "name_aliases": [name],
            "url": url,
            "canonical_url": url,
            "deep_link": url if extracted_route != "HOME" else "",
            "route_type": extracted_route,
            "route_key": "",
            "prefer_edge": False,
            "query_recipe": {},
            "module": modules,
            "question_ids": qids,
            "source_files": sorted({item["source_file"] for item in evidence}),
            "requires_login": "UNKNOWN",
            "browser_automation": "PUBLIC_PAGE_ONLY",
            "manual_only": False,
            "notes": "从公开题干、解析或培训资料抽取；本次生成未把 HTTP 状态当作答案事实。",
            "entrance": url,
            "fields": ["题目指定字段", "页面栏目/结果", "直接详情字段"],
            "operation_path": ["打开该直接链接", "按题目给出的关键词、编号或年份定位", "记录页面字段；遇登录/验证码转人工"],
            "url_kind": "deep" if urlsplit(url).path not in ("", "/") or urlsplit(url).query or urlsplit(url).fragment else "home",
            "url_validity": url_validity(url),
            "match_terms": [],
            "evidence": evidence,
        }
        if record["url_validity"] != "VALID":
            record["manual_only"] = True
            record["browser_automation"] = "MANUAL_ONLY"
            record["notes"] += " URL token 未含完整域名，保留作原始抽取记录，不能直接作为可用入口。"
        records_by_key[url] = record

    records = sorted(records_by_key.values(), key=lambda item: (item["platform"], item["name"], item["url"]))
    usable_records = [record for record in records if record["url_validity"] == "VALID"]
    browser_recipes = sum(1 for record in usable_records if not record["manual_only"] and record["browser_automation"] not in {"MANUAL_ONLY", "NOT_RECOMMENDED"})
    manual_recipes = sum(1 for record in records if record["manual_only"] or record["browser_automation"] == "MANUAL_ONLY")
    platforms = sorted({record["platform"] for record in usable_records})
    summary = {
        "question_count": sum(1 for context in contexts.values() if context["source_type"] == "用户提供模拟题整理"),
        "platform_count": len(platforms),
        "platforms": platforms,
        "url_count": len(records),
        "usable_url_count": len(usable_records),
        "unresolved_url_count": sum(1 for record in records if record["url_validity"] != "VALID"),
        "browser_recipes": browser_recipes,
        "manual_recipes": manual_recipes,
        "extracted_url_count": len(material_urls),
        "material_read_errors": material_errors,
    }
    return records, summary


def md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(records: list[dict], summary: dict) -> str:
    lines = [
        "# 官方 URL 知识库与操作路线",
        "",
        f"> 生成时间：{now_iso()}；覆盖用户提供三套模拟题 {summary['question_count']} 道及公开培训材料。",
        "> 证据边界：公开、合法、可追溯；登录、验证码、校园认证、App 限制和动态统计不自动绕过。URL 状态需按题目指定平台现场复核。",
        "",
        "## 使用顺序",
        "",
        "1. 先查本地题库；未命中再打开本表的题目指定入口。",
        "2. 先用页面文本或公开 PDF；必须执行 JavaScript、点菜单或读取动态结果时才用 Browser CLI/Playwright。",
        "3. 每次记录题目要求的字段、筛选条件、结果数量或截图位置；动态值同时记录访问日期。",
        "4. 遇登录、验证码、二维码、校园认证或 App 限制，停止自动化并转人工。",
        "",
        "## 汇总",
        "",
        f"- 平台标识：{summary['platform_count']} 个；URL：{summary['url_count']} 条；可用 URL：{summary['usable_url_count']} 条；其中直接抽取 URL：{summary['extracted_url_count']} 条。",
        f"- 未解析完整的 URL token：{summary['unresolved_url_count']} 条，保留用于回溯，不作为可用入口。",
        f"- Browser Recipes：{summary['browser_recipes']}；Manual Recipes：{summary['manual_recipes']}。",
        "",
        "## URL 与操作配方",
        "",
        "| 平台 | 名称 | 路由类型 | URL | 模块 | 入口/字段/操作路径 | 登录 | Edge优先 | Browser | 人工 | 题号 | 来源文件 |",
        "|---|---|---|---|---|---|---|---|---|---:|---|---|",
    ]
    for record in records:
        route = (
            f"入口：{record['entrance']}；字段：{'、'.join(record['fields'])}；"
            f"路径：{' → '.join(record['operation_path'])}"
        )
        lines.append("| " + " | ".join([
            md_cell(record["platform"]), md_cell(record["name"]),
            md_cell(record.get("route_type", "")), md_cell(record["url"]),
            md_cell("、".join(record["module"]) or "未分类"), md_cell(route),
            md_cell(record["requires_login"]),
            "是" if record.get("prefer_edge") else "否",
            md_cell(record["browser_automation"]),
            "是" if record["manual_only"] else "否",
            md_cell("、".join(record["question_ids"]) or "—"), md_cell("、".join(record["source_files"]) or "目录")
        ]) + " |")

    recipes = [record for record in records if record.get("query_recipe")]
    if recipes:
        lines.extend([
            "",
            "## Query Recipes（检索式配方）",
            "",
            "同型题只替换括号里的可替换项，不要重写整套检索式。",
            "",
        ])
        for record in recipes:
            recipe = record["query_recipe"]
            lines.append(f"### {record['name']}")
            lines.append("")
            lines.append(f"- 平台：{record['platform']}")
            lines.append(f"- 表达式：`{recipe.get('expression', '')}`")
            for key, value in (recipe.get("filters") or {}).items():
                lines.append(f"- 筛选：{key} = {value}")
            fields_used = recipe.get("fields_used") or []
            if fields_used:
                lines.append(f"- 用到字段标记：{'、'.join(fields_used)}")
            replaceable = recipe.get("replaceable") or []
            if replaceable:
                lines.append(f"- 可替换：{'、'.join(replaceable)}")
            lines.append("")

    lines.extend([
        "",
        "## 字段说明",
        "",
        "- `requires_login`：NO、SOMETIMES、YES、UNKNOWN；不代表允许自动登录。",
        "- `browser_automation`：PUBLIC_PAGE_ONLY 表示只可处理公开页面，MANUAL_ONLY 表示必须人工；动态页面仍需按题目选择一次工具并控制超时。",
        "- `route_type`：HOME / ADVANCED_SEARCH / DATABASE_ENTRY / DEEP_LINK / QUERY_RECIPE / LOGIN_DASHBOARD。题目属于某平台时按此直接选入口，不要先走搜索引擎。",
        "- `prefer_edge`：该入口优先通过用户现有 Microsoft Edge 打开（多数依赖登录态）；不默认 Chrome。",
        "- `canonical_url` / `deep_link`：canonical_url 是清洗后的规范地址；deep_link 仅非首页有值，指可直接跳转的入口。",
        "- 查询串清洗：`uid`、`session`、`token`、`randomt` 等敏感参数与 `utm_*`、`spm`、`dialog` 等追踪参数一律不写入本库，也不会出现在任何导出文件中。",
        "- `question_ids`：题目文本或解析直接提及、或按平台关键词关联的本地题库 ID；用户模拟题答案存在 questions.mock_key（verification_status=MOCK_KEY），不是独立核验的官方标准答案。",
        "- `source_files` 和 `evidence`：保留本地相对路径或目录来源，便于回溯；生成器不会静默覆盖冲突答案。",
        "",
    ])
    if summary["material_read_errors"]:
        lines.extend(["## 材料读取提示", ""])
        lines.extend(f"- {item}" for item in summary["material_read_errors"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="从三套模拟题和公开培训材料抽取、去重并生成官方 URL 操作知识库。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--markdown", default=str(MARKDOWN_PATH))
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    records, summary = build_catalog(conn)
    payload = {
        "schema_version": "2.0",
        "generated_at": now_iso(),
        "evidence_policy": "公开、合法、可追溯；不绕过登录、验证码、二维码、校园认证或 App 限制。",
        "runtime_policy": {
            "hard_timeout_seconds": 180,
            "browser_switch_limit": 1,
            "priority": ["local_question_bank", "direct_http_or_page_text", "known_deep_link", "browser_cli", "playwright", "manual"],
        },
        "summary": summary,
        "urls": records,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = Path(args.markdown).resolve()
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_markdown(records, summary), encoding="utf-8")
    print(json.dumps({"status": "generated", "summary": summary, "json": str(output), "markdown": str(markdown)}, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

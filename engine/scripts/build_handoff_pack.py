"""生成省赛淘汰赛交接包。

产出两份文件：

    handoff/question_bank.md   题库（初赛真题 + 150 模拟题 + 公开样题，三段式）+ 网址检索列表
    handoff/handoff.md         架构经验交接（设计哲学与教训，非照抄）

三段式结构（题目部分）：

    1. 题干与选项
    2. 解题操作流程
    3. 解题/查询网址

网址检索列表在文件末尾，去重、分类、人类可读。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, extract_urls, text
from db_schema import connect_db

ROOT = Path(__file__).resolve().parents[1]
OUT_BANK = ROOT / "handoff" / "question_bank.md"
TMP = ROOT / "data" / "tmp" / "allq.json"


# ---------------------------------------------------------------------------
# 初赛真题（2026-09-19 场次）。
#
# 这些题不在本地题库里，来自用户当天口述/截图。三段式结构中的
# 「操作流程」与「网址」由当时的实测过程回填；未能完成的题如实标注。
# ---------------------------------------------------------------------------
EXAM: list[dict] = [
    {
        "no": 1, "type": "单选",
        "q": "使用中国专利公布公告系统的高级查询功能查找公告日在2010.1.1-2025.12.31期间的发明授权文献，申请（专利权）人输入：%汽车股份有限公司，文本名称输入：新能源汽车，以下说法错误的是？（ ）",
        "opts": {
            "A": "通过列表模式，可以统计出能找到150余条相关文献",
            "B": "除了申请（专利权）人字段支持%，文本名称中也能使用%替代字符。",
            "C": "系统默认结果页面呈现方式是列表模式，还可以选择公布模式、附图模式。",
            "D": "使用%表示代替多个字符，可以检索到“中国第一汽车股份有限公司”作为申请（专利权）人。",
        },
        "ans": "（未作答）",
        "flow": "中国专利公布公告系统 → 高级查询 → 专利类型勾选「发明授权」→ 公告日填 2010.01.01 至 2025.12.31 → 申请（专利权）人填 `%汽车股份有限公司` → 名称填 `新能源汽车` → 查询 → 观察①结果总数 ②结果页展示模式切换项 ③`%` 可用的字段范围",
        "urls": ["http://epub.cnipa.gov.cn/", "http://epub.cnipa.gov.cn/gjcx.jsp",
                 "http://epub.cnipa.gov.cn/Article?index=2"],
        "note": "该系统对本会话返回空文档/HTTP 412（WAF），未能实测。`?`代1字符、`%`代多字符；结果有列表/公布/附图三种模式。",
    },
    {
        "no": 2, "type": "单选",
        "q": "“较真AI”是腾讯新闻推出的智能信息查证工具，微信公众号“全民较真-腾讯新闻”内设访问入口。该工具针对查证类问题生成的回复内容，不包含以下哪部分（ ）？",
        "opts": {"A": "查证结论信心评估", "B": "查证过程", "C": "同类流言汇总", "D": "查证结论"},
        "ans": "C",
        "flow": "微信 → 公众号「全民较真-腾讯新闻」→ 内设较真AI入口；或 QQ浏览器 → 新标签页 → Agent中心 → 「较真AI查真假」→ 输入待查证内容 → 观察回复的板块结构（官方为「结论—过程—评估」三段）",
        "urls": ["https://vp.fact.qq.com/", "https://browser.qq.com/"],
        "note": "较真AI 是“结论—过程—评估”三段结构；「同类流言汇总」不在其中。",
    },
    {
        "no": 3, "type": "单选",
        "q": "小恐龙公文排版助手不支持在哪类办公软件中使用？( )",
        "opts": {"A": "Excel", "B": "都不支持", "C": "WPS", "D": "Word"},
        "ans": "A",
        "flow": "查该插件的官方发布页/下载页，看「支持宿主」一栏 ── 发布标题即写作 for Word/WPS；它基于 VSTO，安装后在 Word 或 WPS 菜单栏出现「公文」选项卡",
        "urls": ["https://github.com/xkonglong/gw/releases", "https://www.onlinedown.net/soft/977518.htm"],
        "note": "支持 Word（2007–2019/365）与 WPS（2013–2019，含 WPS365）；不支持 Excel。",
    },
    {
        "no": 4, "type": "单选",
        "q": "度指数提供了多种产品的行业排行，在汽车行业排行的品牌榜单中，2026年6月1日在品牌指数位列第5的是？（ ）",
        "opts": {"A": "奔驰", "B": "大众", "C": "比亚迪", "D": "奥迪"},
        "ans": "A",
        "flow": "百度指数 → 行业排行 → 汽车行业 → 「品牌指数」标签 → 日榜 → 日期切到 2026-06-01 → 读第 5 名\n（接口：POST /insight/brand/queryTradeRank，参数 trade1=8&trade2=1017&channel=index&type=brand&rankType=daily）",
        "urls": ["https://index.baidu.com/v2/rank/index.html?#/industryrank", "https://index.baidu.com/"],
        "note": "⚠️ 该页默认日期下汽车行业显示「暂无数据」，**必须手动指定历史日期**才有结果 —— 只看首页会误判为查不到。2026-06-01 前五：捷达/丰田/大众/比亚迪/奔驰。",
    },
    {
        "no": 5, "type": "单选",
        "q": "下面哪条属于四川大学发布的《四川大学本科教育教学人工智能工具应用规范（试行）》中，第12页第16条内容？（ ）",
        "opts": {
            "A": "在作业、论文、报告、项目结题材料等使用AI工具的，在正式成果的末尾，需添加“AI工具使用声明”",
            "B": "对于可能公开传播和出版发行的课件、慕课、新形态教材等教学成果，其人工智能生成内容的标注应遵守国家《人工智能生成合成内容标识办法》",
            "C": "标注方式可采用脚注、尾注、括号等形式",
            "D": "使用AI工具须做好过程记录",
        },
        "ans": "C",
        "flow": "下载该 PDF 原件 → 该文件是**纯扫描件（18 页，无文字层，pypdf 抽取全为 0 字符）** → 用浏览器渲染第 12 页（页脚印有「—12—」，PDF页码与正文页码一致）→ 读第十六条全文",
        "urls": [
            "http://202.115.54.22/genai/static/wenjian/《四川大学本科教育教学人工智能工具应用规范（试行）》（川大教〔2025〕28号）.pdf",
            "https://lib.scu.edu.cn/genai/home.html",
        ],
        "note": "第16条全文＝「凡是借鉴、参考、引用AI生成或辅助修改的内容…均需明确标注…」＋「**标注方式可采用脚注、尾注、括号等形式**…」。B 选项是**第十七条**（同页不同条），是本题陷阱。本地副本：`data/raw/public_standards/SCU_AI_gongju_guifan_2025.pdf`",
    },
    {
        "no": 6, "type": "单选",
        "q": "根据AI知数分析数据，2024 年长三角城市群（27 个核心城市）GDP 之和约为多少？",
        "opts": {"A": "约30.1万亿元", "B": "约 28.5 万亿元", "C": "约32.5万亿元", "D": "约26.8万亿元"},
        "ans": "B",
        "flow": "AI知数（data.cnki.net/aidata）→ 数据问答 → 输入「2024年长三角城市群27个核心城市GDP之和是多少？」\n⚠️ 需登录（机构账号＋知网个人账号）；无登录态时改用各市 2024 年官方 GDP 加总",
        "urls": ["https://data.cnki.net/aidata", "https://data.stats.gov.cn/"],
        "note": "27城＝上海＋江苏9＋浙江9＋安徽8（含温州）。逐市加总 285,650 亿元 ≈ 28.57 万亿 → B。C(32.5万亿) 是沪苏浙皖三省一市全域的量级，不是27市口径。",
    },
    {
        "no": 7, "type": "单选",
        "q": "武汉大学图书馆网站的资源-数字资源栏目下有一个名为“人工智能资源导航”的专题网页。下列哪个不是这个网页中的内容？（ ）",
        "opts": {"A": "AI介绍", "B": "AI慕课", "C": "国内外AI政策", "D": "国内外AI法律"},
        "ans": "A",
        "flow": "lib.whu.edu.cn → 资源 → 数字资源 → 「人工智能资源导航」（或首页导航直接点该名称）→ 读正文「人工智能资源专题导航分为八个部分」",
        "urls": [
            "https://www.lib.whu.edu.cn/engine2/general/more?t=23126364060671FE6443EE7692587C14902FD36EC2C8788CD27122043762C9EFF31D7EEE361FAA86912CA5C7B79DB9DA",
            "https://www.lib.whu.edu.cn/",
            "https://www.lib.whu.edu.cn/page/902127/show",
        ],
        "note": "八个部分：AI慕课 / AI使用指南和规范 / 国内外AI政策 / 国内外AI法律 / AI宣言和倡议 / AI素养框架 / AI国际会议 / AI组织机构。**无「AI介绍」**。同页浏览量约 48696。",
    },
    {
        "no": 8, "type": "单选",
        "q": "在全国律师执业诚信信息公示平台查询可知，辽宁泰海律师事务所负责人的律师职业证号后两位数为（ ）？",
        "opts": {"A": "25", "B": "68", "C": "43", "D": "51"},
        "ans": "C",
        "flow": "credit.acla.org.cn → 查询主体切到【律师事务所】→ 关键词「辽宁泰海律师事务所」→ 查询 → 进事务所详情 → 看【负责人】栏 → 核对其执业证号后两位\n⚠️ 该站 `/credit/lawFirm` 路径被 WAF 拦截（HTTP 412），实测未能站内完成",
        "urls": ["https://credit.acla.org.cn/", "http://lnlawyers.net/"],
        "note": "负责人＝唐翔宇，执业证号在两个律师协会来源中均以 **43** 结尾（来源为律师协会系统，非题目指定平台）。",
    },
    {
        "no": 9, "type": "单选",
        "q": "利用Mendeley Reference Manager的“search for articles online”功能（tools菜单下）输入检索词“Intrinsic Motivation”然后按引用频次降序，引用频次最高的文献的发表年份是？（ ）",
        "opts": {"A": "2016", "B": "2013", "C": "2009", "D": "2014"},
        "ans": "D（低置信）",
        "flow": "安装 Mendeley Reference Manager 桌面客户端 → 登录 → Tools 菜单 → Search for articles online → 检索框输入 `Intrinsic Motivation` → 点 Citations 列头切为降序 → 读第一条的 Year",
        "urls": ["https://www.mendeley.com/", "https://www.mendeley.com/download-reference-manager/"],
        "note": "⚠️ **这是全场唯一一道必须下载安装桌面软件才能作答的题**。本机未装（已查 Program Files / Program Files (x86) / %LOCALAPPDATA% / 开始菜单均无），我未能验证，D(2014) 是推断：2009–2016 年间标题以 Intrinsic motivation 起头的最高被引是 Cerasoli, Nicklin & Ford (2014), Psychological Bulletin 140(4):980-1008。",
    },
    {
        "no": 10, "type": "单选",
        "q": "国家图书馆主页的文津搜索提供以下哪种服务？",
        "opts": {
            "A": "提供国家图书馆馆藏数字化资源的在线阅读服务。",
            "B": "提供国家图书馆馆藏实体文献资源的检索和借阅服务。",
            "C": "提供国家图书馆馆藏数字化资源的检索服务。",
            "D": "提供国家图书馆自建和外购资源统一的元数据搜索服务。",
        },
        "ans": "D",
        "flow": "nlc.cn 首页 → 资源服务区 → 【文津搜索】→ 进入 find.nlc.cn → 点【帮助】→ 读「什么是『文津』搜索系统」",
        "urls": ["https://www.nlc.cn/web/index.shtml", "http://find.nlc.cn/", "http://find.nlc.cn/show/help"],
        "note": "官方定义原文：「…有效整合了国家图书馆**自建数据和部分已购买了服务的各类数字资源**…提供…**元数据统一式搜索服务**」。B 是「馆藏目录」的服务，两者在首页并列。",
    },
    {
        "no": 11, "type": "单选",
        "q": "在AI工具文心（网页版）中点击“帮我写作”功能，对话框下方的“教育学习”中不包括（ ）。",
        "opts": {"A": "论文", "B": "读书笔记", "C": "评语", "D": "教案设计"},
        "ans": "B",
        "flow": "wenxin.baidu.com → 首页输入框上方点【帮我写作】→ 弹层里切到【教育学习】标签 → 读该分类下的全部条目",
        "urls": ["https://wenxin.baidu.com/"],
        "note": "教育学习 = 作文 / 论文 / 教案设计 / 评语 / 读后感（5项）。**无「读书笔记」**（最接近的是「读后感」）。五大分栏：全部/办公写作/教育学习/创意文案/写作工具。",
    },
    {
        "no": 12, "type": "单选",
        "q": "访问中国国家图书馆官网首页，在顶部导航栏的“资源服务”下拉菜单中，一共包含多少个数字资源库入口？",
        "opts": {"A": "8-10个", "B": "20-25个", "C": "30及以上", "D": "10-15个"},
        "ans": "C（口径风险）",
        "flow": "nlc.cn 首页 → 顶部导航「资源服务」→ 展开下拉 → 提取该 `<li>` 下全部子菜单项并逐个清点（分 5 组）",
        "urls": ["https://www.nlc.cn/web/index.shtml"],
        "note": "实测 5 组共 **30 个叶子入口**（数字资源4 + 资源推荐7 + 知识服务6 + 特殊群体服务3 + 专题资源10）。若把 5 个分组标题也算作条目则 35。⚠️ 若剔除「资源推荐」整组会变成 23 → 答案是 B，**口径是本题唯一风险点**。",
    },
    {
        "no": 13, "type": "多选",
        "q": "在LeapSpace提问：研究主题为“生物质基智能可穿戴柔性传感材料”的英文期刊有哪些？，不会出现的结果有（）",
        "opts": {"A": "参考文献", "B": "更多建议", "C": "适合关注的期刊列表", "D": "期刊的CiteScore"},
        "ans": "D",
        "flow": "sciencedirect.com/leapspace → 登录 Elsevier 账号 → 输入问题 → 观察回复结构",
        "urls": ["https://www.sciencedirect.com/leapspace", "https://www.sciencedirect.com/search"],
        "note": "实测需登录（跳 id.elsevier.com 授权）。以用户当时贴回的回复为准：含 References（54条）、两张期刊表、Confidence level；**无任何 CiteScore 或期刊计量指标**。",
    },
    {
        "no": 14, "type": "单选",
        "q": "在CNKI数据库中，学位论文“CEEMDAN和改进的Transformer模型在碳交易价格预测中的应用”的学科专业是（ ）。",
        "opts": {"A": "信息经济", "B": "计算科学", "C": "应用统计", "D": "电子信息"},
        "ans": "C",
        "flow": "kns.cnki.net/starter/advanced → 主题填完整篇名 → 检索（命中1条）→ 打开文献知网节 → 读【学科专业】字段",
        "urls": ["https://kns.cnki.net/starter/advanced", "https://www.cnki.net/"],
        "note": "著录：纪雪婷 / 重庆大学 / 导师李声杰 / **学科专业＝应用统计（专业学位）** / 分类号 F832.5;X196;F224。⚠️ 结果页左侧的「学科」分组是 CNKI 专辑分类，**不是**学科专业，只看结果页会选错。",
    },
    {
        "no": 15, "type": "单选",
        "q": "在中国知网学位论文数据库查找四川大学博士生学位论文，以下哪位老师研究新媒体的学生最多（论文主题：新媒体）（ ）？",
        "opts": {"A": "陈华明", "B": "操慧", "C": "蒋晓丽", "D": "朱天"},
        "ans": "（未完成）",
        "flow": "CNKI 高级检索 → 文献类型【学位论文】→ 第一行 主题=新媒体 → 加第二行 学位授予单位=四川大学 → 检索 → 结果页左侧展开【导师】分组，对比四人的论文数",
        "urls": ["https://kns.cnki.net/starter/advanced"],
        "note": "⚠️ 本会话 CNKI 检索子系统触发 blockPuzzle 风控（连续3次），未完成。参考：主题=新媒体的学位论文共 38,253 篇；学位授予单位前20为湖南大学(733)/华中师大(638)/河北大学(638)…四川大学不在前20。",
    },
    {
        "no": 16, "type": "单选",
        "q": "在知网中检索文献“RCEP框架下成渝地区区域价值链整体攀升的实现机制研究”，根据国家标准（GB/T 7714-2015），其文献类型标识为（ ）。",
        "opts": {"A": "J", "B": "C", "C": "D", "D": "M"},
        "ans": "D（内容 M）",
        "flow": "① 确认该文献的**出版形态**（这本是**图书**：西南财经大学出版社、ISBN 978-7-5504-6587-9、许彦等著、185页）② 按 GB/T 7714-2015 取对应标识码",
        "urls": ["https://www.cnki.net/", "https://kns.cnki.net/starter/advanced"],
        "note": "🔴 **本次考试错题（#16）**。GB/T 7714 代码：M=普通图书 C=会议录 J=期刊 D=学位论文 N=报纸 S=标准 P=专利。**陷阱：选项字母和选项内容都是字母**（A→J, B→C, C→D, D→M），必须读内容而非按字母位置找。同型题：SIM26-02-018（万方·电气工程，选项 A.C B.B C.D D.J，答案 A），**两道题的「选项C」内容都是「D」**。",
    },
    {
        "no": 17, "type": "单选",
        "q": "在中国执行信息公开网（https://zxgk.court.gov.cn/）查询“石家庄理工职业学院”的被执行信息，案号为（2025）冀0110执887号的立案时间是（）",
        "opts": {"A": "2025年4月8日", "B": "2025年5月8日", "C": "2025年3月18日", "D": "2025年4月7日"},
        "ans": "C",
        "flow": "zxgk.court.gov.cn → 首页红色大按钮【综合查询被执行人】或图标【被执行人信息】→ 输入「石家庄理工职业学院」→ 过验证码 → 查结果中案号 (2025)冀0110执887号 → 读【立案时间】",
        "urls": ["https://zxgk.court.gov.cn/", "https://zxgk.court.gov.cn/gkw/html/zhixing/index.html"],
        "note": "⚠️ 该站查询子页对本会话返回 HTTP 412（WAF 拦截），未站内验证。第三方公告数据：立案日期 **2025-03-18**，立案法院为石家庄高新技术产业开发区人民法院（冀0110）。",
    },
    {
        "no": 18, "type": "单选",
        "q": "优设导航平台“行业视野”栏目有个多个服务内容，以下不属于其服务内容的是？（ ）",
        "opts": {"A": "网易科技", "B": "优设AI情报", "C": "配色导航", "D": "DoNews"},
        "ans": "C",
        "flow": "hao.uisdc.com → 页面中部找到「**行业视野**」栏目 → 读该栏目下的全部条目",
        "urls": ["https://hao.uisdc.com/"],
        "note": "行业视野 12 条：The Verge / 虎嗅网 / 36氪 / W3C官网 / 极客公园 / 爱范儿 / 优设AI情报 / 设计师图书导航 / 雷锋网 / 网易科技 / 腾讯CDC / DoNews。**无「配色导航」** —— 站内有配色栏目但名为「**配色方案**」（内容是 Adobe Color、COLOURlovers 等），与行业视野并列。",
    },
    {
        "no": 19, "type": "单选",
        "q": "在有道云笔记网页版创建流程图，当输入Ctrl+Shift+O时，会呈现什么内容？（ ）",
        "opts": {"A": "图层", "B": "缩略图", "C": "标签", "D": "放大图"},
        "ans": "（未完成）",
        "flow": "note.youdao.com/web/ → 登录 → 新建【流程图】笔记 → 进入编辑器 → 按 Ctrl+Shift+O → 观察出现的内容；或查编辑器内的快捷键说明",
        "urls": ["https://note.youdao.com/web/", "http://note.youdao.com/help-center/advance_shortcuts.html"],
        "note": "⚠️ 网页版强制跳登录，未实测。官方《桌面端快捷键》表中**流程图相关只有 Ctrl+Shift+L**（锁定/解锁页面），全表无 Ctrl+Shift+O —— 但那是桌面端文档，网页版未单列。",
    },
    {
        "no": 20, "type": "单选",
        "q": "在Github平台（https://github.com）查找题名为“microsoft/TypeScript”（严格匹配）的项目，该项目目前共有（ ）个Releases。",
        "opts": {"A": "低于100", "B": "大于200", "C": "151-200", "D": "101-150"},
        "ans": "B",
        "flow": "github.com/microsoft/TypeScript → 点【Releases】页签 → 读底部分页（共 22 页）→ 每页 10 条 → 打开最后一页数实际条数（8 条）→ 21×10+8 = **218**",
        "urls": ["https://github.com/microsoft/TypeScript/releases", "https://api.github.com/repos/microsoft/TypeScript/releases"],
        "note": "⚠️ GitHub API 未认证时返回 403（限流），改数分页更稳。注意区分 **Releases 与 Tags**（两个页签，数量不同）。",
    },
    {
        "no": 21, "type": "多选",
        "q": "在WILEY数据库，查找题名中含有AIGC，且文中包含DEEP SEEK的期刊论文，以下是命中论文作者的有（ ）？",
        "opts": {"A": "Rongrong Xiang", "B": "Shengli Deng", "C": "Ji Chen", "D": "Fan Wang"},
        "ans": "A、B、C、D（全部）",
        "flow": "onlinelibrary.wiley.com 高级检索 → Title 填 `AIGC`，Anywhere 填 `DeepSeek` → 命中论文：Research on Collaborative Governance of AIGC Applications in the DeepSeek Era（DOI 10.1002/pra2.1311）→ 核对其作者名单",
        "urls": ["https://onlinelibrary.wiley.com/", "https://asistdl.onlinelibrary.wiley.com/doi/10.1002/pra2.1311",
                 "https://api.crossref.org/works/10.1002/pra2.1311"],
        "note": "⚠️ Wiley 站内对本会话返回 Cloudflare 挑战，改用 DOI 登记库核验：Crossref 与 Semantic Scholar **两源一致**列出四位作者（Shengli Deng / Fan Wang / Rongrong Xiang / Ji Chen，均武汉大学），Crossref type=`journal-article`。**本题四个选项全对**，而多选规则为「2—4个正确答案」——若判错多半在此。",
    },
    {
        "no": 22, "type": "多选",
        "q": "在“国家社科基金项目数据库”中，关于项目名称为“主要发达国家大数据和人工智能治理的国际比较研究”的表述，正确的有？",
        "opts": {"A": "项目负责人为崔保国", "B": "项目类别为重大项目", "C": "立项时间为2024年", "D": "项目批准号为25&ZD206"},
        "ans": "A、B",
        "flow": "fz.people.com.cn/skygb/sk/index.php/index/index → 项目名称框填完整名称 → 搜索 → 读著录各字段",
        "urls": ["https://fz.people.com.cn/skygb/sk/index.php/index/index"],
        "note": "实际著录：批准号 **25&ZD216**（非 25&ZD20**6**，中间一位被改）、项目类别 **重大项目**、立项时间 **2025-01-01**、负责人 **崔保国**、单位清华大学。**C 差一年（批准号前缀 25 即锚点）、D 是数字对调**。",
    },
    {
        "no": 23, "type": "多选",
        "q": "在万方数据知识服务平台（简称：万方或万方数据库）中检索可知，会议“第十九届固体废物管理与技术国际会议”收录的论文包括（ ）。",
        "opts": {
            "A": "建材行业零废弃物排放技术路线研究",
            "B": "城中村5G网络覆盖创新:多频立体覆盖方案研究",
            "C": "社会共治视域下的危险废弃物风险治理研究",
            "D": "低比例冷添加再生沥青混合料技术研究",
        },
        "ans": "A、C、D",
        "flow": "万方 → 检索会议名称或按会议论文集浏览 → 逐篇核对题名与**母体文献**是否标注该会议",
        "urls": ["https://www.wanfangdata.com.cn/index.html?index=true", "https://s.wanfangdata.com.cn/paper",
                 "https://d.wanfangdata.com.cn/conference/WFHYXW746400"],
        "note": "A、C、D 均见于《第十九届固体废物管理与技术国际会议论文集》（A=`WFHYXW746401`；C=论文集1212-1221页；D=`WFHYXW746400`，A与D编号连号）。B 是通信工程选题，与固废主题无交集。⚠️ 万方站内持续返回滑块验证，本次经会议论文著录记录核验。",
    },
    {
        "no": 24, "type": "多选",
        "q": "人民网推出的“习近平系列重要讲话数据库”（http://jhsjk.people.cn）中，将学习书库划分成多个栏目，包括（ ）。",
        "opts": {"A": "语言典故", "B": "单行本", "C": "治国理政", "D": "著作集"},
        "ans": "A、B、D",
        "flow": "jhsjk.people.cn → 首页【学习书库】→ 查看更多 → 进入「新时代 新经典——学习习近平新时代中国特色社会主义思想重点数字图书专栏」→ 读顶部导航的栏目名",
        "urls": ["http://jhsjk.people.cn/", "http://theory.people.com.cn/GB/68294/427900/index.html"],
        "note": "学习书库 7 个栏目：**著作集 / 单行本 / 论述摘编 / 读本类 / 思想研究、案例选 / 语言典故 / 生活经历**。「治国理政」**不是栏目**，它只作为书名出现（《习近平谈治国理政》第一至五卷）—— 页面上该词出现频率极高，是本题陷阱。",
    },
    {
        "no": 25, "type": "多选",
        "q": "卫健委政务服务平台的“医卫机构查询”板块设有“委业务主管社会组织名录”查询入口，在该入口检索名称包含“学会”的社会组织，检索结果里相关机构的地址包括（ ）。",
        "opts": {"A": "海淀区", "B": "丰台区", "C": "西城区", "D": "朝阳区"},
        "ans": "A、C",
        "flow": "zwfw.nhc.gov.cn → 查信息 → **医卫机构查询** → **委业务主管社会组织名录** → 关键词框输入「学会」→ 提交 → 读 4 条结果的地址所在区",
        "urls": ["https://zwfw.nhc.gov.cn/", "https://zwfw.nhc.gov.cn/cxx/ywjgcx/",
                 "https://zwfw.nhc.gov.cn/cxx/ywjgcx/wywzgshzzml/"],
        "note": "「学会」命中 4 条：中国人口学会（海淀区）、中国水利电力医学科学技术学会（**西城区**）、中国性学会（海淀区）、中国卫生信息与健康医疗大数据学会（海淀区）→ 出现 **海淀区、西城区**。全量 53 条里确有丰台区、朝阳区，但那些是**基金会**不是学会 —— **必须先筛后看**。",
    },
    {
        "no": 26, "type": "多选",
        "q": "在高校毕业生到国际组织实习任职信息服务平台查找岗位信息，下列属于和平与安全领域，接受本科学历，并在亚洲的实习岗位中，截止日期在2026年5月的岗位是哪些？",
        "opts": {"A": "INTERN Drug Control and Crime Prevention", "B": "Political Affairs Intern",
                 "C": "INTERN Public Information", "D": "Political Affairs Officer"},
        "ans": "A、C",
        "flow": "gj.ncss.cn → 岗位信息 → 筛 组织领域=和平与安全 ＋ 工作性质=实习 ＋ 学历要求=本科及以上 ＋ 工作地点=亚洲 → 得到 31 条 → **逐条读截止日期**，取落在 2026-05 的",
        "urls": ["https://gj.ncss.cn/", "https://gj.ncss.cn/job.html"],
        "note": "筛选后 31 条，只有两条截止日期在 2026 年 5 月：INTERN Drug Control and Crime Prevention 与 INTERN Public Information（均为 UNODC / Bangkok / **2026-05-31**）。B 截止 2025-11-14、D 截止 2024-12-06 —— 二者**都在筛选结果里**，只筛不看日期会选错。",
    },
    {
        "no": 27, "type": "多选",
        "q": "在维普网（https://www.cqvip.com/）的高级检索中，检索复旦大学曾晓洋老师指导的博士论文，关于检索结果，以下哪些说法是正确的？",
        "opts": {"A": "2024年指导的论文作者是陶聪", "B": "共收录了9篇博士论文",
                 "C": "论文学科为工学的有9篇", "D": "数据库没有查到2015年的论文"},
        "ans": "（未完成）",
        "flow": "cqvip.com/advancesearch → 文献类型【学位论文】→ 检索项选【导师】填「曾晓洋」＋【学位授予单位】填「复旦大学」→ 检索 → 逐条看学位年度/作者/学科",
        "urls": ["https://www.cqvip.com/advancesearch", "https://www.cqvip.com/"],
        "note": "⚠️ **维普高级检索的字段里没有「导师」也没有「学位授予单位」**（实测字段仅14个：任意字段/主题词/篇关摘/篇名/关键词/摘要/作者/第一作者/作者单位/刊名/中图分类号/学科分类号/DOI/基金），「导师」只在**专业检索**里。另实测：任意字段=曾晓洋 → 765条（含学位论文21篇）；加 AND 复旦大学后学位论文降为 0。",
    },
    {
        "no": 28, "type": "多选",
        "q": "在国家科技图书文献中心（NSTL）门户网站“知识发现”-科技词表，检索“石墨烯（或graphene）”，这个术语名词隶属哪些学科范畴？",
        "opts": {"A": "光学", "B": "药学", "C": "地球科学", "D": "化学"},
        "ans": "B、C、D",
        "flow": "nstl.gov.cn → 知识发现 → **科技词表** → 检索框输入「石墨烯」→ 调 `searchResourcesButton()` 提交 → 命中1条 → 点开词条详情 → 读【范畴】字段",
        "urls": ["https://www.nstl.gov.cn/", "https://www.nstl.gov.cn/stkos.html",
                 "https://www.nstl.gov.cn/stkos_detail.html?id=C018788088"],
        "note": "词条 graphene｜中文名 石墨烯｜释义引自 NASA｜同义词 4 个（Graphene/graphene/Graphenes/coal-based graphene）｜**范畴：化学、药学、地球科学、工程基础科学、通用技术**。**无「光学」**。注意：该站检索按钮是 `<a onclick=\"searchResourcesButton()\">`，需直接调用该函数才能提交。",
    },
    {
        "no": 29, "type": "多选",
        "q": "在搜狗图片页面，输入关键词搜索图片，在结果页面，支持以下哪几种尺寸筛选方式？（ ）",
        "opts": {"A": "超大尺寸", "B": "大尺寸", "C": "小尺寸", "D": "中尺寸"},
        "ans": "B、C、D",
        "flow": "pic.sogou.com → 搜索任意关键词 → 结果页筛选栏展开【全部尺寸】→ 读全部可选项",
        "urls": ["https://pic.sogou.com/"],
        "note": "尺寸档位只有 **大尺寸 / 中尺寸 / 小尺寸**（外加默认的「全部尺寸」）。**无「超大尺寸」**。同排筛选：全部/最新/高清、使用权限、全部颜色。",
    },
    {
        "no": 30, "type": "多选",
        "q": "关于Excel表格转PDF，以下说法正确的有？",
        "opts": {"A": "Excel不能直接转PDF，需要借助第三方工具", "B": "转换后的PDF表格不可编辑",
                 "C": "可以通过“另存为”选择PDF格式", "D": "可以自定义转换的工作表范围"},
        "ans": "B、C、D",
        "flow": "① 文件 → 导出 → 创建 PDF/XPS；或 文件 → 另存为 → 保存类型选 PDF ② 另存为对话框点【选项…】看可发布的范围",
        "urls": [],
        "note": "A 错：Excel **自带**导出 PDF，无需第三方。D 对：另存为 PDF 时点「选项」，可选 全部/所选内容/活动工作表/整个工作簿；也可先用「打印区域」限定。",
    },
    {
        "no": 31, "type": "多选",
        "q": "在Word中，“审阅”选项卡中的功能包括（ ）。",
        "opts": {"A": "选择窗格", "B": "朗读", "C": "拼写和语法", "D": "中文繁简转换"},
        "ans": "B、C、D",
        "flow": "打开 Word → 点【审阅】选项卡 → 逐组核对功能区",
        "urls": [],
        "note": "审阅含：校对（拼写和语法、同义词库、字数统计、**朗读**）、语言、**中文简繁转换**、批注、修订、比较、保护。**「选择窗格」在【开始】→ 编辑 → 选择 → 选择窗格**，不在审阅。",
    },
    {
        "no": 32, "type": "多选",
        "q": "以下哪些快捷键或操作与QQ截图功能直接相关？",
        "opts": {"A": "Ctrl+Alt+A", "B": "Ctrl+Alt+R（录屏）", "C": "点击QQ聊天窗口的“剪刀”图标", "D": "Win + G"},
        "ans": "A、B、C（口径风险）",
        "flow": "QQ 设置 → 热键 查看快捷键；或在聊天窗口悬停「剪刀」图标看弹出说明",
        "urls": [],
        "note": "截图 Ctrl+Alt+A；录屏 Ctrl+Alt+R，且**录屏内嵌在截图工具中**（入口随截图工具栏一同出现），故算直接相关；剪刀图标点击即进截图。**D 是 Windows 游戏栏（Xbox Game Bar）**，与 QQ 无关。⚠️ 若课件把「截图功能」严格限定为静态截图，答案收缩为 A、C。",
    },
    {
        "no": 33, "type": "多选",
        "q": "使用豆包（网页版）的“快速”模式对话，上传文件后，对话框自动提示的提示词策略包括（ ）。",
        "opts": {"A": "生成脑图", "B": "生成讲义", "C": "生成PPT", "D": "详细总结这篇文档内容"},
        "ans": "A、C、D",
        "flow": "doubao.com/chat → 模式选【快速】→ 上传文件 → 看对话框上方自动出现的提示词按钮",
        "urls": ["https://www.doubao.com/chat/"],
        "note": "实测（由用户完成）自动提示为：**生成脑图 / 生成PPT / 详细总结这篇文档内容**。**无「生成讲义」**（讲义属长文档成稿，在「帮我写作」等入口手动触发）。",
    },
    {
        "no": 34, "type": "判断",
        "q": "学习强国平台的视频支持投屏到电视上观看。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "A",
        "flow": "学习强国 APP → 打开任意视频 → 点【全屏】→ 点右上角「投智能电视屏幕」（部分机型为电视图标/TV）→ 选设备",
        "urls": ["https://www.xuexi.cn/", "https://article.xuexi.cn/articles/index.html?art_id=12259272070767191354"],
        "note": "官方文章《“学习强国”视频一键上智能电视》确认支持。前提：手机与电视同一 WiFi。注：**直播视频与百灵短视频**在「全屏投屏」路径下暂不支持（后续版本可经 电视台→看电视 频道投屏）。",
    },
    {
        "no": 35, "type": "判断",
        "q": "在CNKI（中国知网）学术期刊数据库中使用高级检索功能，检索主题为“人工智能”与“医疗”的文献，截止2026年，发文量最多的中国作者是王浩。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "A",
        "flow": "kns.cnki.net/starter/advanced → 文献类型【学术期刊】→ 主题框填 `人工智能*医疗`（`*`＝与）→ 检索 → 结果页左侧【作者】分组 → 切到「中国」栏 → 读榜首",
        "urls": ["https://kns.cnki.net/starter/advanced"],
        "note": "🔑 **关键在运算符**：单框内 `*`=与、`+`=或。用 `+` 会得到 1,800,162 条且榜首变成方鹏骞(400)；用 `*` 得 **15,802 条，中国作者榜首＝王浩(36)**。**用错符号结论直接反转**。",
    },
    {
        "no": 36, "type": "判断",
        "q": "利用微词云平台（https://www.weiciyun.com/）的“文本词频统计”功能对“2026年政府工作报告”全文进行词频统计（默认参数）。其中特征词表中词频最高的是“改革”。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "B",
        "flow": "weiciyun.com → 文本词频统计 → 粘贴 2026 政府工作报告全文 → 默认参数统计 → 读特征词表首位",
        "urls": ["https://www.weiciyun.com/", "https://fenci.weiciyun.com/cn/",
                 "https://www.gov.cn/gongbao/2026/issue_12646/202603/content_7064134.html"],
        "note": "用官方全文实数字频次：**发展 152** > 建设 97 > 推进 80 > 政策 69 > 经济 65 > 加强 64 > 服务 56 > 推动 45 > 提升 42 ≈ 促进 42 > **改革 40**。改革排第 11 左右，**榜首是「发展」**，差距 3.8 倍，分词/停用词设置不足以反转。",
    },
    {
        "no": 37, "type": "判断",
        "q": "爱课程平台中的教材模块，在其中数学物理系列中，共有21本教材。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "A（以用户实数为准）",
        "flow": "icourses.cn/textbook → 顶部标签切到【数学物理】→ 逐页清点教材条目",
        "urls": ["https://www.icourses.cn/textbook"],
        "note": "该分类分 2 页（每页 12 条），用户实际清点为 **21 本**。",
    },
    {
        "no": 38, "type": "判断",
        "q": "在维普网（https://www.cqvip.com）检索标题名称包含“家用电器”的标准，状态为作废的标准数高于4000条。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "B",
        "flow": "cqvip.com/advancesearch → 检索项【标准名称】填「家用电器」→ 文献类型勾【标准】→ 标准状态勾【作废】→ 检索 → 读结果数\n（也可在结果页左侧「标准状态」分面直接勾【作废】收窄）",
        "urls": ["https://www.cqvip.com/advancesearch", "https://www.cqvip.com/"],
        "note": "⚠️ **表单里的「标准状态」必须先勾再点检索**；先检索后勾选不会生效 —— 判据是分面数字之和：现行7933＋作废2690＋即将实施35＝10,658＝页面结果总数，说明状态筛选未生效。宽口径（任意字段）作废仅 **2690**，收窄到标准名称只会更少 → 不可能 >4000。",
    },
    {
        "no": 39, "type": "判断",
        "q": "万方数据知识服务平台（简称：万方、万方数据、万方数据库）依托平台“智研AI+”板块的订阅功能实现文献追踪；在学者订阅设置界面点击“新增学者”，输入多个学者单位时，可用逗号隔开。",
        "opts": {"A": "错误", "B": "正确"},
        "ans": "A",
        "flow": "zhiyan.wanfangdata.com.cn → 登录 → 首页「智能助手提醒」卡片 →【添加订阅】→ 学者订阅 →【新增学者】→ 看「学者单位」输入框的提示文字",
        "urls": ["https://zhiyan.wanfangdata.com.cn/"],
        "note": "弹窗「新增学者订阅」的输入框提示原文：「请输入一个或多个学者单位，用 **;** 号隔开」—— 是**分号**，不是逗号。注：登录后左侧栏**没有独立的「订阅」菜单**，入口在「智能助手提醒」卡片里的「添加订阅」链接。",
    },
    {
        "no": 40, "type": "判断",
        "q": "在剑桥学术数据库中找到名为“Exploring Environmental Violence”的电子书，这本书的第三部分在该库只有1张插图。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "A",
        "flow": "cambridge.org/core 搜索书名 → 打开书目 → 左侧目录点【Part III】→ 切到【Figures】标签页 → 清点插图",
        "urls": [
            "https://www.cambridge.org/core/books/exploring-environmental-violence/7D605CA3FDCCFEF88FD1CFC6AE524CC7",
            "https://www.cambridge.org/core/books/exploring-environmental-violence/environmental-violence-impacts-responses-resistance-and-alternatives/C592D4920D9CD829914CB409FE5EFCB7",
        ],
        "note": "该书 **Open Access**（CC BY-NC-ND 4.0，ISBN 9781009417150，2024-06-06）。Part III 的 Figures 标签页**只有 Figure 16.1**（Graphical representation of materialism, flow…）。",
    },
    {
        "no": 41, "type": "判断",
        "q": "用搜狗高级搜索可以设定检索一周内关于“欧洲天气”的网页。",
        "opts": {"A": "正确", "B": "错误"},
        "ans": "B",
        "flow": "sogou.com 搜索任意词 → 结果页点【设置】→【高级搜索】→ 逐项检查面板字段",
        "urls": ["https://www.sogou.com/advancedsearch.jsp", "https://www.sogou.com/"],
        "note": "高级搜索面板**只有 5 项**：搜索关键词（拆分/不拆分）、站内搜索、搜索词位于（任何地方/标题/正文/网址）、文件格式、**搜索结果排序方式（按相关性/按时间）**。**没有「时间范围」**。\n「一周内」确实存在，但在**结果页快捷筛选条**上（一天内/一周内/一月内/一年内，参数 `tsn=1..4`、`s_from=inttime_week`）。**「按时间排序」≠「限定一周内」** —— 本题考的就是这个区别。",
    },
    {
        "no": 42, "type": "判断",
        "q": "在万方数据知识服务平台中检索可知，名称为“一种双辐照计推测直射辐照比例的方法”的专利，左侧法律状态栏标明“权利质押、保全及解除”字样。",
        "opts": {"A": "错误", "B": "正确"},
        "ans": "B",
        "flow": "万方 → 搜索该专利名 → 打开专利详情 → 读左侧【法律状态】栏",
        "urls": ["https://d.wanfangdata.com.cn/patent/CN111596381B", "https://www.wanfangdata.com.cn/index.html?index=true",
                 "https://patents.google.com/patent/CN111596381A/zh"],
        "note": "该专利（CN111596381B，天合光能）法律状态含 **2024-01-12「专利权质押合同登记的生效、变更及注销」**（登记生效日 2023-12-26，质权人中国银行常州新北支行）→ **确实存在权利质押类条目**。⚠️ 万方著录条目原名是「专利权质押合同登记的生效、变更及注销」，题干用的是类别统称「权利质押、保全及解除」，两者非逐字相同 —— 若抠字面会判错。",
    },
]


def load_bank() -> list[dict]:
    return json.loads(TMP.read_text(encoding="utf-8"))


def fmt_options(opts: dict) -> list[str]:
    return [f"- **{k}.** {v}" for k, v in opts.items() if text(v)]


def render_question(index: int, q: dict, prefix: str = "") -> list[str]:
    label = f"{prefix}-{index}" if prefix else str(index)
    lines = [f"### {label}. [{q['type']}] {q['q']}", ""]
    lines += fmt_options(q["opts"])
    lines += ["", f"**答案**：{q['ans'] or '—'}", ""]
    lines.append(f"**① 操作流程**：{q['flow'] or '—'}")
    if q["urls"]:
        lines.append("")
        lines.append("**② 查询网址**：")
        lines += [f"    {u}" for u in q["urls"]]
    if q.get("note"):
        lines += ["", f"**③ 备注**：{q['note']}"]
    lines.append("")
    return lines


def url_category(u: str) -> str:
    """按 host 归类。顺序敏感：先匹配到的优先，所以具体站点要排前面。"""
    h = re.sub(r"^https?://", "", u).split("/")[0].lower()
    rules = [
        ("大赛官方入口", ("xxsuyang.com", "zxhnzq.com")),
        ("微信公众号", ("mp.weixin.qq.com",)),
        ("开源与模型社区", ("github.com", "githubusercontent.com", "modelscope.cn", "gitee.com",
                      "huggingface.co", "d2l.ai", "tianchi.aliyun.com", "heywhale.com")),
        ("国际组织与国外馆藏", ("unesco.org", "loc.gov", "worldbank.org", "hathitrust.org",
                        "oecd.org", "un.org", "espacenet.com", "epo.org")),
        ("辟谣·思政·政务宣传", ("piyao.org.cn", "12371.cn", "xhsz.news.cn", "news.cn", "people.cn",
                          "theory.people", "fz.people", "jhsjk.people")),
        ("学术数据库（中文）", ("cnki.net", "wanfangdata", "cqvip", "ncpssd", "pubscholar", "nstl.gov",
                          "chaoxing", "citesxs", "citexs")),
        ("学术数据库（外文）", ("sciencedirect", "onlinelibrary.wiley", "asistdl", "ieeexplore", "ieee.org",
                          "dl.acm", "tandfonline", "academic.oup", "arxiv.org", "pubmed", "ncbi.nlm",
                          "cambridge.org", "nature.com", "science.org", "link.springer", "dspace.mit",
                          "libraries.mit", "oalib", "crossref.org", "doi.org", "semanticscholar",
                          "chinaxiv", "medrxiv", "bioone", "eci.elsevier", "elsevier.cn")),
        ("专利与标准", ("cnipa.gov", "patents.google", "uspto.gov", "wipo.int", "samr.gov", "openstd",
                    "std.samr", "epub.cnipa", "sppt.cfsa")),
        ("政府与公共服务", ("gov.cn", "nhc.gov", "nmpa.gov", "stats.gov", "court.gov", "zxgk.court",
                       "nsfc.cn", "chsi.com", "ncss.cn", "gj.ncss", "most.gov", "nppa.gov",
                       "moj.gov", "sac.net.cn", "amac.org.cn", "china-cba.net", "12371")),
        ("图书馆与馆藏", ("nlc.cn", "find.nlc", "read.nlc", "lib.whu", "lib.scu", "icourses", "dportal",
                      "opac.nlc", "wenxianxue")),
        ("学习与课程平台", ("xuexi.cn", "icourse163", "zhihuishu", "smartedu", "xuetangx", "yuketang",
                       "xueyinonline", "ilab-x", "open.163", "aidaxue", "yixi.tv", "d2l")),
        ("文献管理·分析与工具", ("mendeley", "zotero", "note.youdao", "youdao", "weiciyun", "wjx.cn",
                          "yunzhan365", "echarts", "iconfont", "hippter", "processon", "wps.cn",
                          "docs.qq.com", "ima.qq.com")),
        ("AI 工具与平台", ("doubao.com", "wenxin.baidu", "chatglm", "qianwen.com", "xinghuo.xfyun",
                       "n.cn", "zhida.zhihu", "zhihu.com", "kimi", "yuanbao.tencent", "ai-bot.cn",
                       "ascend.developer.huaweicloud", "data.cnki")),
        ("指数·排行·数据", ("index.baidu", "xueshu.baidu", "vp.fact.qq", "image.so.com", "trendinsight",
                       "data.stats", "data.worldbank", "archive.ics.uci")),
        ("导航与搜索", ("hao.uisdc", "sogou.com", "cn.bing", "baidu.com", "google")),
        ("素材与图片", ("unsplash", "pixabay", "pexels", "pngtree", "wallhaven")),
        ("创作者平台", ("creator.douyin", "douyin.com")),
    ]
    for name, keys in rules:
        if any(k in h for k in keys):
            return name
    return ""  # 交给 host 兜底


def build() -> None:
    bank = load_bank()
    sim = [q for q in bank if q["st"] == "用户提供模拟题整理"]
    pub = [q for q in bank if q["st"] != "用户提供模拟题整理"]

    L: list[str] = []
    w = L.append

    w("# 省赛淘汰赛 · 交接题库")
    w("")
    w("> 生成：2026-10-07｜来源：2026 初赛真题（用户提供）+ 150 道模拟题 + 公开样题")
    w("> 每题按三段式整理：**题干与选项 → 操作流程 → 查询网址**；文末附去重分类的网址检索列表。")
    w("")
    w("## 汇总")
    w("")
    w(f"- 初赛真题：**{len(EXAM)} 道**（含未完成题，已如实标注）")
    w(f"- 模拟题：**{len(sim)} 道**")
    w(f"- 公开样题：**{len(pub)} 道**")
    w(f"- **合计 {len(EXAM) + len(sim) + len(pub)} 道**")
    w("")

    w("---")
    w("")
    w("## 第一部分 · 初赛真题（2026-09-19 场次）")
    w("")
    w("> 这 50 道（用户实际发出 40+ 道）是**最贴近省赛形态**的样本：平台真实、需实操、")
    w("> 且已暴露真实失分点。每题的「备注」栏记录了当场踩到的坑。")
    w("")
    for i, q in enumerate(EXAM, 1):
        L.extend(render_question(i, q, "初赛"))

    w("---")
    w("")
    w("## 第二部分 · 模拟题 150 道")
    w("")
    w("> 三套 2026 模拟题，各 20 单选 + 20 多选 + 10 判断。答案来自题源，未官方核验。")
    w("")
    for i, q in enumerate(sim, 1):
        L.extend(render_question(i, {
            "type": q["qtype"], "q": q["qt"], "opts": q["opts"],
            "ans": q["ans"], "flow": q["flow"],
            "urls": q["url"], "note": f"`{q['id']}`｜{q['mid']}",
        }, "模拟"))

    w("---")
    w("")
    w("## 第三部分 · 公开样题")
    w("")
    for i, q in enumerate(pub, 1):
        L.extend(render_question(i, {
            "type": q["qtype"], "q": q["qt"], "opts": q["opts"],
            "ans": q["ans"], "flow": q["flow"],
            "urls": q["url"], "note": f"`{q['id']}`｜{q['mid']}",
        }, "样题"))

    # ---- 网址检索列表 ----
    all_urls: list[str] = []
    for q in EXAM:
        all_urls += q["urls"]
    for q in bank:
        all_urls += q["url"]
    # 补上官方 URL 知识库里的入口
    try:
        for r in json.loads((ROOT / "config" / "official_urls.json").read_text(encoding="utf-8"))["urls"]:
            if r.get("url_validity") == "VALID":
                all_urls.append(r.get("deep_link") or r.get("url", ""))
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    all_urls = [u for u in all_urls if u and u.startswith("http")]
    uniq = sorted(set(all_urls))

    w("---")
    w("")
    w("# 附：网址检索列表（去重后）")
    w("")
    w(f"共 **{len(all_urls)}** 次引用，去重后 **{len(uniq)}** 个网址，按用途分为 {len({url_category(u) for u in uniq})} 类。")
    w("")
    groups: dict[str, list[str]] = defaultdict(list)
    tail: list[str] = []
    for u in uniq:
        cat = url_category(u)
        if cat:
            groups[cat].append(u)
        else:
            tail.append(u)

    for cat in sorted(groups, key=lambda c: (-len(groups[c]), c)):
        w(f"## {cat}（{len(groups[cat])}）")
        w("")
        for u in groups[cat]:
            w(f"- {u}")
        w("")

    if tail:
        byhost: dict[str, list[str]] = defaultdict(list)
        for u in tail:
            byhost[re.sub(r"^https?://", "", u).split("/")[0].lower()].append(u)
        w(f"## 长尾站点（未归入以上分类，{len(tail)} 个 / {len(byhost)} 站）")
        w("")
        w("> 按站点归拢，便于人工判读；多数是样题/培训材料里出现的单次引用。")
        w("")
        for host in sorted(byhost, key=lambda h: (-len(byhost[h]), h)):
            for u in sorted(byhost[host]):
                w(f"- `{host}` — {u}")
        w("")

    OUT_BANK.parent.mkdir(parents=True, exist_ok=True)
    OUT_BANK.write_text("\n".join(L), encoding="utf-8")
    print(f"写出 {OUT_BANK}｜{len(L)} 行｜{len(''.join(L))} 字符")
    print(f"题目：初赛 {len(EXAM)} + 模拟 {len(sim)} + 样题 {len(pub)} = {len(EXAM)+len(sim)+len(pub)}")
    print(f"网址：{len(all_urls)} 次引用 → 去重 {len(uniq)} 个 → {len(groups)} 类")
    for c in sorted(groups, key=lambda c: -len(groups[c])):
        print(f"  {c}: {len(groups[c])}")


if __name__ == "__main__":
    build()

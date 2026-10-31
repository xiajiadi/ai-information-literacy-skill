# 50 模块极速导航（GENERATED_DRAFT）

> ⚠️ **GENERATED_DRAFT**：本表由 `scripts/build_50_module_nav.py` 从 `db/question_bank.sqlite` 的 modules 表 + `config/official_urls.json` + `config/platform_capabilities.json` + `config/platform_entry_status.json` 自动派生，**不是 Controller 已确认的正式版导航**。
>
> 用途：运行时 5 秒内回答「这题属于哪个模块、去哪、用什么入口、有什么坑」。**本表不存放答案**，也不替代题目指定平台的当前核验。
>
> 键约定：只用 `module_id`。旧库 `questions.module_name` 已确认与 `module_id` 冲突（37/248），不得用于分类。

模块 50 个｜有首选平台 37 个｜有深链接 31 个｜实测直达深链接 30 个｜可完全离线判断 6 个

## 极速索引

| M | 模块 | 触发词 | 首选平台 | 备用 | 深链接 | 状态 | 离线 |
|---|---|---|---|---|---|---|---|
| M01 | AI基础知识与伦理规范 | 生成式人工智能服务管理暂行办法、生成式人工智能服务安全基本要求、人工智能拟人化互动服务管理暂行办法、四川大学本科教育教学人工智能工具应用规范（试行） | unesco | — | https://unesdoc.unesco.org/ark:/48223/pf0000393559 | DIRECT | PARTIAL |
| M02 | AI学习资源的获取与利用 | HIPPTER、一席 | — | — | — | UNKNOWN | PARTIAL |
| M03 | 通用AI工具认知与应用 | 智谱清言、豆包、纳米AI、通义千问 | — | — | — | UNKNOWN | PARTIAL |
| M04 | 办公场景下的AI工具 | 智谱清言、豆包、通义千问、QQ | — | — | — | UNKNOWN | PARTIAL |
| M05 | 科研场景下的AI工具 | 知网、CNKI、中国知网、CNKI AI | cnki | sciencedirect | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M06 | 多模态AI工具 | 智谱清言、豆包、通义千问、讯飞星火 | — | — | — | UNKNOWN | PARTIAL |
| M07 | AI开源与开放数据资源的获取与利用 | 智谱清言、GitHub | github | — | — | UNKNOWN | PARTIAL |
| M08 | 思政信息资源 | 习近平系列重要讲话数据库、国家知识产权局、专利检索、CNIPA | cnipa | — | https://pss-system.cponline.cnipa.gov.cn/conventionalSearch | DIRECT | PARTIAL |
| M09 | 开放数据资源 | 国家知识产权局、国家数据、国家统计局 | stats | cnipa | — | UNKNOWN | PARTIAL |
| M10 | 法律信息资源 | 知网、CNKI、中国知网、CNKI法律智库 | cnki | — | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M11 | 标准与商标信息资源 | 商标查询系统、国家标准全文公开、GB/T、标准全文 | standards | cnki、wanfang | https://openstd.samr.gov.cn/ | DIRECT | PARTIAL |
| M12 | 专利和地理标志 | 专利公布公告、专利检索及分析、地理标志产品检索、政务服务 | cnipa | — | https://pss-system.cponline.cnipa.gov.cn/conventionalSearch | DIRECT | PARTIAL |
| M13 | 反诈防骗信息资源 | 中国互联网联合辟谣平台 | — | — | — | UNKNOWN | PARTIAL |
| M14 | 医卫信息查询 | 国家药品监督管理局、国家药监局数据查询 | nmpa | — | — | UNKNOWN | PARTIAL |
| M15 | 文教信息查询 | 课程思政平台、国家智慧教育平台 | — | — | — | UNKNOWN | NO |
| M16 | 证书资格查询 | 全国律师诚信平台、中国证券业协会、Taylor & Francis Online | — | — | — | UNKNOWN | NO |
| M17 | 在线开放课程资源 | 中国大学MOOC、慕课、MOOC、国家智慧教育平台 | icourse163 | — | https://www.icourse163.org/search.htm | DIRECT | YES |
| M18 | 开放平台中的学习资源 | 知网、CNKI、中国知网、一席 | cnki | wanfang | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M19 | 免费电子书 | NCBI、NCBI Bookshelf、Oxford Academic、Oxford Academic Books | — | — | — | UNKNOWN | YES |
| M20 | 国家图书馆免费数字资源 | 中华古籍资源库、国家图书馆、国家图书馆数字资源 | nlc | — | — | UNKNOWN | YES |
| M21 | 期刊论文的检索 | PubMed、MeSH、CNKI、NCBI | pubmed | wanfang、cnki | https://pubmed.ncbi.nlm.nih.gov/advanced/ | DIRECT | PARTIAL |
| M22 | 学术会议论文及会议信息的检索 | IEEE、ACM Digital Library、CNKI、CNKI会议 | ieee | cnki | https://ieeexplore.ieee.org/search/advanced | DIRECT | NO |
| M23 | 学位论文及资源获取 | 知网、CNKI、中国知网、MIT Libraries | cnki | wanfang | https://kns.cnki.net/starter/advanced | DIRECT | NO |
| M24 | OA、预印本及其他免费资源 | IEEE、OA、预印本及其他免费资源、arXiv | ieee | arxiv、ncpssd | https://ieeexplore.ieee.org/search/advanced | DIRECT | NO |
| M25 | 科研项目数据库 | 国家自然科学基金、自然科学基金、CNKI、国家自然科学基金结题项目 | nsfc | cnki | https://kd.nsfc.cn/finalProjectInit | DIRECT | PARTIAL |
| M26 | 学术搜索 | PubMed、MeSH、ACM Digital Library、百度学术 | pubmed | ncpssd | https://pubmed.ncbi.nlm.nih.gov/advanced/ | DIRECT | NO |
| M27 | 图片搜索 | 知网、CNKI、中国知网、CNKI学术图片 | cnki | — | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M28 | 网址导航 | 奎章阁（公开古籍入口）、中华古籍资源库 | nlc | — | — | UNKNOWN | PARTIAL |
| M29 | 网络指数 | 百度指数、抖音创作者中心、微信指数 | baidu-index | — | https://index.baidu.com/ | AUTH | NO |
| M30 | 馆藏查询系统 | 中华古籍资源库、国家图书馆 | nlc | — | — | UNKNOWN | PARTIAL |
| M31 | 高级检索 | IEEE、CNKI、CNKI高级检索、IEEE Xplore | ieee | cnki、nsfc | https://ieeexplore.ieee.org/search/advanced | DIRECT | NO |
| M32 | 布尔逻辑检索 | 知网、CNKI、中国知网、CNKI高级检索 | cnki | pubmed、sciencedirect | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M33 | 截词检索 | IEEE、IEEE Xplore 高级检索、PubMed 检索式配方（CRISPR 示例）、ScienceDirect | ieee | pubmed、sciencedirect | https://ieeexplore.ieee.org/search/advanced | DIRECT | PARTIAL |
| M34 | 精确与模糊匹配 | 精确匹配、知网、CNKI、中国知网 | cnki | pubmed、vip | https://kns.cnki.net/starter/advanced | DIRECT | NO |
| M35 | 结果筛选 | 知网、CNKI、中国知网、ACM Digital Library | cnki | pubmed、vip | https://kns.cnki.net/starter/advanced | DIRECT | NO |
| M36 | 字段限制检索 | 知网、CNKI、中国知网、CNKI高级检索 | cnki | vip、ieee | https://kns.cnki.net/starter/advanced | DIRECT | PARTIAL |
| M37 | 搜索引擎的检索语法和高级搜索 | IEEE、IEEE Xplore 高级检索 | ieee | — | https://ieeexplore.ieee.org/search/advanced | DIRECT | PARTIAL |
| M38 | 思维导图、笔记软件、问卷调查 | 思维导图、笔记软件、问卷调查、QQ文档 | wenjuanxing | — | https://www.wjx.cn/newwjx/manage/myquestionnaires.aspx | DIRECT | PARTIAL |
| M39 | OFFICE插件和浏览器插件 | 微词云、雨课堂 | — | — | — | UNKNOWN | NO |
| M40 | 截图与录屏 | QQ、QQ文档 | — | — | — | UNKNOWN | PARTIAL |
| M41 | PDF文件处理 | 知网、CNKI、中国知网、MIT Libraries | cnki | — | https://kns.cnki.net/starter/advanced | DIRECT | NO |
| M42 | 学术评价与投稿选刊 | 知网、CNKI、中国知网、百度学术 | cnki | wanfang、sciencedirect | https://kns.cnki.net/starter/advanced | DIRECT | YES |
| M43 | 学术伦理 | 学术出版规范 期刊学术不端行为界定、高等学校预防与处理学术不端行为办法、负责任研究行为规范指引（2023）、国家标准全文公开 | standards | cnki | https://openstd.samr.gov.cn/ | DIRECT | YES |
| M44 | 参考文献著录格式 | 知网、CNKI、中国知网、百度学术 | cnki | vip、wanfang | https://kns.cnki.net/starter/advanced | DIRECT | NO |
| M45 | 论文排版 | — | — | — | — | UNKNOWN | PARTIAL |
| M46 | 文献管理工具 | 知网、CNKI、中国知网、百度学术 | cnki | — | https://kns.cnki.net/starter/advanced | DIRECT | YES |
| M47 | 文献追踪工具 | 万方、CNKI、PubMed、万方数据 / 万方标准 | wanfang | cnki、pubmed | https://s.wanfangdata.com.cn/paper | DIRECT | NO |
| M48 | 数据处理工具 | 微词云 | — | — | — | UNKNOWN | PARTIAL |
| M49 | 数据可视化工具 | 豆包、抖音创作者中心、ECharts、Iconfont | — | — | — | UNKNOWN | NO |
| M50 | 文献可视化工具 | 知网、CNKI、中国知网、CNKI AI | cnki | vip、wanfang | https://kns.cnki.net/starter/advanced | DIRECT | NO |

离线列含义：`YES` = 静态知识，可离线直接判断（但按纪律只能标 🟡 MODEL_REASONING，除非引用到标准/法规原文）；`PARTIAL` = 界面可能改版；`NO` = 动态值，必须实时核验。

## 模块详情

### M01 AI基础知识与伦理规范

- module_id：`知识模块01`｜大类：AI素养
- 首选平台：unesco（UNESCO Digital Library）｜备用：—
- 深链接：https://unesdoc.unesco.org/ark:/48223/pf0000393559（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：AI基础知识与伦理规范、生成式人工智能服务管理暂行办法、生成式人工智能服务安全基本要求、人工智能拟人化互动服务管理暂行办法、四川大学本科教育教学人工智能工具应用规范（试行）、关于在科研活动中规范使用人工智能技术的诚信提醒、上海交通大学关于在教育教学中使用AI的规范、学术出版中AIGC使用边界指南3.0、人工智能伦理问题建议书、生成式人工智能 教育与研究应用指南、学生人工智能能力框架、教师人工智能能力框架、欧盟人工智能法、UNESCO
- 可用字段：ARK 编号、题名、作者、DOI、ISBN、页数、语言、出版年份
- 典型操作：
  1. 学习并了解AI特别是生成式AI的相关知识。
  2. 获取以上与AI相关的法律法规和规范性文件全文，并能从中找出指定细节。
  3. 探索：在《生成式人工智能服务安全基本要求》中，查找文件对语料安全、模型安全、安全措施和安全评估提出了哪些要求。
  4. 探索：阅读《人工智能拟人化互动服务管理暂行办法》，了解其适用范围，以及智能客服、知识问答、工作助手、学习教育、科学研究等服务在何种情况下不适用该办法。
- 主要陷阱：
  - SPA 异步渲染，打开后需等 3-5 秒再读
  - PDF 真实文件名带语言后缀（chi/eng/fre/...），不是固定值
  - ark .../PDF/xxx.pdf 返回的是 SPA 外壳 HTML，不是 PDF
  - 下载端点脱离浏览器返回 403
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M02 AI学习资源的获取与利用

- module_id：`知识模块02`｜大类：AI素养
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：AI学习资源的获取与利用、HIPPTER、一席
- 典型操作：
  1. 熟悉要求的网站，能从中找到指定资源
  2. 把相关网址放到收藏夹
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M03 通用AI工具认知与应用

- module_id：`知识模块03`｜大类：AI素养
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：通用AI工具认知与应用、智谱清言、豆包、纳米AI、通义千问、讯飞星火
- 典型操作：
  1. 把上述AI工具的网址放入浏览器收藏夹，安装APP，有浏览器插件的安装插件。
  2. 登录这些AI工具，深度使用。
  3. 注意部分 AI 工具会根据产品升级调整名称、入口和功能，备赛时应以平台官网和APP 中实际显示的功能为准。
- 主要陷阱：
  - 3.注意部分 AI 工具会根据产品升级调整名称、入口和功能，备赛时应以平台官网和APP 中实际显示的功能为准。
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M04 办公场景下的AI工具

- module_id：`知识模块04`｜大类：AI素养
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：办公场景下的AI工具、智谱清言、豆包、通义千问、QQ
- 典型操作：
  1. 收藏相关网站，安装相关APP。
  2. 深度使用要求的功能。
  3. 只关注免费功能。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M05 科研场景下的AI工具

- module_id：`知识模块05`｜大类：AI素养
- 首选平台：cnki（CNKI 中国知网）｜备用：sciencedirect
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：科研场景下的AI工具、知网、CNKI、中国知网、CNKI AI、CNKI法律智库、豆包
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 收藏网址，注册账号。
  2. 深度使用这几个AI工具。
  3. 探索：使用CNKI AI，利用学术趋势功能，分析近十年发文趋势；输入研究方向，让AI生成文献综述；找到对比分析功能，梳理多篇文献研究方法、结论和创新点，输出对比表格；在学习研读过程中，摘录10条笔记，在辅助创作模块搜索、引用。
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M06 多模态AI工具

- module_id：`知识模块06`｜大类：AI素养
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：多模态AI工具、智谱清言、豆包、通义千问、讯飞星火
- 典型操作：
  1. 收藏网址，注册账号。
  2. 深度使用这几个AI工具及相关多模态功能。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M07 AI开源与开放数据资源的获取与利用

- module_id：`知识模块07`｜大类：AI素养
- 首选平台：github（github.com）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：AI开源与开放数据资源的获取与利用、智谱清言、GitHub
- 典型操作：
  1. 收藏网址，注册账号，若遇到个别网址打不开，可更换浏览器试一下。
  2. 在 GitHub、ModelScope、百度AI Studio飞桨星河社区中分别查找一个AI开源项目、模型或数据集，重点查看资源简介、README 文件、许可证信息、下载入口和使用说明。
  3. 在HeyWhale、阿里云天池、DataFountain、OpenDataLab、OpenML、UCI Machine Learning Repository（Classic 版、Beta 版）中分别查找一个开放数据集，重点查看数据集名称、数据类型、文件格式、样本数量、下载方式和使用限制。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M08 思政信息资源

- module_id：`知识模块08`｜大类：政府开放信息
- 首选平台：cnipa（国家知识产权局）｜备用：—
- 深链接：https://pss-system.cponline.cnipa.gov.cn/conventionalSearch（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：思政信息资源、习近平系列重要讲话数据库、国家知识产权局、专利检索、CNIPA、国家知识产权局专利检索、国家知识产权局专利检索（常规检索）、课程思政平台
- 可用字段：申请号、专利名称、申请人、专利类型、同族、技术领域、附图
- 典型操作：
  1. 根据学习要求中提供的网址，进入相关网站，深度体验、探索，熟悉这些网站中的内容。。
  2. 比赛之前，建议把这些网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
  3. 探索：习近平总书记在哪些场合提到过“数字素养与技能”？
  4. 探索：共产党员网中有哪些可以下载mp4格式视频的党建学习资源？
  5. 探索：在全国高校课程思政教学资源服务平台中找一门国家级课程思政示范课程。
- 主要陷阱：
  - 同名专利歧义大，申请号优先于名称
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M09 开放数据资源

- module_id：`知识模块09`｜大类：政府开放信息
- 首选平台：stats（国家统计局）｜备用：cnipa
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：开放数据资源、国家知识产权局、国家数据、国家统计局
- 典型操作：
  1. 根据学习要求中提供的网址，深度体验、探索，熟悉这些网站的内容。
  2. 探索：能够获取的最近一年的《海南统计年鉴》共有多少页？各省市统计年鉴一般可以在对应地方政府统计局网站中找到，虽然每个网站的界面不一样，但统计年鉴存放的位置一般比较明显，大部分可以在首页中找到。
  3. 探索：能不能找到深圳市公共厕所的相关数据集？各地方政府的开放数据平台，最好能够获取其中的数据集（xlsx、csv、rdf、xml等格式文件）。
  4. 探索：在世界银行的开放数据平台中对比我国和美国、日本、德国的GDP数据。
  5. 探索：在科学数据银行 ScienceDB 中查找一个科学数据集，查看其题名、作者、发布时间、DOI 或 CSTR、数据文件和下载方式。
  6. AI知数需要账号登录，建议提前注册认证。使用时应注意指标名称、数据来源、统计口径、年份范围和地区范围，避免因口径不同导致分析结果不一致。
- 主要陷阱：
  - 1.能够通过国家统计局网站上的数据查询系统（https://data.stats.gov.cn/dg/website/page.html#/pc/national/home，可能会有风险提示，忽略即可）查询统计数据。
  - 6.AI知数需要账号登录，建议提前注册认证。使用时应注意指标名称、数据来源、统计口径、年份范围和地区范围，避免因口径不同导致分析结果不一致。
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M10 法律信息资源

- module_id：`知识模块10`｜大类：政府开放信息
- 首选平台：cnki（CNKI 中国知网）｜备用：—
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：法律信息资源、知网、CNKI、中国知网、CNKI法律智库
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 根据学习要求中提供的网址，深度体验、探索，熟悉这些网站中的内容。
  2. 探索：在中国法律知识资源总库检索哪些法律法规中出现了“人工智能”这个词，以及如何通过关键词、案由、案情、裁判文书查询类案，分析类案。
  3. 探索：看哪个法律法规中出现了“共享单车”这个词？
  4. 探索：涉及本校的判决书有哪些？必须要看到完整全文哦。
  5. 探索：在中国执行信息网（http://zxgk.court.gov.cn）查询被执行人、失信被执行人、限制消费人员，看看“张三”这个名字是否能查得到？能否找到相关详情？
  6. 比赛之前，建议把上述网址放到浏览器收藏夹中，并作出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 4.探索：涉及本校的判决书有哪些？必须要看到完整全文哦。
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M11 标准与商标信息资源

- module_id：`知识模块11`｜大类：政府开放信息
- 首选平台：standards（国家标准）｜备用：cnki、wanfang
- 深链接：https://openstd.samr.gov.cn/（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：标准与商标信息资源、商标查询系统、国家标准全文公开、GB/T、标准全文、CNKI、全国标准信息公共服务平台、全国标准信息标准详情、国家标准全文公开系统、万方数据 / 万方标准
- 可用字段：标准号、标准名称、起草单位、实施日期
- 典型操作：
  1. 探索：某一个标准PDF全文倒数第2页最后一个字是什么？给定一个标准，能够找到并获取全文。
  2. 探索：注册登录商标查询系统，从中查询某一个公司注册的商标并获取细节。
  3. 比赛之前，建议把相关网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
  4. 根据学习要求中提供的网址，进入相关网址，深度体验、探索，熟悉这些网站中的内容。
- 主要陷阱：
  - openstd.samr.gov.cn 是「国家标准全文公开系统」，registration 路由与 std.samr.gov.cn 不同
  - 标准正文 PDF 可能是扫描件（无文字层），必须浏览器渲染后目视读取
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M12 专利和地理标志

- module_id：`知识模块12`｜大类：政府开放信息
- 首选平台：cnipa（国家知识产权局）｜备用：—
- 深链接：https://pss-system.cponline.cnipa.gov.cn/conventionalSearch（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：专利和地理标志、专利公布公告、专利检索及分析、地理标志产品检索、政务服务、地理标志、国家知识产权局、专利检索、CNIPA、国家知识产权局专利检索、国家知识产权局专利检索（常规检索）、国家知识产权局（官方导航）、Oxford Academic
- 可用字段：申请号、专利名称、申请人、专利类型、同族、技术领域、附图
- 典型操作：
  1. “专利检索及分析”这个平台需要注册账号，建议先注册号账号并登陆。注册账号是免费的。
  2. 探索：在国家知识产权局旗下的中国专利公布公告、专利检索及分析系统，以及PPUBS、espacenet、patentscope、cnki、万方、维普查找最近3年华为公司申请的专利。
  3. 根据学习要求中提供的网址，进入相关网址，深度探索，熟悉这些网站中的内容。
  4. 比赛之前，建议通过
- 主要陷阱：
  - 同名专利歧义大，申请号优先于名称
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M13 反诈防骗信息资源

- module_id：`知识模块13`｜大类：政府开放信息
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：反诈防骗信息资源、中国互联网联合辟谣平台
- 典型操作：
  1. 安装国家反诈中心APP，深度体验其中的主要功能。
  2. 进入中国互联网联合辟谣平台实质性探索。
  3. 在微信中搜索“辟谣”，查看相关公众号和小程序。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M14 医卫信息查询

- module_id：`知识模块14`｜大类：政府开放信息
- 首选平台：nmpa（国家药品监督管理局）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：医卫信息查询、国家药品监督管理局、国家药监局数据查询
- 典型操作：
  1. 根据学习要求中提供的网址，进入相关网站，深度体验、探索，熟悉这些网站中的内容。
  2. 探索：分别查询一项药品、化妆品、医疗器械的信息。
  3. 探索：找一位知名的医生，看能否查到他/她的执业资格证书编号？
  4. 探索：利用CHKD AI的AI增强检索和AI辅助分析全面准确获取某一领域的文献，并进行批量文献分析和总结，利用AI智能伴读对多篇文献进行对比分析功能，梳理文献研究方法、结论和创新点，利用AI知识问答查询某个疾病的治疗方案、护理方案等。
  5. 比赛之前，建议把上述网址放到浏览器收藏夹中，并作出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M15 文教信息查询

- module_id：`知识模块15`｜大类：政府开放信息
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：文教信息查询、课程思政平台、国家智慧教育平台
- 典型操作：
  1. 根据学习要求中提供的网址，进入相关网址，深度体验、探索，熟悉这些网站中的内容。
  2. 探索：在研招网中查询哪个“双一流”建设高校有图书馆学专业的硕士点和博士点，并且接受退役大学生士兵专项计划考生报考？
  3. 探索：在国家大学生就业服务平台找工作地点在杭州的小学教师的岗位。
  4. 探索：在高校毕业生到国际组织实习任职信息服务平台中查询适合自己的职位。
  5. 探索：在全国大学生创业服务网中找投资人。
  6. 比赛之前，建议把这几个网址放到浏览器收藏夹中，并作出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M16 证书资格查询

- module_id：`知识模块16`｜大类：政府开放信息
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：证书资格查询、全国律师诚信平台、中国证券业协会、Taylor & Francis Online
- 典型操作：
  1. 收藏网址，深度体验、探索。
  2. 探索：想办法找到真实的毕业证和学位证，在学信网中实质性查询验证。
  3. 探索：查名为“黄一军”的证券从业人员的从业资格信息。
  4. 探索：查询名为“李成蹊”的律师的执业信息，请问结果有几人？分别在哪个律师事务所？证书编号的后两位是？
  5. 探索：查询北信瑞丰基金管理有限公司的基金从业人员有多少人？任选其中的一个给出从业资格证书编号。
  6. 探索：在电视、报纸上找一位记者，在中国记者网中查询ta的记者证信息。
- 主要陷阱：
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M17 在线开放课程资源

- module_id：`知识模块17`｜大类：实用学习资源
- 首选平台：icourse163（中国大学MOOC）｜备用：—
- 深链接：https://www.icourse163.org/search.htm（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：STATIC｜需登录：SOMETIMES｜可否离线：YES
- 触发词：在线开放课程资源、中国大学MOOC、慕课、MOOC、国家智慧教育平台、雨课堂、智慧树
- 可用字段：课程名称、学校、教师
- 典型操作：
  1. 登录这些平台，或者安装相应的APP，找一门课程，看视频，做题目，深度体验。
  2. 比赛之前，建议把相关网址放到浏览器收藏夹中，并做出明确标识，或者安装相应的APP，方便比赛时直接打开使用。
  3. 探索：哪个课程平台中有“大学语文”课程，这些课程的第二节各有几个视频？其中的第一个视频第3分56秒画面上是什么内容？
- 主要陷阱：
  - 同名课程必须按学校+教师核对
  - 点击课程后的详情在新标签页打开
  - 不要 Google 课程答案

### M18 开放平台中的学习资源

- module_id：`知识模块18`｜大类：实用学习资源
- 首选平台：cnki（CNKI 中国知网）｜备用：wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：开放平台中的学习资源、知网、CNKI、中国知网、一席、智慧树
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 登录这些平台，或者安装相应的APP，找一些学习资源，看视频，深度体验。
  2. 比赛之前，建议把这几个网址放到浏览器收藏夹中，并作出明确标识，或者安装相应的APP，方便比赛时直接打开使用。
  3. 探索：在高校信息素养教育数据库的直播讲座栏目中找到2025年信息素养公益大讲堂第六期第四讲的讲座，请问这个讲座的时长是多少？提醒：这个栏目可以免费访问。
  4. 探索：在一席、TED中分别找一个指定演讲，截取4分28秒的界面。
  5. 探索：在知乎中查找有关EXCEL函数的高赞回答。
  6. 探索：在和鲸社区 HeyWhale 中查找一个数据科学学习项目或实战训练营，查看其名称、学习主题、内容简介和参与方式。
- 主要陷阱：
  - 答案解析：百度一下，找到这个数据库的官网；选择“直播讲座”栏目。（如果不在校园网内，可能会有登录提示，选择“不登录”即可，这个公益讲座是开放的）；选择“公益大讲堂”栏目，找到课程；播放视频，看进度条。
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M19 免费电子书

- module_id：`知识模块19`｜大类：实用学习资源
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：STATIC｜需登录：SOMETIMES｜可否离线：YES
- 触发词：免费电子书、NCBI、NCBI Bookshelf、Oxford Academic、Oxford Academic Books
- 典型操作：
  1. 登录这几个平台，查找具体图书，一定要能获取到全文。
  2. 比赛题目很大可能性是让你在这些平台中找具体一本书，然后问你这本书的一些细节。
  3. 比赛之前，建议把这几个网址放到浏览器收藏夹中，并作出明确标识，方便比赛时直接打开使用。
  4. 探索：在剑桥数据库中找到名为《Data Management for Social Scientists》的电子书，获取第24页的全文。
- 主要陷阱：
  - 2.比赛题目很大可能性是让你在这些平台中找具体一本书，然后问你这本书的一些细节。

### M20 国家图书馆免费数字资源

- module_id：`知识模块20`｜大类：实用学习资源
- 首选平台：nlc（国家图书馆）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：STATIC｜需登录：SOMETIMES｜可否离线：YES
- 触发词：国家图书馆免费数字资源、中华古籍资源库、国家图书馆、国家图书馆数字资源
- 典型操作：
  1. 收藏网址，方便比赛时直接打开。
  2. 我国国家图书馆的多数数字资源可以免费获取，注册登录后可以获取更多。（提醒：注册免费，通过“读者门户登录注册”入口注册）。
  3. 美国国会图书馆，首页右上角有搜索区，可选择文献类型并输入关键词。
- 主要陷阱：
  - 未实测到具体陷阱；按平台当前显示核对，不要凭记忆。

### M21 期刊论文的检索

- module_id：`知识模块21`｜大类：学术信息资源
- 首选平台：pubmed（PubMed）｜备用：wanfang、cnki、ncpssd、sciencedirect
- 深链接：https://pubmed.ncbi.nlm.nih.gov/advanced/（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：期刊论文的检索、PubMed、MeSH、CNKI、NCBI、NCBI Bookshelf、国家哲学社会科学文献中心、Oxford Academic
- 可用字段：Title、Title/Abstract、Author、MeSH Terms、Journal、Date - Publication
- 典型操作：
  1. 去这些资源系统中，实质性检索并获取全文。
  2. LeapSpace：需要账号登录，建议提前注册认证。
  3. 除了LeapSpace，这几个系统检索是免费的；除了LeapSpace其他几个外文系统，不但检索免费，而且能获取部分（OA）全文。LeapSpace开通后，参赛期间免费，且也能获取部分（OA）全文。
  4. CNS三大国际顶级学术期刊的官网不仅可以检索现刊，而且可以检索过刊。
  5. 探索：《图书馆众筹研究》这篇论文在CNKI、万方、维普中都能找到吗？
  6. 探索：《Determining and assessing characteristics of data element names impacting the performance of annotation using Usagi》这篇文章在ScienceDirect、Wiley、Taylor&Francis、ACM数据库中都能找到吗？
- 主要陷阱：
  - 字段标记与截词规则不能套用到 CNKI / 万方 / 维普 / ScienceDirect
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M22 学术会议论文及会议信息的检索

- module_id：`知识模块22`｜大类：学术信息资源
- 首选平台：ieee（IEEE Xplore）｜备用：cnki
- 深链接：https://ieeexplore.ieee.org/search/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：学术会议论文及会议信息的检索、IEEE、ACM Digital Library、CNKI、CNKI会议、IEEE Xplore
- 可用字段：Document Title、Author、Publication Year、Author Affiliations、Publication Title、Abstract、Index Terms
- 典型操作：
  1. 深度体验CNKI、万方的会议论文数据库，这两个数据库，检索是免费的。
  2. 探索：进入IEEE官网的会议栏目，动手查找“人工智能”方面的会议信息。
  3. 探索：从CNKI中国学术会议网中查找最近3个月的会议。
  4. 探索：《数字时代背景下体育教师教学推进路径研究》这篇会议论文，在CNKI、万方、维普都能找到吗？
- 主要陷阱：
  - 首页 ieee.org 不是正确入口，必须走 /search/advanced
  - wildcard 语法不得复制到其他平台
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M23 学位论文及资源获取

- module_id：`知识模块23`｜大类：学术信息资源
- 首选平台：cnki（CNKI 中国知网）｜备用：wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：学位论文及资源获取、知网、CNKI、中国知网、MIT Libraries、MIT Theses、万方数据 / 万方标准
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. CNKI、万方和维普的学位论文数据库，查询是免费的，无论本校购买与否，都能查询。
  2. 探索：国家图书馆博士论文数据库可以免费检索，检索标题中包含“大数据”的博士学位论文，结果有多少篇？
  3. 探索：MIT Theses可以获取大部分学位论文的全文，查找两篇题目中包含“education”的学位论文，获取全文。
  4. 探索：《 接纳承诺疗法对DR患者心理灵活性及负性情绪的干预研究》这篇硕士学位论文在CNKI、万方、维普都能找到吗？
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M24 OA、预印本及其他免费资源

- module_id：`知识模块24`｜大类：学术信息资源
- 首选平台：ieee（IEEE Xplore）｜备用：arxiv、ncpssd、sciencedirect
- 深链接：https://ieeexplore.ieee.org/search/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：OA、预印本及其他免费资源、IEEE、OA、预印本及其他免费资源、arXiv、IEEE Xplore、IEEE Xplore 高级检索、国家哲学社会科学文献中心、OALib
- 可用字段：Document Title、Author、Publication Year、Author Affiliations、Publication Title、Abstract、Index Terms
- 典型操作：
  1. 深度使用这些系统，至少从每一个系统中找到一篇全文。
  2. 探索：在LeapSpace中通过prompt提问获取10篇包含“AI”的OA论文。
  3. 探索：在arXiv中找到一篇篇名中包含“education”和“big data”的论文全文。
  4. 探索：在ScienceDirect中找一篇篇名中包含“AIGC”的OA论文并获取全文。
  5. 比赛之前，建议把这些网址放到浏览器收藏夹中，并作出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 首页 ieee.org 不是正确入口，必须走 /search/advanced
  - wildcard 语法不得复制到其他平台
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M25 科研项目数据库

- module_id：`知识模块25`｜大类：学术信息资源
- 首选平台：nsfc（国家自然科学基金）｜备用：cnki
- 深链接：https://kd.nsfc.cn/finalProjectInit（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：科研项目数据库、国家自然科学基金、自然科学基金、CNKI、国家自然科学基金结题项目、国家社科基金
- 可用字段：结题年度、资助类型/项目类型、申请代码、依托单位、负责人
- 典型操作：
  1. 深度使用这两个系统。
  2. 探索：在国家社科基金项目数据库中检索本校最近4年的国家社科立项信息和结项信息。
  3. 探索：在国家自然科学基金大数据知识管理服务门户中查找2023年结题的深度学习方面的自科项目成果。
  4. 比赛之前，建议把这些网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 答案解析：登录国家社科基金项目数据库（http://fz.people.com.cn/skygb/sk/index.php/index/index/4541）。在“项目名称”检索点下输入“西南地区族际通婚促进民族文化交融机制研究”，然后搜索。在找到的结果中查看信息。注意，点击右箭头可以看到更多信息，“重庆大学”这个信息，就需要这样查看。
  - 不要从 kd.nsfc.cn 首页重新寻找「信息检索」再进结题项目
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M26 学术搜索

- module_id：`知识模块26`｜大类：信息检索系统
- 首选平台：pubmed（PubMed）｜备用：ncpssd
- 深链接：https://pubmed.ncbi.nlm.nih.gov/advanced/（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：学术搜索、PubMed、MeSH、ACM Digital Library、百度学术、NCBI、NCBI Bookshelf、国家哲学社会科学文献中心
- 可用字段：Title、Title/Abstract、Author、MeSH Terms、Journal、Date - Publication
- 典型操作：
  1. 登录这几个网站，实质性搜索具体文献，深度了解其中的各项功能。
  2. 探索:《创新、企业规模和市场竞争:基于中国企业层面的面板数据分析》这篇文章，在百度学术中能找到吗？能获取全文吗？
  3. 探索：《The role of data science in healthcare advancements: applications, benefits, and future prospects》这篇文章，pubmed给出了哪几种全文获取的链接？
  4. 《Enterotypes of the Human Gut Mycobiome》这篇文章在AMiner中的被引量是多少？
  5. 在pubscholar中，检索字段选择“主题”，检索词输入“人工智能”，能找到多少篇最近3年的OA文献？
- 主要陷阱：
  - 字段标记与截词规则不能套用到 CNKI / 万方 / 维普 / ScienceDirect
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M27 图片搜索

- module_id：`知识模块27`｜大类：信息检索系统
- 首选平台：cnki（CNKI 中国知网）｜备用：—
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：图片搜索、知网、CNKI、中国知网、CNKI学术图片、360图片
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 找到这些图片资源平台，实际使用一下其中的检索系统。
  2. 了解这些图片资源的版权问题。
  3. CNKI学术图片库：需要账号登录，建议提前注册认证。
  4. 探索：百度的图片搜索结果页面中，系统提供了哪些筛选项？
  5. 探索：使用CNKI学术图片库中的图片对比、图片解析功能。
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M28 网址导航

- module_id：`知识模块28`｜大类：信息检索系统
- 首选平台：nlc（国家图书馆）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：SOMETIMES｜可否离线：PARTIAL
- 触发词：网址导航、奎章阁（公开古籍入口）、中华古籍资源库
- 典型操作：
  1. 这些网址导航，打开看看。
  2. 比赛之前，建议把这些网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
  3. 探索：AI工具集的“AI智能体”栏目下收录了哪些AI工具网站？
  4. 探索：中国古典文献资源导航系统有哪些栏目？
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M29 网络指数

- module_id：`知识模块29`｜大类：信息检索系统
- 首选平台：baidu-index（baidu-index）｜备用：—
- 深链接：https://index.baidu.com/（AUTH，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：网络指数、百度指数、抖音创作者中心、微信指数
- 可用字段：关键词、行业、时间范围、地域
- 典型操作：
  1. 微信指数：在微信中直接搜索微信指数即可找到。
  2. 百度指数需要登录，如果没有百度账号请提前免费注册百度账号。赛前建议先登录。
  3. 抖音指数需要登录，如果没有抖音账号请提前免费注册抖音账号。赛前建议先登录。
  4. 深度体验这些网络指数的关键词对比、时间限定等功能。
  5. 探索：在百度指数和抖音指数（原巨量算数）两个平台上，分别对比最近一个月四川大学和重庆大学在陕西省的指数情况。
- 主要陷阱：
  - 默认日期下显示「暂无数据」，必须手动选历史日期
  - 需要登录态
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M30 馆藏查询系统

- module_id：`知识模块30`｜大类：信息检索系统
- 首选平台：nlc（国家图书馆）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：馆藏查询系统、中华古籍资源库、国家图书馆
- 典型操作：
  1. 图书馆的馆藏查询系统，英文名称是：OPAC（Online Public Access Catalog，联机公共目录检索系统）。不同的图书馆，名称可能会有差异，比如馆藏查询、馆藏目录、书目查询、馆藏书目等。有些图书馆官网首页有明显的搜索框。
  2. 通常一个图书馆会提供多种馆藏查询的入口，包括官网、微信公众号、移动图书馆APP。任意选择几个图书馆尝试找到馆藏查询入口并检索文献信息。
  3. 重点关注我国国家图书馆、985大学图书馆、省级公共图书馆、全球排名靠前的国外名校图书馆的馆藏查询系统。
  4. 探索：《一流大学图书馆治理能力现代化的探索与实践》这本书在四川大学图书馆的索书号是？根据这个索书号中包含的中图分类号判断这本书在中国图书馆分类法体系中所在的大类。
- 主要陷阱：
  - 1.图书馆的馆藏查询系统，英文名称是：OPAC（Online Public Access Catalog，联机公共目录检索系统）。不同的图书馆，名称可能会有差异，比如馆藏查询、馆藏目录、书目查询、馆藏书目等。有些图书馆官网首页有明显的搜索框。
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M31 高级检索

- module_id：`知识模块31`｜大类：信息检索理论与技术
- 首选平台：ieee（IEEE Xplore）｜备用：cnki、nsfc、vip、wanfang
- 深链接：https://ieeexplore.ieee.org/search/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：高级检索、IEEE、CNKI、CNKI高级检索、IEEE Xplore、IEEE Xplore 高级检索
- 可用字段：Document Title、Author、Publication Year、Author Affiliations、Publication Title、Abstract、Index Terms
- 典型操作：
  1. 大部分数据库都有高级检索功能，在首页一般有链接。
  2. 进入CNKI、万方、维普、ScienceDirect、Wiley、Taylor&Francis、PubMed、IEEE Xplore等数据库进行检索，实质性体验高级检索功能。
  3. 探索：在CNKI、万方、维普的高级检索界面，选择不同的文献类型，高级检索界面一样吗？
  4. 探索：ScienceDirect、Wiley、Taylor&Francis、PubMed、IEEE Xplore这些数据库的高级检索界面，可以设置哪些检索条件？
- 主要陷阱：
  - 首页 ieee.org 不是正确入口，必须走 /search/advanced
  - wildcard 语法不得复制到其他平台
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M32 布尔逻辑检索

- module_id：`知识模块32`｜大类：信息检索理论与技术
- 首选平台：cnki（CNKI 中国知网）｜备用：pubmed、sciencedirect、wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：布尔逻辑检索、知网、CNKI、中国知网、CNKI高级检索、NCBI、NCBI Bookshelf、PubMed
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 进入CNKI、万方、维普、ScienceDirect、Wiley、Taylor&Francis、PubMed、IEEE Xplore、ACM等中英文数据库，采用布尔逻辑算符进行检索，并对比各数据布尔逻辑算符表示方法的不同。
  2. 比赛之前，建议把这些网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
  3. 检索模式：ADVANCED_FORM / PROFESSIONAL_EXPRESSION
  4. 结果读取位置：结果总数标签；结果页左侧「学科」是专辑分类不是学位论文学科专业，必须进详情页
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M33 截词检索

- module_id：`知识模块33`｜大类：信息检索理论与技术
- 首选平台：ieee（IEEE Xplore）｜备用：pubmed、sciencedirect
- 深链接：https://ieeexplore.ieee.org/search/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：截词检索、IEEE、IEEE Xplore 高级检索、PubMed 检索式配方（CRISPR 示例）、ScienceDirect
- 可用字段：Document Title、Author、Publication Year、Author Affiliations、Publication Title、Abstract、Index Terms
- 典型操作：
  1. 大部分系统，用问号和星号作为截词符，星号可以表示多个字符，问号表示一个字符。但这个并不绝对，有些系统的截词符用的是其他字符，具体看系统的说明。
  2. 中国专利公布公告系统中可以用问号和百分号对检索词进行扩展，虽然不能称为严格意义上的截词检索，但与外文系统中的截词检索比较类似。
  3. 探索：找到上面提到的四个数据库中与截词检索相关的帮助说明，了解具体规则。
  4. 探索：在PubMed的检索框中输入 comput*[title] ，查看检索结果，分析检索结果的标题，看是否实现了截词检索。
  5. 探索：在中国专利公布公告系统的高级查询页面，检索字段选择“申请人”，检索框中输入：中国%大学 ，分析检索结果中的申请人，思考%的作用。
- 主要陷阱：
  - 答案解析：在ACM数据库中，星号代表可能的一个或多个字母，问号代表一个字母，所以，括号中应该是问号。在高级检索中，按照题目中给出的条件设置，找到的结果应该是1327条。
  - 首页 ieee.org 不是正确入口，必须走 /search/advanced
  - wildcard 语法不得复制到其他平台
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M34 精确与模糊匹配

- module_id：`知识模块34`｜大类：信息检索理论与技术
- 首选平台：cnki（CNKI 中国知网）｜备用：pubmed、vip、wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：精确与模糊匹配、精确匹配、知网、CNKI、中国知网、CNKI高级检索、PubMed、PubMed 检索式配方（CRISPR 示例）、Taylor & Francis Online
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 进入CNKI、维普、万方等数据库，试用精确匹配与模糊匹配功能，并对比检索结果的不同。
  2. 探索：在CNKI的高级检索中，通过实践理解精确匹配在不同检索字段（如标题、作者单位）下含义的不同。
  3. 外文数据库，一般用半角双引号实现精确匹配，也就是输入的检索词会被当做词组或者短语处理，不被系统拆分。
  4. 参考各数据库的帮助。
- 主要陷阱：
  - 在CNKI的高级检索中，文献类型选择“学术期刊”，“篇名”和“作者”检索字段进行如图设置，其他条件默认。请问：这样的检索条件，下列哪些论文可能出现在检索结果中？（ ）
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M35 结果筛选

- module_id：`知识模块35`｜大类：信息检索理论与技术
- 首选平台：cnki（CNKI 中国知网）｜备用：pubmed、vip、ieee、standards
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：结果筛选、知网、CNKI、中国知网、ACM Digital Library、CNKI高级检索、IEEE、PubMed
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 结果筛选，一般在检索结果左侧。
  2. 进入CNKI、万方、维普、ScienceDirect、Wiley、Taylor&Francis、PubMed、IEEE Xplore、ACM等中英文数据库试用结果筛选功能。重点关注筛选字段。
  3. 检索模式：ADVANCED_FORM / PROFESSIONAL_EXPRESSION
  4. 结果读取位置：结果总数标签；结果页左侧「学科」是专辑分类不是学位论文学科专业，必须进详情页
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M36 字段限制检索

- module_id：`知识模块36`｜大类：信息检索理论与技术
- 首选平台：cnki（CNKI 中国知网）｜备用：vip、ieee、nlc、pubmed
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：字段限制检索、知网、CNKI、中国知网、CNKI高级检索、IEEE Xplore 高级检索、国家图书馆
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 在CNKI、万方、维普、ScienceDirect、Wiley、Taylor&Francis、PubMed、IEEE Xplore、ACM等数据库的高级检索中动手试一下，看有哪些检索字段。
  2. 探索：找研究“鲁迅”的文章，检索字段应该是？
  3. 比赛之前，建议把这些网址放到浏览器收藏夹中，并做出明确标识，方便比赛时直接打开使用。
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M37 搜索引擎的检索语法和高级搜索

- module_id：`知识模块37`｜大类：信息检索理论与技术
- 首选平台：ieee（IEEE Xplore）｜备用：—
- 深链接：https://ieeexplore.ieee.org/search/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：搜索引擎的检索语法和高级搜索、IEEE、IEEE Xplore 高级检索
- 可用字段：Document Title、Author、Publication Year、Author Affiliations、Publication Title、Abstract、Index Terms
- 典型操作：
  1. 自己动手，找到各搜索引擎的高级检索入口。 在主流搜索引擎中实质性使用filetype、site、inurl等搜索语法。百度的高级检索界面有两个：一个是首页右上角“设置”→“高级搜索”，另一个是：https://www.baidu.com/gaoji/advanced.html。
  2. 深度使用这些高级搜索中的具体功能，对比搜索结果，体会语法规则。
  3. 检索模式：ADVANCED_FORM
  4. 结果读取位置：结果页 Result Count 与年份筛选
- 主要陷阱：
  - 首页 ieee.org 不是正确入口，必须走 /search/advanced
  - wildcard 语法不得复制到其他平台
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M38 思维导图、笔记软件、问卷调查

- module_id：`知识模块38`｜大类：知识管理工具
- 首选平台：wenjuanxing（问卷星）｜备用：—
- 深链接：https://www.wjx.cn/newwjx/manage/myquestionnaires.aspx（DIRECT，来源 PREFLIGHT，实测 2026-09-19T13:53:52）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：思维导图、笔记软件、问卷调查、思维导图、笔记软件、问卷调查、QQ文档、问卷星、问卷星后台（我的问卷）
- 典型操作：
  1. 腾讯文档思维导图、WPS 思维导图和有道云笔记脑图均提供免费功能，建议熟悉思维导图的创建、节点编辑、层级调整、导出和分享等常用操作。
  2. 有道云笔记虽然有付费功能，但免费功能也比较实用，建议重点体验普通笔记、内容收藏、脑图笔记等常用功能。
  3. 安装豆包APP、通义APP，体验实时记录功能，熟悉录音转文字、自动摘要、重点提炼、待办事项识别等功能。
  4. 建议深度使用腾讯文档思维导图、WPS思维导图、有道云笔记及问卷星的各项功能。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M39 OFFICE插件和浏览器插件

- module_id：`知识模块39`｜大类：知识管理工具
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：OFFICE插件和浏览器插件、微词云、雨课堂
- 典型操作：
  1. 上面要求安装或熟练掌握的插件，安装并深度使用。
  2. 探索：用雨课堂插件在PPT中增加一个多选题。
  3. 探索：用OfficeAI助手把word文档中单行字体颜色改为红色，双行字体颜色改为蓝色。
  4. 探索：用智谱清言浏览器插件自动在arXiv中检索文献。
  5. 探索：用小恐龙公文排版助手批量把半角标点符号改为全角。
  6. 探索：Microsoft Edge浏览器的扩展商店中有哪些与AI相关的浏览器插件。
- 主要陷阱：
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M40 截图与录屏

- module_id：`知识模块40`｜大类：知识管理工具
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：截图与录屏、QQ、QQ文档
- 典型操作：
  1. QQ的截图、录屏功能有快捷键。截图后出现的工具条，其中的每一个按钮都要了解具体功能，动手操作实践一下。
  2. 探索：用LICEcap录制一段屏幕操作，然后把录制好的gif动图贴在ppt中播放，看效果。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M41 PDF文件处理

- module_id：`知识模块41`｜大类：知识管理工具
- 首选平台：cnki（CNKI 中国知网）｜备用：—
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：PDF文件处理、知网、CNKI、中国知网、MIT Libraries、MIT Theses、Oxford Academic、Oxford Academic Books
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. WORD、EXCEL、PPT内置转PDF功能，点击“另存为”即可看到。
  2. 深度使用云展网中的PDF合并、PDF拆分、PDF压缩、PDF加密、PDF添加页面、PDF文件转换等功能。
  3. 检索模式：ADVANCED_FORM / PROFESSIONAL_EXPRESSION
  4. 结果读取位置：结果总数标签；结果页左侧「学科」是专辑分类不是学位论文学科专业，必须进详情页
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M42 学术评价与投稿选刊

- module_id：`知识模块42`｜大类：学术写作
- 首选平台：cnki（CNKI 中国知网）｜备用：wanfang、sciencedirect、vip
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：STATIC｜需登录：NO_OR_UNKNOWN｜可否离线：YES
- 触发词：学术评价与投稿选刊、知网、CNKI、中国知网、百度学术、CNKI AI、LeapSpace、维普中文期刊服务平台
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 影响因子的计算、H指数的判断，找点教程，一定要学会。
  2. 判断是不是CSSCI、北大核心、CSCD、AMI，在CNKI、维普、万方中通过搜索即可搞定。比如：输入期刊名或文章名，勾选CSSCI，看能否找到。这些数据库的期刊主页中也有。
  3. 探索：《会计之友》是不是正规的期刊？是不是北大核心期刊？是不是CSSCI期刊？是不是AMI期刊？是不是CSCD期刊？在CNKI中的综合影响因子和复合影响因子分别是多少？
  4. 探索：在CNKI写作投稿服务平台页面，输入篇名、摘要等信息，适配对应期刊。
  5. 探索：在 LeapSpace 中通过提示词（如“研究方向”、“期刊匹配”、“分区解读”、“投稿匹配矩阵”等），适配对应期刊。
- 主要陷阱：
  - 4.能够使用CNKI写作投稿服务平台（xztg.cnki.net）追踪学术热点、选题分析、智能选刊（其他商用功能不命题）
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码

### M43 学术伦理

- module_id：`知识模块43`｜大类：学术写作
- 首选平台：standards（国家标准）｜备用：cnki
- 深链接：https://openstd.samr.gov.cn/（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：STATIC｜需登录：SOMETIMES｜可否离线：YES
- 触发词：学术伦理、学术出版规范 期刊学术不端行为界定、高等学校预防与处理学术不端行为办法、负责任研究行为规范指引（2023）、国家标准全文公开、GB/T、标准全文、CNKI、全国标准信息公共服务平台、全国标准信息标准详情
- 可用字段：标准号、标准名称、起草单位、实施日期
- 典型操作：
  1. 多看几遍，主要关注各种学术不端行为。
  2. 建议把这个标准下载下来，方便比赛时查询。
  3. 检索模式：SEARCH / RESOURCE_DETAIL
  4. 结果读取位置：标准详情页与标准正文
- 主要陷阱：
  - openstd.samr.gov.cn 是「国家标准全文公开系统」，registration 路由与 std.samr.gov.cn 不同
  - 标准正文 PDF 可能是扫描件（无文字层），必须浏览器渲染后目视读取

### M44 参考文献著录格式

- module_id：`知识模块44`｜大类：学术写作
- 首选平台：cnki（CNKI 中国知网）｜备用：vip、wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：NO
- 触发词：参考文献著录格式、知网、CNKI、中国知网、百度学术、维普中文期刊服务平台、万方数据 / 万方标准
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 国标《信息与文献—参考文献著录规则》（GB/T 7714-2025）需要认真掌握，如：图书 M、期刊 J、学位论文 D、会议录 C、标准 S、专利 P、报纸 N、报告 R、网站/网页 EB、数据集 DS、预印本 PP 等。
  2. 探索：找几本被SCI收录期刊，查看其中文章的参考文献，确定具体格式。
  3. 探索：从CNKI中查找文献，选定期刊论文、学位论文、会议论文、标准、专利各一篇，按照GB/T 7714-2025的格式导出。
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M45 论文排版

- module_id：`知识模块45`｜大类：学术写作
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：论文排版
- 典型操作：
  1. 找个教程，系统学习word（wps）排版。B站中有大量这方面的视频，搜索学习。
  2. 从备赛考虑，重点学习要求中提到的WORD功能。
  3. 探索：在word（或wps）的替换中把“^p^p”替换为“^p”，替换效果是什么？
  4. 探索：在word（或wps）的替换中，把“正确答案”替换为“^m正确答案”，替换效果是什么？
  5. 探索：在word（或wps）的替换中，如何把文档中的“信息”两字批量替换为红色？
  6. 探索：在word（或wps）的替换中，如何把文档中含有“节 ”（“节”字后面接一个空格）的段落批量设置为三级标题样式？
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M46 文献管理工具

- module_id：`知识模块46`｜大类：科研工具
- 首选平台：cnki（CNKI 中国知网）｜备用：—
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：STATIC｜需登录：NO_OR_UNKNOWN｜可否离线：YES
- 触发词：文献管理工具、知网、CNKI、中国知网、百度学术、Zotero
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. Mendeley、Zotero是免费工具，有网页版也有客户端，请安装深度体验其中的具体功能。
  2. 可以安装并深度体验知网研学E-study（https://x.cnki.net/web/search/#/down）
  3. 探索：在知网研学E-study页面，了解如何将参考文献导入文献管理软件
  4. 其他几个文献管理工具，至少要了解哪些是免费的。
- 主要陷阱：
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码

### M47 文献追踪工具

- module_id：`知识模块47`｜大类：科研工具
- 首选平台：wanfang（万方数据）｜备用：cnki、pubmed
- 深链接：https://s.wanfangdata.com.cn/paper（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：文献追踪工具、万方、CNKI、PubMed、万方数据 / 万方标准、万方智研
- 可用字段：题名、关键词、摘要、作者、作者单位、期刊名称、日期、基金
- 典型操作：
  1. 在CNKI的检索结果页面，点击“主题定制”即可跟踪该主题，在CNKI首页中“我的CNKI”中即可查看；在CNKI的期刊详情页面，点击“RSS订阅”即可看到该期刊的RSS地址。
  2. 在PUBMED（https://pubmed.ncbi.nlm.nih.gov）检索结果页面，检索框下方有“Create RSS”和“Create alert”选项，点击根据提示操作即可（请提前注册）。
  3. 在万方数据库首页登录个人账号（请提前注册）， 网页右上角在“学习中心”中使用“我的订阅”，包含期刊订阅、关键词订阅、RSS订阅。
- 主要陷阱：
  - 高级检索默认是「模糊」不是「精确」
  - 筛选控件不响应合成点击，需改用页面自身 XHR 或直接调用页面函数
  - 万方智研是与主站并列的独立路由
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M48 数据处理工具

- module_id：`知识模块48`｜大类：科研工具
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：SEMI_DYNAMIC｜需登录：NO_OR_UNKNOWN｜可否离线：PARTIAL
- 触发词：数据处理工具、微词云
- 典型操作：
  1. 找excel的帮助，学习这几个数据处理常用的函数。
  2. 探索：基于excel中的数据，让AI给出实现具体需求的excel函数。
  3. 探索：从百度 AI Studio、阿里云天池、OpenDataLab、OpenML 或 UCI Machine Learning Repository（Classic 版或 Beta 版）中下载一个表格型数据集，查看其字段名称、样本数量、数据格式和缺失值情况，并基于下载的数据集，让 AI 工具给出 EXCEL 函数或数据处理步骤，并对结果进行人工核验。
- 主要陷阱：
  - 界面/栏目/功能可能改版，作答以题目指定平台当前显示为准。

### M49 数据可视化工具

- module_id：`知识模块49`｜大类：科研工具
- 首选平台：未识别（—）｜备用：—
- 深链接：—（UNKNOWN，来源 —）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：数据可视化工具、豆包、抖音创作者中心、ECharts、Iconfont、微词云
- 典型操作：
  1. 按题目指定平台进入检索入口，设置题目给出的字段与筛选条件。
- 主要陷阱：
  - 4、能够使用微词云（https://www.weiciyun.com）统计长文本词频并生成词云图（非会员每日只能免费使用三次词频统计，请同学们在考试当天谨慎使用此功能！！！）。
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

### M50 文献可视化工具

- module_id：`知识模块50`｜大类：科研工具
- 首选平台：cnki（CNKI 中国知网）｜备用：vip、wanfang
- 深链接：https://kns.cnki.net/starter/advanced（DIRECT，来源 KNOWN_HISTORY，实测 2026-09-19）
- 动态性：DYNAMIC｜需登录：SOMETIMES｜可否离线：NO
- 触发词：文献可视化工具、知网、CNKI、中国知网、CNKI AI、维普中文期刊服务平台、万方数据 / 万方标准
- 可用字段：主题、篇关摘、关键词、篇名、全文、作者、第一作者、通讯作者、作者单位、基金、摘要、小标题
- 典型操作：
  1. 要求中提到的工具和功能，最好实质性用一下。
  2. CNKI AI需要登录账号，建议提前注册和认证。
  3. 从备赛的角度， CiteSpace、VOSViewer这两个工具，知道是做什么的即可，赛特新思（citexs）的文献调研分析功能需要熟练掌握。
  4. 分别在CNKI、万方、维普选择一个检索词，然后在检索结果页面找到文献分析功能，进行实质性体验。
  5. 探索：在赛特新思的文献调研分析功能界面中，学科选择“医学”，关键词输入“大数据”，可视化图形中圆圈最大的文献是哪一篇？
  6. 探索：2020—2025年西安交通大学发表CSSCI论文数量排名前5的作者依次是？
- 主要陷阱：
  - 答案解析：CSSCI论文，一般在中文期刊论文数据库中检索，其中比较常用的是CNKI、维普、万方。在这三个数据库中，只有CNKI有“第一单位”（第一作者单位）这个检索点。所以选择CNKI。在CNKI的高级检索界面，文献类型选择“学术期刊”，检索点选择“第一单位”，检索词输入“四川师范大学”，匹配方式选择默认的“模糊”，时间限制2011-2020，来源期刊勾选“CSSCI”，然后点击“检索”。在检索结果页面，选择“导出与分析”→“可视化分析”→“全部检索结果分析”，在分析结果页面，选择“中国作者分布”项，即可看到高频作者排序柱状图。
  - 单框内 `*`=与、`+`=或；用错符号会把结论反转（同一判断题答案相反）
  - 单框内容上限 120 字符
  - 连续检索会触发 blockPuzzle 风控；一次会话连发七八次后整个会话不可用
  - 直连 kns8s/AdvSearch 或 kns8s/search 会跳验证码
  - 动态题：数值/排名/统计会变，必须记录 observed_at，不得当作永久事实。

---

生成命令：`uv run python scripts/build_50_module_nav.py`。重新生成会覆盖本文件；请勿手工编辑，改动请改源数据。

# 考试当天 7 平台配方（2026-09-19 实测）

本文件只记录**本次实测通过**的入口与字段。与模拟题不同，正式题会换对象，
但平台、入口、字段、筛选位置不变 —— 这正是本文件存在的意义：
**换参数，不换流程。**

实测方式：HTTP 探活 `scripts/preflight_platforms.py` + 真实浏览器渲染核对。
未实测的项目一律标注「未验证」，不得当作已确认。

---

## 0. 浏览器策略（先读这一节）

优先级（高 → 低）：

1. 用户现有 Edge 登录态
2. Edge + 用户既有 Profile
3. Edge 自动化独立会话
4. 用户人工在 Edge 中操作
5. 其他浏览器（仅在题目无需登录且 Edge 技术性不可用时）

**当前实测状态**：用户 Edge 正在运行并占用 `Default` Profile，且未开启远程调试端口，
因此自动化复用登录态**当前不可用**。不允许强占 Profile、删锁文件或改 Profile 数据库。
登录受控平台一律走人工交接（见各平台「人工交接」小节）。

细节见 `config/edge_profile.yaml`。

---

## 1. CNKI 中国知网

**入口（重要）**

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://www.cnki.net/ | ✅ 200 |
| 高级检索 | https://kns.cnki.net/starter/advanced | ✅ 直接进高级检索页 |
| 总库检索 | https://kns.cnki.net/kns8s/search | ⚠️ 直接访问命中 blockPuzzle |
| 专业检索 | 高级检索页内「专业检索」页签 | ✅ |

> **关键**：直接访问 `kns8s/AdvSearch` 或 `kns8s/search` 会跳
> `kns.cnki.net/verify/home?captchaType=blockPuzzle` 安全验证。
> 从首页点「高级检索」或直接走 `starter/advanced` 可正常进入，**不触发验证码**。
> 这是本次实测最有价值的发现 —— 不要把 blockPuzzle 当成必然。

**检索项（下拉，16 项）**

    主题 / 篇关摘 / 关键词 / 篇名 / 全文 / 作者 / 第一作者 / 通讯作者 /
    作者单位 / 基金 / 摘要 / 小标题 / 参考文献 / 分类号 / 文献来源 / DOI

**其他控件**

- 匹配方式：`精确` / `模糊`
- 逻辑：`AND` / `OR` / `NOT`
- 时间范围：不限 / 最近一周 / 最近一月 / 最近半年 / 最近一年 / 今年迄今 / 上一年度
  ，另有「发表时间」「更新时间」起止
- 复选项：OA出版 / 网络首发 / 增强出版 / 基金文献 / 中英文扩展 / 同义词扩展
- 文献分类：基础科学 / 工程科技Ⅰ辑 / 工程科技Ⅱ辑 / 农业科技 / 医药卫生科技 /
  哲学与人文科学 / 社会科学Ⅰ辑 / 社会科学Ⅱ辑 / 信息科技 / 经济与管理科学

**高级检索框内运算符规则（官方说明）**

- `*` = 与，`+` = 或，`-` = 非；优先级用**英文半角括号**确定
- 检索词含空格或 `* + - ( ) / % =` 时，须用英文半角单/双引号引起
- 单框内容 **≤ 120 字符**
- 例：`(锻造 + 自由锻) * 裂纹`；`'digital library' * 'information service'`

> 高级检索框填**裸表达式**；`SU=` 等字段代码只在**专业检索**用。见
> `skill/cnki_search_syntax.md`。

**机构识别**：本机访问时页面识别为「湖南师范大学」，属机构网络识别，个人登录态未确认。

**人工交接**：若命中 blockPuzzle 或需看全文，按 `config/fast_profile.yaml` 的
`manual_handoff_must_include` 给出 官网 / 入口 / 可复制检索式 / 目标字段。

---

## 2. 维普

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://www.cqvip.com/ | ✅ 200 |
| 高级检索 | https://www.cqvip.com/advancesearch | ✅ 正常打开 |
| 期刊检索（旧入口） | https://qikan.cqvip.com/Qikan/Search/Index | ⚠️ HTTP 412（反爬），勿用 |

**检索项（14 项）**

    任意字段 / 主题词 / 篇关摘 / 篇名 / 关键词 / 摘要 / 作者 / 第一作者 /
    作者单位 / 刊名 / 中图分类号 / 学科分类号 / DOI / 基金

**其他控件**

- 匹配方式：`模糊` / `精确`
- 逻辑：`AND` / `OR` / `NOT`
- 文献类型：期刊论文 / 学位论文 / 会议论文 / 专利 / 标准
- 时间范围：开始日期 — 结束日期
- 检索扩展：同义词扩展 / 中英文扩展
- 其他模式：高级检索 / 专业检索 / 作者发文检索

**布尔规则（官方说明）**

- `AND`(and / `*`)、`OR`(or / `+`)、`NOT`(not / `-`)；**运算符前后需空格**
- 优先级：`NOT` > `AND` > `OR`；`()` 内优先
- 检索词本身含运算符时用 `""` 包裹，如 `"C++"`

> ⚠️ **维普的「精确/模糊」语义与 CNKI 不同，不可套用**：
> 精确 = 不做分词处理，允许前后加内容；
> 模糊 = 允许分词及位置调换。
> **作者 / 第一作者 / 导师 / 刊名 / 系列分类号 / DOI** 字段例外，其「精确」= 完全命中。

---

## 3. 万方数据

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://www.wanfangdata.com.cn/index.html?index=true | ✅ 200 |
| 检索页 | https://s.wanfangdata.com.cn/paper | ✅ 200 |

流程：**高级检索 → 先选文献类型 → 再配字段和年份 → 结果页左侧分组/筛选**。

结果数量、作者排名、机构排名**优先用结果页已有的「分组」「筛选」「分析」**，不要逐条数。

---

## 4. PubMed

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://pubmed.ncbi.nlm.nih.gov/ | ✅ 200 |
| Advanced Search | https://pubmed.ncbi.nlm.nih.gov/advanced/ | ✅ 200 |
| MeSH Database | https://www.ncbi.nlm.nih.gov/mesh/ | ✅ 200 |

**优先生成可复制检索式**，不要只写自然语言。

常用字段标记：

    [Title]  [Title/Abstract]  [Author]  [MeSH Terms]  [Journal]  [Date - Publication]

运算符：`AND` / `OR` / `NOT`，精确短语用 `"..."`。

题目给 **年份 / Article type / Text availability** 时用结果页左侧 **Filter** 配置。

> PubMed 的字段标记与截词规则**不能**套到 CNKI、万方、维普、ScienceDirect 上。

人工路线直接给可复制 Query。

---

## 5. 中国大学MOOC（重点：同平台换课程）

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://www.icourse163.org/ | ✅ 200 |
| 课程搜索 | `https://www.icourse163.org/search.htm?search=<关键词>` | ✅ 200 |
| 课程页 | `https://www.icourse163.org/course/<学校代码>-<课程ID>` | ✅ 200 |

**实测结论：课程大纲无需登录即可读取。**

课程详情页的 `.outline` / `.outlineBody` 元素直接包含完整章节 + 小节标题，例如：

    第一章 破案：精确信息检索
      1.信息素养的哲学三问
      2.欢迎进入搜索世界
      ...
      第一章 精确文献的查找_单元测试题
    第二章 解题：主题信息检索（上）
      ...

**固定流程**

1. 搜索课程名称
2. **核对学校 + 教师**，避免同名课程（搜索结果卡片同时给出课程名、学校、教师名）
3. 打开课程详情（注意：点击后在新标签打开）
4. 读 `.outline` 取章节结构
5. 定位题目要求的小节 / 视频 / 标题

> 模拟题考「MOOC A 课程第 2 章」，正式题考「MOOC B 课程第 5 章」时，
> **流程完全不变**，只替换课程名与章节号。不要当成新题从零研究。
> **不要 Google 课程答案。**

课程页还能直接读到：第 N 次开课、开课时间、进行至第几周/共几周、参加人数。

**人工交接（30 秒展不开目录时）**

    🔴 需要你操作
    官网：https://www.icourse163.org/
    搜索：`<课程名称>`
    核对：学校：XXX  教师：XXX
    进入：课程大纲 → 第X章 → X.X
    看：小节标题 / 视频标题 / 数量

---

## 6. ScienceDirect

| 用途 | URL | 实测 |
|---|---|---|
| 首页 | https://www.sciencedirect.com/ | ❌ HTTP 403（Cloudflare，浏览器也卡「请稍候…」） |
| **Advanced Search** | https://www.sciencedirect.com/search | ✅ **直接可用，跳过首页拦截** |

> **关键**：首页被 Cloudflare 挑战拦住，但直接访问 `/search` 能正常进入
> Advanced Search。**做题时直接走 `/search`，不要先开首页。**

**高级检索字段（实测）**

- `Find articles with these terms`（快速检索框）
- `In this journal or book title`（期刊/书内检索）
- `Year(s)`、`Author(s)`、`Author affiliation`
- `Volume(s)`、`Issue(s)`、`Page(s)`
- 点 `Show all fields` 展开：`Title, abstract or author-specified keywords`、
  `Title`、`References`、`ISSN or ISBN`
- `Submit advanced search` 提交

登录态：未登录（页面显示 `Sign In` / `My account`）。全文可能受订阅限制。

> ⚠️ **ScienceDirect 的截词与布尔规则不能与其他数据库混用**。
> 不要直接套用 IEEE / PubMed 的符号。用官网 Advanced Search 或期刊内检索。
> 页头有 `LeapSpace` 入口（对应模块 05）。

---

## 7. UNESCO Digital Library（老师点名）

**老师点名文档**

    https://unesdoc.unesco.org/ark:/48223/pf0000393559

**实测元数据**

| 字段 | 值 |
|---|---|
| 题名 | 生成式人工智能 教育与研究应用指南 |
| 合著者 | 联合国教科文组织 |
| 作者 | Miao, Fengchun；Holmes, Wayne |
| DOI | https://doi.org/10.54675/PYTW8189 |
| ISBN | 978-92-3-500058-0 |
| 页数 | 47 pages |
| 语言 | 汉语 |
| 出版年份 | 2025 |
| 许可 | CC BY-SA 3.0 IGO |
| 类型 | 书 |
| 访问 | Online Open Access |

**PDF 取法（重要）**

- 真实 PDF 文件名是 **`393559chi.pdf`**（中文版），**不是** `393559eng.pdf`。
  语言后缀会变（chi / eng / fre / spa / rus / ara …）。
- `https://unesdoc.unesco.org/ark:/48223/pf0000393559/PDF/393559chi.pdf`
  **返回的是 SPA 外壳 HTML，不是 PDF**（实测 Content-Type: text/html）。
- 真实下载端点走 `documentViewer.xhtml` 内嵌 iframe 的
  `annotationSVC/DownloadWatermarkedAttachment/...` —— 脱离浏览器直接请求返回 **403**。
- **结论：UNESCO PDF 必须用浏览器打开，不能靠 HTTP 直取。**

**页码规则（题目最容易埋坑的地方）**

必须区分：

    PDF viewer page   ≠   printed / body page（正文页码）

ARK 页面标题是「UNESCO 数字图书馆」的 SPA，页面内容异步渲染，
**打开后需等 3–5 秒**再读取（实测首次 evaluate 为空，等待后才有内容）。

**人工交接**

    🔴 需要你操作
    官网：https://unesdoc.unesco.org/ark:/48223/pf0000393559
    1. 打开后用页面内的 PDF 查看器
    2. 注意切分「PDF 第X页」与「正文第X页」
    看：表X / 颜色 / 页末文字 / 表格名称

---

## 8. 通用执行顺序（正式题）

    Exact Match（原题命中）
      → Variant / Pattern Match（同平台同操作，换参数）
      → Platform Recipe（本文件）
      → 修改参数并执行
      → Manual Handoff

| 档位 | 硬上限 | 目标 |
|---|---|---|
| NORMAL | 180 秒 | — |
| FAST | 120 秒 | 变体题尽量 **60 秒内**完成 |

立即转人工的条件：微信/App/验证码/复杂登录、连续 2 次浏览器失败、30–60 秒仍未找到正确入口。

**「从零 Web Research」是最低优先级**，不要在变体题上使用。

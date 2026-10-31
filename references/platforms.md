# 平台配方

> 所有条目均为浏览器实测入口。站点改版频繁，先验证入口能打开，再按配方操作。

## 维普（cqvip.com）

- 高级检索：`https://www.cqvip.com/advancesearch`
- 旧入口 `qikan.cqvip.com` 返回 412，不要用。

**匹配方式（最容易错）**

| 方式 | 语义 |
|---|---|
| 精确 | 不做分词，允许前后加内容 → 等价于「包含某个连续字符串」 |
| 模糊 | 分词 + 位置调换 → 召回更多，数量常翻倍 |

题目说「包含」时优先用**精确**；若四个选项都对不上，再切模糊试。

**常用字段**：任意字段、主题词、篇关摘、篇名、关键词、摘要、作者、第一作者、作者单位、刊名、中图分类号、学科分类号、DOI、基金。

**筛选**：结果页左侧「核心收录」有 北大核心 / CSSCI / CSCD / CA / 卓越期刊；「年份」「学科」分面同样在左侧。

- 左侧核心收录分面的数字只有带检索词时才可靠。
- 基金字段检索示例：检索项=基金，匹配=精确，值=完整项目名。

## CNKI（kns.cnki.net）

- 高级检索：`https://kns.cnki.net/starter/advanced`（直连旧接口 `kns8s/AdvSearch` 容易触发验证）

**高级检索单框运算符**

| 符号 | 含义 |
|---|---|
| `*` | 与 |
| `+` | 或 |
| `-` | 非 |
| `()` | 分组 |

优先级：`()` > `NOT` > `AND` > `OR`。含运算符的词要加英文双引号。

「专业检索」才使用 `SU= / TI= / KY= / AU=` 字段代码。

**陷阱**：结果页左侧「学科」是专辑分类，不是学位论文详情页里的「学科专业」。

## 万方（wanfangdata.com.cn）

- 检索：`https://s.wanfangdata.com.cn/paper`

**默认值是「模糊」**，题目要精确时必须手动切换。
有滑块验证，触发后不要重试，直接转人工。

结果页分面：年份、文献类型（期刊/学位/会议/标准/专利）、学科。

## ScienceDirect

- 检索：`https://www.sciencedirect.com/search`
- 首页 `sciencedirect.com` 常被 Cloudflare 拦，直接进 `/search`。

文献类型分面在结果页左侧（Research articles / Review articles / Mini reviews / Correspondence 等）。
期刊限定可用 `?pub=<期刊名>`。

## 国家自然科学基金（kd.nsfc.cn）

- 结题项目：`https://kd.nsfc.cn/finalProjectInit`
- 首页检索框输入批准号或负责人，回车后跳到 `finalSearchList?s=<关键词>`。

结果卡片包含：项目名称、批准号、申请代码、项目类别、负责人、资助经费（万元）、批准/结题年度、依托单位、关键词。

## arXiv

`https://arxiv.org/abs/<标识符>`，例：`https://arxiv.org/abs/2606.19348`。
标题在 `h1.title`。

## 和鲸社区（heywhale.com）

- 数据集列表：`https://www.heywhale.com/home/dataset`
- 带关键词：`https://www.heywhale.com/home/dataset?keyword=<词>`
- 数据集内部 API：`/api/datasets?page=1&perPage=20&Visible=true&needMeta=true&Title=<词>`
  （`Title` 参数可用；`keyword`/`search` 会报「未知字段」）

数据集详情页 → 「文件」页签 → **数据概览** 直接给出「行数 / 列数」，比看预览表头更可靠。

## 国家药品监督管理局

- 数据查询：`https://datasearch.nmpa.gov.cn/datasearch/home-index.html`
- 旧地址 `nmpa.gov.cn/datasearch/` 已停用。
- GLP 机构信息平台入口实际跳转 `beian.cfdi.org.cn/GLP/apps/pub/main.jsp`，该站经常连接被重置；连不上时用 GLP 认证公告目录（NMPA 附件 .doc）比对。
- 「GLP认证（2023年7月1日后认证信息）」目录只列**新增批次**，不是累计全量。

## 中国注册会计师协会

- 行业管理信息系统：`cmispub.cicpa.org.cn`
- 事务所详情页可展开「注册会计师」名单。
- 连不上时可用北京注协（bicpa.org.cn）历年执业会员公告交叉核对。

## 美国国会图书馆（LOC）

- 检索：`https://www.loc.gov/search/?q=<词>&fo=json`
- 条目：`https://www.loc.gov/item/<LCCN>/`、`https://www.loc.gov/resource/<id>/`

条目页「Download」区列出可下载格式及文件大小（JPEG / TIFF / PNG / GIF 视条目而定）。
loc.gov 对数据中心 IP 常见 Cloudflare 拦截。

## 全国标准信息公共服务平台

`https://std.samr.gov.cn/`：按标准名称/号检索，状态分「现行 / 废止 / 即将实施」。
统计条数时先确认筛选条件已生效。

## 通用：分面数字自证法

勾选筛选后，把分面各项数字相加：

- 若总和 = 结果总数 → 筛选**没有**生效
- 若总和明显小于总数 → 筛选已生效（其余为落在其他分面的记录）

这是判断「筛选到底点没点上」最快的方法。

---
name: ai-information-literacy-skill
description: Use when answering AI+ information literacy competition questions (AI+信息素养大赛) or similar Chinese database retrieval tasks that need live verification on CNKI, 维普, 万方, ScienceDirect, NMPA, CICPA, NSFC, arXiv, 和鲸, or the Library of Congress — especially when a query returns different counts under different match modes, filters, or a captcha wall.
---

# AI+ 信息素养大赛答题

## 核心原则

**先实测，再回答；答实测值，不答选项字母。**

A/B/C/D 只是题目的外壳，真正有价值的是从官方页面读到的数字、名称或字段。
答案首行给实测值，下面给来源路径；不要写「A」「答案：A」。

## 答题格式

    **1439**

    来源：维普高级检索 → 篇名 + 精确 + `信息素养` → 核心收录勾选「北大核心」

- 判断题 → 首行 `正确` / `错误`，下一行写实测到的事实（如「实测 2 条，不是 4 条」）
- 多选题 → 逐项列出确实成立的项
- 无法核验 → 写明卡在哪一步，并给出人工交接，不要伪装成已核验

## 解题顺序

    精确命中（题库/原题）
      → 同型题配方复用（只复用法方，不沿用旧答案）
      → 平台配方（见 references/platforms.md）
      → 官方站点实测
      → 人工交接
      → 从零检索（最低优先级）

**同一路线自动化失败 2 次就转人工**，不要在一题上烧时间。

## 平台速查

| 平台 | 入口 | 关键点 |
|---|---|---|
| 维普 | `cqvip.com/advancesearch` | 「精确」=不分词、允许前后加内容（=包含）；「模糊」=分词+换位，结果会翻倍 |
| CNKI | `kns.cnki.net/starter/advanced` | 高级检索单框内 `*`=与、`+`=或、`-`=非；结果页「学科」是专辑，不是学位论文的学科专业 |
| 万方 | `s.wanfangdata.com.cn/paper` | 默认「模糊」不是精确；有滑块验证 |
| ScienceDirect | `sciencedirect.com/search` | 首页常被 Cloudflare 拦，用 `/search`；可能出 CAPTCHA |
| NSFC 结题 | `kd.nsfc.cn/finalProjectInit` | 直接搜批准号即可，结果页 `finalSearchList?s=<批准号>` |
| arXiv | `arxiv.org/abs/<id>` | 题目给标识符就直接开摘要页 |
| 和鲸 | `heywhale.com/home/dataset?keyword=` | 数据集详情看「文件」页签的「数据概览」行数列数 |
| NMPA | `datasearch.nmpa.gov.cn` | GLP 机构平台 `beian.cfdi.org.cn` 经常连不上 |
| CICPA | `cmispub.cicpa.org.cn` | 事务所页可查注册会计师名单 |
| LOC | `loc.gov/resource/<id>` | 条目页 Download 区看可下载格式；Cloudflare 拦截常见 |

详细配方、字段名、URL 参数见 **references/platforms.md**。

## 高频陷阱

1. **匹配方式语义因库而异**，选错会让结果翻倍且四个选项全对不上。
   四个选项都差得远 → 先怀疑检索条件，不要硬选。
2. **筛选要在检索前设置**。事后勾选可能不生效。
   自证：分面各项之和 = 结果总数 → 说明筛选没生效。
3. **默认值会误导**：万方默认模糊、百度指数默认日期无数据、维普默认排序无关。
4. **页面字段名 ≠ 题目问的字段**（CNKI 学科 vs 学科专业；维普无「导师」字段）。
5. **选项字母 ≠ 选项内容**。两者都是字母时最容易看错行。
6. **不要用首页的默认排行分面做结论**，它常是抽样推荐；必须带检索词再读分面。
7. **专利有 18 个月公开滞后**，当年数据不完整，排名可能随时间变化。

## 遇到拦截

验证码、滑块、登录墙、Cloudflare 人机验证 → **立即停止自动化，转人工**，不要尝试绕过。

人工交接格式：

    需要你操作
    官网：<URL>
    1. <入口路径>
    2. <可复制的检索式或筛选条件>
    3. <看哪个字段>
    我要的结果：<需要回传的数字或名单>

无头浏览器可用于公开页面；headless UA 中含 `HeadlessChrome` 时部分站点直接返回 412，
把 UA 换成同版本普通 Chrome UA 属于兼容处理，不是绕过验证。

## 脚本

`scripts/headless_chrome.py`：无头 Chrome 取正文 / 执行 JS / 点击 / 输入 / 截图。

```bash
python scripts/headless_chrome.py --url "https://example.com"
python scripts/headless_chrome.py --url URL --js "document.title"
python scripts/headless_chrome.py --url URL --click ".el-checkbox" --wait-ms 2500
python scripts/headless_chrome.py --url URL --focus "#kw" --type "关键词" --enter
```

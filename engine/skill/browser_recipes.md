# Browser Recipes（指针）

CANONICAL SOURCE: config/official_urls.json

<!-- 次要来源：config/platforms.yaml、skill/official_links.md、skill/platform_routes.md -->

本文件是**索引指针**，不是新内容。代码必须读取上面的 CANONICAL SOURCE，
不要解析本文件。项目里没有单独的 browser_recipes.md，浏览器配方已经存在于
canonical 文件；请以它们为准，不要在此重复维护。

| 需要什么 | 去哪里看 | 规模 |
|---|---|---|
| 逐题 URL 配方（平台、入口、字段、操作路径、登录与自动化边界） | `config/official_urls.json` | 326 条配方 / 183 个平台 |
| 同上的可读版 | `skill/official_links.md` | 同上 |
| 12 个平台的总路线（route / automation） | `config/platforms.yaml` | 12 个平台 |
| 平台分类与检索路线 | `skill/platform_routes.md` | — |

## 运行时边界

`config/official_urls.json` 的 `runtime_policy.hard_timeout_seconds` 为 **180**（普通档）。
FAST 档位见 `config/fast_profile.yaml`，硬上限 **120 秒**，启用 FAST EXAM MODE 时生效。

## 取用顺序

1. 先按题目指定平台在 `official_urls.json` 里定位配方（按题号或平台名）。
2. 配方给出的入口是唯一首选入口；不要先用搜索引擎找入口。
3. 配方标注的 `login` / `automation` 边界即停止线；命中即转人工，不尝试绕过。

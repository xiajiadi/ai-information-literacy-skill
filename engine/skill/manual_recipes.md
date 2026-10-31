# Manual Recipes（指针）

CANONICAL SOURCE: config/rules.yaml

<!-- 次要来源：config/official_urls.json（逐题入口/字段）、skill/SKILL.md（输出格式） -->

本文件是**索引指针**，不是新内容。代码必须读取上面的 CANONICAL SOURCE，
不要解析本文件。项目里没有单独的 manual_recipes.md，人工交接所需的字段
已经存在于 canonical 文件。

| 需要什么 | 去哪里看 |
|---|---|
| 触发人工的条件清单（captcha / qr_login / sms / campus_auth / app_only / drm_pdf / dynamic_player） | `config/rules.yaml` → `human_handoff.trigger` |
| 逐题入口、字段、可复现条件 | `config/official_urls.json` |
| 人工接管输出格式 | `skill/SKILL.md` → 「浏览器与人工接管」 |
| CNKI 检索式写法（高级检索 vs 专业检索，字段代码表） | `skill/cnki_search_syntax.md` |

**各平台检索语法不通用**：CNKI 的写法不能套到万方、PubMed、IEEE Xplore 上。
交接检索式时必须写明「界面上选哪个字段 + 框里填什么」，只给一行裸表达式等于没交接。

## 人工交接必须包含（见 `config/fast_profile.yaml`）

    🔴 NEEDS HUMAN
    官网：<official_url>
    1. <入口路径>
    2. <可复制检索式或筛选条件>
    3. <看哪个字段>

    复制：
    <可直接粘贴的检索表达式>

    看：<需要回传的结果>

缺任何一项都算交接不合格。禁止只写「请用户自己查」。

## 硬性约束

- 不绕过验证码、二维码、短信验证、校园认证、App 限定或 DRM。
- 登录后内容不属于本项目范围。
- 交接后停止自动化，不做二次尝试。

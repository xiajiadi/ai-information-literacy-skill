# AI+信息素养本地解题 Skill

> **省赛淘汰赛模式**：省赛的运行规则、时间预算、浏览器栈与输出格式**不在本文件**，
> 见 `skill/provincial_live_protocol.md`。本文件保留的是校赛期（FAST Replica）的离线解题流程。
> 两者冲突时以 `config/compliance_policy.yaml`（P0）与省赛协议为准。

## 任务边界

本 Skill 服务于 2026 大学生 AI+信息素养大赛的公开资料复习、逐题核验和本地记录。它不提供未公开校赛原题，不访问登录后训练题，不绕过验证码、二维码、校园认证或 App 限制。

公开训练入口为 https://csc.xxsuyang.com/training。当前访问若跳转统一登录，只记录访问边界。公开模块快照为 https://jsgateway.zhixinst.com/SCC/Website/GetKnowledgeList?kind=csc2025。

## 每题工作流

策略优先级（高 → 低）：

    Exact Match（原题命中）→ Variant Match（同型换参数）→ Platform Recipe
    → 官方平台快速执行 → Manual Handoff → 从零 Web Research（最低）

1. 先查本地 SQLite。依次尝试 L0 精确题干与选项、L1 标准化题干、L2 相似题干、L3 题干加选项内容集合。
2. 命中公开题库且已有官方标准答案时，直接返回题库答案，不用当前网页数据改写标准答案。
3. **未命中原题时，先找同型题，不要从零研究。** 判定本题与 150 题的哪一道
   「平台相同、操作任务相同、只有参数不同」。这类题必须复用旧题的
   platform / entry point / field settings / filter method / browser recipe /
   manual recipe，**但严禁复用旧答案**。实现见 `scripts/variant_match.py`。
4. 无同型题时，按 50 模块分类，锁定题目指定平台，查 `skill/exam_platform_recipes.md`
   取该平台已实测的入口、字段与筛选位置。设置题名、作者、单位、关键词、主题、
   摘要、年份、文献类型、来源类别、匹配方式、布尔关系或截词符等条件。
5. 核对题名、作者、年份、来源、DOI、卷期、页码、结果总数和统计口径。多选题逐项判断 A、B、C、D。
6. 每题立即写 attempts。当前判断只写 provisional_answer；最终公布答案交给 reconcile_answers.py。

## 三种命中状态

| 状态 | 含义 | 输出 |
|---|---|---|
| `ANSWER` | 原题命中，题库有答案 | 直接给答案 |
| `OFFICIAL_MOCK_VARIANT` | 同平台同操作、参数已变 | **只给配方，答案为空** |
| `NEW_PATTERN` | 无同型题 | 走平台配方或人工 |

题型模板的最短策略见 `skill/answer_patterns.md`；平台入口、字段和操作路径见 `skill/official_links.md`。两份文件均是操作索引，不替代题目指定平台的当前核验。

## 来源优先级

P0 是官方模拟题及官方公布标准答案。其后依次为 2026 官网公开知识模块、组委会或官方培训资料、老师培训资料、2024/2025 公开备赛指南、题目指定官方平台实时查询、第三方辅助网页和模型推断。

题目指定哪个网站，就先用哪个网站。官方打不开时不能偷偷换成知乎、CSDN 或搜索摘要并称为官方验证。若指定来源、同机构入口和原始论文/PDF 都未能完成验证，输出“当前未能在题目指定官方来源完成验证”，第三方内容只标为辅助证据。

## 置信度

- HIGH：命中官方标准答案、官方指定来源已核验，或原始论文/PDF直接支持。
- MEDIUM：可靠第一方证据较强，但指定平台仍有一个细节未完成。
- LOW：第三方辅助来源或间接推断。
- NEEDS_HUMAN：登录、验证码、动态页面或复杂人工操作阻断核验。

## 动态题

STATIC、SEMI_DYNAMIC、DYNAMIC 只描述题目事实的变化风险。DYNAMIC 题同时保留 official standard_answer、current_observed_value 和 observed_at。当前官网观察值不能覆盖官方模拟题标准答案。

## 浏览器与人工接管

**浏览器优先级：Microsoft Edge 优先。** 依次为：用户现有 Edge 登录态 →
Edge + 既有 Profile → Edge 自动化独立会话 → 用户人工在 Edge 中操作 →
其他浏览器。**Chrome / Chromium 不是默认路径**，且禁止在 Edge 失败时静默
回退到 Chrome 并让用户误以为登录态仍在。

本机实测状态与安全边界见 `config/edge_profile.yaml`：不读取或导出 Cookie /
Token / Session，不强杀用户 Edge，不删除锁文件，不修改 Profile 数据库。
Profile 被占用时如实说明并转人工，不抢占。

公开页面可以使用浏览器、Computer Use 或 Playwright 辅助。遇到验证码、二维码、短信验证、校园认证、App限定、动态播放器、DRM PDF 或要求人为确认的页面，立即停止自动提交。

人工接管格式：

    🔴 NEEDS HUMAN
    操作：
    1. 打开指定网站。
    2. 进入指定菜单或检索入口。
    3. 输入题目中的关键词和筛选条件。
    4. 查看指定字段并截图。
    我要看的结果：……

## 输出格式

题库命中时：

    【题库命中】
    答案：BC
    题库ID：Qxxxx
    来源：公开来源
    置信度：🟢 HIGH

新题核验完成时，给出答案、官方证据、来源和置信度。多选题同时列出 A/B/C/D 的独立判断。无法核验时给人工路径，并明确“暂不提交答案”。

## 本地接口

- 初始化：uv run python scripts/init_db.py
- 导入 Excel：uv run python scripts/ingest_xlsx.py data/seed/原始文件.xlsx
- 扫描材料：uv run python scripts/ingest_materials.py
- 生成 50 模块：uv run python scripts/build_skill.py
- 匹配题目：uv run python scripts/match_question.py "题干"
- 考试极短输出：uv run python scripts/match_question.py "题干" --exam-mode --option-a "A" --option-b "B" --option-c "C" --option-d "D"
- 重建题干/选项哈希和 FTS：uv run python scripts/rebuild_indexes.py
- 生成官方 URL 操作知识库：uv run python scripts/build_official_urls.py
- 考试前预检：uv run python scripts/preflight.py
- 平台探活 + Edge 检测：uv run python scripts/preflight_platforms.py
- 变体（同型题）匹配：uv run python scripts/solve_question.py "题干" --explain
- 构建平台注册表：uv run python scripts/build_platform_registry.py
- 同型题路由验收：uv run python scripts/test_variant_routing.py
- 变体匹配测试：uv run python -m pytest tests/test_variant_match.py -q

## FAST 路由底座

    config/platform_registry.json   平台 → 路由 → 状态（125 平台 / 207 路由）
    config/query_templates.json     按平台分开的可复制检索式模板
    config/official_urls.json       逐题 URL 配方（canonical 源）
    config/edge_profile.yaml        Edge 策略与安全边界

流程：题目 → Exact Match → Variant Match → Platform Registry → 深链接 → 检索。
`route_status` 中 `ACTIVE_EDGE_ONLY` 表示 HTTP 读不到但浏览器可用，
**不等于 BROKEN**。
- 150 题离线基准：uv run python scripts/benchmark_matching.py
- 质量审计：uv run python scripts/quality_audit.py
- 新增题目和 attempt：uv run python scripts/add_question.py --question-text "题干" --answer "A"
- 回填最终答案：uv run python scripts/reconcile_answers.py final_answers.jsonl
- 导出：uv run python scripts/export_question_bank.py

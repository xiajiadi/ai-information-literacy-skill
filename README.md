# AI+ 信息素养大赛答题技能

一个给 Claude Code 用的 **Skill**：把「AI+信息素养大赛」这类**必须去官网实测**的检索题，做成稳定可复用的解题流程。

不是题库，也不含任何比赛原题答案。它沉淀的是**方法与坑**：

- 答案写实测值（`1439`），不写选项字母（`A`）
- 同一平台在不同匹配方式下结果可能差一倍，先判断条件再判断答案
- 无法核验时明确写「卡在哪一步」，绝不把推断伪装成实测

## 安装

把整个目录放进你的 skills 目录：

```bash
# Claude Code（用户级）
cp -r ai-information-literacy-skill ~/.claude/skills/

# 或项目级
cp -r ai-information-literacy-skill .claude/skills/
```

重启会话后，Claude 会在遇到相关任务时自动加载 `SKILL.md`。

## 目录

```
SKILL.md                     核心流程、答题格式、平台速查、高频陷阱
references/platforms.md      维普/CNKI/万方/ScienceDirect/NSFC/arXiv/和鲸/
                             NMPA/CICPA/LOC/标准平台 的入口、字段与筛选位置
scripts/headless_chrome.py   无头 Chrome（CDP）：取正文 / 执行 JS / 点击 / 输入 / 截图
```

## 无头浏览器

```bash
pip install websocket-client

python scripts/headless_chrome.py --url "https://example.com"
python scripts/headless_chrome.py --url URL --js "document.title"
python scripts/headless_chrome.py --url URL --click ".el-checkbox" --wait-ms 2500
python scripts/headless_chrome.py --url URL --focus "#kw" --type "关键词" --enter
python scripts/headless_chrome.py --url URL --shot out.png
python scripts/headless_chrome.py --shutdown
```

- `--headless=new`，不弹出窗口
- 使用独立的临时 profile，不读取、不修改你日常浏览器的数据
- 默认把 UA 里的 `HeadlessChrome` 换成同版本 `Chrome`（部分站点否则直接回 412）

## 边界

- 只用于**公开页面**的检索与核对。
- 遇到验证码、滑块、登录墙、Cloudflare 人机验证：**停止自动化，转人工**，不绕过。
- 站点条款与比赛规则优先于本技能；请遵守所在赛事的合规要求。
- 题目的正确性最终以官方公布为准，本技能只保证「检索过程可复现、来源可回溯」。

## License

MIT

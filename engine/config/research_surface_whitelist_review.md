# 研究面白名单复核（research_surface.confirmed_hosts）

> 复核时间：2026-10-08｜复核对象：`config/compliance_policy.yaml` 的
> `research_surface.confirmed_hosts`
> 复核人：省赛淘汰赛执行体（供 Controller 审定）

## 1. 判定顺序（为什么白名单无法覆盖比赛面）

`scripts/compliance_gate.py` 的 `classify()` 顺序是**固定的**：

```
1. 比赛面（known_hosts ∪ host_suffix_patterns）  -> BLOCKED        ← 永远先判
2. confirmed_hosts                              -> ALLOWED
3. platform_entry_status 中已实测的公开主机       -> ALLOWED
4. 其他                                         -> UNKNOWN -> 需 Controller
```

因此**即使某个域名同时出现在比赛面与白名单里，比赛面判定也会先命中并 BLOCKED**。
白名单不可能把比赛面"放行"。

## 2. 匹配语义

- 后缀匹配，但要求「相等或以 `.` 结尾」。
- `github.com` 匹配 `github.com`、`api.github.com`；
  **不匹配** `notgithub.com`、`github.com.evil.test`。
- 比赛面 `xxsuyang.com` 同理：**不匹配** `evil-xxsuyang.com`（但该名字会落到
  UNKNOWN → 同样禁止自动化，见第 4 节）。

## 3. 逐条复核

| 主机 | 用途 | 证据来源 | 风险 | 结论 |
|---|---|---|---|---|
| `example.com` | 冒烟测试 / benchmark fixture 的占位 | IANA 保留的文档示例域，非真实服务 | 极低（无真实内容） | 保留 |
| `bing.com` / `cn.bing.com` | 站内限定搜索定位官方页 | 通用搜索引擎，用于 `site:` 检索 | 低；搜索摘要不得作为最终证据（已写入策略） | 保留 |
| `github.com` | M07 开源项目 / 模拟题多次点名 | `config/platforms.yaml` 已策展；模拟题 M07 锚点 | 低；GitHub 拥有其子域 | 保留 |
| `stats.gov.cn` | M09 开放数据，官方一手数据源 | `config/platforms.yaml`；官方国家统计局 | 低；政府域，子域归其所有 | 保留 |
| `modelscope.cn` | M07 魔搭社区，官方模型/数据集 | `config/platforms.yaml`；模拟题点名 | 低 | 保留 |
| `arxiv.org` | M24 预印本 | `config/platforms.yaml`；平台注册表 | 低 | 保留 |
| `nppa.gov.cn` | M11 期刊/刊号查询（国家新闻出版署） | `config/platforms.yaml` | 低；政府域 | 保留 |
| `nsfc.cn` | M25 国家自然科学基金结题项目 | **注意**：NSFC 主站是 `nsfc.gov.cn`；`kd.nsfc.cn` 是科学基金共享服务网（NSFC 运营） | **中**：`nsfc.cn` 与 `nsfc.gov.cn` 是两个不同注册域。白名单只应覆盖确实要访问的 `kd.nsfc.cn` | **建议收紧为 `kd.nsfc.cn`** |

## 4. 通配与相似域风险测试（已自动断言）

| 输入 | 期望 | 理由 |
|---|---|---|
| `https://www.stats.gov.cn/` | ALLOWED | 白名单子域 |
| `https://github.com/...` | ALLOWED | 白名单本域 |
| `https://notgithub.com/` | UNKNOWN（禁止自动化） | 非子域，不得误放行 |
| `https://github.com.evil.test/` | UNKNOWN（禁止自动化） | 后缀陷阱 |
| `https://evil-xxsuyang.com/` | UNKNOWN（禁止自动化） | 相似域，不是比赛面子域，但也不放行 |
| `https://csc.xxsuyang.com/*` | BLOCKED | 比赛面优先 |

`tests/test_provincial_compliance.py` 中 `test_suffix_matching_does_not_over_allow_lookalike_hosts`
与 `test_competition_suffix_does_not_match_lookalike` 固化了这些断言。

## 5. 浏览器级强制层（本次新增，2026-10-08）

白名单只作用于**路由器**。实测发现 `agent-browser` 的原始 CLI **没有任何域名拦截**
能力（`--allowed-domains` 与 `--cdp` 互斥），也就是说绕过路由器就能直接载入比赛页。

因此新增**浏览器级**隔离（`scripts/start_research_chrome.py`）：

```
--host-resolver-rules=MAP *.xxsuyang.com 127.0.0.1,
                      MAP xxsuyang.com 127.0.0.1,
                      MAP *.zxhnzq.com 127.0.0.1,
                      MAP zxhnzq.com 127.0.0.1
```

它只改写**本专用 Chrome** 的 DNS 解析，不关闭沙箱/安全浏览/证书检查，
也不影响日常 Chrome。三个后端共用这一个浏览器，因此一次性覆盖
CLI、MCP 及未来任何客户端。

## 6. 残余风险

1. `--host-resolver-rules` 依赖 DNS 层；若题目给出的比赛页是**纯 IP 直连**
   （如 `http://1.2.3.4/exam`），该规则不生效。此时仅剩路由器与 MCP 两层。
   **需要 Controller 确认比赛系统的确切访问方式。**
2. `nsfc.cn` 建议收紧为 `kd.nsfc.cn`（见第 3 节）。
3. 白名单是"允许自动化"的白名单，不是"可信"白名单；其中的内容仍需按
   🟠/🟢 证据分级处理。

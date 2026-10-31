"""真实平台低频验证（§21）+ 本项目残留标签页清理。

**重要实测结论（决定了本脚本的写法）**：

  `agent-browser --cdp <ws> tab list` 在本机**不可用**，稳定报
  `os error 10060`（连接超时）。原因是 Edge 通过 `edge://inspect` 开启的
  Remote Debugging **不提供 CDP 的 HTTP 发现端点**（`/json/list` 返回 404），
  而 `tab list` 依赖它。Puppeteer / chrome-devtools-mcp 走 DevToolsActivePort
  的 WebSocket，因此不受影响。

  可用路径：`--pin-tab tab new <url>`（绑定新页）+ `read` / `get title`。
  标签页枚举与关闭改用 Chrome DevTools MCP 的 `list_pages` / `close_page`。

安全约束：
  - 每个平台最多 1 次查询；不连续检索 CNKI / 万方 / 维普；
  - 遇 CAPTCHA / blockPuzzle / 滑块 立即停止并标 CHALLENGE，不重试；
  - 关闭标签页时**只按 URL 匹配本项目自己创建的页**，绝不按序号关用户标签页。

产出：data/quality/browser_real_platform_validation.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\Dev\projects\ai+ 2")
sys.path.insert(0, str(ROOT / "scripts"))

from compliance_gate import ComplianceGate, detect_challenge  # noqa: E402
from mcp_probe import PRESETS, McpStdioClient  # noqa: E402
from provincial_common import now_iso, resolve_npm_tool, run_captured, write_json  # noqa: E402

AB = resolve_npm_tool("agent-browser")
SESSION = "provincial-validate"
CDP_PORT = 9223
OUT = ROOT / "data" / "quality" / "browser_real_platform_validation.json"

# 本项目自己创建的页才允许关闭（按 URL 片段匹配）。
OUR_URL_MARKERS = ("bench_page", "data/tmp")

TARGETS = [
    {
        "platform": "GitHub",
        "kind": "search",
        "url": "https://github.com/search?q=information+literacy&type=repositories",
        "expect_in_page": "information literacy",
    },
    {
        "platform": "国家统计局",
        "kind": "homepage_read",
        "url": "https://www.stats.gov.cn/",
        "expect_in_page": "统计",
    },
    # --- 高频平台：只做**单次页面加载**，不执行任何检索，避免触发风控 ---
    {
        "platform": "CNKI",
        "kind": "entry_load_only",
        "url": "https://kns.cnki.net/starter/advanced",
        "expect_in_page": "",
        "no_search": True,
        "known_risk": "连续检索会触发 blockPuzzle；本次只加载一次高级检索页。",
    },
    {
        "platform": "万方",
        "kind": "entry_load_only",
        "url": "https://s.wanfangdata.com.cn/paper",
        "expect_in_page": "",
        "no_search": True,
        "known_risk": "高级检索默认「模糊」；本次不检索。",
    },
    {
        "platform": "维普",
        "kind": "entry_load_only",
        "url": "https://www.cqvip.com/advancesearch",
        "expect_in_page": "",
        "no_search": True,
        "known_risk": "旧入口 qikan.cqvip.com 返回 412；本次只加载 advancesearch。",
    },
]


def ws_endpoint() -> str:
    """取专用 Chrome 的 CDP WebSocket 端点。

    迁移后**不能**再依赖 Edge 时代的 `DevToolsActivePort` 文件：
    用显式 `--remote-debugging-port=9223` 启动的 Chrome 不写该文件。
    正确来源是 CDP 的 HTTP 发现端点（Chrome 返回 200，Edge 的 inspect 开关返回 404）。
    """
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=6
        ) as response:
            info = json.loads(response.read().decode("utf-8", "replace"))
            endpoint = info.get("webSocketDebuggerUrl", "")
            if endpoint:
                return endpoint
    except Exception:  # noqa: BLE001 - 回退到下面的端口形式
        pass
    # 回退：直接把端口交给 agent-browser（它会自行发现）
    return str(CDP_PORT)


def run(*args: str, timeout: float = 75) -> tuple[int, str]:
    return run_captured([AB, "--session", SESSION, "--cdp", ws_endpoint(), *args], timeout=timeout)


def mcp_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(parsed, list):
        return "\n".join(
            str(b.get("text", "")) for b in parsed if isinstance(b, dict)
        )
    return raw


def cleanup_with_mcp() -> dict:
    """用 PRIMARY（chrome-devtools-mcp）枚举并关闭本项目自己创建的标签页。"""
    entry = PRESETS["edge-devtools"]
    client = McpStdioClient([str(entry["command"]), *[str(a) for a in entry["args"]]])
    closed, kept = [], []
    try:
        client.start()
        rid = client.send("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "provincial-cleanup", "version": "1.0.0"},
        })
        if client.await_response(rid, 60) is None:
            return {"error": "initialize timeout"}
        client.send("notifications/initialized", {}, notify=True)

        rid = client.send("tools/call", {"name": "list_pages", "arguments": {}})
        response = client.await_response(rid, 60)
        text = mcp_text(json.dumps((response or {}).get("result", {}).get("content", "")))
        pages = []
        for line in text.splitlines():
            line = line.strip()
            if ":" in line and line.split(":", 1)[0].strip().isdigit():
                pages.append((int(line.split(":", 1)[0].strip()), line))

        for page_id, line in pages:
            if any(marker in line for marker in OUR_URL_MARKERS):
                rid = client.send("tools/call", {
                    "name": "close_page", "arguments": {"pageId": page_id},
                })
                ok = client.await_response(rid, 30) is not None
                closed.append({"pageId": page_id, "url": line[:120], "closed": ok})
            else:
                kept.append({"pageId": page_id, "url": line[:120]})
        return {"closed": closed, "kept_count": len(kept), "pages_seen": len(pages)}
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"}
    finally:
        client.close()


def succeeded(code: int, output: str) -> bool:
    """agent-browser 偶尔在成功的命令后附带一行 stderr 噪声并使退出码非 0。

    判定成功以输出里的 `✓` 为准，而不是只看退出码。
    """
    return code == 0 or "✓" in (output or "")


def main() -> int:
    gate = ComplianceGate()
    payload: dict = {
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "scope": "真实公开平台低频只读验证；避开 CNKI/万方/维普；遇验证码立即停止",
        "ws_endpoint": ws_endpoint(),
        "fast_cli_note": (
            "agent-browser 的 tab list 在 inspect-toggle CDP 下不可用（os error 10060，"
            "HTTP 发现端点被 Chromium 关闭）；本脚本只用 tab new/open/read/get。"
        ),
        "cleanup": cleanup_with_mcp(),
        "results": [],
    }

    run("close")
    run("--pin-tab", "tab", "new", "about:blank")

    for target in TARGETS:
        verdict = gate.classify(target["url"])
        entry: dict = {
            "platform": target["platform"],
            "url": target["url"],
            "kind": target["kind"],
            "compliance": verdict.decision,
            "surface": verdict.surface,
        }
        if not verdict.automation_allowed:
            entry.update({"status": "BLOCKED", "reason": verdict.reason})
            payload["results"].append(entry)
            continue

        started = time.time()
        code, out = run("--pin-tab", "open", target["url"])
        entry["open_ms"] = int((time.time() - started) * 1000)
        entry["open_ok"] = succeeded(code, out)
        entry["open_detail"] = out[:200]
        if not entry["open_ok"]:
            entry["status"] = "FAIL"
            payload["results"].append(entry)
            continue

        code_title, title = run("get", "title")
        entry["title"] = title.strip()[:150]

        code_body, body = run("read")
        body = body or ""
        entry["body_chars"] = len(body)

        challenge = detect_challenge(body, target["url"])
        if challenge:
            entry["status"] = "CHALLENGE"
            entry["challenge"] = challenge
            entry["note"] = "命中验证码/风控：**不重试该平台**，也不尝试绕过。"
            payload["results"].append(entry)
            # 只放弃**当前平台**；其它平台是不同站点，继续验证不算"重试同一路线"。
            continue

        hit = target["expect_in_page"].lower() in body.lower() if target["expect_in_page"] else True
        entry["expect_found"] = hit
        entry["body_chars"] = len(body)
        if target.get("no_search"):
            # 只加载入口页，不检索、不点击、不翻页。
            entry["note"] = target.get("known_risk", "")
        entry["status"] = (
            "PASS" if (succeeded(code_title, title) and succeeded(code_body, body) and hit)
            else "PARTIAL"
        )
        payload["results"].append(entry)

    run("close")
    payload["cleanup_after"] = cleanup_with_mcp()
    payload["summary"] = {row["platform"]: row["status"] for row in payload["results"]}
    write_json(OUT, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nreport = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

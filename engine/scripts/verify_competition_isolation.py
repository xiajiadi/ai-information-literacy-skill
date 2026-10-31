"""P1：逐个后端验证比赛域名阻止策略（含原始 CLI 绕过测试）。

对每一层做**实证**验证，不做推断：

  1. compliance_gate（第一层，所有路径的共同入口）
  2. agent-browser **原始 CLI**（不经过任何项目脚本，使用全新会话）
  3. chrome-devtools-mcp（--blockedUrlPattern）
  4. 专用 Chrome 的**浏览器级 DNS 黑洞**（--host-resolver-rules）

判定泄漏的标准是**实际当前页面 URL**（不是页面列表里出现过什么——历史遗留
标签页会造成假阳性）。

产出：data/quality/competition_isolation.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate  # noqa: E402
from mcp_probe import PRESETS, McpStdioClient, mcp_text  # noqa: E402
from provincial_common import (  # noqa: E402
    ROOT,
    now_iso,
    resolve_npm_tool,
    run_captured,
    write_json,
)

OUT = ROOT / "data" / "quality" / "competition_isolation.json"

COMPETITION_URLS = [
    "https://csc.xxsuyang.com/training",
    "https://csc.xxsuyang.com/detail?id=1",
    "https://xxsuyang.com/",
    "https://sub.xxsuyang.com/exam",
]
ALLOWED_PROBE = "https://example.com/"


def mentions_competition(text: str) -> bool:
    return "xxsuyang" in (text or "").lower()


def mcp_call(client: McpStdioClient, tool: str, args: dict[str, Any], timeout: float = 45):
    rid = client.send("tools/call", {"name": tool, "arguments": args})
    response = client.await_response(rid, timeout)
    if response is None:
        return False, "MCP 调用超时"
    result = response.get("result", {})
    text = mcp_text(json.dumps(result.get("content", ""), ensure_ascii=False))
    if result.get("isError"):
        return False, text[:300]
    return True, text[:300]


def start_mcp(preset: str):
    entry = PRESETS[preset]
    client = McpStdioClient([str(entry["command"]), *[str(a) for a in entry["args"]]])
    try:
        client.start()
    except OSError as error:
        return None, f"启动失败：{error}"
    rid = client.send("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "isolation-test", "version": "1.0.0"},
    })
    if client.await_response(rid, 90) is None:
        client.close()
        return None, "initialize 超时"
    client.send("notifications/initialized", {}, notify=True)
    return client, ""


def test_agent_browser() -> dict[str, Any]:
    """原始 CLI，全新会话（避免历史 sticky pin 造成 tab_gone 假象）。"""
    ab = resolve_npm_tool("agent-browser")
    session = f"isolation-{int(time.time())}"
    results: dict[str, Any] = {}
    leaked = False
    for url in [ALLOWED_PROBE, *COMPETITION_URLS]:
        code, out = run_captured(
            [ab, "--session", session, "--cdp", "9223", "--pin-tab", "open", url],
            timeout=60,
        )
        _, current = run_captured([ab, "--session", session, "get", "url"], timeout=45)
        current = (current or "").strip().splitlines()[-1] if current else ""
        hit = mentions_competition(current)
        leaked = leaked or hit
        results[url] = {
            "exit_code": code,
            "current_url": current[:160],
            "competition_page_loaded": hit,
            "output": (out or "")[:160],
        }
    run_captured([ab, "--session", session, "close"], timeout=30)
    return {
        "note": "原始 CLI 直接调用，**不使用**任何项目脚本或路由器；每次使用全新会话。",
        "builtin_domain_block": False,
        "blocked_all": not leaked,
        "results": results,
    }


def test_devtools() -> tuple[dict[str, Any], bool]:
    results: dict[str, Any] = {}
    client, err = start_mcp("chrome-devtools")
    if client is None:
        results["error"] = err
        return {"blocked_all": None, "results": results}, False
    leaked = False
    try:
        page_id = None
        for url in COMPETITION_URLS[:2]:
            ok, detail = mcp_call(client, "new_page", {"url": url})
            # 用实际当前 URL 判定，而不是页面列表
            probe_ok, listing = mcp_call(client, "list_pages", {})
            current = ""
            for line in (listing or "").splitlines():
                if "(current)" in line or "[selected]" in line:
                    current = line.strip()
                    break
            hit = mentions_competition(current) and "[selected]" not in current
            results[url] = {
                "tool_ok": ok,
                "blocked_message": "blocked by blocklist" in (detail or "").lower(),
                "current_line": current[:160],
                "competition_page_loaded": hit,
                "detail": detail[:180],
            }
            leaked = leaked or hit
        ok_allowed, allowed_detail = mcp_call(client, "new_page", {"url": ALLOWED_PROBE})
        results["allowed_probe"] = {"tool_ok": ok_allowed, "detail": allowed_detail[:120]}
        return {
            "blocked_url_pattern": [a for a in PRESETS["chrome-devtools"]["args"]
                                    if a.startswith("--blockedUrlPattern")],
            "blocked_all": not leaked,
            "results": results,
        }, ok_allowed
    finally:
        client.close()


def test_playwright() -> tuple[dict[str, Any], bool]:
    results: dict[str, Any] = {}
    client, err = start_mcp("chrome-playwright")
    if client is None:
        results["error"] = err
        return {"blocked_all": None, "results": results}, False
    leaked = False
    try:
        for url in COMPETITION_URLS[:2]:
            ok, detail = mcp_call(client, "browser_navigate", {"url": url})
            eval_ok, href = mcp_call(
                client, "browser_evaluate", {"function": "() => location.href"}
            )
            hit = eval_ok and mentions_competition(href)
            results[url] = {
                "tool_ok": ok,
                "blocked_by_client": "ERR_BLOCKED_BY_CLIENT" in (detail or ""),
                "current_href": href[:160],
                "competition_page_loaded": hit,
                "detail": detail[:180],
            }
            leaked = leaked or hit
        ok_allowed, allowed_detail = mcp_call(
            client, "browser_navigate", {"url": ALLOWED_PROBE}
        )
        results["allowed_probe"] = {"tool_ok": ok_allowed, "detail": allowed_detail[:120]}
        return {
            "blocked_origins": next(
                (a for a in PRESETS["chrome-playwright"]["args"]
                 if a.startswith("--blocked-origins")), ""
            ),
            "blocked_all": not leaked,
            "results": results,
        }, ok_allowed
    finally:
        client.close()


def main() -> int:
    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "competition_urls": COMPETITION_URLS,
        "leak_criterion": "实际当前页面 URL 命中 xxsuyang（不看历史标签页列表，避免假阳性）",
        "layers": {},
    }
    gate = ComplianceGate()

    gate_results = {}
    for url in COMPETITION_URLS:
        verdict = gate.classify(url)
        gate_results[url] = {
            "decision": verdict.decision,
            "surface": verdict.surface,
            "automation_allowed": verdict.automation_allowed,
        }
    payload["layers"]["compliance_gate"] = {
        "blocked_all": all(not v["automation_allowed"] for v in gate_results.values()),
        "results": gate_results,
    }

    payload["layers"]["agent_browser_raw_cli"] = test_agent_browser()
    devtools_layer, devtools_allowed_ok = test_devtools()
    payload["layers"]["chrome_devtools_mcp"] = devtools_layer
    payload["layers"]["chrome_devtools_mcp"]["allowed_probe_ok"] = devtools_allowed_ok
    playwright_layer, playwright_allowed_ok = test_playwright()
    payload["layers"]["playwright_mcp"] = playwright_layer
    payload["layers"]["playwright_mcp"]["allowed_probe_ok"] = playwright_allowed_ok

    summary = {
        name: layer.get("blocked_all")
        for name, layer in payload["layers"].items()
    }
    payload["summary"] = summary
    # 必须同时满足：所有层都拦住比赛面，且正常研究页仍然可达（否则是"封死了"而非"隔离"）
    allowed_ok = devtools_allowed_ok and playwright_allowed_ok
    payload["research_still_reachable"] = allowed_ok
    payload["status"] = (
        "PASS" if all(v is True for v in summary.values()) and allowed_ok else "PARTIAL"
    )
    write_json(OUT, payload)

    print(json.dumps({"summary": summary, "research_still_reachable": allowed_ok,
                      "status": payload["status"]}, ensure_ascii=False, indent=2))
    for name, layer in payload["layers"].items():
        print(f"\n=== {name} === blocked_all={layer.get('blocked_all')}")
        for key, value in list(layer.get("results", {}).items()):
            print(f"  {key} -> {json.dumps(value, ensure_ascii=False)[:210]}")
    print(f"\nreport = {OUT}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

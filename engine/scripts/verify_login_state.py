"""P1：登录态验收（隐私优先）。

规则：
  - **只**在明确的研究站点上判定登录状态；
  - **绝不**对 accounts.google.com / myaccount.google.com 等身份站点求值；
  - 只回传**布尔值**（是否存在退出登录入口 / 是否存在登录入口），
    不回传、不记录、不上传任何账户名、邮箱、头像、Cookie 或 Token；
  - 不导航到账户页，不点击任何元素。

产出：data/quality/login_state_verification.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_probe import PRESETS, McpStdioClient, mcp_text  # noqa: E402
from provincial_common import ROOT, now_iso, write_json  # noqa: E402

OUT = ROOT / "data" / "quality" / "login_state_verification.json"

# 身份站点黑名单：即使是用户打开的，也一律不求值、不读取。
IDENTITY_HOST_BLOCKLIST = (
    "accounts.google.com",
    "myaccount.google.com",
    "login.microsoftonline.com",
    "login.live.com",
    "appleid.apple.com",
    "passport.baidu.com",
    "login.taobao.com",
    "account.jetbrains.com",
)

# 允许判定登录态的研究站点（题目/交接资料里出现过的公开学术与学习平台）。
RESEARCH_HOSTS = (
    "cqvip.com",
    "cnki.net",
    "wanfangdata.com.cn",
    "icourse163.org",
    "github.com",
    "nsfc.cn",
    "stats.gov.cn",
    "ncpssd.org",
    "sciencedirect.com",
)

# 只返回布尔值，不返回任何文本内容、也不返回机构名称。
#
# 三态判定（修正过一次误判）：
#   个人账号已登录 -> 出现「退出 / 个人中心 / 我的知网」
#   机构（IP）已认证 -> 出现「个人登录」这类**切换到个人登录**的入口，
#                       同时**没有**个人账号的退出入口。
#                       未认证时这里只会是普通「登录」，不是「个人登录」。
#   匿名 -> 只有普通「登录 / 注册」
LOGIN_PROBE = """() => {
  const t = (document.body && document.body.innerText) || '';
  const personalAccount = /退出|注销|个人中心|我的知网|账户设置|log ?out|sign ?out|my account/i.test(t);
  const switchToPersonal = /个人登录|个人用户登录|切换到个人/.test(t);
  const institutional = /机构登录|机构用户|IP登录|机构认证|欢迎.{0,12}(大学|学院|图书馆)/.test(t);
  const plainLogin = /登录|注册|sign ?in|log ?in/i.test(t);
  return {
    hasPersonalAccountIndicator: personalAccount,
    hasSwitchToPersonalIndicator: switchToPersonal,
    hasInstitutionalIndicator: institutional,
    hasLoginIndicator: plainLogin,
    bodyLength: t.length
  };
}"""


def call(client: McpStdioClient, tool: str, args: dict[str, Any], timeout: float = 45):
    rid = client.send("tools/call", {"name": tool, "arguments": args})
    response = client.await_response(rid, timeout)
    if response is None:
        return False, "MCP 调用超时"
    result = response.get("result", {})
    text = mcp_text(json.dumps(result.get("content", ""), ensure_ascii=False))
    if result.get("isError"):
        return False, text[:300]
    return True, text


def host_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


# 会话类查询参数：config/platform_registry.json 的 url_cleaning 明确要求
# 「canonical URL 一律不带它，也不写进 JSON/YAML/Markdown/SQLite/logs」。
# 实测 CNKI 会在 URL 上带 uid=<session>，必须在此剥离，绝不落盘。
SESSION_QUERY_KEYS = {
    "uid", "token", "session", "sessionid", "cookie",
    "randomt", "queryid", "sid", "auth", "ticket", "code", "state",
}


def redact_url(url: str) -> str:
    """只保留 scheme://host/path（丢弃全部查询与片段），防止会话参数落盘。"""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "(unparsable)"
    if not parts.hostname:
        return url[:2] + "…" if url else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def classify_auth_state(
    personal: bool, switch_to_personal: bool, institutional: bool, has_login: bool
) -> str:
    """把探针布尔值映射成认证状态。

    为什么需要三态：机构（IP）认证**不会**出现个人账号的退出入口。
    早期只按「有退出=已登录」判定，把已通过机构认证的知网误判成未登录。
    机构态的可观测标志是「个人登录」这类**切换到个人登录**的入口——
    匿名访问时那里只会是普通「登录」。
    """
    if personal:
        return "AUTHENTICATED_PERSONAL"
    if switch_to_personal or institutional:
        return "AUTHENTICATED_INSTITUTIONAL"
    if has_login:
        return "ANONYMOUS"
    return "UNKNOWN"


def main() -> int:
    entry = PRESETS["chrome-devtools"]
    client = McpStdioClient([str(entry["command"]), *[str(a) for a in entry["args"]]])
    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "privacy": {
            "identity_hosts_never_probed": list(IDENTITY_HOST_BLOCKLIST),
            "returned_fields": ["host", "url", "page_id", "hasLogoutIndicator", "hasLoginIndicator"],
            "explicitly_not_collected": [
                "account name", "email", "avatar", "cookies", "tokens",
                "page text", "screenshots of account pages",
            ],
        },
        "probes": [],
        "identity_sessions_observed": [],
    }
    client.start()
    try:
        rid = client.send("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "login-verify", "version": "1.0.0"},
        })
        if client.await_response(rid, 90) is None:
            payload["error"] = "initialize 超时"
            return 1
        client.send("notifications/initialized", {}, notify=True)

        ok, listing = call(client, "list_pages", {})
        if not ok:
            payload["error"] = listing
            return 1

        pages: list[tuple[int, str]] = []
        for line in listing.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            head, _, rest = line.partition(":")
            if not head.strip().isdigit():
                continue
            pages.append((int(head.strip()), rest.strip()))

        # 1. 记录（但不读取）身份站点会话的存在性
        for page_id, line in pages:
            host = host_of(line[line.find("(") + 1: line.rfind(")")]) if "(" in line else ""
            if any(b in host for b in IDENTITY_HOST_BLOCKLIST) or "google" in host:
                payload["identity_sessions_observed"].append(
                    {"page_id": page_id, "host": host, "probed": False,
                     "reason": "身份站点：按隐私规则不求值、不读取"}
                )

        # 2. 只在研究站点上判定登录态
        probed = 0
        for page_id, line in pages:
            if "(" not in line or ")" not in line:
                continue
            url = line[line.find("(") + 1: line.rfind(")")]
            host = host_of(url)
            if not host or not any(host.endswith(h) for h in RESEARCH_HOSTS):
                continue
            if any(b in host for b in IDENTITY_HOST_BLOCKLIST):
                continue
            ok_sel, _ = call(client, "select_page", {"pageId": page_id})
            ok_eval, raw = call(
                client, "evaluate_script", {"pageId": page_id, "function": LOGIN_PROBE}
            )
            record: dict[str, Any] = {
                "page_id": page_id,
                "host": host,
                # 只记录 canonical（已剥离查询串），会话类参数绝不落盘
                "canonical_url": redact_url(url),
                "had_session_like_query": any(
                    key in url.lower() for key in SESSION_QUERY_KEYS
                ),
            }
            if ok_eval:
                # raw 是 MCP 文本包装，含我们自己的布尔对象 JSON
                start, end = raw.find("{"), raw.rfind("}")
                try:
                    parsed = json.loads(raw[start:end + 1])
                    personal = bool(parsed.get("hasPersonalAccountIndicator"))
                    switch_personal = bool(parsed.get("hasSwitchToPersonalIndicator"))
                    institutional = bool(parsed.get("hasInstitutionalIndicator"))
                    record.update({
                        "hasPersonalAccountIndicator": personal,
                        "hasSwitchToPersonalIndicator": switch_personal,
                        "hasInstitutionalIndicator": institutional,
                        "hasLoginIndicator": bool(parsed.get("hasLoginIndicator")),
                        "bodyLength": int(parsed.get("bodyLength") or 0),
                    })
                    # 三态：显式退出 > 切换个人登录/机构标识 > 仅普通登录
                    record["auth_state"] = classify_auth_state(
                        personal, switch_personal, institutional,
                        record["hasLoginIndicator"],
                    )
                    record["logged_in"] = record["auth_state"].startswith("AUTHENTICATED")
                except (ValueError, TypeError):
                    record["error"] = "无法解析探针结果"
            else:
                record["error"] = raw[:160]
            payload["probes"].append(record)
            probed += 1

        payload["probed_research_pages"] = probed
        payload["detected_logged_in_hosts"] = sorted(
            {p["host"] for p in payload["probes"] if p.get("logged_in")}
        )
        payload["status"] = "PASS" if probed else "NOT_DETECTED"
        return 0
    finally:
        client.close()
        write_json(OUT, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\nreport = {OUT}")


if __name__ == "__main__":
    raise SystemExit(main())

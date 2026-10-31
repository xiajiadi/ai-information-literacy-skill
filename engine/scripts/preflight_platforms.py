"""考试当天 7 平台 Preflight 探活。

只做入口可达性检查，不做深度检索。对每个平台探测：

    home          首页
    search        检索入口
    advanced      高级检索入口（有则记，无则记 NOT_APPLICABLE）
    pdf/ark       老师点名文档入口（UNESCO）

每条记录 status / final_url / redirect 链 / elapsed_ms / 是否跳登录。
登录判定基于最终 URL 与响应正文里的登录特征串，只做「疑似」标记，
不尝试任何登录动作。

用法：

    .venv\\Scripts\\python.exe scripts\\preflight_platforms.py
    .venv\\Scripts\\python.exe scripts\\preflight_platforms.py --json-only
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "quality" / "platform_preflight.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 登录/身份认证特征。命中只标记「疑似需要登录」，不代表一定不可公开访问。
LOGIN_MARKERS = (
    "login", "signin", "sign-in", "passport", "sso", "wayf", "oauth",
    "统一身份认证", "用户登录", "请先登录", "账号登录", "登录知网",
)

# 平台与入口清单。URL 是候选入口，实际可达性以本次探测结果为准。
PLATFORMS: list[dict[str, Any]] = [
    {
        "id": "unesco_digital_library",
        "name": "UNESCO Digital Library",
        "note": "老师点名平台；PDF 正文页 vs PDF 页码必须分开",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://unesdoc.unesco.org/"},
            {
                "kind": "ark",
                "name": "老师点名文档 pf0000393559",
                "url": "https://unesdoc.unesco.org/ark:/48223/pf0000393559",
            },
            {
                # 实测：真实 PDF 文件名带语言后缀（本题为 chi）。该路径只返回
                # SPA 外壳 HTML，真实下载端点 403 —— PDF 必须用浏览器打开。
                "kind": "ark_pdf",
                "name": "同文档 PDF（实测非直链）",
                "url": "https://unesdoc.unesco.org/ark:/48223/pf0000393559/PDF/393559chi.pdf",
            },
        ],
    },
    {
        "id": "cnki",
        "name": "中国知网",
        "note": "先选文献类型再进对应库；高级检索填裸表达式，专业检索才用 SU= 前缀",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://www.cnki.net/"},
            {"kind": "search", "name": "总库检索", "url": "https://kns.cnki.net/kns8s/search"},
            {"kind": "advanced", "name": "高级检索", "url": "https://kns.cnki.net/kns8s/AdvSearch"},
        ],
    },
    {
        "id": "cqvip",
        "name": "维普",
        "note": "期刊库为主；字段与 CNKI 不通用",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://www.cqvip.com/"},
            {"kind": "search", "name": "期刊检索", "url": "https://qikan.cqvip.com/Qikan/Search/Index"},
        ],
    },
    {
        "id": "wanfang",
        "name": "万方数据",
        "note": "高级检索先选文献类型；结果页左侧分组优先于逐条数",
        "entries": [
            {
                "kind": "home",
                "name": "首页",
                "url": "https://www.wanfangdata.com.cn/index.html?index=true",
            },
            {"kind": "search", "name": "检索页", "url": "https://s.wanfangdata.com.cn/paper"},
            {
                "kind": "deep",
                "name": "万方智研（独立路由）",
                "url": "https://zhiyan.wanfangdata.com.cn/",
            },
        ],
    },
    {
        "id": "pubmed",
        "name": "PubMed",
        "note": "优先生成可复制检索式；字段标记不可套用到其它库",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://pubmed.ncbi.nlm.nih.gov/"},
            {"kind": "advanced", "name": "Advanced Search", "url": "https://pubmed.ncbi.nlm.nih.gov/advanced/"},
            {"kind": "mesh", "name": "MeSH Database", "url": "https://www.ncbi.nlm.nih.gov/mesh/"},
        ],
    },
    {
        "id": "icourse163",
        "name": "中国大学MOOC",
        "note": "必须核对学校+教师避免同名课程；目录 30 秒展不开转人工",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://www.icourse163.org/"},
            {
                "kind": "search",
                "name": "课程搜索（示例词）",
                "url": "https://www.icourse163.org/search.htm?search=%E4%BF%A1%E6%81%AF%E7%B4%A0%E5%85%BB",
            },
        ],
    },
    {
        "id": "sciencedirect",
        "name": "ScienceDirect",
        "note": "截词与布尔规则不与 IEEE/PubMed 通用；优先 Advanced Search 或期刊内检索",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://www.sciencedirect.com/"},
            {"kind": "advanced", "name": "Advanced Search", "url": "https://www.sciencedirect.com/search"},
            {"kind": "deep", "name": "LeapSpace", "url": "https://www.sciencedirect.com/leapspace"},
        ],
    },
    {
        "id": "ieee_xplore",
        "name": "IEEE Xplore",
        "note": "题目写明 IEEE Xplore 时直接进高级检索，不要从 ieee.org 首页点击",
        "entries": [
            {
                "kind": "advanced",
                "name": "Advanced Search",
                "url": "https://ieeexplore.ieee.org/search/advanced",
            },
        ],
    },
    {
        "id": "cnipa",
        "name": "CNIPA 专利检索",
        "note": "具体检索题走 conventionalSearch；导航页仅在不知入口时用",
        "entries": [
            {
                "kind": "entry",
                "name": "常规检索",
                "url": "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch",
            },
            {
                "kind": "home",
                "name": "官方导航页",
                "url": "https://www.cnipa.gov.cn/col/col171/index.html",
            },
        ],
    },
    {
        "id": "nsfc",
        "name": "国家自然科学基金",
        "note": "结题项目题直接进 finalProjectInit，不要从首页找「信息检索」",
        "entries": [
            {
                "kind": "entry",
                "name": "结题项目",
                "url": "https://kd.nsfc.cn/finalProjectInit",
            },
            {"kind": "home", "name": "首页", "url": "https://kd.nsfc.cn/"},
        ],
    },
    {
        "id": "ncpssd",
        "name": "国家哲学社会科学文献中心",
        "note": "用户实际可用入口 NCPSD_MAIN；期刊/集刊/CSSCI 来源筛选",
        "entries": [
            {"kind": "home", "name": "首页", "url": "https://www.ncpssd.org/index"},
        ],
    },
    {
        "id": "wenjuanxing",
        "name": "问卷星",
        "note": "依赖登录态，优先用户 Edge；canonical 不含 randomt",
        "entries": [
            {
                "kind": "dashboard",
                "name": "我的问卷后台",
                "url": "https://www.wjx.cn/newwjx/manage/myquestionnaires.aspx",
            },
        ],
    },
    {
        "id": "douyin_creator",
        "name": "抖音创作者中心",
        "note": "依赖登录态；出现二维码/扫码立即转人工",
        "entries": [
            {
                "kind": "dashboard",
                "name": "算术指数",
                "url": "https://creator.douyin.com/creator-micro/creator-count/arithmetic-index",
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Microsoft Edge 检测
#
# 只探测「安装位置 / Profile 列表 / 是否运行 / 是否可安全接管」。
# 绝不读取 Cookie、Login Data、加密密钥等认证数据；登录态一律不推断。
# ---------------------------------------------------------------------------

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# 需要在用户 Edge 中人工确认登录态的平台。自动化不做推断。
EDGE_LOGIN_PLATFORMS = (
    ("CNKI", "https://www.cnki.net/"),
    ("维普", "https://www.cqvip.com/"),
    ("万方", "https://www.wanfangdata.com.cn/index.html?index=true"),
    ("中国大学MOOC", "https://www.icourse163.org/"),
    ("智慧树", "https://www.zhihuishu.com/"),
)


def detect_edge() -> dict[str, Any]:
    """探测本机 Microsoft Edge 的安装、Profile 与运行状态。"""
    import os
    import subprocess

    result: dict[str, Any] = {
        "executable": "",
        "version": "",
        "user_data_dir": "",
        "profiles": [],
        "running": False,
        "process_count": 0,
        "cdp_attach_available": False,
        "reuse_login_state_available": False,
        "reuse_blocked_reason": "",
    }

    for candidate in EDGE_CANDIDATES:
        if Path(candidate).exists():
            result["executable"] = candidate
            break
    if not result["executable"]:
        result["reuse_blocked_reason"] = "未找到 msedge.exe"
        return result

    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-Item '{result['executable']}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=30,
        )
        result["version"] = (completed.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    user_data = Path(local_appdata) / "Microsoft" / "Edge" / "User Data" if local_appdata else None
    if user_data and user_data.exists():
        result["user_data_dir"] = str(user_data)
        local_state = user_data / "Local State"
        if local_state.exists():
            try:
                # 只取 profile 名称与目录；Local State 里的加密密钥一律不碰。
                payload = json.loads(local_state.read_text(encoding="utf-8", errors="replace"))
                info = (payload.get("profile") or {}).get("info_cache") or {}
                result["profiles"] = [
                    {"directory": key, "name": (value or {}).get("name", "")}
                    for key, value in info.items()
                ]
                result["last_used_profile"] = (payload.get("profile") or {}).get("last_used", "")
            except (OSError, json.JSONDecodeError, AttributeError, TypeError):
                pass

    # Edge 是否正在运行，以及有没有可安全接管的远程调试端口。
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        lines = [l for l in (completed.stdout or "").splitlines() if l.strip()]
        result["process_count"] = len(lines)
        result["running"] = bool(lines)
        temp_root = os.path.join(os.environ.get("TEMP", ""), "agent-browser-chrome-")
        real = [l for l in lines if l.split("|", 1)[-1] and temp_root not in l.split("|", 1)[-1]]
        result["cdp_attach_available"] = any(
            "--remote-debugging-port=" in l.split("|", 1)[-1]
            and "--remote-debugging-port=0" not in l.split("|", 1)[-1]
            for l in real
        )
    except (OSError, subprocess.SubprocessError):
        pass

    if result["running"] and not result["cdp_attach_available"]:
        result["reuse_blocked_reason"] = (
            "Edge 正在运行且未开启远程调试端口；按安全规则不得强占 Profile、"
            "不得删除锁文件，因此自动化无法复用登录态。"
        )
    elif result["running"]:
        result["reuse_login_state_available"] = True
    else:
        result["reuse_login_state_available"] = True

    return result


def _ssl_context() -> ssl.SSLContext:
    """部分国内站点证书链不完整，探活不应因此判死。"""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def probe(entry: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = entry["url"]
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    )
    started = time.monotonic()
    record: dict[str, Any] = {
        "kind": entry.get("kind", ""),
        "name": entry.get("name", ""),
        "url": url,
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            body = response.read(60_000).decode("utf-8", errors="replace")
            final_url = response.geturl()
            record.update(
                ok=True,
                status=response.status,
                final_url=final_url,
                redirected=final_url.rstrip("/") != url.rstrip("/"),
                bytes=len(body),
            )
            haystack = (final_url + " " + body[:4000]).lower()
            hits = [m for m in LOGIN_MARKERS if m.lower() in haystack]
            record["login_suspected"] = bool(hits)
            record["login_markers"] = hits[:4]
            # 正文过短通常意味着 JS 壳页面：HTTP 可达但需要浏览器渲染。
            record["likely_js_shell"] = len(body) < 2000
    except urllib.error.HTTPError as exc:
        # 4xx 说明主机有响应。403/429 多为 WAF/限流，不是「站点挂了」。
        record.update(
            ok=exc.code < 500,
            status=exc.code,
            classification="HTTP_RESPONSE",
            note="WAF/限流或需登录，主机可达" if exc.code in (401, 403, 429) else "",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        record.update(ok=False, status=None, classification=type(exc).__name__, error=str(exc)[:200])
    record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--json-only", action="store_true", help="只输出 JSON，不打印表格")
    args = parser.parse_args()

    jobs: list[tuple[str, str, dict]] = []
    for platform in PLATFORMS:
        for entry in platform["entries"]:
            jobs.append((platform["id"], platform["name"], entry))

    results: dict[str, list[dict]] = {p["id"]: [] for p in PLATFORMS}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(probe, entry, args.timeout): (pid, pname)
            for pid, pname, entry in jobs
        }
        for future in as_completed(futures):
            pid, _pname = futures[future]
            results[pid].append(future.result())

    platforms_out = []
    for platform in PLATFORMS:
        entries = sorted(results[platform["id"]], key=lambda r: r["url"])
        reachable = [e for e in entries if e.get("ok")]
        platforms_out.append(
            {
                "id": platform["id"],
                "name": platform["name"],
                "note": platform["note"],
                "home_reachable": any(e["kind"] in ("home", "ark") and e.get("ok") for e in entries),
                "reachable_count": len(reachable),
                "entry_count": len(entries),
                "status": "PASS" if reachable else "FAIL",
                "entries": entries,
            }
        )

    edge = detect_edge()
    edge["platform_login_state"] = [
        {
            "platform": name,
            "url": url,
            # 登录态必须在用户 Edge 中人工确认；自动化不读取认证数据，因此不推断。
            "edge_reachable": "UNVERIFIED",
            "logged_in": "UNKNOWN",
            "login_required": "UNKNOWN",
            "automation_operable": "UNKNOWN",
        }
        for name, url in EDGE_LOGIN_PLATFORMS
    ]

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform_count": len(platforms_out),
        "passed": sum(1 for p in platforms_out if p["status"] == "PASS"),
        "failed": sorted(p["id"] for p in platforms_out if p["status"] != "PASS"),
        "platforms": platforms_out,
        "edge": edge,
        "default_browser": "Microsoft Edge",
    }

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json_only:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"{'平台':<24}{'入口':<22}{'状态':<7}{'耗时':>8}  最终地址/备注")
    print("-" * 110)
    for platform in platforms_out:
        for entry in platform["entries"]:
            status = "OK" if entry.get("ok") else "FAIL"
            marker = ""
            if entry.get("login_suspected"):
                marker = " [疑似登录]"
            elif entry.get("likely_js_shell"):
                marker = " [JS壳]"
            elif entry.get("note"):
                marker = f" [{entry['note']}]"
            print(
                f"{platform['name']:<24}{entry['name']:<22}{status:<7}"
                f"{entry['elapsed_ms']:>7.0f}ms  {entry.get('final_url') or entry.get('classification','')}{marker}"
            )
    print("-" * 110)
    print(f"通过 {payload['passed']}/{payload['platform_count']}；失败：{payload['failed'] or '无'}")

    print()
    print("=== Microsoft Edge ===")
    print(f"Edge executable：{edge['executable'] or '未找到'}")
    print(f"Edge version：   {edge['version'] or '未知'}")
    print(f"Edge active profile：{_active_profile(edge)}")
    print(f"复用登录态：     {'YES' if edge['reuse_login_state_available'] else 'NO'}")
    if edge["reuse_blocked_reason"]:
        print(f"  原因：{edge['reuse_blocked_reason']}")
    print(f"Playwright Edge：{'可用' if edge['executable'] else '不可用（未找到 msedge.exe）'}")
    print("默认 Browser：   Microsoft Edge")
    print()
    print("平台登录态（需在你的 Edge 中人工确认，自动化不读取认证数据）：")
    print(f"  {'平台':<16}{'Edge可达':<12}{'已登录':<10}{'需登录':<10}{'自动化可操作'}")
    for row in edge["platform_login_state"]:
        print(f"  {row['platform']:<16}{row['edge_reachable']:<12}{row['logged_in']:<10}"
              f"{row['login_required']:<10}{row['automation_operable']}")

    print()
    print(f"报告：{output}")
    return 0


def _active_profile(edge: dict[str, Any]) -> str:
    profiles = edge.get("profiles") or []
    if not profiles:
        return "未检测到"
    if len(profiles) == 1:
        return f"{profiles[0]['directory']}（{profiles[0]['name']}）—— 唯一 Profile，即当前活动"
    last = edge.get("last_used_profile") or ""
    for profile in profiles:
        if profile["directory"] == last:
            return f"{profile['directory']}（{profile['name']}）"
    return "、".join(p["directory"] for p in profiles)


if __name__ == "__main__":
    raise SystemExit(main())

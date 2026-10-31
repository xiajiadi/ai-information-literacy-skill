"""浏览器栈健康检查（§24）。

只做**只读探测**。禁止：登录任何网站、触发真实检索、启动浏览器导航。

输出：

    EDGE             PASS / FAIL
    REMOTE_DEBUG     PASS / FAIL
    AGENT_BROWSER    PASS / FAIL
    DEVTOOLS_MCP     PASS / PARTIAL / FAIL
    PLAYWRIGHT_MCP   PASS / PARTIAL / MANUAL_REQUIRED / FAIL
    DSH_MCP          PASS / PARTIAL / FAIL

产出：data/quality/browser_stack_health.json

用法：
    uv run python scripts/check_browser_stack.py
    uv run python scripts/check_browser_stack.py --json
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    ROOT,
    load_json,
    load_yaml,
    now_iso,
    resolve_npm_tool,
    run_captured,
    write_json,
)

BROWSER_STACK_PATH = ROOT / "config" / "browser_stack.yaml"
VERSIONS_PATH = ROOT / "config" / "browser_versions.json"
HEALTH_PATH = ROOT / "data" / "quality" / "browser_stack_health.json"
PRIMARY_PATCH = ROOT / "config" / "dsh" / "primary-chrome-devtools.patch.yml"
FALLBACK_PATCH = ROOT / "config" / "dsh" / "fallback-chrome-playwright.patch.yml"
LEGACY_EDGE_DIR = ROOT / "config" / "dsh" / "legacy-edge"

PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"
MANUAL_REQUIRED = "MANUAL_REQUIRED"

PROBE_TIMEOUT = 60


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _run(cmd: list[str], timeout: int = PROBE_TIMEOUT) -> tuple[int, str]:
    # 用 run_captured（临时文件而不是管道）：agent-browser 的常驻 daemon 会继承
    # 管道句柄，用 capture_output 会阻塞到超时。
    return run_captured(cmd, timeout=timeout)


def find_edge_processes() -> list[dict[str, Any]]:
    return _chrome_family_processes("msedge.exe")


def find_chrome_processes_for_profile(profile_dir: str) -> list[dict[str, Any]]:
    """只返回**使用本项目专用 Profile** 的 chrome.exe（按命令行精确匹配）。

    不按进程名判定归属，避免把日常 Chrome 误算进来。
    """
    rows = [
        row for row in _cim_processes() if str(row.get("Name", "")).lower() == "chrome.exe"
    ]
    marker = str(profile_dir).lower()
    return [
        row for row in rows
        if row.get("CommandLine") and marker in str(row["CommandLine"]).lower()
    ]


def _cim_processes() -> list[dict[str, Any]]:
    code, raw = _run([
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process "
        "| Select-Object ProcessId,ParentProcessId,Name,CommandLine "
        "| ConvertTo-Json -Compress -Depth 3",
    ], timeout=150)
    if code != 0 or not (raw or "").strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [r for r in rows if isinstance(r, dict)]


def _chrome_family_processes(image_name: str) -> list[dict[str, Any]]:
    code, out = _run([
        "powershell", "-NoProfile", "-Command",
        f"Get-Process {image_name.replace('.exe','')} -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName | ConvertTo-Json -Compress",
    ], timeout=60)
    if code != 0 or not out:
        return []
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def devtools_port_file(stack: dict[str, Any]) -> Path:
    return Path(stack["browser"]["edge"]["devtools_active_port_file"])


def read_devtools_port(path: Path) -> tuple[int | None, str]:
    if not path.exists():
        return None, ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return None, str(error)
    if not lines:
        return None, ""
    try:
        return int(lines[0].strip()), (lines[1].strip() if len(lines) > 1 else "")
    except ValueError:
        return None, lines[0]


def port_reachable(port: int, host: str = "127.0.0.1") -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def check_edge(stack: dict[str, Any]) -> CheckResult:
    """CHROME：专用研究 Chrome 是否在运行，且用的是专用 Profile。"""
    chrome = stack["browser"]["chrome"]
    exe = Path(chrome["executable"])
    profile = chrome["user_data_dir"]
    if not exe.exists():
        return CheckResult("CHROME", FAIL, f"未找到 Chrome 可执行文件：{exe}")
    processes = find_chrome_processes_for_profile(profile)
    if not processes:
        return CheckResult(
            "CHROME", PARTIAL,
            f"专用 Chrome 未运行（{exe} 存在）。请运行 scripts/start_research_chrome.py。",
            {"executable": str(exe), "profile": profile, "running": False},
        )
    daily = Path.home() / "AppData/Local/Google/Chrome/User Data"
    return CheckResult(
        "CHROME", PASS,
        f"专用 Chrome 运行中，{len(processes)} 个进程；profile={profile}",
        {
            "executable": str(exe),
            "profile": profile,
            "running": True,
            "process_count": len(processes),
            "is_dedicated_profile": str(profile) != str(daily),
        },
    )


def check_remote_debug(stack: dict[str, Any]) -> CheckResult:
    """CDP：专用 Chrome 的 CDP 端口是否可达（HTTP 发现应当返回 200）。"""
    chrome = stack["browser"]["chrome"]
    port = int(chrome["remote_debugging"]["port"])
    address = chrome["remote_debugging"]["address"]
    reachable = port_reachable(port, address)
    info: dict[str, Any] = {"port": port, "address": address, "tcp_reachable": reachable}
    browser = ""
    http_ok = False
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"http://{address}:{port}/json/version", timeout=5
        ) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
            browser = payload.get("Browser", "")
            http_ok = True
    except Exception as error:  # noqa: BLE001
        info["http_error"] = str(error)[:120]
    info["http_discovery_ok"] = http_ok
    info["browser"] = browser

    if reachable and http_ok:
        return CheckResult(
            "REMOTE_DEBUG", PASS,
            f"CDP {address}:{port} 可达，HTTP 发现正常（200）；{browser}",
            info,
        )
    if reachable:
        return CheckResult(
            "REMOTE_DEBUG", PARTIAL,
            f"CDP 端口 {port} 可达但 HTTP 发现失败：{info.get('http_error', '')}",
            info,
        )
    return CheckResult(
        "REMOTE_DEBUG", FAIL,
        f"CDP {address}:{port} 不可达。请运行 scripts/start_research_chrome.py",
        info,
    )


def _legacy_check_remote_debug(stack: dict[str, Any]) -> CheckResult:
    path = devtools_port_file(stack)
    if not path.exists():
        return CheckResult(
            "REMOTE_DEBUG", FAIL,
            "DevToolsActivePort 不存在 -> Edge 未开启 Remote Debugging。"
            "需要用户操作：Edge → edge://inspect → Remote debugging → "
            "勾选 Allow remote debugging for this browser instance。",
            {"devtools_active_port_file": str(path), "exists": False},
        )
    port, ws_path = read_devtools_port(path)
    if not port:
        return CheckResult(
            "REMOTE_DEBUG", FAIL,
            f"DevToolsActivePort 存在但无法解析端口：{ws_path}",
            {"devtools_active_port_file": str(path), "exists": True},
        )
    reachable = port_reachable(port)
    return CheckResult(
        "REMOTE_DEBUG", PASS if reachable else PARTIAL,
        f"DevToolsActivePort 端口 {port} " + ("可达" if reachable else "不可达"),
        {
            "devtools_active_port_file": str(path),
            "exists": True,
            "port": port,
            "websocket_path_present": bool(ws_path),
            "port_reachable": reachable,
        },
    )


def check_agent_browser() -> CheckResult:
    wrapper = shutil.which("agent-browser")
    if not wrapper:
        return CheckResult("AGENT_BROWSER", FAIL, "PATH 上找不到 agent-browser。")
    code, out = _run([wrapper, "--version"])
    version = out.splitlines()[0] if out else ""
    if code != 0:
        return CheckResult("AGENT_BROWSER", FAIL, f"agent-browser --version 失败：{out[:200]}")
    return CheckResult(
        "AGENT_BROWSER", PASS,
        f"{version}（{wrapper}）",
        {"path": str(wrapper), "version": version},
    )


def npx_cache_lookup(package: str) -> str:
    """在 npx 缓存里找已下载的包版本，避免每次健康检查都联网。"""
    cache_root = Path(os.environ.get("LOCALAPPDATA", "")) / "npm-cache" / "_npx"
    if not cache_root.exists():
        return ""
    for manifest in cache_root.glob(f"*/node_modules/{package}/package.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return str(data.get("version", ""))
    return ""


def check_mcp_package(package: str, pinned: str, registry_timeout: int = 45) -> tuple[str, str]:
    cached = npx_cache_lookup(package)
    if cached:
        return cached, "npx cache"
    npm = resolve_npm_tool("npm")
    code, out = _run([npm, "view", package, "version"], timeout=registry_timeout)
    if code == 0 and out:
        return out.splitlines()[-1].strip(), "npm registry"
    return "", f"unreachable: {out[:120]}"


def check_devtools_mcp(versions: dict[str, Any]) -> CheckResult:
    pinned = str(versions["versions"]["chrome-devtools-mcp"]["version"])
    found, source = check_mcp_package("chrome-devtools-mcp", pinned)
    if not found:
        return CheckResult("DEVTOOLS_MCP", FAIL, f"无法确认 chrome-devtools-mcp 可用：{source}")
    status = PASS if found == pinned else PARTIAL
    return CheckResult(
        "DEVTOOLS_MCP", status,
        f"registry/cache 版本 {found}（锁定 {pinned}，来源 {source}）",
        {"pinned": pinned, "found": found, "source": source},
    )


def playwright_extension_state(stack: dict[str, Any]) -> tuple[str, str]:
    """迁移后 FALLBACK 走 CDP，不再需要扩展。

    仍保留检测，仅用于 Edge 回滚路线与既有环境说明。
    """
    edge = stack["browser"].get("edge_legacy", {})
    user_data = Path(edge.get("user_data_dir", ""))
    if not user_data.exists():
        return "NOT_APPLICABLE", "迁移到 --cdp-endpoint 后不再需要 Playwright 扩展"
    extensions = user_data / "Default" / "Extensions"
    if not extensions.exists():
        return "NOT_APPLICABLE", "迁移到 --cdp-endpoint 后不再需要 Playwright 扩展"
    for manifest in list(extensions.glob("*/manifest.json")) + list(
        extensions.glob("*/*/manifest.json")
    ):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if "playwright" in json.dumps(data).lower():
            return "INSTALLED", f"{data.get('name')} v{data.get('version')}"
    return "NOT_APPLICABLE", "迁移到 --cdp-endpoint 后不再需要 Playwright 扩展"


def check_playwright_mcp(stack: dict[str, Any], versions: dict[str, Any]) -> CheckResult:
    pinned = str(versions["versions"]["playwright-mcp"]["version"])
    found, source = check_mcp_package("@playwright/mcp", pinned)
    ext_state, ext_detail = playwright_extension_state(stack)
    fallback = stack["backends"]["fallback"]
    evidence = {
        "pinned": pinned, "found": found, "source": source,
        "extension_state": ext_state, "extension_detail": ext_detail,
        "connection_mode": fallback["connection_mode"],
        "cdp_endpoint": fallback["cdp_endpoint"],
        "extension_required": fallback["extension_required"],
    }
    if not found:
        return CheckResult("PLAYWRIGHT_MCP", FAIL, f"MCP 包不可用：{source}", evidence)
    # CDP 模式下不再要求浏览器扩展
    if fallback["extension_required"] is False and fallback["connection_mode"] == "cdp-endpoint":
        return CheckResult(
            "PLAYWRIGHT_MCP", PASS,
            f"包 {found}；以 {fallback['cdp_endpoint']} CDP 连接，无需浏览器扩展（{ext_detail}）",
            evidence,
        )
    if ext_state == "INSTALLED":
        return CheckResult("PLAYWRIGHT_MCP", PASS, f"包 {found}；扩展已安装：{ext_detail}", evidence)
    return CheckResult(
        "PLAYWRIGHT_MCP", MANUAL_REQUIRED,
        f"包 {found} 可用，但当前为扩展模式且未安装扩展。", evidence,
    )


def check_dsh_mcp(stack: dict[str, Any]) -> CheckResult:
    dsh_home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
    profiles_root = dsh_home / "profiles"
    plugin = profiles_root / "node_modules" / "@deepseek-ai" / "dsh-mcp-client" / "package.json"
    evidence: dict[str, Any] = {"dsh_home": str(dsh_home), "plugin_manifest": str(plugin)}

    if not plugin.exists():
        return CheckResult(
            "DSH_MCP", FAIL,
            f"未找到 @deepseek-ai/dsh-mcp-client：{plugin}", evidence,
        )
    try:
        version = json.loads(plugin.read_text(encoding="utf-8")).get("version", "")
    except (OSError, json.JSONDecodeError) as error:
        return CheckResult("DSH_MCP", FAIL, f"插件 manifest 不可读：{error}", evidence)
    evidence["plugin_version"] = version

    configured = False
    for patch in (PRIMARY_PATCH, FALLBACK_PATCH):
        if not patch.exists():
            continue
        text = patch.read_text(encoding="utf-8", errors="replace")
        if "dsh-mcp-client" in text:
            configured = True
            evidence.setdefault("patch_files", []).append(str(patch))

    profile_patch = profiles_root / "web" / "cordis.patch.yml"
    evidence["profile_patch"] = str(profile_patch)
    live_configured = False
    if profile_patch.exists():
        live_configured = "dsh-mcp-client" in profile_patch.read_text(
            encoding="utf-8", errors="replace"
        )
    evidence["configured_in_live_profile"] = live_configured

    if live_configured:
        return CheckResult("DSH_MCP", PASS, f"插件 {version}，已写入活动 profile", evidence)
    if configured:
        return CheckResult(
            "DSH_MCP", PARTIAL,
            f"插件 {version} 已安装，overlay 已就绪但尚未写入活动 profile（需重启/HMR 后生效）",
            evidence,
        )
    return CheckResult("DSH_MCP", FAIL, f"插件 {version} 已安装，但没有可用的 overlay 配置", evidence)


def run_health() -> dict[str, Any]:
    stack = load_yaml(BROWSER_STACK_PATH)
    versions = load_json(VERSIONS_PATH)
    checks = [
        check_edge(stack),
        check_remote_debug(stack),
        check_agent_browser(),
        check_devtools_mcp(versions),
        check_playwright_mcp(stack, versions),
        check_dsh_mcp(stack),
    ]
    summary = {c.name: c.status for c in checks}
    payload = {
        "generated_at": now_iso(),
        "agent": "Provincial Elimination Executor",
        "scope": "只读探测；不登录网站、不触发真实检索、不启动页面导航",
        "browser": "dedicated-google-chrome",
        "checks": [c.__dict__ for c in checks],
        "summary": summary,
        "ready_for_smoke": all(
            summary.get(name) in {PASS, PARTIAL}
            for name in ("CHROME", "REMOTE_DEBUG", "AGENT_BROWSER")
        ),
        # PRIMARY 需要专用 Chrome 在跑且 CDP 通；FALLBACK 走同一 CDP 端点。
        "primary_backend_ready": (
            summary.get("REMOTE_DEBUG") == PASS and summary.get("CHROME") == PASS
        ),
        "fallback_backend_ready": summary.get("PLAYWRIGHT_MCP") in {PASS, PARTIAL},
    }
    write_json(HEALTH_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    payload = run_health()
    if "--json" in args:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for check in payload["checks"]:
            print(f"{check['name']:16s} {check['status']:16s} {check['detail'][:150]}")
        print()
        print(f"primary_backend_ready = {payload['primary_backend_ready']}")
        print(f"ready_for_smoke       = {payload['ready_for_smoke']}")
        print(f"report = {HEALTH_PATH}")
    return 0 if payload["primary_backend_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""浏览器执行栈契约测试（ADDENDUM §1–§29）。

覆盖：
  - 三条已冻结路线与浏览器优先级
  - Backend Router 的全部决策分支
  - Tab 隔离（Research Tab / Competition Tab / TAB_GONE）
  - DSH MCP overlay 可解析且不含凭证
  - 版本固定与比赛当天禁止升级
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from browser_router import (  # noqa: E402
    AGENT_BROWSER,
    BACKEND_ORDER,
    BLOCKED_COMPETITION,
    DIRECT,
    EDGE_DEVTOOLS_MCP,
    HUMAN_REQUIRED,
    PLAYWRIGHT_MCP,
    TAB_GONE,
    BackendRouter,
    BrowserTask,
    build_backend_plan,
    load_browser_stack,
)
from provincial_common import (  # noqa: E402
    ROOT,
    load_json,
    load_yaml,
    parse_yaml_subset,
    patch_inserted_entries,
    resolve_npm_tool,
)

STACK_PATH = ROOT / "config" / "browser_stack.yaml"
VERSIONS_PATH = ROOT / "config" / "browser_versions.json"
PRIMARY_PATCH = ROOT / "config" / "dsh" / "primary-edge-devtools.patch.yml"
FALLBACK_PATCH = ROOT / "config" / "dsh" / "fallback-edge-playwright.patch.yml"

RESEARCH_URL = "https://www.icourse163.org/search.htm"
COMPETITION_URL = "https://csc.xxsuyang.com/training"

SECRET_MARKERS = ("cookie", "password", "token", "secret", "authorization")


@pytest.fixture(scope="module")
def stack():
    return load_browser_stack()


@pytest.fixture(scope="module")
def router(stack):
    return BackendRouter(stack=stack)


# ---------------------------------------------------------------------------
# 配置契约
# ---------------------------------------------------------------------------

def test_primary_browser_is_a_dedicated_chrome(stack):
    """2026-10-08 迁移：研究浏览器改为**专用** Google Chrome。

    关键约束不是「不能用 Chrome」，而是「不能碰日常 Chrome Profile」。
    """
    browser = stack["browser"]
    assert browser["primary"] == "chrome"
    assert browser["never_modify_daily_chrome_profile"] is True
    chrome = browser["chrome"]
    assert chrome["is_dedicated_profile"] is True
    assert chrome["copies_edge_user_data"] is False
    assert chrome["incognito"] is False
    assert chrome["temporary_profile"] is False
    # 专用 Profile 必须在项目工具目录下，且不是用户的日常 Chrome 目录
    assert chrome["user_data_dir"] == "D:\\Dev\\tools\\provincial-chrome-profile"
    assert "AppData" not in chrome["user_data_dir"]

    forbidden = set(browser["forbidden_operations"])
    assert "change_default_browser" in forbidden
    assert "clear_cookies" in forbidden
    assert "read_or_print_password" in forbidden
    assert "read_browser_password_database" in forbidden
    assert "modify_daily_chrome_profile" in forbidden
    assert "copy_edge_user_data_directory" in forbidden
    # 迁移回归的防呆：禁止按进程名批量杀进程
    assert "kill_processes_by_name_only" in forbidden


def test_edge_is_archived_as_a_deprecated_fallback(stack):
    legacy = stack["browser"]["edge_legacy"]
    assert legacy["deprecated"] is True
    assert legacy["overlay_backup"].startswith("config/dsh/legacy-edge/")


def test_chrome_paths_are_absolute_not_env_expansions(stack):
    chrome = stack["browser"]["chrome"]
    for key in ("executable", "user_data_dir"):
        value = chrome[key]
        assert value[1:3] == ":\\", f"{key} 必须是绝对路径：{value}"
        assert "%" not in value, f"{key} 不得依赖环境变量展开：{value}"
    assert chrome["remote_debugging"]["address"] == "127.0.0.1"
    assert chrome["remote_debugging"]["exposed_to_lan_or_public"] is False


def test_chrome_security_features_are_not_disabled(stack):
    security = stack["browser"]["chrome"]["security"]
    assert security["sandbox_disabled"] is False
    assert security["safe_browsing_disabled"] is False
    assert security["certificate_checks_disabled"] is False
    assert security["stealth_or_fingerprint_tools"] is False


def test_exactly_three_frozen_backends(stack):
    backends = stack["backends"]
    assert set(backends) == {"fast", "primary", "fallback"}
    assert backends["fast"]["type"] == "agent-browser"
    assert backends["fast"]["transport"] == "cdp"
    assert backends["fast"]["pin_tab"] is True
    assert backends["fast"]["endpoint"] == "http://127.0.0.1:9223"
    assert backends["primary"]["type"] == "chrome-devtools-mcp"
    assert backends["primary"]["server_name"] == "chrome-devtools"
    assert backends["primary"]["connection_mode"] == "browser-url"
    assert backends["primary"]["auto_connect"] is False
    assert backends["fallback"]["type"] == "playwright-mcp"
    assert backends["fallback"]["server_name"] == "chrome-playwright"
    assert backends["fallback"]["connection_mode"] == "cdp-endpoint"
    # 迁移的实际收益之一：FALLBACK 不再需要浏览器扩展
    assert backends["fallback"]["extension"] is False
    assert backends["fallback"]["extension_required"] is False


def test_backend_order_matches_the_frozen_priority(router):
    assert router.allowed_backends() == [
        "DIRECT", "AGENT_BROWSER", "EDGE_DEVTOOLS_MCP", "PLAYWRIGHT_MCP", "HUMAN_REQUIRED",
    ]
    assert BACKEND_ORDER == router.allowed_backends()


def test_competition_surface_is_never_automatable(stack):
    competition = stack["competition"]
    assert competition["automate_competition_surface"] is False
    assert competition["dom_read"] is False
    assert competition["ocr_question_capture"] is False
    assert competition["screenshot_question_capture"] is False
    assert competition["api_listen"] is False
    assert competition["auto_fill_answer"] is False
    assert competition["auto_submit"] is False
    assert competition["question_ingress"] == "HUMAN_ONLY"
    assert competition["answer_egress"] == "HUMAN_ONLY"


def test_forbidden_optimizations_are_listed(stack):
    forbidden = set(stack["forbidden_optimizations"])
    for required in (
        "stealth_browser_plugin", "captcha_solver", "waf_bypass_tool",
        "anti_detect_browser", "fingerprint_spoofing",
        "residential_proxy_rotation", "cookie_stealing_or_import_tool",
    ):
        assert required in forbidden, required


def test_no_backend_specific_forbidden_flag_is_actually_used(stack):
    """--allowed-domains 会与 --cdp 冲突并让 CDP 路线失效。"""
    assert "--allowed-domains" in stack["backends"]["fast"]["forbidden_flags"]
    assert "--allowed-domains" not in " ".join(
        _patch_args(PRIMARY_PATCH) + _patch_args(FALLBACK_PATCH)
    )


def test_timeouts_fit_inside_the_question_budget(stack):
    timeouts = stack["timeouts"]
    assert timeouts["must_fit_inside_question_budget"] == 65000
    assert timeouts["navigation_ms"] <= 8000
    assert timeouts["interaction_ms"] <= 5000
    assert timeouts["mcp_tool_call_timeout_ms"] <= 20000
    assert stack["backends"]["primary"]["tool_call_timeout_ms"] <= 20000


def test_update_policy_forbids_competition_day_upgrades(stack):
    policy = stack["update_policy"]
    assert policy["t_minus_1_day"] == "freeze_versions"
    assert policy["competition_day"] == "forbid_update"
    forbidden = " ".join(policy["forbidden_on_competition_day"])
    assert "npm update" in forbidden
    assert "pnpm update" in forbidden
    assert policy["exception_requires_controller_approval"] is True


def test_security_section_forbids_persisting_auth_state(stack):
    security = stack["security"]
    assert security["save_auth_state_to_repo"] is False
    assert security["export_cookies"] is False
    assert security["commit_storage_state"] is False
    assert security["dump_password_database"] is False
    assert security["print_authorization_header"] is False


# ---------------------------------------------------------------------------
# 后端路由
# ---------------------------------------------------------------------------

def test_known_answer_short_circuits_the_browser(router):
    decision = router.decide(BrowserTask(answer_known_without_browser=True, kind="READ_COUNT"))
    assert decision.backend == DIRECT


def test_simple_deterministic_task_uses_the_fast_cli(router):
    for kind in ("OPEN_URL", "SEARCH_INPUT", "CLICK", "READ_COUNT", "READ_TABLE", "EXISTS_CHECK"):
        decision = router.decide(BrowserTask(kind=kind, url=RESEARCH_URL))
        assert decision.backend == AGENT_BROWSER, kind


def test_complex_task_uses_the_primary_devtools_backend(router):
    for kind in ("COMPLEX_DOM", "SPA_STATE", "JAVASCRIPT", "NETWORK", "ASYNC_XHR", "MULTI_TAB"):
        decision = router.decide(BrowserTask(kind=kind, url=RESEARCH_URL))
        assert decision.backend == EDGE_DEVTOOLS_MCP, kind


def test_primary_failure_degrades_to_playwright(router):
    decision = router.decide(
        BrowserTask(kind="COMPLEX_DOM", url=RESEARCH_URL, devtools_available=False,
                    playwright_available=True)
    )
    assert decision.backend == PLAYWRIGHT_MCP


def test_all_backends_down_requires_human(router):
    decision = router.decide(
        BrowserTask(kind="COMPLEX_DOM", url=RESEARCH_URL, devtools_available=False)
    )
    assert decision.backend == HUMAN_REQUIRED
    assert decision.requires_human is True


def test_two_cli_failures_escalate_to_primary(router):
    first = router.decide(BrowserTask(kind="READ_COUNT", url=RESEARCH_URL, cli_consecutive_failures=0))
    second = router.decide(BrowserTask(kind="READ_COUNT", url=RESEARCH_URL, cli_consecutive_failures=2))
    assert first.backend == AGENT_BROWSER
    assert second.backend == EDGE_DEVTOOLS_MCP
    assert any("连续失败" in note for note in second.notes)


@pytest.mark.parametrize(
    "signal",
    ["captcha", "cloudflare", "waf", "qr_login", "sms_verification",
     "campus_authentication", "account_login", "drm_pdf"],
)
def test_auth_challenges_always_go_to_human(router, signal):
    decision = router.decide(
        BrowserTask(kind="READ_COUNT", url=RESEARCH_URL, auth_challenge=signal)
    )
    assert decision.backend == HUMAN_REQUIRED
    assert decision.challenge == signal
    assert decision.requires_human is True


def test_captcha_detected_from_page_text_blocks_automation(router):
    decision = router.decide(
        BrowserTask(kind="READ_COUNT", url=RESEARCH_URL,
                    page_text="请拖动滑块完成验证")
    )
    assert decision.backend == HUMAN_REQUIRED
    assert decision.challenge == "captcha"


def test_competition_url_is_blocked_before_any_browser_choice(router):
    decision = router.decide(BrowserTask(kind="SIMPLE_NAV", url=COMPETITION_URL))
    assert decision.backend == BLOCKED_COMPETITION
    assert decision.compliance_surface == "COMPETITION_SURFACE"
    assert decision.requires_human is True


def test_unknown_surface_requires_controller(router):
    decision = router.decide(
        BrowserTask(kind="SIMPLE_NAV", url="https://unknown-portal.invalid/x")
    )
    assert decision.backend == HUMAN_REQUIRED


# ---------------------------------------------------------------------------
# Tab 隔离
# ---------------------------------------------------------------------------

def test_research_tab_passes_the_guard(router):
    decision = router.check_tab(RESEARCH_URL, tab_name="Research-1")
    assert decision.backend == AGENT_BROWSER
    assert decision.compliance_surface == "RESEARCH_SURFACE"


def test_competition_tab_is_blocked(router):
    decision = router.check_tab(COMPETITION_URL, tab_name="Competition")
    assert decision.backend == BLOCKED_COMPETITION
    assert decision.requires_human is True


def test_missing_tab_reports_tab_gone_and_never_rebinds(router):
    decision = router.check_tab("", tab_name="Research-1")
    assert decision.backend == TAB_GONE
    assert decision.requires_human is True
    assert "不得自动接管" in decision.reason


def test_tab_isolation_config(stack):
    isolation = stack["tab_isolation"]
    assert isolation["pin_tab"] is True
    assert isolation["competition_tab"] == "HUMAN_ONLY"
    assert isolation["on_bound_tab_closed"] == "TAB_GONE_HUMAN_REQUIRED"
    assert isolation["never_auto_take_over_other_tab"] is True
    assert "Research-1" in isolation["research_tabs"]


def test_no_concurrent_backend_on_the_same_tab():
    plan = build_backend_plan(
        [
            BrowserTask(kind="SIMPLE_NAV", tab_name="Research-1", url=RESEARCH_URL,
                        concurrent_group="g1"),
            BrowserTask(kind="COMPLEX_DOM", tab_name="Research-1", url=RESEARCH_URL,
                        concurrent_group="g1"),
        ]
    )
    assert plan["concurrent_backend_violations"], "同一标签页并发两个后端应当被拦下"
    assert plan["never_run_two_backends_on_same_tab"] is False


def test_sequential_handoff_is_not_a_violation():
    plan = build_backend_plan(
        [
            BrowserTask(kind="SIMPLE_NAV", tab_name="Research-1", url=RESEARCH_URL),
            BrowserTask(kind="COMPLEX_DOM", tab_name="Research-1", url=RESEARCH_URL),
        ]
    )
    assert plan["concurrent_backend_violations"] == []
    assert plan["never_run_two_backends_on_same_tab"] is True
    assert plan["tab_backend_timeline"]["Research-1"] == [AGENT_BROWSER, EDGE_DEVTOOLS_MCP]


# ---------------------------------------------------------------------------
# DSH MCP overlay
# ---------------------------------------------------------------------------

def _patch_args(path: Path) -> list[str]:
    """从 overlay 的 insert 条目里取出 args。"""
    entries = patch_inserted_entries(path)
    if not entries:
        return []
    return [str(a) for a in (entries[0].get("config", {}).get("args") or [])]


def _patch_config(path: Path) -> dict:
    entries = patch_inserted_entries(path)
    assert entries, f"{path} 没有任何 insert 条目"
    return entries[0]["config"]


def test_primary_overlay_targets_edge_devtools():
    config = _patch_config(PRIMARY_PATCH)
    entry = patch_inserted_entries(PRIMARY_PATCH)[0]
    assert entry["name"] == "@deepseek-ai/dsh-mcp-client"
    assert config["serverName"] == "edge-devtools"
    assert config["transport"] == "stdio"
    args = config["args"]
    assert "--autoConnect" in args
    assert any(a.startswith("--user-data-dir=C:\\") for a in args)
    assert "--no-usage-statistics" in args
    assert config["failOnStartupError"] is False
    assert config["reconnect"]["enabled"] is True
    assert config["toolCallTimeoutMs"] <= 20000


def test_primary_overlay_blocks_the_competition_surface():
    blocked = [a for a in _patch_args(PRIMARY_PATCH) if a.startswith("--blockedUrlPattern=")]
    assert any("xxsuyang.com" in a for a in blocked), blocked


def test_primary_overlay_trims_slow_tool_categories():
    args = _patch_args(PRIMARY_PATCH)
    for category in ("--no-category-performance", "--no-category-memory",
                     "--no-category-emulation"):
        assert category in args
    # 保留 network（比赛需要读 XHR）、navigation、input，不要一刀切
    assert "--no-category-network" not in args
    assert "--no-category-navigation" not in args
    assert "--no-category-input" not in args
    assert "--slim" not in args


def test_fallback_overlay_targets_edge_and_is_timeout_tightened():
    config = _patch_config(FALLBACK_PATCH)
    args = config["args"]
    assert config["serverName"] == "edge-playwright"
    assert "--extension" in args
    assert "--browser=msedge" in args
    assert "--timeout-navigation=8000" in args
    assert "--timeout-action=5000" in args


@pytest.mark.parametrize("path", [PRIMARY_PATCH, FALLBACK_PATCH])
def test_overlays_contain_no_credentials(path):
    text = path.read_text(encoding="utf-8").lower()
    config = _patch_config(path)
    serialized = json.dumps(config, ensure_ascii=False).lower()
    for marker in SECRET_MARKERS:
        # 允许出现在注释里说明「不含凭证」，但不得作为配置键出现
        assert f'"{marker}"' not in serialized, f"{path.name} 疑似含凭证字段 {marker}"
        assert f"{marker}:" not in serialized, f"{path.name} 疑似含凭证字段 {marker}"
    assert "bearer " not in text


def test_overlays_do_not_expose_websocket_endpoints():
    for path in (PRIMARY_PATCH, FALLBACK_PATCH):
        serialized = json.dumps(_patch_config(path), ensure_ascii=False)
        assert "ws://" not in serialized
        assert "wss://" not in serialized


# ---------------------------------------------------------------------------
# 版本固定
# ---------------------------------------------------------------------------

def test_versions_file_pins_every_backend_component():
    versions = load_json(VERSIONS_PATH)["versions"]
    for key in ("edge", "node", "dsh", "dsh-mcp-client", "chrome-devtools-mcp",
                "agent-browser", "playwright-mcp"):
        assert key in versions, key
    assert versions["chrome-devtools-mcp"]["version"] == "1.10.1"
    assert versions["playwright-mcp"]["version"] == "0.0.83"
    assert versions["agent-browser"]["version"] == "0.38.1"


def test_versions_file_records_what_is_not_yet_verified():
    versions = load_json(VERSIONS_PATH)["versions"]
    assert versions["playwright-extension"]["verified"] is False
    assert versions["pnpm"]["verified"] is False
    assert load_json(VERSIONS_PATH)["freeze"]["frozen"] is False


def test_pinned_versions_match_the_stack_config(stack):
    versions = load_json(VERSIONS_PATH)["versions"]
    assert stack["backends"]["primary"]["version"] == versions["chrome-devtools-mcp"]["version"]
    assert stack["backends"]["fallback"]["version"] == versions["playwright-mcp"]["version"]
    assert stack["backends"]["fast"]["version"] == versions["agent-browser"]["version"]
    assert stack["browser"]["chrome"]["version"] == versions["chrome"]["version"]
    # Edge 仅作为已停用的回滚路线保留
    assert stack["browser"]["edge_legacy"]["version"] == versions["edge"]["version"]
    assert versions["edge"]["deprecated"] is True


def test_npm_tools_resolve_to_executable_form():
    """Windows 上必须解析成 .cmd/.exe，否则 subprocess 报 WinError 2。"""
    for name in ("npm", "npx"):
        resolved = resolve_npm_tool(name)
        assert resolved.lower().endswith((".cmd", ".exe", ".bat")), resolved


# ---------------------------------------------------------------------------
# 健康检查 / benchmark 产物
# ---------------------------------------------------------------------------

def test_health_report_shape():
    path = ROOT / "data" / "quality" / "browser_stack_health.json"
    if not path.exists():
        pytest.skip("尚未生成健康检查报告")
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert set(summary) == {
        "CHROME", "REMOTE_DEBUG", "AGENT_BROWSER", "DEVTOOLS_MCP",
        "PLAYWRIGHT_MCP", "DSH_MCP",
    }
    assert "不登录网站" in payload["scope"]
    assert payload["browser"] == "dedicated-google-chrome"


def test_benchmark_report_shape():
    path = ROOT / "data" / "quality" / "browser_backend_benchmark.json"
    if not path.exists():
        pytest.skip("尚未生成 benchmark 报告")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["policy"].startswith("只用本地 fixture")
    assert set(payload["recommendation"]) == {"FAST_DEFAULT", "PRIMARY_FULL", "FALLBACK"}
    for backend in payload["backends"]:
        assert "startup_ms" in backend
        assert "tool_count" in backend
        assert "success_rate" in backend
        if backend["failure_reason"]:
            assert backend["available"] is False

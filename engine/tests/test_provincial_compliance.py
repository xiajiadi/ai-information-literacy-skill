"""TEST 2 / TEST 5 / TEST 6：合规硬隔离、验证码交接、重试预算。

TEST 2  Competition Surface 不能调用自动浏览。
TEST 5  遇到 CAPTCHA / WAF 能触发 HUMAN_REQUIRED。
TEST 6  同一路径失败超过预算后停止，而不是无限重试。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compliance_gate import (  # noqa: E402
    ALLOWED,
    BLOCKED,
    BLOCKED_PENDING_CONTROLLER,
    CHALLENGE_SIGNALS,
    COMPETITION,
    RESEARCH,
    UNKNOWN_SURFACE,
    ComplianceGate,
    RouteBudget,
    detect_challenge,
    route_budget_from_config,
)
from handoff_format import HandoffRequest, render, trigger_advice  # noqa: E402
from provincial_common import (  # noqa: E402
    COMPLIANCE_POLICY_PATH,
    MODULE_NAV_JSON_PATH,
    PROVINCIAL_CONFIG_PATH,
    ROOT,
    load_compliance_policy,
    load_provincial_config,
)

COMPETITION_URLS = [
    "https://csc.xxsuyang.com/training",
    "https://csc.xxsuyang.com/detail?id=ecee8d2e-46a5-11f0-8ca6-b8599f11e190",
    "https://xxsuyang.com/",
    "http://sub.xxsuyang.com/exam",
]

AUTOMATION_ACTIONS = [
    "browse", "read", "dom_read", "screenshot", "eval",
    "click", "fill", "api", "xhr", "ocr", "clipboard",
    "fill_answer", "submit", "select",
]


@pytest.fixture(scope="module")
def gate():
    return ComplianceGate()


# ---------------------------------------------------------------------------
# TEST 2 — Competition Surface 硬隔离
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", COMPETITION_URLS)
def test_competition_surface_is_always_blocked(gate, url):
    verdict = gate.classify(url)
    assert verdict.surface == COMPETITION
    assert verdict.decision == BLOCKED
    assert verdict.automation_allowed is False


@pytest.mark.parametrize("action", AUTOMATION_ACTIONS)
def test_no_automation_action_is_ever_authorized_on_competition_surface(gate, action):
    for url in COMPETITION_URLS:
        verdict = gate.authorize(url, action)
        assert verdict.decision == BLOCKED, f"{action} 在比赛面上被放行了：{url}"


def test_competition_surface_has_dom_read_and_api_disabled_by_policy():
    policy = load_compliance_policy()
    surface = policy["competition_surface"]
    assert surface["automation_allowed"] is False
    assert surface["dom_read_allowed"] is False
    assert surface["devtools_automation_allowed"] is False
    assert surface["api_or_xhr_access_allowed"] is False
    assert surface["auto_fill_allowed"] is False
    assert surface["auto_submit_allowed"] is False
    assert surface["ocr_allowed"] is False
    assert surface["screenshot_analysis_allowed"] is False
    assert surface["clipboard_capture_allowed"] is False
    assert surface["unknown_surface_policy"]["action"] == "TREAT_AS_COMPETITION_SURFACE"


def test_public_research_surface_is_still_allowed(gate):
    """硬隔离不能把正常研究也一起封死。"""
    for url in [
        "https://kns.cnki.net/starter/advanced",
        "https://pubmed.ncbi.nlm.nih.gov/advanced/",
        "https://www.icourse163.org/search.htm",
        "https://www.cqvip.com/advancesearch",
    ]:
        verdict = gate.classify(url)
        assert verdict.surface == RESEARCH
        assert verdict.decision == ALLOWED


def test_unknown_surface_defaults_to_competition_and_asks_controller(gate):
    verdict = gate.classify("https://unknown-provincial-exam-portal.invalid/quiz")
    assert verdict.surface == UNKNOWN_SURFACE
    assert verdict.decision == BLOCKED_PENDING_CONTROLLER
    assert verdict.automation_allowed is False


def test_confirmed_research_hosts_match_subdomains(gate):
    """确认主机必须按后缀匹配，否则 www.stats.gov.cn 会被误挡。"""
    for url in ("https://www.stats.gov.cn/", "https://github.com/search?q=x"):
        verdict = gate.classify(url)
        assert verdict.decision == ALLOWED, url
        assert verdict.surface == RESEARCH


def test_suffix_matching_does_not_over_allow_lookalike_hosts(gate):
    """notgithub.com 不是 github.com 的子域，不得被放行。"""
    for url in ("https://notgithub.com/", "https://github.com.evil.test/"):
        assert gate.classify(url).automation_allowed is False, url


def test_competition_suffix_does_not_match_lookalike(gate):
    """evil-xxsuyang.com 不是子域；虽不判为比赛面，但同样不得放行。"""
    verdict = gate.classify("https://evil-xxsuyang.com/")
    assert verdict.surface == UNKNOWN_SURFACE
    assert verdict.decision == BLOCKED_PENDING_CONTROLLER


def test_competition_check_runs_before_the_research_whitelist(gate):
    """白名单不得覆盖比赛面：即使同名也必须是 BLOCKED。"""
    for url in COMPETITION_URLS:
        verdict = gate.classify(url)
        assert verdict.surface == COMPETITION
        assert verdict.decision == BLOCKED
        assert verdict.automation_allowed is False


def test_nsfc_whitelist_is_host_scoped_not_domain_wide(gate):
    """复核结论：只放行 kd.nsfc.cn，不整域放行 nsfc.cn。"""
    assert gate.classify("https://kd.nsfc.cn/finalProjectInit").decision == ALLOWED
    assert gate.classify("https://nsfc.cn/").automation_allowed is False


def test_browser_level_competition_block_is_configured():
    """浏览器级 DNS 黑洞必须存在：它是唯一能拦住原始 CLI 的层。"""
    from start_research_chrome import COMPETITION_HOST_RULES

    assert "MAP" in COMPETITION_HOST_RULES
    assert "xxsuyang.com" in COMPETITION_HOST_RULES
    # 必须覆盖裸域与全部子域
    assert "*.xxsuyang.com" in COMPETITION_HOST_RULES
    assert "127.0.0.1" in COMPETITION_HOST_RULES


def test_batch_assertion_reports_every_blocked_url(gate):
    blocked = gate.assert_no_automation(
        COMPETITION_URLS + ["https://kns.cnki.net/starter/advanced"]
    )
    assert len(blocked) == len(COMPETITION_URLS)


def test_nav_layer_contains_no_competition_surface_entry():
    """导航层是运行时入口来源，绝不能带比赛面 URL。"""
    if not MODULE_NAV_JSON_PATH.exists():
        pytest.skip("导航层尚未生成")
    nav = json.loads(MODULE_NAV_JSON_PATH.read_text(encoding="utf-8"))
    gate = ComplianceGate()
    for module in nav["modules"]:
        for key in ("deep_link", "primary_platform"):
            value = module.get(key) or ""
            if key == "primary_platform":
                assert value not in {"competition", "competition-training"}
                continue
            if value:
                assert gate.classify(value).surface != COMPETITION, (
                    f"M{module['module_no']} 的深链接落在比赛面：{value}"
                )


def test_forbidden_actions_cover_every_required_prohibition():
    policy = load_compliance_policy()
    forbidden = set(policy["forbidden_actions"])
    required = {
        "auto_read_competition_dom",
        "capture_question_via_playwright_or_selenium_or_devtools",
        "listen_or_replay_competition_api",
        "extract_question_via_ocr_or_screenshot_watcher",
        "extract_question_via_clipboard_watcher",
        "auto_select_option_on_competition_page",
        "auto_fill_answer",
        "auto_click_next_question",
        "auto_submit",
        "bypass_captcha",
        "bypass_waf",
        "bypass_login",
    }
    assert required.issubset(forbidden), required - forbidden


# ---------------------------------------------------------------------------
# TEST 5 — CAPTCHA / WAF 触发 HUMAN_REQUIRED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("请拖动滑块完成验证", "captcha"),
        ("安全验证 captcha verification", "captcha"),
        ("Checking your browser before accessing", "cloudflare"),
        ("Access Denied - WAF", "waf"),
        ("请扫码登录后继续", "qr_login"),
        ("请输入短信验证码", "sms_verification"),
        ("请使用统一身份认证登录", "campus_authentication"),
        ("登录后查看全文", "account_login"),
        ("请扫码下载 App 打开", "app_only"),
    ],
)
def test_challenge_detection_maps_to_handoff_reasons(text, expected):
    assert detect_challenge(text) == expected


def test_challenge_detection_from_url():
    assert detect_challenge(
        "", "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
    ) == "captcha"


def test_challenge_signals_cover_required_categories():
    for required in ("captcha", "cloudflare", "waf", "qr_login", "sms_verification",
                     "campus_authentication"):
        assert required in CHALLENGE_SIGNALS


def test_captcha_advice_is_first_second_handoff():
    advice = trigger_advice("captcha")
    assert advice["handoff_at_second"] == "1"
    assert "禁止绕过" in advice["note"]


def test_handoff_render_matches_required_format():
    request = HandoffRequest(
        official_url="https://kns.cnki.net/starter/advanced",
        steps=["打开高级检索", "字段选「篇名」", "时间填 2024"],
        copyable_query="信息素养 * 人工智能",
        target_field="结果总数",
        what_to_report_back="只告诉我结果总数=xxx",
        reason="captcha",
    )
    block = render(request)
    for marker in ("🔴 HUMAN_REQUIRED", "官网：", "操作：", "复制：", "查看：", "回传："):
        assert marker in block
    assert request.validate() == []


def test_incomplete_handoff_is_rejected():
    request = HandoffRequest(official_url="https://example.com/", steps=["打开"])
    missing = request.validate()
    assert "copyable_query（可复制检索式，或等价的分行填写说明）" in missing
    with pytest.raises(ValueError):
        render(request)


def test_challenge_entry_platform_triggers_handoff_expected():
    from task_router import route

    routing = route("在中国专利公布公告系统的高级查询功能中，检索申请人为某公司的发明专利。")
    if routing.target_platform != "epub":
        pytest.skip("路由未落到专利公布公告系统，跳过")
    assert routing.handoff_expected is True
    assert routing.entry_status in {"CHALLENGE", "AUTH", "BROKEN", "UNKNOWN"}


# ---------------------------------------------------------------------------
# TEST 6 — 重试预算
# ---------------------------------------------------------------------------

def test_retry_budget_stops_after_one_retry():
    budget = RouteBudget(max_retries=1)
    assert budget.record_failure("cnki_advanced") is True
    assert budget.record_failure("cnki_advanced") is False
    assert budget.can_retry("cnki_advanced") is False
    assert budget.should_stop("cnki_advanced") is True
    assert "cnki_advanced" in budget.exhausted


def test_risk_control_signal_blocks_retry_immediately():
    budget = RouteBudget(max_retries=5)
    assert budget.record_failure("vip_adv", "captcha") is False
    assert budget.should_stop("vip_adv") is True
    assert budget.stopped_reason == "captcha"


def test_retry_budget_is_per_route_not_global():
    budget = RouteBudget(max_retries=1)
    assert budget.record_failure("route_a") is True
    assert budget.record_failure("route_a") is False
    # 另一条路线仍然可用
    assert budget.can_retry("route_b") is True


def test_configured_retry_budget_matches_policy():
    budget = route_budget_from_config()
    config = load_provincial_config()
    assert budget.max_retries == int(config["risk"]["retry_same_route_max"])
    assert budget.max_retries == 1


def test_policy_files_exist_and_parse():
    assert COMPLIANCE_POLICY_PATH.exists()
    assert PROVINCIAL_CONFIG_PATH.exists()
    compliance = load_compliance_policy()
    provincial = load_provincial_config()
    assert compliance["precedence"] == "P0"
    assert compliance["overridable"] is False
    assert provincial["compliance"]["competition_dom_read"] is False
    assert provincial["risk"]["retry_same_route_max"] == 1

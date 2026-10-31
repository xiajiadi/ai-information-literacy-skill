"""认证状态判定的契约测试。

背景（真实误判）：第一版探针按「出现退出/个人中心 = 已登录」判定，
把**已通过机构 IP 认证**的中国知网判成了未登录——机构认证根本不显示
个人账号菜单，它显示的是「个人登录」这个**切换到个人登录**的入口。

本测试把这个三态语义钉死，防止再退回单态判定。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from provincial_common import ROOT  # noqa: E402
from verify_login_state import (  # noqa: E402
    IDENTITY_HOST_BLOCKLIST,
    LOGIN_PROBE,
    classify_auth_state,
    redact_url,
)

LOGIN_REPORT = ROOT / "data" / "quality" / "login_state_verification.json"


def test_institutional_auth_is_not_mistaken_for_anonymous():
    """机构态：有「个人登录」入口、无个人账号退出入口 -> AUTHENTICATED_INSTITUTIONAL。"""
    assert classify_auth_state(
        personal=False, switch_to_personal=True, institutional=False, has_login=True
    ) == "AUTHENTICATED_INSTITUTIONAL"


def test_institutional_marker_alone_is_enough():
    assert classify_auth_state(
        personal=False, switch_to_personal=False, institutional=True, has_login=True
    ) == "AUTHENTICATED_INSTITUTIONAL"


def test_personal_account_wins_over_institutional():
    assert classify_auth_state(
        personal=True, switch_to_personal=True, institutional=True, has_login=True
    ) == "AUTHENTICATED_PERSONAL"


def test_anonymous_when_only_a_plain_login_entry_exists():
    assert classify_auth_state(
        personal=False, switch_to_personal=False, institutional=False, has_login=True
    ) == "ANONYMOUS"


def test_unknown_when_no_signal_at_all():
    assert classify_auth_state(
        personal=False, switch_to_personal=False, institutional=False, has_login=False
    ) == "UNKNOWN"


def test_probe_reports_only_booleans_and_no_identity():
    """探针不得回传账户名、邮箱等任何身份字段。"""
    for forbidden in ("email", "username", "accountName", "avatar", "userId", "cookie"):
        assert forbidden not in LOGIN_PROBE
    for expected in (
        "hasPersonalAccountIndicator",
        "hasSwitchToPersonalIndicator",
        "hasInstitutionalIndicator",
        "hasLoginIndicator",
    ):
        assert expected in LOGIN_PROBE


def test_session_parameters_are_redacted_before_persisting():
    """uid/token/session 等会话参数绝不能落盘。"""
    cnki_like = (
        "https://www.cnki.net/?uid=WEEvREcwSlJHSldSdmVpdm1HMEd0VTllakdsU0J2S2RF"
        "OFkvZzlKZmhnZz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!"
    )
    assert redact_url(cnki_like) == "https://www.cnki.net/"
    assert redact_url("https://example.com/path?a=1&token=deadbeef") == "https://example.com/path"


def test_login_report_contains_no_session_parameters():
    if not LOGIN_REPORT.exists():
        pytest.skip("尚未生成登录态报告")
    raw = LOGIN_REPORT.read_text(encoding="utf-8")
    for marker in ("uid=", "token=", "session=", "WEEvREcw"):
        assert marker not in raw, f"登录态报告里出现了会话参数：{marker}"
    payload = json.loads(raw)
    for probe in payload.get("probes", []):
        assert "canonical_url" in probe
        assert "?" not in probe["canonical_url"]


def test_identity_hosts_are_never_probed():
    """身份站点必须在黑名单里，且报告要显式记录「未求值」。"""
    assert "accounts.google.com" in IDENTITY_HOST_BLOCKLIST
    assert "myaccount.google.com" in IDENTITY_HOST_BLOCKLIST
    if not LOGIN_REPORT.exists():
        pytest.skip("尚未生成登录态报告")
    payload = json.loads(LOGIN_REPORT.read_text(encoding="utf-8"))
    for observed in payload.get("identity_sessions_observed", []):
        assert observed["probed"] is False, observed


def test_login_report_records_institutional_auth_when_present():
    if not LOGIN_REPORT.exists():
        pytest.skip("尚未生成登录态报告")
    payload = json.loads(LOGIN_REPORT.read_text(encoding="utf-8"))
    states = {
        probe.get("host"): probe.get("auth_state")
        for probe in payload.get("probes", [])
        if probe.get("auth_state")
    }
    # 只要有已认证主机，其状态必须来自三态判定而不是布尔猜测
    for host in payload.get("detected_logged_in_hosts", []):
        assert states.get(host, "").startswith("AUTHENTICATED")

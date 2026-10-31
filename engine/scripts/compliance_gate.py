"""合规闸门：Competition Surface 硬隔离 + 风控纪律。

这是本执行体的 P0 组件。任何自动化控制器（agent-browser / Playwright /
HTTP 抓取 / 自定义脚本）在接触某个 URL **之前**都必须先过这道闸门。

设计原则：

    比赛面        -> BLOCKED，永不自动化，永不读 DOM，永不碰接口
    已确认研究面  -> ALLOWED
    未知面        -> BLOCKED_PENDING_CONTROLLER（默认视为比赛面，先问 Controller）

「已确认研究面」的判定顺序：
    1. config/compliance_policy.yaml 的 research_surface.confirmed_hosts（人工显式）
    2. config/platform_entry_status.json 中 source 为 KNOWN_HISTORY / PREFLIGHT 的
       入口主机——即本项目**实际实测过**的公开站点。
    REGISTRY 来源（自动派生、未实测）**不算确认**，仍然要 Controller 点头。

本模块不联网、不启动浏览器，纯判定。可离线单测。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    load_compliance_policy,
    load_entry_status,
    load_provincial_config,
)

COMPETITION = "COMPETITION_SURFACE"
RESEARCH = "RESEARCH_SURFACE"
UNKNOWN_SURFACE = "UNKNOWN_SURFACE"

ALLOWED = "ALLOWED"
BLOCKED = "BLOCKED"
BLOCKED_PENDING_CONTROLLER = "BLOCKED_PENDING_CONTROLLER"

HUMAN_REQUIRED = "HUMAN_REQUIRED"

# 页面侧的风控信号 -> 人工交接触发原因。命中即停止自动化，不尝试绕过。
CHALLENGE_SIGNALS: dict[str, tuple[str, ...]] = {
    "captcha": (
        "captcha", "验证码", "blockpuzzle", "滑块", "slide to verify",
        "security check", "安全验证", "人机验证", "拖动滑块",
    ),
    "cloudflare": ("cloudflare", "cf-challenge", "checking your browser", "请稍候"),
    "waf": ("waf", "access denied", "412 precondition", "请求被拦截"),
    "qr_login": (
        # 同样只认「登录墙」措辞：页头挂一个「扫码登录」选项 ≠ 必须扫码。
        # 实测 万方 s.wanfangdata.com.cn/paper 正文可读，却因页头有「扫码登录」
        # 被误判为 qr_login。
        "请扫码登录", "扫码登录后", "需扫码登录", "扫码登录以", "扫描二维码登录",
        "scan the qr code to log in", "scan qr code to sign in",
    ),
    "sms_verification": ("短信验证码", "手机验证码", "请输入短信验证", "获取验证码"),
    "campus_authentication": ("统一身份认证", "校园网", "学号登录", "校园认证"),
    "account_login": (
        # 只认**真正的登录墙**措辞。
        # 不要用裸的 "sign in" / "log in"：GitHub、知乎等公开页面顶栏永远有
        # "Sign in" 链接，用它会把正常公开浏览误判成需要人工登录（实测误报）。
        "请登录", "请先登录", "登录后查看", "登录后可见", "登录后阅读",
        "登录以继续", "登录才能", "需要登录",
        "sign in to continue", "log in to continue", "sign in required",
        "login required", "please log in", "please sign in",
    ),
    "app_only": ("请下载app", "扫码下载", "客户端打开", "微信小程序"),
    "drm_pdf": ("drm", "加密pdf", "受保护文档"),
    "dynamic_player": ("播放器加载中", "drm player"),
}

# 命中这些平台级原因时，不允许"再试一次"，必须直接交接。
NO_RETRY_REASONS = {"captcha", "cloudflare", "waf", "qr_login", "sms_verification",
                    "campus_authentication", "drm_pdf"}

KNOWN_HISTORY_SOURCES = {"KNOWN_HISTORY", "PREFLIGHT"}


def _host_of(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    return (urlsplit(value).hostname or "").lower()


def _host_matches(host: str, candidate: str) -> bool:
    host = host.lower().strip(".")
    candidate = candidate.lower().strip(".")
    if not host or not candidate:
        return False
    return host == candidate or host.endswith("." + candidate)


@dataclass
class SurfaceVerdict:
    url: str
    host: str
    surface: str
    decision: str
    reason: str
    matched_rule: str = ""

    @property
    def automation_allowed(self) -> bool:
        return self.decision == ALLOWED

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "host": self.host,
            "surface": self.surface,
            "decision": self.decision,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
        }


class ComplianceGate:
    """URL 级合规判定。无状态副作用，可反复实例化。"""

    def __init__(
        self,
        policy: dict[str, Any] | None = None,
        entry_status: dict[str, Any] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else load_compliance_policy()
        surface = self.policy.get("competition_surface", {}) or {}
        self.competition_hosts = [
            str(h).lower() for h in (surface.get("known_hosts") or [])
        ]
        self.competition_suffixes = [
            str(s).lower().strip(".") for s in (surface.get("host_suffix_patterns") or [])
        ]
        research = self.policy.get("research_surface", {}) or {}
        self.confirmed_hosts = {
            str(h).lower() for h in (research.get("confirmed_hosts") or [])
        }
        self._entry_status = entry_status
        self._verified_hosts_cache: set[str] | None = None

    # -- 已实测公开主机 ---------------------------------------------------
    @property
    def verified_public_hosts(self) -> set[str]:
        if self._verified_hosts_cache is not None:
            return self._verified_hosts_cache
        hosts: set[str] = set()
        try:
            data = self._entry_status if self._entry_status is not None else load_entry_status()
        except FileNotFoundError:
            data = {"entries": []}
        for entry in data.get("entries", []):
            if entry.get("source") not in KNOWN_HISTORY_SOURCES:
                continue
            host = _host_of(entry.get("url", ""))
            if host and not self.is_competition_host(host):
                hosts.add(host)
        self._verified_hosts_cache = hosts
        return hosts

    # -- 判定 -------------------------------------------------------------
    def is_competition_host(self, host: str) -> bool:
        if not host:
            return False
        for known in self.competition_hosts:
            if _host_matches(host, known):
                return True
        for suffix in self.competition_suffixes:
            if _host_matches(host, suffix):
                return True
        return False

    def is_confirmed_research_host(self, host: str) -> bool:
        """确认的研究主机同样按后缀匹配，否则 www.stats.gov.cn 会被误挡。

        `_host_matches` 要求「相等或以 . 前缀结尾」，所以 notgithub.com
        不会误命中 github.com。
        """
        if not host:
            return False
        return any(_host_matches(host, item) for item in self.confirmed_hosts)

    def is_verified_public_host(self, host: str) -> bool:
        if not host:
            return False
        return any(_host_matches(host, item) for item in self.verified_public_hosts)

    def classify(self, url: str) -> SurfaceVerdict:
        host = _host_of(url)
        if not host:
            return SurfaceVerdict(
                url=url,
                host="",
                surface=UNKNOWN_SURFACE,
                decision=BLOCKED_PENDING_CONTROLLER,
                reason="URL 无法解析出主机名，无法判定归属；默认按比赛面处理。",
                matched_rule="unparsable_url",
            )

        if self.is_competition_host(host):
            return SurfaceVerdict(
                url=url,
                host=host,
                surface=COMPETITION,
                decision=BLOCKED,
                reason="比赛平台及其同源域为 Human Only，禁止任何自动化接触。",
                matched_rule="competition_surface.known_hosts|host_suffix_patterns",
            )

        if self.is_confirmed_research_host(host):
            return SurfaceVerdict(
                url=url,
                host=host,
                surface=RESEARCH,
                decision=ALLOWED,
                reason="主机在 compliance_policy.research_surface.confirmed_hosts 中显式确认（含子域）。",
                matched_rule="research_surface.confirmed_hosts",
            )

        if self.is_verified_public_host(host):
            return SurfaceVerdict(
                url=url,
                host=host,
                surface=RESEARCH,
                decision=ALLOWED,
                reason="主机来自本项目实测记录（platform_entry_status: KNOWN_HISTORY/PREFLIGHT），且不属于比赛面。",
                matched_rule="platform_entry_status.verified",
            )

        return SurfaceVerdict(
            url=url,
            host=host,
            surface=UNKNOWN_SURFACE,
            decision=BLOCKED_PENDING_CONTROLLER,
            reason="无法确认该页面是否属于比赛系统；默认视为比赛面，禁止自动控制，需 Controller 确认。",
            matched_rule="unknown_surface_policy.TREAT_AS_COMPETITION_SURFACE",
        )

    def authorize(self, url: str, action: str = "browse") -> SurfaceVerdict:
        """带动作语义的授权。比赛面上的任何动作都拒绝，包括只读。"""
        verdict = self.classify(url)
        if verdict.surface == COMPETITION and action in {
            "browse", "read", "dom_read", "screenshot", "eval", "click", "fill",
            "api", "xhr", "ocr", "clipboard", "fill_answer", "submit", "select",
        }:
            verdict.decision = BLOCKED
            verdict.reason = (
                f"action={action} 命中比赛面硬隔离：{verdict.reason} "
                "题目只能由选手人工读取，答案只能由选手手动提交。"
            )
        return verdict

    def assert_no_automation(self, urls: Iterable[str]) -> list[SurfaceVerdict]:
        """批量校验一组 URL；返回被拒绝的条目。空列表代表全部放行。"""
        return [self.classify(u) for u in urls if not self.classify(u).automation_allowed]


# 判定优先级（先判更具体的原因）。「验证码」这种宽泛词排在扫码/短信/校园认证之后，
# 否则「请输入短信验证码」会被误判成 captcha。
CHALLENGE_PRIORITY = (
    "qr_login",
    "sms_verification",
    "campus_authentication",
    "app_only",
    "drm_pdf",
    "dynamic_player",
    "cloudflare",
    "waf",
    "captcha",
    "account_login",
)


def detect_challenge(page_text: str, url: str = "") -> str:
    """从页面文本或 URL 判定是否需要人工交接，返回原因；无信号返回空串。"""
    if not page_text and not url:
        return ""
    if url:
        lowered_url = url.lower()
        for reason in CHALLENGE_PRIORITY:
            markers = CHALLENGE_SIGNALS.get(reason, ())
            if any(marker in lowered_url for marker in markers):
                return reason
    lowered = (page_text or "").lower()
    for reason in CHALLENGE_PRIORITY:
        markers = CHALLENGE_SIGNALS.get(reason, ())
        if any(marker in lowered for marker in markers):
            return reason
    return ""


@dataclass
class RouteBudget:
    """同一路线的重试预算。超过预算必须停止，而不是继续重试。"""

    max_retries: int = 1
    attempts: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)
    stopped_reason: str = ""

    def record_failure(self, route_key: str, reason: str = "") -> bool:
        """记录一次失败。返回 True 表示还可以再试一次。"""
        count = self.attempts.get(route_key, 0) + 1
        self.attempts[route_key] = count
        if reason in NO_RETRY_REASONS:
            self.exhausted.add(route_key)
            self.stopped_reason = reason
            return False
        if count > self.max_retries:
            self.exhausted.add(route_key)
            self.stopped_reason = reason or "retry_budget_exhausted"
            return False
        return True

    def can_retry(self, route_key: str) -> bool:
        return (
            route_key not in self.exhausted
            and self.attempts.get(route_key, 0) <= self.max_retries
        )

    def should_stop(self, route_key: str) -> bool:
        return not self.can_retry(route_key)


def route_budget_from_config() -> RouteBudget:
    config = load_provincial_config()
    risk = config.get("risk", {}) or {}
    retries = risk.get("retry_same_route_max", 1)
    try:
        retries = int(retries)
    except (TypeError, ValueError):
        retries = 1
    return RouteBudget(max_retries=max(retries, 0))


def main(argv: list[str] | None = None) -> int:
    """CLI：python scripts/compliance_gate.py <url> [更多 url...]"""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法：python scripts/compliance_gate.py <url> [<url> ...]")
        return 2
    gate = ComplianceGate()
    exit_code = 0
    for url in args:
        verdict = gate.classify(url)
        marker = {"ALLOWED": "OK  ", "BLOCKED": "STOP", "BLOCKED_PENDING_CONTROLLER": "ASK "}[
            verdict.decision
        ]
        print(f"[{marker}] {verdict.surface:17s} {verdict.host:32s} {verdict.reason}")
        if verdict.decision != ALLOWED:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

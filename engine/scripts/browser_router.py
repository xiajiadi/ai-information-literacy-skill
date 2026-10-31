"""浏览器 Backend Router + Tab 隔离守卫（§11 / §14）。

三条已冻结的路线：

    FAST CLI    : Edge + CDP + agent-browser
    PRIMARY MCP : Edge + Chrome DevTools MCP
    FALLBACK    : Edge + Playwright MCP Extension

路由是**纯决策函数**，不启动任何进程，可离线单测。

两条硬约束：
  1. 同一道题不得同时启动两套工具抢同一个标签页（never_run_two_backends_on_same_tab）。
  2. 比赛面标签页永远不进入任何 backends 的候选集合；绑定的 Research Tab 被关闭时
     返回 TAB_GONE，**不得**自动接管最近活跃的其他标签页。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compliance_gate import ComplianceGate, detect_challenge  # noqa: E402
from provincial_common import (  # noqa: E402
    CONFIG_DIR,
    load_yaml,
    now_iso,
)

BROWSER_STACK_PATH = CONFIG_DIR / "browser_stack.yaml"

DIRECT = "DIRECT"
AGENT_BROWSER = "AGENT_BROWSER"
EDGE_DEVTOOLS_MCP = "EDGE_DEVTOOLS_MCP"
PLAYWRIGHT_MCP = "PLAYWRIGHT_MCP"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
TAB_GONE = "TAB_GONE"
BLOCKED_COMPETITION = "BLOCKED_COMPETITION"

BACKEND_ORDER = [DIRECT, AGENT_BROWSER, EDGE_DEVTOOLS_MCP, PLAYWRIGHT_MCP, HUMAN_REQUIRED]

# 任务形态 -> 是否需要 PRIMARY（复杂 DOM / JS / Network）
COMPLEX_KINDS = {
    "COMPLEX_DOM", "SPA_STATE", "JAVASCRIPT", "NETWORK", "MULTI_TAB",
    "ASYNC_XHR", "REAL_DOM_ATTRS", "SNAPSHOT_INSUFFICIENT", "DYNAMIC_COMPONENT",
}
SIMPLE_KINDS = {
    "OPEN_URL", "SEARCH_INPUT", "CLICK", "FILTER", "READ_COUNT",
    "READ_FIELD", "READ_TABLE", "OPEN_DETAIL", "EXISTS_CHECK", "SIMPLE_NAV",
}


@dataclass
class BrowserTask:
    kind: str = "SIMPLE_NAV"
    url: str = ""
    tab_url: str = ""
    tab_name: str = ""
    answer_known_without_browser: bool = False
    cli_consecutive_failures: int = 0
    devtools_available: bool = True
    playwright_available: bool = False
    page_text: str = ""
    auth_challenge: str = ""
    # 只有显式声明「与同组任务并发」时才可能构成同标签页抢页面。
    # 顺序降级（CLI 失败 -> PRIMARY）不是冲突，而是规定的升级路径。
    concurrent_group: str = ""

    def observed_challenge(self) -> str:
        return self.auth_challenge or detect_challenge(self.page_text, self.url)


@dataclass
class RoutingDecision:
    backend: str
    reason: str
    compliance_decision: str = ""
    compliance_surface: str = ""
    challenge: str = ""
    requires_human: bool = False
    exclusive: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def load_browser_stack() -> dict[str, Any]:
    if not BROWSER_STACK_PATH.exists():
        raise FileNotFoundError(f"浏览器栈配置缺失：{BROWSER_STACK_PATH}")
    return load_yaml(BROWSER_STACK_PATH)


class BackendRouter:
    def __init__(
        self,
        stack: dict[str, Any] | None = None,
        gate: ComplianceGate | None = None,
    ) -> None:
        self.stack = stack if stack is not None else load_browser_stack()
        self.gate = gate if gate is not None else ComplianceGate()
        routing = self.stack.get("routing", {}) or {}
        self.order = routing.get("order") or BACKEND_ORDER
        self.max_cli_failures = 2

    # -- Tab 隔离 ---------------------------------------------------------
    def check_tab(self, tab_url: str, tab_name: str = "") -> RoutingDecision:
        """绑定的 Research Tab 是否可以继续操作。"""
        if not tab_url:
            return RoutingDecision(
                backend=TAB_GONE,
                reason="绑定的 Research Tab 已关闭或不可读；按纪律不得自动接管其他标签页。",
                requires_human=True,
                notes=["on_bound_tab_closed = TAB_GONE_HUMAN_REQUIRED"],
            )
        verdict = self.gate.classify(tab_url)
        if verdict.surface == "COMPETITION_SURFACE":
            return RoutingDecision(
                backend=BLOCKED_COMPETITION,
                reason=f"目标标签页属于比赛面（{tab_name or tab_url}），Human Only，禁止自动化。",
                compliance_decision=verdict.decision,
                compliance_surface=verdict.surface,
                requires_human=True,
            )
        if not verdict.automation_allowed:
            return RoutingDecision(
                backend=HUMAN_REQUIRED,
                reason=f"无法确认标签页归属：{verdict.reason}",
                compliance_decision=verdict.decision,
                compliance_surface=verdict.surface,
                requires_human=True,
            )
        return RoutingDecision(
            backend=AGENT_BROWSER,
            reason="Research Tab 校验通过。",
            compliance_decision=verdict.decision,
            compliance_surface=verdict.surface,
        )

    # -- 主路由 -----------------------------------------------------------
    def decide(self, task: BrowserTask) -> RoutingDecision:
        notes: list[str] = []

        # 1. 不需要浏览器就能答
        if task.answer_known_without_browser:
            return RoutingDecision(
                backend=DIRECT,
                reason="已有可直接使用的答案/知识，无需启动浏览器。",
                notes=["省下整段浏览器预算"],
            )

        # 2. 合规：目标 URL 必须是研究面
        target = task.url or task.tab_url
        compliance_decision = ""
        compliance_surface = ""
        if target:
            verdict = self.gate.classify(target)
            compliance_decision = verdict.decision
            compliance_surface = verdict.surface
            if verdict.surface == "COMPETITION_SURFACE":
                return RoutingDecision(
                    backend=BLOCKED_COMPETITION,
                    reason="目标是比赛面，禁止任何自动化接触。",
                    compliance_decision=verdict.decision,
                    compliance_surface=verdict.surface,
                    requires_human=True,
                )
            if not verdict.automation_allowed:
                return RoutingDecision(
                    backend=HUMAN_REQUIRED,
                    reason=f"目标面归属未确认：{verdict.reason}",
                    compliance_decision=verdict.decision,
                    compliance_surface=verdict.surface,
                    requires_human=True,
                )

        # 3. 人工挑战：验证码 / 登录 / 扫码 / 短信 / 2FA
        challenge = task.observed_challenge()
        if challenge:
            return RoutingDecision(
                backend=HUMAN_REQUIRED,
                reason=f"命中人工挑战信号：{challenge}。立即交接，不尝试绕过、不重试。",
                challenge=challenge,
                compliance_decision=compliance_decision,
                compliance_surface=compliance_surface,
                requires_human=True,
                notes=["auth_challenge = human"],
            )

        kind = (task.kind or "").upper()
        complex_task = kind in COMPLEX_KINDS
        simple_task = kind in SIMPLE_KINDS or not kind

        # 4. CLI 连续失败两次 -> 升级到 DevTools MCP
        if task.cli_consecutive_failures >= self.max_cli_failures:
            notes.append(
                f"agent-browser 连续失败 {task.cli_consecutive_failures} 次，升级到 PRIMARY"
            )
            complex_task = True

        # 5. 简单确定性短操作优先 CLI
        if simple_task and not complex_task:
            return RoutingDecision(
                backend=AGENT_BROWSER,
                reason="短、确定性的 UI 操作（目标 1-4 次 browser command）。",
                compliance_decision=compliance_decision,
                compliance_surface=compliance_surface,
                notes=notes + ["simple_ui = fast"],
            )

        # 6. 复杂任务走 PRIMARY
        if task.devtools_available:
            return RoutingDecision(
                backend=EDGE_DEVTOOLS_MCP,
                reason="需要复杂 DOM / JS / Network / SPA 状态读取。",
                compliance_decision=compliance_decision,
                compliance_surface=compliance_surface,
                notes=notes + ["complex_ui|javascript|network = primary"],
            )

        # 7. PRIMARY 不可用 -> FALLBACK
        if task.playwright_available:
            return RoutingDecision(
                backend=PLAYWRIGHT_MCP,
                reason="Chrome DevTools MCP 不可用，降级到 Playwright MCP Extension。",
                compliance_decision=compliance_decision,
                compliance_surface=compliance_surface,
                notes=notes + ["primary_failure = fallback"],
            )

        return RoutingDecision(
            backend=HUMAN_REQUIRED,
            reason="PRIMARY 与 FALLBACK 均不可用，且任务无法用 CLI 完成。",
            compliance_decision=compliance_decision,
            compliance_surface=compliance_surface,
            requires_human=True,
            notes=notes,
        )

    def allowed_backends(self) -> list[str]:
        return list(self.order)


def build_backend_plan(tasks: list[BrowserTask]) -> dict[str, Any]:
    """给出一组任务的路由计划，并断言不存在同一标签页的**并发**后端。

    顺序降级（agent-browser 失败 -> Chrome DevTools MCP -> Playwright MCP）是
    规定的升级路径，不算冲突。只有显式标记为同一 concurrent_group、作用于同一
    标签页、却选了不同后端时，才构成「两套工具抢同一个页面」。
    """
    router = BackendRouter()
    decisions = []
    timeline: dict[str, list[str]] = {}
    concurrent: dict[tuple[str, str], set[str]] = {}
    violations: list[str] = []
    short_circuit = {DIRECT, HUMAN_REQUIRED, TAB_GONE, BLOCKED_COMPETITION}

    for task in tasks:
        decision = router.decide(task)
        key = task.tab_name or task.tab_url or "default"
        timeline.setdefault(key, []).append(decision.backend)
        if task.concurrent_group and decision.backend not in short_circuit:
            slot = (task.concurrent_group, key)
            concurrent.setdefault(slot, set()).add(decision.backend)
        decisions.append({"task": task.kind, "tab": key, **decision.as_dict()})

    for (group, tab), backends in concurrent.items():
        if len(backends) > 1:
            violations.append(
                f"concurrent_group={group} tab={tab} 同时选了多个后端：{sorted(backends)}"
            )

    return {
        "generated_at": now_iso(),
        "router_order": router.allowed_backends(),
        "decisions": decisions,
        "tab_backend_timeline": timeline,
        "concurrent_backend_violations": violations,
        "never_run_two_backends_on_same_tab": not violations,
        "exclusive_per_tab": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--plan" in args:
        plan = build_backend_plan(
            [
                BrowserTask(kind="READ_COUNT", tab_name="Research-1",
                            url="https://kns.cnki.net/starter/advanced"),
                BrowserTask(kind="SIMPLE_NAV", tab_name="Research-1",
                            url="https://www.icourse163.org/"),
                BrowserTask(kind="SPA_STATE", tab_name="Research-2",
                            url="https://unesdoc.unesco.org/ark:/48223/pf0000393559"),
                BrowserTask(kind="JAVASCRIPT", tab_name="Research-2",
                            url="https://www.icourse163.org/search.htm"),
                BrowserTask(kind="SIMPLE_NAV", tab_name="Research-1",
                            url="https://csc.xxsuyang.com/training"),
                BrowserTask(kind="READ_FIELD", tab_name="Research-1",
                            url="https://kns.cnki.net/starter/advanced",
                            page_text="请拖动滑块完成验证"),
                BrowserTask(kind="COMPLEX_DOM", tab_name="Research-2",
                            url="https://example.com/",
                            devtools_available=False, playwright_available=True),
                BrowserTask(kind="COMPLEX_DOM", tab_name="Research-2",
                            url="https://example.com/", devtools_available=False),
                BrowserTask(kind="READ_FIELD", tab_name="Research-1",
                            url="https://kns.cnki.net/starter/advanced",
                            cli_consecutive_failures=2),
            ]
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if "--tab" in args:
        index = args.index("--tab")
        tab_url = args[index + 1] if index + 1 < len(args) else ""
        decision = BackendRouter().check_tab(tab_url)
        print(json.dumps(decision.as_dict(), ensure_ascii=False, indent=2))
        return 0 if decision.backend not in {TAB_GONE, BLOCKED_COMPETITION} else 1
    print("用法：python scripts/browser_router.py --plan | --tab <url>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

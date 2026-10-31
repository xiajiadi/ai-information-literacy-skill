"""人工交接格式化：把「我卡住了」变成「你 30 秒能搞定」。

统一格式（缺任何一项都算交接不合格）：

    🔴 HUMAN_REQUIRED
    官网：<URL>
    操作：
    1. ...
    2. ...
    复制：
    <可直接粘贴的检索式>
    查看：
    <需要读取哪个字段>
    回传：
    <让我继续所需的最少信息>

纪律（§12 / §19）：
  - 预计会卡就立刻交接，不要先浪费 60 秒再交接。
  - 识别到「这一步必然需要登录/验证码」时，第 1 秒就交接。
  - 交接后停止自动化，不做二次尝试。
  - 只索取最小必要信息，不要要求用户回传整页内容。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import EVIDENCE_HUMAN_REQUIRED  # noqa: E402

HEADER = "🔴 HUMAN_REQUIRED"

REQUIRED_FIELDS = (
    "official_url",
    "steps",
    "copyable_query",
    "target_field",
    "what_to_report_back",
)

# 触发原因 -> 建议在第几秒交接 + 一句原因说明
TRIGGER_POLICY: dict[str, tuple[str, str]] = {
    "captcha": ("1", "命中验证码/滑块，属于正常状态，禁止绕过。"),
    "block_puzzle": ("1", "CNKI blockPuzzle 安全验证，禁止绕过。"),
    "cloudflare": ("1", "Cloudflare 挑战，禁止绕过。"),
    "waf": ("1", "WAF/412 拦截，禁止绕过。"),
    "qr_login": ("1", "需要扫码登录，只能由选手本人完成。"),
    "sms_verification": ("1", "短信验证码只能由选手本人接收。"),
    "campus_authentication": ("1", "校园统一身份认证只能由选手本人完成。"),
    "account_login": ("1", "需要登录态；本执行体不接触任何凭证。"),
    "app_only": ("1", "仅限 App / 公众号，浏览器无法完成。"),
    "wechat_mp_or_miniprogram": ("1", "微信生态入口，转人工。"),
    "drm_pdf": ("1", "DRM 文档，禁止绕过。"),
    "dynamic_player": ("1", "动态播放器，需人工目视。"),
    "manual_visual_check": ("1", "需要人工目视读取（如扫描件 PDF）。"),
    "automation_failed_once": ("30", "第一次正常自动化路径失败，换人工比再试更快。"),
    "automation_failed_twice": ("45", "同一路线已失败两次，按纪律停止重试。"),
    "retry_budget_exhausted": ("45", "重试预算已用尽，按纪律停止重试。"),
    "platform_entry_unknown": ("10", "入口未实测，人工确认比临场试错快。"),
}


@dataclass
class HandoffRequest:
    official_url: str
    steps: list[str] = field(default_factory=list)
    copyable_query: str = ""
    target_field: str = ""
    what_to_report_back: str = ""
    reason: str = ""
    platform: str = ""
    field_instructions: list[str] = field(default_factory=list)
    expected_seconds: int = 30

    def validate(self) -> list[str]:
        missing: list[str] = []
        if not self.official_url.strip():
            missing.append("official_url（官网）")
        if not [s for s in self.steps if str(s).strip()]:
            missing.append("steps（操作步骤）")
        if not self.copyable_query.strip() and not self.field_instructions:
            missing.append("copyable_query（可复制检索式，或等价的分行填写说明）")
        if not self.target_field.strip():
            missing.append("target_field（需要查看哪个字段）")
        if not self.what_to_report_back.strip():
            missing.append("what_to_report_back（需要回传的最少信息）")
        return missing


def trigger_advice(reason_key: str) -> dict[str, str]:
    second, note = TRIGGER_POLICY.get(
        reason_key, ("30", "自动化不确定，人工路径更稳。")
    )
    return {"trigger": reason_key, "handoff_at_second": second, "note": note}


def render(request: HandoffRequest) -> str:
    missing = request.validate()
    if missing:
        raise ValueError(
            "交接不合格，缺少：" + "；".join(missing)
            + "。缺任何一项都算交接失败，禁止只写「请你自己查」。"
        )
    lines = [HEADER, f"官网：{request.official_url}"]
    if request.reason:
        advice = trigger_advice(request.reason)
        lines.append(f"原因：{advice['note']}（建议第 {advice['handoff_at_second']} 秒交接）")
    lines.append("")
    lines.append("操作：")
    for index, step in enumerate(request.steps, 1):
        lines.append(f"{index}. {step}")
    if request.field_instructions:
        for instruction in request.field_instructions:
            lines.append(f"   · {instruction}")
    lines.append("")
    lines.append("复制：")
    lines.append(request.copyable_query.strip() or "（该平台无可复制表达式，按上面的分行说明填写）")
    lines.append("")
    lines.append("查看：")
    lines.append(request.target_field.strip())
    lines.append("")
    lines.append("回传：")
    lines.append(request.what_to_report_back.strip())
    lines.append("")
    lines.append(f"（预计人工耗时约 {request.expected_seconds} 秒；本执行体已停止自动化，不再重试。）")
    return "\n".join(lines)


def from_routing(routing: Any, copyable_query: str = "", target_field: str = "") -> HandoffRequest:
    """从 task_router.Routing 直接生成交接请求。"""
    steps = [f"打开 {routing.primary_entry}"] if routing.primary_entry else []
    if routing.fallback_entry:
        steps.append(f"若上面打不开，改用备用入口：{routing.fallback_entry}")
    if routing.required_fields:
        steps.append("在检索界面选择字段：" + "、".join(routing.required_fields))
    if routing.filters:
        steps.append("设置筛选：" + json.dumps(routing.filters, ensure_ascii=False))
    if routing.time_constraint:
        steps.append(f"设置时间范围：{routing.time_constraint}")
    steps.append("读取结果并回传下面要求的最少信息")

    reason = "manual_visual_check"
    if routing.entry_status == "AUTH":
        reason = "account_login"
    elif routing.entry_status == "CHALLENGE":
        reason = "captcha"
    elif routing.entry_status == "BROKEN":
        reason = "platform_entry_unknown"
    elif routing.handoff_expected:
        reason = "platform_entry_unknown"

    return HandoffRequest(
        official_url=routing.primary_entry,
        steps=steps,
        copyable_query=copyable_query,
        target_field=target_field or routing.expected_output or "题目要求的字段",
        what_to_report_back=(
            f"只告诉我：{routing.expected_output or '题目要求的字段值'}"
            f"（以及你看到的访问日期）。"
        ),
        reason=reason,
        platform=routing.target_platform,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    question = " ".join(args).strip()
    if not question:
        print("用法：python scripts/handoff_format.py <题干> [--platform <平台>]")
        return 2
    from task_router import route
    from query_builder import build_query

    declared = ""
    if "--platform" in args:
        index = args.index("--platform")
        declared = args[index + 1] if index + 1 < len(args) else ""
        question = " ".join(a for a in args[:index]).strip()

    routing = route(question, declared_platform=declared)
    query_text = ""
    if routing.target_platform and routing.required_fields:
        try:
            result = build_query(
                routing.target_platform,
                [{"field": f, "value": "<题目给出的词>"} for f in routing.required_fields[:1]],
            )
            query_text = result.expression
        except (ValueError, KeyError):
            query_text = ""
    request = from_routing(routing, copyable_query=query_text)
    print(render(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

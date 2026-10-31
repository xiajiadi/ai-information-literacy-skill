"""PHASE 2 修正 §4 · 输出统一合规检查的契约测试。

Controller 要求：
  「扩大测试范围到所有来源字段、嵌套结构、备用入口和**生成的执行计划**」
  「必须阻止被屏蔽的比赛 URL 进入自动化执行路径」
  「所有新字段必须经过**统一**合规检查」

此前只对历史题库的 `reusable_recipe` 做了清洗；本组测试钉住**路由自己生成**的
输出也必须过同一个闸门。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from output_compliance import enforce_output_compliance, extract_urls  # noqa: E402
from task_router import route  # noqa: E402

COMPETITION = "https://csc.xxsuyang.com/detail?id=1"


def test_blocks_competition_url_at_every_nesting_level():
    payload = {
        "top": COMPETITION,
        "list": [f"打开 {COMPETITION}"],
        "deep": {"deeper": {"urls": ["https://example.com/ok", COMPETITION]}},
    }
    cleaned, report = enforce_output_compliance(payload)
    assert report["clean"] is False
    assert report["blocked_count"] == 3
    assert set(report["blocked_surfaces"]) == {"COMPETITION_SURFACE"}
    # 原始 URL 文本不得残留在输出里
    assert "xxsuyang" not in json.dumps(cleaned, ensure_ascii=False)


def test_keeps_legitimate_research_urls_untouched():
    payload = {
        "a": "https://www.cnki.net/",
        "b": ["https://github.com/x/y", "https://example.com/z"],
    }
    cleaned, report = enforce_output_compliance(payload)
    assert report["clean"] is True
    assert "https://www.cnki.net/" in json.dumps(cleaned, ensure_ascii=False)
    assert "https://github.com/x/y" in json.dumps(cleaned, ensure_ascii=False)


def test_blocked_records_carry_host_and_surface_but_not_the_url():
    cleaned, report = enforce_output_compliance({"u": COMPETITION})
    entry = report["blocked"][0]
    assert entry["host"] == "csc.xxsuyang.com"
    assert entry["surface"] == "COMPETITION_SURFACE"
    assert "url" not in entry, "拦截记录不应保留原始 URL"
    assert "detail?id" not in json.dumps(report, ensure_ascii=False)


def test_non_url_strings_pass_through_unchanged():
    payload = {"text": "检索路径：篇名精确检索", "n": 3, "flag": True, "none": None}
    cleaned, report = enforce_output_compliance(payload)
    assert report["blocked_count"] == 0
    assert cleaned["text"] == payload["text"]
    assert cleaned["n"] == 3 and cleaned["flag"] is True and cleaned["none"] is None


def test_live_route_output_never_leaks_competition_surface():
    """端到端：真实题干走 route()，输出里不得出现比赛面 URL。

    注意：断言的是**比赛面**不泄漏。按合规策略，默认拒绝会把
    `UNKNOWN_SURFACE`（未在白名单里、也未实测登记的主机）一并拦下，
    因此 `output_compliance.clean` 可能为 False —— 那是策略生效，不是缺陷。
    """
    probes = [
        "在CNKI高级检索界面，精确检索作者为黄智的论文，2014-2024年间共有多少篇期刊论文？",
        "武汉大学图书馆网站的资源-数字资源栏目下有一个名为“人工智能资源导航”的专题网页。下列哪个不是这个网页中的内容？",
        "在Word中，“审阅”选项卡中的功能包括（ ）。",
        "在有道云笔记网页版创建流程图，当输入Ctrl+Shift+O时，会呈现什么内容？",
    ]
    for stem in probes:
        result = route(stem)
        report = result.output_compliance or {}
        assert "COMPETITION_SURFACE" not in (report.get("blocked_surfaces") or []), stem
        blob = json.dumps(
            {
                "primary_entry": result.primary_entry,
                "fallback_entry": result.fallback_entry,
                "entry_avoid": result.entry_avoid,
                "reusable_recipe": result.reusable_recipe,
            },
            ensure_ascii=False,
        )
        assert not any("xxsuyang" in url for url in extract_urls(blob)), stem


def test_unknown_surface_hosts_are_conservatively_blocked():
    """记录一个**已知取舍**：未登记的合法主机（如 ai.cnki.net）也会被拦。

    这是合规策略「未知归属默认按比赛面处理」的直接后果。
    被拦后 entry_avoid 里的提示文本会变成 ⛔[UNKNOWN_SURFACE]，
    信息量下降，但安全边界更严。此行为是**有意的**，如需放开必须由
    Controller 把主机加入 research_surface.confirmed_hosts。
    """
    from output_compliance import enforce_output_compliance

    payload = {"entry_avoid": [{"url": "https://ai.cnki.net/", "why": "会跳验证码"}]}
    cleaned, report = enforce_output_compliance(payload)
    assert report["blocked_surfaces"] == ["UNKNOWN_SURFACE"]
    assert "⛔[UNKNOWN_SURFACE]" in json.dumps(cleaned, ensure_ascii=False)
    # 说明文字应保留，只有 URL 被替换
    assert "会跳验证码" in json.dumps(cleaned, ensure_ascii=False)


def test_execution_plan_steps_are_covered():
    """「生成的执行计划」也要过闸门 —— 步骤文本里嵌 URL 是常见形态。"""
    plan = {
        "steps": [
            "1. 打开目标平台首页",
            f"2. 若首页不可用，改走 {COMPETITION}",
            "3. 记录结果并标注访问日期",
        ],
        "field_instructions": [f"备用入口：{COMPETITION}"],
    }
    cleaned, report = enforce_output_compliance(plan)
    assert report["blocked_count"] == 2
    assert "xxsuyang" not in json.dumps(cleaned, ensure_ascii=False)
    assert "打开目标平台首页" in json.dumps(cleaned, ensure_ascii=False)

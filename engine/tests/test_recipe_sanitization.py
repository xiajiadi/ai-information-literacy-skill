"""PHASE 2 · 历史题库污染字段的数据卫生契约测试。

两个**实测存在**的污染（不是假设）：

1) `question_routes.retrieval_path` 本该写检索路径，实际写的是答案解析文本
   （实测 92/288 题），例如
       "公开样题原始答案/解析"
       "可通过使用该插件，得出答案"
   路由把它透出成 `reusable_recipe.retrieval_path`，等于把旧题答案摆在
   「操作指引」的位置。

2) `question_routes.official_url` 里混入**比赛系统**链接
   （实测 157/288 题），例如
       https://csc.xxsuyang.com/detail?id=...
   路由把它透出成「可复现的官方入口」。四层实时隔离挡得住「去访问」，
   但数据层把比赛面当成官方入口透出，是**另一条独立风险路径**。

两者都必须在透出前屏蔽。本测试钉住这个行为。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from task_router import route, sanitize_recipe  # noqa: E402


def test_answer_like_retrieval_path_is_neutralised():
    recipe = {"platform": "CNKI", "retrieval_path": "公开样题原始答案/解析"}
    cleaned = sanitize_recipe(recipe)
    assert cleaned["retrieval_path_polluted"] is True
    assert "答案" not in cleaned["retrieval_path"] or "屏蔽" in cleaned["retrieval_path"]
    # 原文不得留在任何字段里
    assert "公开样题原始答案/解析" not in json.dumps(cleaned, ensure_ascii=False)


def test_legitimate_retrieval_path_is_untouched():
    recipe = {"platform": "CNKI", "retrieval_path": "高级检索 → 篇名精确 → 记录结果数"}
    cleaned = sanitize_recipe(recipe)
    assert "retrieval_path_polluted" not in cleaned
    assert cleaned["retrieval_path"] == recipe["retrieval_path"]


def test_competition_surface_url_is_blocked_in_recipes():
    recipe = {
        "platform": "CNKI",
        "official_url": "https://csc.xxsuyang.com/detail?id=ecee9f6f-46a5-11f0",
    }
    cleaned = sanitize_recipe(recipe)
    # 递归清洗后：被拦的字段被替换，且拦截记录里**只有 host 与判定，没有原始 URL**
    assert "COMPETITION_SURFACE" in json.dumps(cleaned, ensure_ascii=False)
    assert "官方_url" not in cleaned
    assert "https://csc.xxsuyang.com" not in json.dumps(cleaned, ensure_ascii=False)
    assert cleaned["_blocked_surfaces"] == ["COMPETITION_SURFACE"]
    hosts = [item["host"] for item in cleaned["_blocked_urls"]]
    assert hosts == ["csc.xxsuyang.com"]


def test_nested_and_fallback_entries_are_also_sanitised():
    """Controller 要求把防线扩大到嵌套结构与备用入口。"""
    recipe = {
        "platform": "X",
        "nested": {"entry": "https://csc.xxsuyang.com/a"},
        "entries": ["https://example.com/ok", "https://sub.xxsuyang.com/b"],
        "fallback_entry": "https://xxsuyang.com/c",
    }
    cleaned = sanitize_recipe(recipe)
    blob = json.dumps(cleaned, ensure_ascii=False)
    assert "https://csc.xxsuyang.com" not in blob
    assert "https://sub.xxsuyang.com" not in blob
    assert "https://xxsuyang.com" not in blob
    assert "https://example.com/ok" in blob, "合法的研究站不应被误伤"
    blocked_fields = {item["field"] for item in cleaned["_blocked_urls"]}
    assert any("nested" in f for f in blocked_fields)
    assert any("entries" in f for f in blocked_fields)
    assert any("fallback" in f for f in blocked_fields)


def test_redirect_target_is_checked_not_just_the_initial_url():
    """Controller：避免只检查初始 URL 而忽略最终目标。"""
    from task_router import check_redirect_target

    result = check_redirect_target(
        "https://example.com/r", ["https://csc.xxsuyang.com/detail?id=1"]
    )
    assert result["verdict"] == "BLOCKED"
    assert result["blocked_at_some_hop"] is True
    assert len(result["hops"]) == 2

    safe = check_redirect_target("https://example.com/r", ["https://github.com/a"])
    assert safe["verdict"] == "ALLOWED"


def test_research_surface_url_is_not_blocked():
    recipe = {"platform": "GitHub", "official_url": "https://github.com/microsoft/TypeScript"}
    cleaned = sanitize_recipe(recipe)
    assert cleaned["official_url"] == recipe["official_url"]
    assert "official_url_blocked_surface" not in cleaned


def test_sanitize_recipe_handles_empty_and_none():
    assert sanitize_recipe({}) == {}
    assert sanitize_recipe(None) is None


def test_live_route_never_exposes_competition_url_or_answer_text():
    """端到端：真实题干走一遍 route()，输出里不得有比赛面 URL 或答案文本。"""
    probes = [
        "武汉大学图书馆网站的资源-数字资源栏目下有一个名为“人工智能资源导航”的专题网页。下列哪个不是这个网页中的内容？",
        "在有道云笔记网页版创建流程图，当输入Ctrl+Shift+O时，会呈现什么内容？",
        "在Word中，“审阅”选项卡中的功能包括（ ）。",
    ]
    for stem in probes:
        result = route(stem)
        blob = json.dumps(result.reusable_recipe or {}, ensure_ascii=False)
        assert "csc.xxsuyang.com" not in blob, stem
        assert "xxsuyang" not in blob, stem
        # 屏蔽后的警告文本本身含「答案/解析」字样，因此只检查非警告字段
        recipe = result.reusable_recipe or {}
        for key, value in recipe.items():
            if key.startswith("retrieval_path") or str(key).endswith("_blocked_surface"):
                continue
            text_value = str(value)
            assert "答案" not in text_value, f"{stem} :: {key}"
            assert "解析" not in text_value, f"{stem} :: {key}"

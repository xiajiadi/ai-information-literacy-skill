"""变体匹配：正式题与模拟题「同平台、同操作、换参数」时复用配方。

正式题与三套模拟题「题目设计类似」，但会更换具体对象 —— 例如模拟题考
「中国大学MOOC A 课程第 2 章」，正式题考「中国大学MOOC B 课程第 5 章」。
这类题的流程、平台、入口、字段、筛选位置完全一致，只有参数不同。

因此定义三个状态：

    OFFICIAL_MOCK_EXACT     正式题与某道模拟题完全同题
                            -> 可以直接用该题答案（由 match_engine 处理）

    OFFICIAL_MOCK_VARIANT   平台相同、操作任务相同，但课程名/论文名/作者/
                            年份/关键词/检索对象/章节/地区/机构等参数变化
                            -> 禁止使用旧题答案，但必须复用旧题的
                               platform / entry point / field settings /
                               filter method / browser recipe / manual recipe

    NEW_PATTERN             没有可比对的旧模式，走平台配方或人工

本模块只负责变体识别与配方复用，**绝不返回旧题答案**。

模板判定（A–N）是路由提示，不是事实判断；它只用来挑选可复用的配方。
"""

from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from common import normalize_question, text
from match_engine import row_field, row_options


# 变体判定的相似度下界。低于它视为无关题。
#
# 注意这里**没有有效的相似度上界**：真实的「换参数」变体在文本上与原题几乎
# 一样 —— 例如「中国大学MOOC A 课程第 2 章」改成「中国大学MOOC B 课程第 5 章」，
# 相似度常在 0.95 以上。曾经设过 0.98 的上界，结果正是这类最典型的正式题
# 被排除出去、退回 NEEDS_HUMAN，拿不到配方。
#
# 上界本来只是想避开「已由 match_engine 判定 exact/normalized_exact 并已复用
# 答案」的题，但那类题在进入本模块之前就已经返回了，不需要在这里再挡一次。
# 保守方向是对的：同型题只给配方、不给答案，宁可多标变体，不可错用旧答案。
VARIANT_FLOOR = 0.42
VARIANT_CEILING = 1.0

EXACT = "OFFICIAL_MOCK_EXACT"
VARIANT = "OFFICIAL_MOCK_VARIANT"
NEW = "NEW_PATTERN"


# 平台识别：题目文本里出现的平台名 -> 规范平台标签。
PLATFORM_ALIASES: dict[str, tuple[str, ...]] = {
    "CNKI": ("中国知网", "知网", "CNKI", "kns.cnki"),
    "维普": ("维普", "cqvip"),
    "万方": ("万方", "wanfang"),
    "PubMed": ("PubMed", "pubmed"),
    "中国大学MOOC": ("中国大学MOOC", "MOOC", "慕课", "icourse163"),
    "ScienceDirect": ("ScienceDirect", "sciencedirect", "Elsevier"),
    "UNESCO": ("UNESCO", "教科文组织", "unesdoc"),
    "IEEE": ("IEEE",),
    "国家标准全文公开系统": ("国家标准全文公开系统", "openstd", "GB/T"),
    "国家知识产权局": ("国家知识产权局", "专利", "商标"),
    "arXiv": ("arXiv",),
    "国家统计局": ("国家统计局", "统计年鉴"),
    "智慧树": ("智慧树",),
    "国家图书馆": ("国家图书馆", "国图"),
}

# 模板判定（A–N）。顺序敏感：先匹配到的优先。
#
# 顺序原则：**先判「问的是什么」，再判「在哪个界面问」**。
# 例如「在CNKI高级检索界面，精确检索……共有多少篇」问的是数量，
# 应判 B（结果数量），而不是因为出现「精确」就判 J（检索语法）。
# 因此 J 的关键词只保留真正的语法术语，不含「精确/模糊」这类通用词。
TEMPLATE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("N 多选逐项", ("多选", "以下说法", "正确的是", "不正确的是")),
    ("G 视频时长", ("时长", "前10秒", "播放")),
    ("H App/微信", ("微信", "公众号", "小程序", "APP", "App")),
    ("D PDF页码", ("PDF", "页码", "第几页", "页末", "表格名称")),
    ("L 标准/专利/药品", ("标准号", "专利", "药品", "资格", "注册号", "批准文号", "索书号")),
    ("M 馆藏/课程章节", ("课程", "章节", "小节", "大纲", "馆藏", "古籍", "藏书")),
    ("B 结果数量", ("共有", "多少条", "多少篇", "结果数量", "命中", "篇数", "条数")),
    ("C 作者机构筛选", ("第一单位", "作者单位", "机构", "导师", "排名", "排序", "筛选")),
    ("J 检索语法", ("AND", "OR", "NOT", "截词", "通配符", "运算符", "布尔", "检索式")),
    ("E 论文元数据", ("参考文献", "DOI", "卷期", "页数", "元数据", "出版信息")),
    ("F 统计/排名", ("统计", "指数", "词频", "排行榜")),
    ("I 办公软件", ("Word", "Excel", "PPT", "快捷键", "函数")),
    ("K AI产品功能", ("大模型", "豆包", "Kimi", "智谱", "通义", "文心", "讯飞")),
    ("A 平台菜单/功能", ("菜单", "功能", "栏目", "首页", "入口", "模块")),
)


@dataclass
class VariantMatch:
    status: str
    source_row: sqlite3.Row | None = None
    similarity: float = 0.0
    platform: str = ""
    template: str = ""
    recipe: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def detect_platform(*texts: str) -> str:
    """从题目文本或记录字段里识别平台标签。"""
    haystack = " ".join(text(t) for t in texts if t)
    for label, aliases in PLATFORM_ALIASES.items():
        if any(alias.lower() in haystack.lower() for alias in aliases):
            return label
    return ""


def detect_template(*texts: str) -> str:
    """判定题目模板（A–N）。仅作路由提示。"""
    haystack = " ".join(text(t) for t in texts if t)
    if not haystack:
        return ""
    for label, needles in TEMPLATE_RULES:
        if any(needle.lower() in haystack.lower() for needle in needles):
            return label
    return ""


def row_recipe(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """抽取一道题的可复用配方。**不含答案**。"""
    # 部分记录的 retrieval_query 只是把题干原样存了一遍，那不是可复制的检索式。
    # 回显旧题干容易被误当成「照抄就行」，因此这种值一律丢掉。
    query = text(row_field(row, "retrieval_query"))
    if query and query.strip() == text(row_field(row, "question_text")).strip():
        query = ""
    return {
        "platform": text(row_field(row, "official_platform")),
        "official_url": text(row_field(row, "official_url")),
        "retrieval_path": text(row_field(row, "retrieval_path")),
        "retrieval_query": query,
        "retrieval_fields": text(row_field(row, "retrieval_fields")),
        "retrieval_filters": text(row_field(row, "retrieval_filters")),
        "module_id": text(row_field(row, "module_id")),
        "module_name": text(row_field(row, "module_name")),
    }


def list_parameter_diff(source: sqlite3.Row | dict[str, Any],
                        question_text: str) -> list[str]:
    """列出「哪些参数变了」——即不能照抄旧答案的理由。

    只做提示，不参与判定。
    """
    changes: list[str] = []
    src = text(row_field(source, "question_text"))
    # 数字（年份、章节号、页码、数量）变化
    src_nums = re.findall(r"\d+", src)
    new_nums = re.findall(r"\d+", text(question_text))
    if src_nums != new_nums:
        changes.append(f"数字参数变化：原 {src_nums[:6]} -> 新 {new_nums[:6]}")
    # 书名号 / 引号内的专名变化
    pattern = r"[《“\"']([^》”\"']{2,40})[》”\"']"
    src_names = re.findall(pattern, src)
    new_names = re.findall(pattern, text(question_text))
    if src_names != new_names:
        changes.append(f"专名变化：原 {src_names[:4]} -> 新 {new_names[:4]}")
    return changes


def find_variant(
    conn: sqlite3.Connection,
    question_text: str,
    rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row],
    floor: float = VARIANT_FLOOR,
    ceiling: float = VARIANT_CEILING,
    limit: int = 3,
) -> VariantMatch:
    """在题库里找与本题最像的「同型题」。

    排序依据（依次）：平台匹配 > 模板匹配 > 文本相似度。
    找到后返回可复用配方；**不返回旧题答案**。
    """
    normalized = normalize_question(question_text)
    if not normalized:
        return VariantMatch(status=NEW, notes=["题干为空"])

    target_platform = detect_platform(question_text)
    target_template = detect_template(question_text)

    scored: list[tuple[int, int, float, sqlite3.Row]] = []
    for row in rows:
        source_text = text(row_field(row, "question_text"))
        if not source_text:
            continue
        ratio = difflib.SequenceMatcher(
            None, normalized, text(row_field(row, "normalized_question")) or normalize_question(source_text)
        ).ratio()
        if ratio < floor or ratio > ceiling:
            continue
        row_platform = detect_platform(
            text(row_field(row, "official_platform")), source_text
        )
        row_template = detect_template(source_text)
        scored.append((
            1 if (target_platform and target_platform == row_platform) else 0,
            1 if (target_template and target_template == row_template) else 0,
            ratio,
            row,
        ))

    if not scored:
        return VariantMatch(
            status=NEW, platform=target_platform, template=target_template,
            notes=[f"未找到 {floor:.2f}–{ceiling:.2f} 区间内的同型题，按平台配方处理"],
        )

    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]["id"]))
    platform_hit, template_hit, ratio, best = scored[0]

    # 题干里未必点名平台（例如「在高级检索界面，精确检索作者为……」）。
    # 此时必须回落到参照题自身的平台，否则配方会丢掉平台这一最关键字段。
    reference_platform = detect_platform(
        text(row_field(best, "official_platform")),
        text(row_field(best, "question_text")),
        text(row_field(best, "official_url")),
        text(row_field(best, "module_name")),
    )
    resolved_platform = target_platform or reference_platform

    notes = []
    if platform_hit:
        notes.append(f"平台一致：{target_platform}")
    elif resolved_platform:
        notes.append(f"平台由参照题回落：{resolved_platform}")
    if template_hit:
        notes.append(f"操作类型一致：{target_template}")
    notes.append(f"文本相似度 {ratio:.2f}（区间 {floor:.2f}–{ceiling:.2f}）")
    notes += list_parameter_diff(best, question_text)[:2]

    recipe = row_recipe(best)
    # 有路由记录时以路由为准，它比题目快照更接近真实入口。
    route = conn.execute(
        "SELECT * FROM question_routes WHERE question_id = ? "
        "ORDER BY (deep_link <> '') DESC, route_confidence LIMIT 1",
        (best["id"],),
    ).fetchone()
    if route:
        recipe.update({
            "platform": text(route["official_platform"]) or recipe["platform"],
            "official_url": text(route["deep_link"]) or text(route["official_url"]) or recipe["official_url"],
            "retrieval_recipe": text(route["retrieval_recipe"]),
            "manual_recipe": text(route["manual_recipe"]),
            "requires_login": text(route["requires_login"]),
            "manual_only": int(route["manual_only"] or 0),
            "platform_key": text(route["platform_key"]),
        })
        notes.append(f"复用路由配方：{text(route['platform_key'])}")

    return VariantMatch(
        status=VARIANT,
        source_row=best,
        similarity=ratio,
        platform=resolved_platform or recipe.get("platform", ""),
        template=target_template or detect_template(text(row_field(best, "question_text"))),
        recipe=recipe,
        notes=notes,
    )


def render_variant(match: VariantMatch, question_text: str) -> str:
    """变体题输出：给流程与参数位，**不给答案**。"""
    if match.status != VARIANT or match.source_row is None:
        return ""

    recipe = match.recipe
    lines = [
        "🟡 模拟题同型题（换参数）",
        f"参照：{match.source_row['id']}  相似度 {match.similarity:.2f}",
        f"平台：{match.platform or recipe.get('platform') or '需确认'}",
        f"操作类型：{match.template or '未判定'}",
        "",
        "复用配方（参数需替换为本题的）：",
    ]
    url = recipe.get("official_url")
    if url:
        lines.append(f"入口：{url}")
    steps = text(recipe.get("retrieval_recipe")) or text(recipe.get("retrieval_path"))
    if steps:
        for index, step in enumerate(re.split(r"\s*→\s*", steps), 1):
            if step.strip():
                lines.append(f"{index}. {step.strip()}")
    for label, key in (("字段", "retrieval_fields"), ("筛选", "retrieval_filters"),
                       ("检索式", "retrieval_query")):
        value = text(recipe.get(key))
        if value:
            lines.append(f"{label}：{value}")
    if recipe.get("requires_login") == "YES" or recipe.get("manual_only"):
        lines += ["", "🔴 该配方需登录/人工，直接转人工交接。"]
    lines += ["", "⚠️ 参数已变，禁止套用参照题答案，必须在官方平台重新核验。"]
    return "\n".join(lines)

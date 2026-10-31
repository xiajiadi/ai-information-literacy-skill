"""检索式生成：把「平台 + 字段 + 词 + 逻辑 + 时间」变成可直接粘贴的检索式。

铁律（§9 / §17 / skill/manual_recipes.md）：

    CNKI 语法 ≠ 万方   PubMed 语法 ≠ IEEE   Wiley 语法 ≠ ScienceDirect

不同库的语法**严禁混用**。本模块按平台分派到独立的生成器，任何一个生成器
都不会借用另一个平台的运算符或字段标记。不确定语法时一律要求改用图形高级检索，
不猜语法。

输出永远是「可复制的表达式 + 界面上选哪个字段 + 匹配方式」，只给一行裸表达式
等于没交接。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import (  # noqa: E402
    LEGACY_QUERY_TEMPLATES_PATH,
    load_json,
)

MODE_BARE_ADVANCED = "ADVANCED_SEARCH_BARE"
MODE_PROFESSIONAL = "PROFESSIONAL_EXPRESSION"
MODE_FIELD_EQUALS = "FIELD_EQUALS"
MODE_TAGGED = "TAGGED_FIELD"
MODE_SITE_SEARCH = "SITE_SEARCH"
MODE_URL_QUERY = "URL_QUERY"
MODE_NOT_AN_EXPRESSION = "NOT_AN_EXPRESSION"
MODE_UNSUPPORTED = "UNSUPPORTED"

# CNKI 专业检索字段代码（来源：skill/cnki_search_syntax.md，官方手册）
CNKI_CODES = {
    "主题": "SU", "篇关摘": "TKA", "关键词": "KY", "篇名": "TI", "全文": "FT",
    "作者": "AU", "第一作者": "FI", "通讯作者": "RP", "作者单位": "AF",
    "基金": "FU", "摘要": "AB", "小标题": "CO", "参考文献": "RF",
    "分类号": "CLC", "文献来源": "LY", "DOI": "DOI", "被引频次": "CF",
}

# PubMed 字段标记（官方语法）
PUBMED_TAGS = {
    "Title": "[Title]", "Title/Abstract": "[Title/Abstract]", "Author": "[Author]",
    "MeSH Terms": "[MeSH Terms]", "Journal": "[Journal]",
    "Date - Publication": "[dp]", "Abstract": "[Abstract]",
}

CNKI_SPECIAL_CHARS = set(" *+-()/%=")


@dataclass
class Clause:
    field: str = ""
    value: str = ""
    op: str = "AND"


@dataclass
class QueryResult:
    platform_key: str
    mode: str
    expression: str = ""
    entry: str = ""
    syntax_verified: bool = False
    verification_note: str = ""
    warnings: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    field_instructions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _templates() -> dict[str, dict[str, Any]]:
    data = load_json(LEGACY_QUERY_TEMPLATES_PATH)
    return {t["platform_key"]: t for t in data.get("templates", [])}


def _quote_cnki(value: str) -> str:
    value = value.strip()
    if any(char in CNKI_SPECIAL_CHARS for char in value):
        if "'" in value:
            return f'"{value}"'
        return f"'{value}'"
    return value


def _op_cnki(op: str) -> str:
    return {"AND": "*", "OR": "+", "NOT": "-"}.get(op.upper(), "*")


def _op_word(op: str) -> str:
    op = (op or "AND").upper()
    return op if op in {"AND", "OR", "NOT"} else "AND"


def _require_clauses(clauses: list[Clause]) -> list[Clause]:
    cleaned = [c for c in clauses if c.value and c.value.strip()]
    if not cleaned:
        raise ValueError("检索式至少需要一个检索词。")
    if any(not c.field.strip() for c in cleaned):
        raise ValueError("每个检索词都必须指定字段；不指定字段等于没有交接。")
    return cleaned


# ---------------------------------------------------------------------------
# 各平台生成器
# ---------------------------------------------------------------------------

def build_cnki(clauses: list[Clause], professional: bool = False) -> QueryResult:
    """CNKI：高级检索框内只填**裸表达式**；专业检索才用字段代码前缀。

    这是 CNKI 最容易出错的地方：高级检索的字段是**界面下拉**选的，把
    `篇名=xxx` 写进高级检索框是错的。因此：

      - 同一字段的多个词  -> 可合成一条裸表达式放进单个框
      - 跨字段的多个条件  -> 输出「每行选哪个字段 + 框里填什么」，不硬凑成一行
    """
    clauses = _require_clauses(clauses)
    template = _templates().get("cnki", {})
    warnings: list[str] = [
        "高级检索框内 `*`=与、`+`=或；用错符号会让结论反转。",
        "高级检索框内只填裸表达式，字段由界面下拉选定；`SU=` 等字段代码只在专业检索用。",
    ]

    if professional:
        parts = []
        for index, clause in enumerate(clauses):
            code = CNKI_CODES.get(clause.field.strip())
            if not code:
                raise ValueError(
                    f"CNKI 专业检索没有字段「{clause.field}」。"
                    f"可用字段：{'、'.join(CNKI_CODES)}"
                )
            prefix = "" if index == 0 else f" {_op_word(clause.op)} "
            parts.append(f"{prefix}{code}='{clause.value.strip()}'")
        return QueryResult(
            platform_key="cnki",
            mode=MODE_PROFESSIONAL,
            expression="".join(parts),
            entry=template.get("entry", "https://kns.cnki.net/starter/advanced"),
            syntax_verified=bool(template.get("verified")),
            verification_note=template.get("verification_note", ""),
            warnings=warnings,
            field_instructions=["界面切到【专业检索】页签，整行粘贴到检索框。"],
        )

    fields = {c.field.strip() for c in clauses}
    if len(fields) == 1:
        field = clauses[0].field.strip()
        expression = ""
        for index, clause in enumerate(clauses):
            term = _quote_cnki(clause.value)
            if index == 0:
                expression = term
            else:
                expression += f" {_op_cnki(clause.op)} {term}"
        if len(expression) > 120:
            warnings.append(
                f"表达式 {len(expression)} 字符，超过 CNKI 单框 120 字符上限；请减少检索词。"
            )
        return QueryResult(
            platform_key="cnki",
            mode=MODE_BARE_ADVANCED,
            expression=expression,
            entry=template.get("entry", "https://kns.cnki.net/starter/advanced"),
            syntax_verified=bool(template.get("verified")),
            verification_note=template.get("verification_note", ""),
            warnings=warnings,
            field_instructions=[f"高级检索：字段下拉选【{field}】，框内粘贴上面的表达式。"],
        )

    # 跨字段：不合成一行，改为逐行交接。
    rows = []
    instructions = []
    for index, clause in enumerate(clauses):
        field = clause.field.strip()
        if field not in CNKI_CODES:
            raise ValueError(
                f"CNKI 高级检索没有检索项「{field}」。可用字段：{'、'.join(CNKI_CODES)}"
            )
        op = "（首行）" if index == 0 else _op_cnki(clause.op)
        rows.append(f"行{index + 1}｜字段={field}｜逻辑={op}｜框内填：{_quote_cnki(clause.value)}")
        instructions.append(
            f"第 {index + 1} 行：下拉选【{field}】，逻辑选【{op}】，框内填 {_quote_cnki(clause.value)}"
        )
    warnings.append(
        "跨字段条件无法合成到 CNKI 高级检索的单个框内（字段由下拉决定）；按下面的分行说明逐行填写。"
    )
    return QueryResult(
        platform_key="cnki",
        mode=MODE_BARE_ADVANCED,
        expression="",
        entry=template.get("entry", "https://kns.cnki.net/starter/advanced"),
        syntax_verified=bool(template.get("verified")),
        verification_note=template.get("verification_note", ""),
        warnings=warnings,
        steps=rows,
        field_instructions=instructions,
    )


def build_vip(clauses: list[Clause]) -> QueryResult:
    clauses = _require_clauses(clauses)
    template = _templates().get("vip", {})
    parts = []
    for index, clause in enumerate(clauses):
        prefix = "" if index == 0 else f" {_op_word(clause.op)} "
        parts.append(f"{prefix}{clause.field.strip()}={clause.value.strip()}")
    expression = "".join(parts)
    return QueryResult(
        platform_key="vip",
        mode=MODE_FIELD_EQUALS,
        expression=expression,
        entry=template.get("entry", "https://www.cqvip.com/advancesearch"),
        syntax_verified=bool(template.get("verified")),
        verification_note=template.get("verification_note", ""),
        warnings=[
            "运算符前后必须有空格；优先级 NOT > AND > OR。",
            "维普的「精确/模糊」语义与 CNKI 不同，不要套用。",
        ],
        field_instructions=["在【高级检索】逐行选择检索项，按上面顺序填写检索词与逻辑关系。"],
    )


def build_wanfang(clauses: list[Clause]) -> QueryResult:
    clauses = _require_clauses(clauses)
    template = _templates().get("wanfang", {})
    parts = []
    for index, clause in enumerate(clauses):
        prefix = "" if index == 0 else f" {_op_word(clause.op)} "
        parts.append(f"{prefix}({clause.field.strip()}:{clause.value.strip()})")
    return QueryResult(
        platform_key="wanfang",
        mode=MODE_FIELD_EQUALS,
        expression="".join(parts),
        entry=template.get("entry", "https://s.wanfangdata.com.cn/paper"),
        syntax_verified=bool(template.get("verified")),
        verification_note=template.get("verification_note", ""),
        warnings=[
            "万方运算符符号本轮未逐条实测，语法为未验证：优先用图形高级检索。",
            "万方高级检索默认「模糊」不是「精确」，必须手动改。",
        ],
        field_instructions=["打开高级检索，先选文献类型，再配字段与年份。"],
    )


def build_pubmed(
    clauses: list[Clause], start_year: str = "", end_year: str = ""
) -> QueryResult:
    clauses = _require_clauses(clauses)
    template = _templates().get("pubmed", {})
    parts = []
    for index, clause in enumerate(clauses):
        tag = PUBMED_TAGS.get(clause.field.strip())
        if not tag:
            raise ValueError(
                f"PubMed 没有字段标记「{clause.field}」。可用：{'、'.join(PUBMED_TAGS)}"
            )
        prefix = "" if index == 0 else f" {_op_word(clause.op)} "
        parts.append(f'{prefix}{clause.value.strip()}{tag}')
    expression = "".join(parts)
    if start_year and end_year:
        expression += f" AND {start_year}:{end_year}[dp]"
    elif start_year:
        expression += f" AND {start_year}[dp]"
    return QueryResult(
        platform_key="pubmed",
        mode=MODE_TAGGED,
        expression=expression,
        entry=template.get("entry", "https://pubmed.ncbi.nlm.nih.gov/advanced/"),
        syntax_verified=bool(template.get("verified")),
        verification_note=template.get("verification_note", ""),
        warnings=[],
        field_instructions=["可直接把整条式粘贴进 PubMed 检索框，或用 Advanced Search 逐行构建。"],
    )


def build_ieee(clauses: list[Clause]) -> QueryResult:
    clauses = _require_clauses(clauses)
    template = _templates().get("ieee", {})
    supported = {
        "Document Title", "Author", "Publication Year", "Author Affiliations",
        "Publication Title", "Abstract", "Index Terms",
    }
    parts = []
    for index, clause in enumerate(clauses):
        if clause.field.strip() not in supported:
            raise ValueError(
                f"IEEE Xplore 高级检索没有字段「{clause.field}」。可用：{'、'.join(sorted(supported))}"
            )
        prefix = "" if index == 0 else f" {_op_word(clause.op)} "
        parts.append(f'{prefix}("{clause.value.strip()}")')
    return QueryResult(
        platform_key="ieee",
        mode=MODE_TAGGED,
        expression="".join(parts),
        entry=template.get("entry", "https://ieeexplore.ieee.org/search/advanced"),
        syntax_verified=bool(template.get("verified")),
        verification_note=template.get("verification_note", ""),
        warnings=[
            "IEEE 的 wildcard 语法不得复制到其他平台；本轮未实测通配符写法。",
            "优先用 /search/advanced 图形界面逐字段填写。",
        ],
        field_instructions=["进入 /search/advanced，在每个字段框分别填写。"],
    )


def build_site_search(domain: str, terms: str) -> QueryResult:
    template = _templates().get("_search_engine", {})
    return QueryResult(
        platform_key="_search_engine",
        mode=MODE_SITE_SEARCH,
        expression=f"site:{domain.strip()} {terms.strip()}".strip(),
        entry="https://cn.bing.com/",
        syntax_verified=True,
        verification_note="通用搜索引擎语法。",
        warnings=["搜索结果只用于定位官方页面；打开官方源后再取证据，不得以摘要作为最终证据。"],
    )


def build_url_query(platform_key: str, base: str, param: str, value: str) -> QueryResult:
    from urllib.parse import quote

    separator = "&" if "?" in base else "?"
    return QueryResult(
        platform_key=platform_key,
        mode=MODE_URL_QUERY,
        expression=f"{base}{separator}{param}={quote(value)}",
        entry=base,
        syntax_verified=True,
        warnings=[],
        field_instructions=["直接打开该 URL，页面加载后读取结果字段。"],
    )


def build_navigation(platform_key: str, steps: list[str], entry: str) -> QueryResult:
    return QueryResult(
        platform_key=platform_key,
        mode=MODE_NOT_AN_EXPRESSION,
        expression="",
        entry=entry,
        syntax_verified=True,
        warnings=["该平台没有可复制的检索表达式，按步骤在图形界面操作。"],
        steps=steps,
        field_instructions=["按 steps 逐步操作，遇到登录/验证码立即转人工。"],
    )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

SUPPORTED = {"cnki", "vip", "wanfang", "pubmed", "ieee", "_search_engine"}


def build_query(
    platform_key: str,
    clauses: list[dict[str, Any]] | list[Clause],
    time_range: tuple[str, str] | None = None,
    professional: bool = False,
) -> QueryResult:
    """按平台生成检索式。平台不支持时返回 mode=UNSUPPORTED，并要求改用图形界面。"""
    key = (platform_key or "").strip().lower()
    normalized: list[Clause] = []
    for clause in clauses:
        if isinstance(clause, Clause):
            normalized.append(clause)
        else:
            normalized.append(
                Clause(
                    field=str(clause.get("field", "")),
                    value=str(clause.get("value", "")),
                    op=str(clause.get("op", "AND")),
                )
            )

    if key == "cnki":
        return build_cnki(normalized, professional=professional)
    if key == "vip":
        return build_vip(normalized)
    if key == "wanfang":
        return build_wanfang(normalized)
    if key == "pubmed":
        start, end = (time_range or ("", ""))
        return build_pubmed(normalized, start, end)
    if key == "ieee":
        return build_ieee(normalized)
    if key in {"_search_engine", "search_engine"}:
        first = normalized[0] if normalized else Clause(value="")
        return build_site_search(first.field or "", first.value)

    template = _templates().get(key, {})
    if template:
        return QueryResult(
            platform_key=key,
            mode=MODE_UNSUPPORTED,
            entry=template.get("entry", ""),
            syntax_verified=False,
            warnings=[
                f"平台 {key} 没有经过验证的检索语法生成器。",
                "不要借用其他平台的运算符；改用该平台的图形高级检索。",
            ],
            steps=template.get("steps", []) or [],
        )
    return QueryResult(
        platform_key=key,
        mode=MODE_UNSUPPORTED,
        syntax_verified=False,
        warnings=[
            f"未收录平台 {key}。",
            "不得自行猜测语法；先用图形高级检索，或转人工交接。",
        ],
    )


def assert_no_syntax_mixing(result: QueryResult, target_platform: str) -> None:
    """防止把 A 平台的语法套到 B 平台上。"""
    if result.platform_key != (target_platform or "").strip().lower():
        # 搜索引擎模板是通用语法，允许跨平台定位官方页。
        if result.platform_key not in {"_search_engine"}:
            raise ValueError(
                f"语法混用：为 {result.platform_key} 生成的表达式不能用于 {target_platform}。"
            )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        print(
            "用法：python scripts/query_builder.py <platform> <field> <value> "
            "[<op> <field> <value> ...] [--professional] [--years YYYY-YYYY]"
        )
        print("示例：python scripts/query_builder.py cnki 篇名 信息素养")
        return 2
    professional = "--professional" in args
    args = [a for a in args if a != "--professional"]
    years: tuple[str, str] | None = None
    if "--years" in args:
        index = args.index("--years")
        span = args[index + 1] if index + 1 < len(args) else ""
        del args[index:index + 2]
        if "-" in span:
            years = tuple(span.split("-", 1))  # type: ignore[assignment]

    platform = args[0]
    rest = args[1:]
    clauses: list[dict[str, Any]] = []
    for index in range(0, len(rest), 3):
        chunk = rest[index:index + 3]
        if len(chunk) < 2:
            break
        field, value = chunk[0], chunk[1]
        op = chunk[2] if len(chunk) > 2 else "AND"
        clauses.append({"field": field, "value": value, "op": op})

    result = build_query(platform, clauses, years, professional=professional)
    payload = result.as_dict()
    payload["copyable"] = result.expression or "（该平台无可复制表达式，见 steps）"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

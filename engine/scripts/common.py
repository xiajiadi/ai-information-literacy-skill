from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "question_bank.sqlite"
RAW_DIR = ROOT / "data" / "raw"
NORMALIZED_DIR = ROOT / "data" / "normalized"
EVIDENCE_DIR = ROOT / "data" / "evidence"
EXPORT_DIR = ROOT / "data" / "exports"
LOG_PATH = ROOT / "logs" / "activity.jsonl"

SOURCE_TYPE_TO_ID = {
    "2026官网公开知识模块样题": "S02",
    "2025公开备赛指南样题": "S07",
    "2024公开备赛指南样题": "S08",
}

SOURCE_PRIORITY = {
    # The three 2026 simulation sets are the P0 answer key for original-question
    # matching. Their keys live in questions.mock_key, never in standard_answer.
    "用户提供模拟题整理": 0,
    "2026官网公开知识模块样题": 1,
    "组委会/官方培训资料": 2,
    "2025公开备赛指南样题": 4,
    "2024公开备赛指南样题": 4,
    "官方平台实时查询": 5,
    "第三方辅助网页": 6,
    "模型推断": 7,
}

# URLs in the supplied HTML/PDF text are followed by Chinese prose very
# often. Restricting the token to URL-safe ASCII characters avoids storing
# that prose as part of the URL while retaining query strings and fragments.
URL_TOKEN_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'*+,;=%-]+", re.IGNORECASE)
MARKDOWN_URL_RE = re.compile(
    r"\[([^\]\r\n]+)\]\(\s*https?://[^)\s]+\s*\)",
    re.IGNORECASE,
)
MARKDOWN_TARGET_RE = re.compile(
    r"\[([^\]\r\n]+)\]\(\s*(https?://[^)\s]+)\s*\)",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_text(value: Any, strip_urls: bool) -> str:
    raw = html.unescape(unicodedata.normalize("NFKC", text(value))).lower()
    if strip_urls:
        # A URL is evidence/metadata, not part of the semantic question match.
        # This makes raw URL, Markdown URL and URL-removed variants equivalent.
        raw = MARKDOWN_URL_RE.sub(" ", raw)
        raw = URL_TOKEN_RE.sub(" ", raw)
    else:
        # Option URLs are answer-bearing content. For a Markdown-wrapped URL,
        # compare the target URL rather than the visual label.
        raw = MARKDOWN_TARGET_RE.sub(r"\2", raw)
    raw = raw.replace("\u3000", " ")
    raw = re.sub(r"https?://\s+", "http://", raw)
    raw = re.sub(r"(?<=\d)[,\s]+(?=\d)", "", raw)
    punctuation = {
        "（": "(", "）": ")", "【": "[", "】": "]", "：": ":",
        "，": ",", "。": ".", "；": ";", "！": "!", "？": "?",
        "“": '"', "”": '"', "‘": "'", "’": "'", "、": ",",
        "—": "-", "–": "-", "－": "-", "·": " ",
    }
    raw = "".join(punctuation.get(ch, ch) for ch in raw)
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"\s*([,.;:!?()\[\]])\s*", r"\1", raw)
    return raw.strip()


def normalize_question(value: Any) -> str:
    return _normalize_text(value, strip_urls=True)


def normalize_option(value: Any) -> str:
    return _normalize_text(value, strip_urls=False)


def option_signature(options: dict[str, Any]) -> str:
    values = [normalize_option(options.get(letter, "")) for letter in "ABCD"]
    return "|".join(sorted(v for v in values if v))


def question_hash(question_text: Any, options: dict[str, Any] | None = None) -> str:
    normalized = normalize_question(question_text)
    option_part = option_signature(options or {})
    return hashlib.sha256((normalized + "\n" + option_part).encode("utf-8")).hexdigest()


def infer_stability(question_text: Any, explanation: Any = "") -> str:
    value = f"{text(question_text)} {text(explanation)}"
    dynamic = (
        "当前", "实时", "排名", "词频", "指数", "检索结果",
        "收录", "发文最多", "关注量", "订阅地址", "结果最多",
        "排名前", "近十年", "截至",
    )
    static = (
        "标准", "法规", "文件正文", "第29页", "第10页", "页码", "快捷键",
        "GB/T", "著录", "学术不端", "标题样式", "函数", "DOI", "identifier",
        "许可证", "license", "原始论文", "正文第",
    )
    semi_dynamic = (
        "网站", "官网", "页面", "功能", "栏目", "入口", "工具", "插件",
        "登录", "数据库", "系统", "界面", "菜单", "平台", "AI", "app",
        "网页版", "客户端", "搜索", "检索",
    )
    if any(token.lower() in value.lower() for token in dynamic):
        return "DYNAMIC"
    if any(token.lower() in value.lower() for token in static):
        return "STATIC"
    if any(token.lower() in value.lower() for token in semi_dynamic):
        return "SEMI_DYNAMIC"
    return "STATIC"


def source_id_for_type(source_type: Any) -> str:
    return SOURCE_TYPE_TO_ID.get(text(source_type), "S99")


def source_priority_for_type(source_type: Any) -> int:
    return SOURCE_PRIORITY.get(text(source_type), 7)


def verification_for_seed(source_type: Any) -> str:
    value = text(source_type)
    if value in SOURCE_TYPE_TO_ID:
        return "OFFICIAL_ANSWER"
    return "UNVERIFIED"


def confidence_for_seed(source_type: Any) -> str:
    return "HIGH" if text(source_type) in SOURCE_TYPE_TO_ID else "LOW"


def extract_urls(value: Any) -> list[str]:
    found = URL_TOKEN_RE.findall(html.unescape(text(value)))
    cleaned: list[str] = []
    for url in found:
        value = url.rstrip(".,;:!?，。；：！？")
        # The token regex intentionally permits parentheses in query/path
        # text. Remove only an unmatched closing delimiter from prose.
        for close, opening in ((")", "("), ("]", "["), ("}", "{")):
            while value.endswith(close) and value.count(close) > value.count(opening):
                value = value[:-1]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def module_no(module_id: Any) -> int | None:
    match = re.search(r"(\d{1,2})", text(module_id))
    return int(match.group(1)) if match else None


def category_for_module(module_no_value: int | None) -> str:
    if module_no_value is None:
        return "未分类"
    ranges = [
        (1, 7, "AI素养"),
        (8, 16, "政府开放信息"),
        (17, 20, "实用学习资源"),
        (21, 25, "学术信息资源"),
        (26, 30, "信息检索系统"),
        (31, 37, "信息检索理论与技术"),
        (38, 41, "知识管理工具"),
        (42, 45, "学术写作"),
        (46, 50, "科研工具"),
    ]
    for start, end, category in ranges:
        if start <= module_no_value <= end:
            return category
    return "未分类"


def field_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def log_activity(event: str, payload: dict[str, Any] | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": now_iso(), "event": event, **(payload or {})}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json_text(record) + "\n")

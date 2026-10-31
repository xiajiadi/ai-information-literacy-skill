from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, normalize_option, now_iso, text
from db_schema import connect_db, ensure_schema


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URLS = ROOT / "config" / "official_urls.json"
DEFAULT_REPORT = ROOT / "data" / "quality" / "mock_quality_report.md"
DEFAULT_JSON = ROOT / "data" / "quality" / "mock_quality.json"
LETTERS = "ABCD"


def canonical_answer(value: str) -> set[str]:
    raw = text(value).upper()
    return {char for char in raw if char in LETTERS}


def probe_url(url: str, timeout: int) -> dict:
    parts = urlsplit(url)
    request_url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    request = urllib.request.Request(request_url, method="HEAD", headers={"User-Agent": "AIPlusQuestionBankQuality/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "status": response.status, "classification": "HTTP_RESPONSE", "ok": True}
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code, "classification": "HTTP_RESPONSE", "ok": exc.code not in {404, 410}}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"url": url, "status": None, "classification": type(exc).__name__, "ok": False}


def conflict_items(rows) -> list[dict]:
    findings = []
    for row in rows:
        answer = canonical_answer(row["standard_answer"] or row["provisional_answer"])
        explanation = text(row["answer_explanation"])
        if not answer or not explanation:
            continue
        for letter in LETTERS:
            says_wrong = re.search(fr"{letter}\s*(?:选项|答案)?\s*(?:错误|不正确|不对|有误)", explanation, re.IGNORECASE)
            says_right = re.search(fr"{letter}\s*(?:选项|答案)?\s*(?:正确|是正确)", explanation, re.IGNORECASE)
            if says_wrong and letter in answer:
                findings.append({"category": "答案/解析潜在冲突", "id": row["id"], "detail": f"答案含 {letter}，解析同时出现“{letter}选项错误”表述。"})
            if says_right and letter not in answer and row["question_type"] != "判断题":
                findings.append({"category": "答案/解析潜在冲突", "id": row["id"], "detail": f"解析出现“{letter}选项正确”，但答案未含 {letter}。"})
    return findings


def typo_items(rows) -> list[dict]:
    findings = []
    explicit = ("的的", "单击击", "设置设置", "输入输入", "搜索搜索", "点击点击", "多余10")
    for row in rows:
        combined = f"{row['question_text'] or ''} {row['answer_explanation'] or ''}"
        hits = [token for token in explicit if token in combined]
        if hits:
            findings.append({"category": "解析/题干疑似笔误", "id": row["id"], "detail": "发现：" + "、".join(hits) + "；保留原文，待人工确认。"})
        if "�" in combined or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", combined):
            findings.append({"category": "题干异常字符", "id": row["id"], "detail": "出现替换字符或控制字符。"})
    return findings


def option_items(rows) -> list[dict]:
    findings = []
    for row in rows:
        values: dict[str, list[str]] = {}
        expected = ("A", "B") if row["question_type"] == "判断题" else LETTERS
        for letter in expected:
            value = normalize_option(row[f"option_{letter.lower()}"])
            if value:
                values.setdefault(value, []).append(letter)
        duplicates = ["/".join(letters) for letters in values.values() if len(letters) > 1]
        if duplicates:
            findings.append({"category": "选项文本重复", "id": row["id"], "detail": "重复选项：" + "、".join(duplicates)})
    return findings


def year_items(rows) -> list[dict]:
    findings = []
    for row in rows:
        combined = f"{row['question_text'] or ''} {row['answer_explanation'] or ''}"
        years = [int(value) for value in re.findall(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)", combined)]
        unusual = sorted({year for year in years if year > 2026 or year < 1900})
        if unusual:
            findings.append({"category": "年份异常", "id": row["id"], "detail": "出现待确认年份：" + "、".join(map(str, unusual))})
    return findings


def platform_alias_items(rows) -> list[dict]:
    aliases = {
        "知网": "CNKI",
        "中国知网": "CNKI",
        "国家数据": "国家统计局国家数据",
        "Pub scholar": "PubScholar",
        "维普资讯": "维普",
        "通义": "通义千问/千问",
    }
    findings = []
    for row in rows:
        combined = f"{row['question_text'] or ''} {row['answer_explanation'] or ''}"
        hits = [f"{alias}→{canonical}" for alias, canonical in aliases.items() if alias in combined]
        if hits:
            findings.append({"category": "平台名称别名", "id": row["id"], "detail": "；".join(hits) + "；不自动改写原题。"})
    return findings


def render_report(result: dict) -> str:
    counts = result["finding_counts"]
    lines = [
        "# 150 道模拟题质量审计",
        "",
        f"> 审计时间：{result['generated_at']}；范围：{result['question_count']} 道用户提供模拟题。",
        "> 本报告只标记疑点，不修改 `standard_answer`、`provisional_answer`、题干、选项或解析原文。用户提供模拟题答案仍是练习参考。",
        "",
        "## 汇总",
        "",
        f"- 发现题库异常：{result['issue_count']} 项。",
        f"- 潜在答案/解析冲突：{counts.get('答案/解析潜在冲突', 0)}；疑似笔误/字符：{counts.get('解析/题干疑似笔误', 0) + counts.get('题干异常字符', 0)}；重复选项：{counts.get('选项文本重复', 0)}。",
        f"- URL 明确失效：{result['url_failures_count']} 条；不完整 token：{result['url_unresolved_count']} 条；网络超时/访问受限：{result['url_probe_warnings_count']} 条（不直接判定为失效）。",
        "",
        "## 最重要的 3 项异常",
        "",
    ]
    lines.extend(f"{index}. {item['category']}｜{item['id']}｜{item['detail']}" for index, item in enumerate(result["top_findings"], 1))
    if not result["top_findings"]:
        lines.append("1. 未发现需要列为重点的题库异常。")
    lines.extend(["", "## 分类明细", ""])
    for category, items in sorted(result["findings_by_category"].items()):
        lines.append(f"### {category}（{len(items)}）")
        lines.append("")
        lines.extend(f"- `{item['id']}`：{item['detail']}" for item in items[:100])
        if len(items) > 100:
            lines.append(f"- 其余 {len(items) - 100} 项见 `data/quality/mock_quality.json`。")
        lines.append("")
    lines.extend(["## URL 检查", "", "- 仅将 HTTP 404/410 计为明确失效；401/403/429、JavaScript/WAF、登录页和网络超时单独列为访问提示。", ""])
    for item in result["url_failures"]:
        lines.append(f"- `{item['status']}` `{item['url']}`")
    if not result["url_failures"]:
        lines.append("- 未发现 HTTP 404/410 的明确失效 URL。")
    if result["url_probe_warnings"]:
        lines.append("")
        lines.append(f"- 访问提示 {len(result['url_probe_warnings'])} 条，未当作题库异常；详情见 `data/quality/mock_quality.json`。")
    lines.extend(["", "## 处理建议", "", "- 对答案/解析冲突、笔误、平台别名先人工复核；审计不替换题源答案。", "- 动态平台、登录页、验证码或反爬返回不等于 URL 失效；现场答题按指定平台和当前页面核对。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 150 道模拟题的答案/解析、文本、选项、年份、平台名称和 URL。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--urls", default=str(DEFAULT_URLS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json", dest="json_path", default=str(DEFAULT_JSON))
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    rows = conn.execute("SELECT * FROM questions WHERE source_type=? ORDER BY id", ("用户提供模拟题整理",)).fetchall()
    findings = conflict_items(rows) + typo_items(rows) + option_items(rows) + year_items(rows) + platform_alias_items(rows)
    by_category: dict[str, list[dict]] = {}
    for item in findings:
        by_category.setdefault(item["category"], []).append(item)

    urls = json.loads(Path(args.urls).resolve().read_text(encoding="utf-8")) if Path(args.urls).exists() else {"urls": []}
    url_records = urls.get("urls", [])
    url_unresolved = [
        {"category": "URL token不完整", "id": "URL", "detail": f"保留的原始 token 不是完整域名：{record['url']}；来源：{'、'.join(record.get('source_files', [])) or '目录'}。"}
        for record in url_records if record.get("url_validity") != "VALID"
    ]
    findings.extend(url_unresolved)
    for item in url_unresolved:
        by_category.setdefault(item["category"], []).append(item)
    probes: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(probe_url, record["url"], args.timeout) for record in url_records if record.get("url", "").startswith(("http://", "https://")) and record.get("url_validity", "VALID") == "VALID"]
        for future in as_completed(futures):
            probes.append(future.result())
    probes.sort(key=lambda item: item["url"])
    url_failures = [item for item in probes if item.get("status") in {404, 410}]
    probe_warnings = [item for item in probes if item.get("status") is None or item.get("status") in {401, 403, 429, 500, 502, 503, 504}]
    # URL probes are useful evidence but are not folded into question findings;
    # otherwise a transient WAF/network response would inflate the data issue count.
    priority = {
        "答案/解析潜在冲突": 4,
        "解析/题干疑似笔误": 3,
        "题干异常字符": 3,
        "选项文本重复": 4,
        "年份异常": 2,
        "平台名称别名": 1,
        "URL token不完整": 2,
    }
    top_findings = sorted(findings, key=lambda item: (-priority.get(item["category"], 0), item["id"], item["category"]))[:3]
    result = {
        "generated_at": now_iso(),
        "status": "PASS" if not findings and not url_failures else "REVIEW",
        "question_count": len(rows),
        "issue_count": len(findings) + len(url_failures),
        "finding_counts": dict(Counter(item["category"] for item in findings)),
        "findings_by_category": by_category,
        "top_findings": top_findings,
        "url_failures_count": len(url_failures),
        "url_unresolved_count": len(url_unresolved),
        "url_probe_warnings_count": len(probe_warnings),
        "url_failures": url_failures,
        "url_probe_warnings": probe_warnings,
        "url_probes": probes,
        "db": str(Path(args.db).resolve()),
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    json_path = Path(args.json_path).resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "question_count": result["question_count"], "issue_count": result["issue_count"], "finding_counts": result["finding_counts"], "url_failures": result["url_failures_count"], "probe_warnings": result["url_probe_warnings_count"], "top_findings": result["top_findings"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

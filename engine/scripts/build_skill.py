from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, NORMALIZED_DIR, RAW_DIR, json_text, log_activity, now_iso, text
from db_schema import connect_db, ensure_schema
from ingest_materials import clean_bullets, html_to_text, section, urls_from_text


def load_json_list(value: Any) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return [text(item) for item in result if text(item)]
    except (TypeError, json.JSONDecodeError):
        return []


def compact(value: str, limit: int = 900) -> str:
    value = re.sub(r"\s+", " ", text(value))
    return value if len(value) <= limit else value[:limit].rstrip() + "……"


def render_question(row) -> str:
    options = [
        f"{letter}. {text(row[f'option_{letter.lower()}'])}"
        for letter in "ABCD"
        if text(row[f"option_{letter.lower()}"])
    ]
    parts = [
        f"- {row['id']}（{row['question_type']}）{row['question_text']}",
        "  - 选项：" + "；".join(options),
        (
            f"  - 2026 模拟题题源答案（MOCK_KEY，未独立核验）：{text(row['mock_key'])}"
            if text(row["source_type"]) == "用户提供模拟题整理"
            else (
                f"  - Seed 标准答案：{text(row['standard_answer'])}"
                if text(row["standard_answer"])
                else f"  - 当前答案：{text(row['provisional_answer']) or '未回填'}"
            )
        ),
        f"  - 答案依据：{compact(row['answer_explanation'], 650)}",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="根据公开模块快照和 Seed 题库生成 50 模块 Skill。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--public-json", default=str(RAW_DIR / "public_knowledge_list_csc2025.json"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "skill" / "module_01_50.md"))
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    public_entries: dict[int, dict[str, Any]] = {}
    public_path = Path(args.public_json).resolve()
    if public_path.exists():
        payload = json.loads(public_path.read_text(encoding="utf-8"))
        for entry in payload.get("data", payload if isinstance(payload, list) else []):
            match = re.search(r"知识模块\s*0?(\d{1,2})", text(entry.get("title")))
            if match:
                public_entries[int(match.group(1))] = entry

    modules = conn.execute("SELECT * FROM modules ORDER BY module_no").fetchall()
    profiles: list[dict[str, Any]] = []
    markdown: list[str] = [
        "# 2026 AI+信息素养 50 模块 Skill",
        "",
        "本文件由本地公开模块快照、公开指南和题库生成。公开来源题目的标准答案只对来源中明确给出的答案负责；用户提供模拟题的答案仅作练习参考，不作为官方标准答案。正式考试题、登录后题目和未公开题库不在本文件中。",
        "",
        "## 使用方式",
        "",
        "先查本地题库，再按模块的官方入口和检索路径核验。涉及登录、验证码、校园认证、App 限制或动态统计时，停止自动提交并转人工操作。模块内容可能随官网和平台升级变化，动态性字段是操作提示，不是对未来页面的保证。",
        "",
    ]

    for module in modules:
        number = int(module["module_no"])
        entry = public_entries.get(number, {})
        plain = html_to_text(entry.get("content"))
        official_requirements = load_json_list(module["core_points"])
        guidance = load_json_list(module["retrieval_path"])
        key_fields = load_json_list(module["key_fields"])
        traps = load_json_list(module["common_traps"])
        if not official_requirements:
            official_requirements = clean_bullets(section(plain, "具体要求", ("学习指导", "参考资源", "样题")))
        if not guidance:
            guidance = clean_bullets(section(plain, "学习指导及备赛建议", ("参考资源", "样题")))
        refs_text = section(plain, "参考资源", ("样题", "正确答案"))
        references = urls_from_text(refs_text)
        qrows = conn.execute(
            "SELECT * FROM questions WHERE module_id=? ORDER BY id",
            (module["module_id"],),
        ).fetchall()
        qtypes = sorted({text(row["question_type"]) for row in qrows if text(row["question_type"])})
        q_dynamicity = {text(row["question_stability"]) for row in qrows}
        dynamicity = "DYNAMIC" if "DYNAMIC" in q_dynamicity else ("SEMI_DYNAMIC" if "SEMI_DYNAMIC" in q_dynamicity else "STATIC")
        question_urls = []
        for row in qrows:
            question_urls.extend(urls_from_text(text(row["answer_explanation"])))
            question_urls.extend(urls_from_text(text(row["official_url"])))
        urls = list(dict.fromkeys(references + question_urls))
        if not traps:
            traps = ["页面、菜单、功能和统计口径可能更新，作答时以题目指定平台当前显示和官方说明为准。"]

        profile = {
            "module_id": module["module_id"],
            "module_no": number,
            "module_name": module["module_name"],
            "category": module["category"],
            "official_url": module["official_url"],
            "requires_login": module["requires_login"],
            "core_points": official_requirements,
            "common_question_types": qtypes,
            "retrieval_path": guidance,
            "key_fields": key_fields,
            "common_traps": traps,
            "dynamicity": dynamicity,
            "browser_automation": module["browser_automation"],
            "manual_method": module["manual_method"],
            "references": urls,
            "sample_question_ids": [row["id"] for row in qrows],
        }
        profiles.append(profile)
        markdown.extend([
            f"## 知识模块 {number:02d}：{module['module_name']}",
            "",
            f"- 大类：{module['category']}",
            f"- 主要平台/官方链接：{module['official_url']}",
            f"- 相关参考链接：{'; '.join(urls[:12]) if urls else '以题目指定官方平台为准，当前快照未提取到额外 URL。'}",
            f"- 是否需要登录：{module['requires_login']}",
            f"- 动态性：{dynamicity}",
            f"- 常见题型：{', '.join(qtypes) if qtypes else '待补充'}",
            "",
            "### 核心考点",
            "",
        ])
        markdown.extend([f"- {item}" for item in official_requirements] or ["- 当前公开快照未提取到具体要求，需打开模块详情人工核对。"])
        markdown.extend(["", "### 检索路径", ""])
        markdown.extend([f"{index}. {item}" for index, item in enumerate(guidance, 1)] or ["1. 锁定题目指定平台，进入对应栏目或高级检索入口。", "2. 设置题目给出的字段、筛选项和时间范围，逐项核验结果。"])
        markdown.extend(["", "### 关键字段", "", ", ".join(key_fields) if key_fields else "按题目给出的题名、作者、单位、年份、来源、检索点或页面栏目核对。", "", "### 常见陷阱", ""])
        markdown.extend([f"- {item}" for item in traps])
        markdown.extend(["", "### 浏览器自动化与人工操作", "", f"- 浏览器自动化：{module['browser_automation'] or '公开页面可辅助；受限步骤转人工。'}", f"- 人工操作：{module['manual_method'] or '按官方链接进入，完成页面操作后截图或记录关键字段。'}", "", "### Seed 样题与答案", ""])
        markdown.extend([render_question(row) for row in qrows] or ["- 当前 Seed 没有本模块题目；模块知识点仍来自公开模块详情。"])
        markdown.extend(["", "---", ""])

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(markdown).rstrip() + "\n", encoding="utf-8")
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    (NORMALIZED_DIR / "module_profiles.jsonl").write_text(
        "".join(json_text(item) + "\n" for item in profiles),
        encoding="utf-8",
    )
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("skill_generated_at", "generated", now_iso()),
    )
    conn.commit()
    log_activity("skill_generated", {"modules": len(profiles), "output": str(output)})
    print(json.dumps({
        "status": "skill_generated",
        "modules": len(profiles),
        "output": str(output),
        "profiles": str(NORMALIZED_DIR / "module_profiles.jsonl"),
    }, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

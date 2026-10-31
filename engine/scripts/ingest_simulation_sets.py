from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DB_PATH,
    EXPORT_DIR,
    NORMALIZED_DIR,
    RAW_DIR,
    category_for_module,
    extract_urls,
    infer_stability,
    json_text,
    log_activity,
    normalize_question,
    now_iso,
    question_hash,
    text,
)
from db_schema import connect_db, ensure_schema  # noqa: E402


INPUT_DIR = RAW_DIR / "simulation_sets"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "evidence" / "simulation_manifest.json"
SOURCE_TYPE = "用户提供模拟题整理"
YEAR = "2026"
TRACK = "本科/研究生"
# The three simulation sets are the P0 answer key for original-question
# matching. Their keys are stored in questions.mock_key -- a distinct tier from
# standard_answer (independently verified) and provisional_answer (project-derived).
P0_PRIORITY = 0

HEADER_RE = re.compile(r"^\s*(\d{1,3})\s*[.、)]\s*(单选题|多选题|判断题)\s*$")
ANSWER_RE = re.compile(r"正确答案\s*[：:]\s*([A-D]+)")
YOUR_ANSWER_RE = re.compile(r"你的答案\s*[：:]\s*([A-D]+|未作答)")


@dataclass
class ParsedQuestion:
    source_set: int
    source_id: str
    source_file: str
    source_question_no: int
    question_type: str
    question_text: str
    options: dict[str, str]
    source_answer: str
    your_answer: str
    answer_explanation: str
    raw_block: str


@dataclass
class ImportedQuestion:
    source_set: int
    source_question_no: int
    question_id: str
    match_level: str
    question_type: str
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    source_answer: str
    your_answer: str
    answer_explanation: str
    question_stability: str
    module_id: str
    module_name: str
    source_file: str
    raw_record_id: str


# These rules are intentionally conservative. A blank module is preferable to
# assigning a plausible-looking but unsupported classification.
MODULE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("知识模块16", ("中国证券业协会", "证券公司", "律师诚信", "律师事务所", "国际组织实习")),
    ("知识模块49", ("iconfont", "图标库")),
    ("知识模块15", ("研招网", "院校库", "研究生招生", "毕业生到国际组织")),
    ("知识模块05", ("cnki ai", "知乎直答", "知答")),
    ("知识模块04", ("ima.qq", "个人知识库", "知识库文件排序")),
    ("知识模块28", ("奎章阁", "古典文献资源导航", "古籍目录")),
    ("知识模块48", ("mid(a1", "excel", "函数", "数据表")),
    ("知识模块18", ("一席", "高校图书馆网站", "生成式人工智能专题")),
    ("知识模块47", ("rss", "订阅地址", "期刊订阅")),
    ("知识模块44", ("gb/t 7714", "文献类型标识", "参考文献格式")),
    ("知识模块41", ("云展网", "图片格式转换")),
    ("知识模块27", ("学术图片", "相关图片", "图片类型")),
    ("知识模块11", ("中外标准数据库", "标准数据", "起草单位")),
    ("知识模块26", ("acm", "digital library", "文献检索系统")),
    ("知识模块02", ("ai大学堂", "科大讯飞", "hippter")),
    ("知识模块06", ("音乐生成", "图像生成", "视频生成")),
    ("知识模块08", ("共产党员网", "先进典型", "张桂梅")),
    ("知识模块13", ("反诈app", "反诈", "防骗")),
    ("知识模块43", ("aigc使用边界", "学术出版中aigc", "中信所")),
    ("知识模块45", ("word文档", "快速分页", "ctrl", "shift")),
    ("知识模块30", ("索书号", "图书馆", "馆藏")),
    ("知识模块01", ("联合国教科文组织", "unesco", "底纹")),
    ("知识模块21", ("国家哲学社会科学文献中心", "cssci来源集刊")),
    ("知识模块09", ("庭审公开网", "案件视频", "庭审")),
    ("知识模块06", ("清影", "ai生视频", "首尾帧", "ai画图", "图像生成", "视频生成")),
    ("知识模块05", ("leapspace", "ai选题分析", "ai对比阅读", "文献研读", "deepresearch", "深度研究", "ai问答")),
    ("知识模块07", ("github", "开源", "开放数据资源")),
    ("知识模块04", ("通义千问", "讯飞星火", "办公场景", "会议记录", "录音纪要")),
    ("知识模块03", ("纳米ai", "通用ai", "ai工具")),
    ("知识模块01", ("生成式人工智能教育与研究应用指南", "可信验证", "观点网络")),
    ("知识模块02", ("人工智能学习路线", "ai学习资源")),
    ("知识模块50", ("citespace", "vosviewer", "文献可视化")),
    ("知识模块49", ("echarts", "可视化图表", "数据可视化")),
    ("知识模块48", ("excel", "函数公式", "微词云", "数据处理")),
    ("知识模块47", ("文献追踪", "期刊订阅", "新增期刊订阅", "订阅功能")),
    ("知识模块46", ("文献管理", "zotero", "endnote", "mendeley")),
    ("知识模块45", ("论文排版", "word的替换", "word替换", "排版")),
    ("知识模块44", ("mla", "apa", "参考文献", "引文格式", "引用格式")),
    ("知识模块43", ("学术不端", "同一老师指导")),
    ("知识模块42", ("影响因子", "h指数", "智能荐刊", "选题分析")),
    ("知识模块41", ("pdf", "云展网pdf")),
    ("知识模块40", ("qq软件截图", "qq截图", "截图", "录屏")),
    ("知识模块39", ("雨课堂插件", "office插件", "浏览器插件")),
    ("知识模块38", ("问卷星", "思维导图", "笔记软件")),
    ("知识模块37", ("百度高级搜索", "搜索引擎", "文件格式")),
    ("知识模块33", ("截词", "通配符", "^#", "^g")),
    ("知识模块34", ("精确匹配", "模糊匹配", "双引号")),
    ("知识模块36", ("检索字段", "作者字段", "主题字段", "题名字段", "字段选择")),
    ("知识模块35", ("筛选条件", "过滤器", "应用筛选", "结果数量")),
    ("知识模块32", ("布尔逻辑", "布尔检索", "不含", " and ", " or ", " not ", " and/", " or/")),
    ("知识模块31", ("高级检索", "高级搜索", "检索表达式")),
    ("知识模块30", ("馆藏", "收藏分馆", "分馆", "书目查询")),
    ("知识模块29", ("微信指数", "百度指数", "人群画像", "指数")),
    ("知识模块27", ("图片搜索", "查版权", "图片链接")),
    ("知识模块26", ("百度学术", "pubmed", "学术搜索")),
    ("知识模块25", ("自然科学基金", "科研项目", "基金项目")),
    ("知识模块24", ("pubscholar", "oalib", "arxiv", "预印本", "全文获取渠道")),
    ("知识模块23", ("学位论文", "学位年度")),
    ("知识模块22", ("学术会议", "会议网", "会议文献", "会议年份")),
    ("知识模块21", ("期刊论文", "sciencedirect", "wiley数据库", "pubmed")),
    ("知识模块20", ("国家图书馆", "古籍特藏", "民族文字", "西夏文献")),
    ("知识模块19", ("电子书", "免费电子书")),
    ("知识模块18", ("智慧树", "阿里云开发者社区", "开放平台")),
    ("知识模块17", ("在线开放课程", "慕课", "mooc", "公开课程")),
    ("知识模块16", ("证书", "资格查询")),
    ("知识模块15", ("高等教育智慧教育平台", "研究生教育", "教学部门")),
    ("知识模块14", ("国家卫健委", "托育", "药品监督管理局", "国药准字")),
    ("知识模块13", ("辟谣", "谣言", "防骗")),
    ("知识模块12", ("专利", "商标", "地理标志", "知识产权局")),
    ("知识模块11", ("国家标准", "标准全文", "标准检索", "issn")),
    ("知识模块10", ("法律知识资源", "法律智库", "司法解释")),
    ("知识模块09", ("国家统计局", "开放数据", "ai知数", "统计数据")),
    ("知识模块08", ("课程思政", "思政信息")),
)


def canonical_answer(value: Any) -> str:
    raw = text(value).upper().replace("、", "").replace(",", "").replace("，", "")
    raw = "".join(ch for ch in raw if not ch.isspace() and ch not in "[]()")
    if raw and all(ch in "ABCD" for ch in raw):
        return "".join(sorted(set(raw)))
    return raw


def clean_text(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(line.strip() for line in lines if line.strip())).strip()


def label_of(line: str) -> str:
    value = line.lstrip()
    return value[0].upper() if value and value[0].upper() in "ABCD" else ""


def option_value(line: str) -> str:
    value = line.lstrip()[1:]
    if value[:1] in ".、)":
        value = value[1:]
    return value.strip()


def option_positions(lines: list[str], expected: str) -> list[int]:
    candidates: list[list[int]] = []
    for start, line in enumerate(lines):
        if label_of(line) != expected[0]:
            continue
        positions = [start]
        cursor = start + 1
        valid = True
        for letter in expected[1:]:
            while cursor < len(lines) and label_of(lines[cursor]) != letter:
                cursor += 1
            if cursor >= len(lines):
                valid = False
                break
            positions.append(cursor)
            cursor += 1
        if valid:
            # A question can itself begin with the letter A. Prefer a
            # candidate with visible question text before the option list.
            if any(lines[:start]):
                candidates.append(positions)
    if not candidates:
        return []
    return min(candidates, key=lambda positions: (positions[0], positions[-1] - positions[0]))


def parse_options(lines: list[str], question_type: str) -> tuple[str, dict[str, str]]:
    expected = "AB" if question_type == "判断题" else "ABCD"
    positions = option_positions(lines, expected)
    if question_type == "" and positions:
        question_type = "单选题" if expected == "ABCD" else "判断题"
    elif not positions and question_type == "":
        positions = option_positions(lines, "ABCD")
        if positions:
            question_type = "单选题"
        else:
            positions = option_positions(lines, "AB")
            question_type = "判断题" if positions else question_type
    if not positions:
        raise ValueError("未找到完整的选项序列")
    options: dict[str, str] = {}
    for index, position in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(lines)
        segment = [lines[position]] + lines[position + 1 : end]
        options[expected[index]] = clean_text([option_value(segment[0]), *segment[1:]])
    question_text = clean_text(lines[: positions[0]])
    return question_type, options


def split_blocks(lines: list[str]) -> list[tuple[re.Match[str] | None, list[str]]]:
    headers: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = HEADER_RE.match(line)
        if match:
            headers.append((index, match))
    if not headers:
        raise ValueError("未找到题型题号标题")
    blocks: list[tuple[re.Match[str] | None, list[str]]] = []
    first_index = headers[0][0]
    if first_index > 0 and any(line.strip() for line in lines[:first_index]):
        blocks.append((None, lines[:first_index]))
    for offset, (start, match) in enumerate(headers):
        end = headers[offset + 1][0] if offset + 1 < len(headers) else len(lines)
        blocks.append((match, lines[start + 1 : end]))
    return blocks


def parse_file(path: Path, source_set: int) -> list[ParsedQuestion]:
    lines = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    records: list[ParsedQuestion] = []
    for block_index, (header, body) in enumerate(split_blocks(lines), 1):
        question_no = int(header.group(1)) if header else 1
        question_type = header.group(2) if header else ""
        block_lines = ([header.group(0)] if header else []) + body
        answer_index = next((i for i, line in enumerate(body) if ANSWER_RE.search(line)), -1)
        if answer_index < 0:
            raise ValueError(f"第 {question_no} 题缺少正确答案")
        answer_match = ANSWER_RE.search(body[answer_index])
        assert answer_match is not None
        source_answer = canonical_answer(answer_match.group(1))
        your_match = YOUR_ANSWER_RE.search(body[answer_index])
        your_answer = your_match.group(1) if your_match else ""
        marker_index = next((i for i, line in enumerate(body[: answer_index + 1]) if line.strip() == "收起解析"), answer_index)
        question_type, options = parse_options(body[:marker_index], question_type)
        option_expected = "AB" if question_type == "判断题" else "ABCD"
        option_lines = option_positions(body[:marker_index], option_expected)
        if not option_lines:
            raise ValueError(f"第 {question_no} 题无法回读选项位置")
        question_text = clean_text(body[: option_lines[0]])
        explanation_marker = next((i for i in range(answer_index + 1, len(body)) if body[i].strip() == "解析"), -1)
        explanation = clean_text(body[explanation_marker + 1 :] if explanation_marker >= 0 else [])
        records.append(
            ParsedQuestion(
                source_set=source_set,
                source_id=f"SIM{source_set:02d}",
                source_file=str(path),
                source_question_no=question_no,
                question_type=question_type,
                question_text=question_text,
                options=options,
                source_answer=source_answer,
                your_answer=your_answer,
                answer_explanation=explanation,
                raw_block="\n".join(block_lines).strip(),
            )
        )
    if [record.source_question_no for record in records] != list(range(1, len(records) + 1)):
        raise ValueError(f"题号不连续：{path}")
    return records


def validate_records(records: list[ParsedQuestion]) -> None:
    errors: list[str] = []
    by_set: dict[int, list[ParsedQuestion]] = {}
    for record in records:
        by_set.setdefault(record.source_set, []).append(record)
        expected = set("AB" if record.question_type == "判断题" else "ABCD")
        actual = {key for key, value in record.options.items() if value}
        if actual != expected:
            errors.append(f"SIM{record.source_set:02d}-{record.source_question_no:02d} 选项不完整: {sorted(actual)}")
        if not record.source_answer or any(letter not in expected for letter in record.source_answer):
            errors.append(f"SIM{record.source_set:02d}-{record.source_question_no:02d} 答案异常: {record.source_answer}")
        if record.question_type == "多选题" and len(record.source_answer) < 2:
            errors.append(f"SIM{record.source_set:02d}-{record.source_question_no:02d} 多选答案不是多字母")
        if not record.question_text:
            errors.append(f"SIM{record.source_set:02d}-{record.source_question_no:02d} 缺少题干")
        if not record.answer_explanation:
            errors.append(f"SIM{record.source_set:02d}-{record.source_question_no:02d} 缺少解析")
    for source_set, rows in sorted(by_set.items()):
        type_counts = Counter(row.question_type for row in rows)
        if len(rows) != 50:
            errors.append(f"SIM{source_set:02d} 题数为 {len(rows)}，不是 50")
        expected_counts = Counter({"单选题": 20, "多选题": 20, "判断题": 10})
        if type_counts != expected_counts:
            errors.append(f"SIM{source_set:02d} 题型分布为 {dict(type_counts)}，不是 {dict(expected_counts)}")
    if len(records) != 150:
        errors.append(f"总题数为 {len(records)}，不是 150")
    if errors:
        raise ValueError("\n".join(errors))


def module_guess(record: ParsedQuestion) -> str:
    haystack = f"{record.question_text} {record.answer_explanation}".lower()
    for module_id, keywords in MODULE_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            return module_id
    return ""


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(path: Path) -> str:
    root = Path(__file__).resolve().parents[1]
    return str(path.resolve().relative_to(root)).replace("/", "\\")


def source_upsert(conn, path: Path, source_set: int) -> None:
    stamp = now_iso()
    source_id = f"SIM{source_set:02d}"
    conn.execute(
        """
        INSERT INTO sources(
            source_id, source_priority, source_type, title, url, source_date,
            access_status, access_notes, raw_path, sha256, url_hash,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_priority=excluded.source_priority,
            source_type=excluded.source_type,
            title=excluded.title,
            source_date=excluded.source_date,
            access_status=excluded.access_status,
            access_notes=excluded.access_notes,
            raw_path=excluded.raw_path,
            sha256=excluded.sha256,
            updated_at=excluded.updated_at
        """,
        (
            source_id,
            7,
            SOURCE_TYPE,
            f"2026 三套模拟题整理（第 {source_set} 套）",
            "",
            YEAR,
            "USER_PROVIDED",
            "用户提供的整理文本；答案和解析未由本次导入自动核验，不等同于官方公开标准答案。",
            relative_path(path),
            source_digest(path),
            "",
            stamp,
            stamp,
        ),
    )


def find_existing(conn, record: ParsedQuestion, preferred_id: str) -> tuple[Any | None, str]:
    by_id = conn.execute("SELECT * FROM questions WHERE id=?", (preferred_id,)).fetchone()
    if by_id:
        return by_id, "IDEMPOTENT_RELOAD"
    options = {letter: record.options.get(letter, "") for letter in "ABCD"}
    qhash = question_hash(record.question_text, options)
    exact = conn.execute("SELECT * FROM questions WHERE question_hash=? ORDER BY id LIMIT 1", (qhash,)).fetchone()
    if exact:
        return exact, "L0_EXACT"
    normalized = normalize_question(record.question_text)
    same_question = conn.execute(
        "SELECT * FROM questions WHERE normalized_question=? ORDER BY id LIMIT 1", (normalized,)
    ).fetchone()
    if same_question:
        return same_question, "L1_NORMALIZED_OPTIONS_DIFFER"
    return None, "NEW"


def fuzzy_note(conn, record: ParsedQuestion) -> str:
    normalized = normalize_question(record.question_text)
    candidates = conn.execute("SELECT id, normalized_question FROM questions").fetchall()
    best: tuple[float, str] | None = None
    for candidate in candidates:
        score = difflib.SequenceMatcher(None, normalized, candidate["normalized_question"]).ratio()
        if best is None or score > best[0]:
            best = (score, candidate["id"])
    if best and best[0] >= 0.88:
        return f"L2相似候选={best[1]}({best[0]:.3f})，未自动合并"
    return ""


def insert_question(conn, record: ParsedQuestion, question_id: str, module_names: dict[str, str], match_level: str) -> None:
    module_id = module_guess(record)
    module_name = module_names.get(module_id, "")
    category = category_for_module(int(module_id[-2:])) if module_id else ""
    urls = extract_urls(f"{record.question_text} {record.answer_explanation}")
    stamp = now_iso()
    note_parts = [
        "题源为用户提供的模拟题整理文本。",
        "文本中的答案写入 mock_key（P0 题源答案），verification_status=MOCK_KEY；"
        "standard_answer 留空，等待独立官方来源核验；provisional_answer 仅存本项目自行推导的答案。",
        f"模拟题套数={record.source_set}，原题号={record.source_question_no}，匹配层级={match_level}。",
    ]
    if urls:
        note_parts.append("解析中给出的检索入口尚未由本次导入自动访问：" + "; ".join(urls[:6]))
    fuzzy = fuzzy_note(conn, record) if match_level == "NEW" else ""
    if fuzzy:
        note_parts.append(fuzzy)
    options = {letter: record.options.get(letter, "") for letter in "ABCD"}
    payload = (
        question_id,
        YEAR,
        TRACK,
        SOURCE_TYPE,
        category,
        module_id or None,
        module_name,
        record.question_type,
        record.question_text,
        options["A"],
        options["B"],
        options["C"],
        options["D"],
        "",                            # standard_answer: independently verified only
        record.source_answer,          # mock_key: the 2026 simulation-set key
        "",                            # provisional_answer: project-derived only
        record.answer_explanation,
        "",
        urls[0] if urls else "",
        record.answer_explanation,
        record.question_text,
        "",
        "",
        infer_stability(record.question_text, record.answer_explanation),
        "",
        "",
        "HIGH",                        # 🟢: high certainty in the source key
        "MOCK_KEY",                    # ...but not independently re-verified
        P0_PRIORITY,
        "",
        " ".join(note_parts),
        normalize_question(record.question_text),
        question_hash(record.question_text, options),
        stamp,
        stamp,
    )
    conn.execute(
        """
        INSERT INTO questions(
            id, year, track, source_type, category, module_id, module_name,
            question_type, question_text, option_a, option_b, option_c, option_d,
            standard_answer, mock_key, provisional_answer, answer_explanation,
            official_platform, official_url, retrieval_path, retrieval_query,
            retrieval_fields, retrieval_filters, question_stability,
            current_observed_value, observed_at, confidence, verification_status,
            source_priority,
            verified_at, notes, normalized_question, question_hash, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        payload,
    )


def import_records(records: list[ParsedQuestion], db_path: Path, output_dir: Path) -> list[ImportedQuestion]:
    conn = connect_db(db_path)
    ensure_schema(conn)
    module_names = {
        row["module_id"]: row["module_name"]
        for row in conn.execute("SELECT module_id, module_name FROM modules")
    }
    for source_set in sorted({record.source_set for record in records}):
        path = next(record.source_file for record in records if record.source_set == source_set)
        source_upsert(conn, Path(path), source_set)

    imported: list[ImportedQuestion] = []
    for record in records:
        preferred_id = f"SIM26-{record.source_set:02d}-{record.source_question_no:03d}"
        existing, match_level = find_existing(conn, record, preferred_id)
        question_id = existing["id"] if existing else preferred_id
        if existing is None:
            insert_question(conn, record, question_id, module_names, match_level)
        elif match_level == "IDEMPOTENT_RELOAD":
            question_id = existing["id"]
            guessed_module = module_guess(record)
            if existing["source_type"] == SOURCE_TYPE and not text(existing["module_id"]) and guessed_module:
                conn.execute(
                    "UPDATE questions SET category=?, module_id=?, module_name=?, updated_at=? WHERE id=?",
                    (category_for_module(int(guessed_module[-2:])), guessed_module, module_names.get(guessed_module, ""), now_iso(), question_id),
                )

        raw_record_id = f"SIM{record.source_set:02d}-R{record.source_question_no:03d}"
        raw_payload = asdict(record)
        raw_payload["source_file"] = relative_path(Path(record.source_file))
        raw_payload["options"] = dict(record.options)
        raw_payload["raw_file_sha256"] = source_digest(Path(record.source_file))
        stamp = now_iso()
        conn.execute(
            """
            INSERT INTO raw_records(
                record_id, source_id, source_row_no, question_id, source_url,
                payload_json, created_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(record_id) DO UPDATE SET
                source_id=excluded.source_id,
                source_row_no=excluded.source_row_no,
                question_id=excluded.question_id,
                source_url=excluded.source_url,
                payload_json=excluded.payload_json
            """,
            (
                raw_record_id,
                record.source_id,
                record.source_question_no,
                question_id,
                "",
                json_text(raw_payload),
                stamp,
            ),
        )
        question = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if question is None:
            raise RuntimeError(f"题目写入后无法读取：{question_id}")
        existing_standard = text(question["standard_answer"])
        answer_conflict = bool(existing_standard and canonical_answer(existing_standard) != record.source_answer)
        relation_type = "source_record" if match_level in {"NEW", "IDEMPOTENT_RELOAD"} else (
            "duplicate_exact" if match_level == "L0_EXACT" else "normalized_match_different_options"
        )
        relation_notes = f"用户提供模拟题第 {record.source_set} 套第 {record.source_question_no} 题；匹配={match_level}。"
        if answer_conflict:
            relation_notes += f" 与既有 standard_answer={existing_standard} 冲突，未覆盖。"
        has_primary = conn.execute(
            "SELECT 1 FROM question_sources WHERE question_id=? AND is_primary=1 LIMIT 1", (question_id,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO question_sources(
                question_id, source_id, raw_record_id, relation_type, is_primary,
                source_url, source_answer, source_explanation, source_date, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(question_id, source_id, raw_record_id) DO UPDATE SET
                relation_type=excluded.relation_type,
                is_primary=excluded.is_primary,
                source_answer=excluded.source_answer,
                source_explanation=excluded.source_explanation,
                source_date=excluded.source_date,
                notes=excluded.notes
            """,
            (
                question_id,
                record.source_id,
                raw_record_id,
                relation_type,
                1 if not has_primary else 0,
                "",
                record.source_answer,
                record.answer_explanation,
                YEAR,
                relation_notes,
            ),
        )
        imported.append(
            ImportedQuestion(
                source_set=record.source_set,
                source_question_no=record.source_question_no,
                question_id=question_id,
                match_level=match_level,
                question_type=record.question_type,
                question_text=record.question_text,
                option_a=record.options.get("A", ""),
                option_b=record.options.get("B", ""),
                option_c=record.options.get("C", ""),
                option_d=record.options.get("D", ""),
                source_answer=record.source_answer,
                your_answer=record.your_answer,
                answer_explanation=record.answer_explanation,
                question_stability=infer_stability(record.question_text, record.answer_explanation),
                module_id=text(question["module_id"]),
                module_name=text(question["module_name"]),
                source_file=relative_path(Path(record.source_file)),
                raw_record_id=raw_record_id,
            )
        )
    conn.execute(
        """
        INSERT INTO meta(key,value,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        ("simulation_sets", json_text({"records": len(records), "source_type": SOURCE_TYPE}), now_iso()),
    )
    conn.commit()
    log_activity(
        "simulation_sets_ingested",
        {
            "records": len(records),
            "unique_question_ids": len({row.question_id for row in imported}),
            "db": str(db_path.resolve()),
        },
    )
    conn.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "simulation_question_bank.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(imported[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(row) for row in imported)
    jsonl_path = output_dir / "simulation_question_bank.jsonl"
    jsonl_path.write_text("".join(json_text(asdict(row)) + "\n" for row in imported), encoding="utf-8")
    normalized_path = NORMALIZED_DIR / "simulation_questions.jsonl"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text("".join(json_text(asdict(row)) + "\n" for row in imported), encoding="utf-8")
    raw_path = NORMALIZED_DIR / "simulation_raw_records.jsonl"
    raw_rows = []
    for record in records:
        raw_row = asdict(record)
        raw_row["source_file"] = relative_path(Path(record.source_file))
        raw_rows.append(raw_row)
    raw_path.write_text("".join(json_text(row) + "\n" for row in raw_rows), encoding="utf-8")
    manifest = {
        "generated_at": now_iso(),
        "source_type": SOURCE_TYPE,
        "records": len(records),
        "unique_question_ids": len({row.question_id for row in imported}),
        "files": [
            {
                "source_set": source_set,
                "source_id": f"SIM{source_set:02d}",
                "path": relative_path(Path(next(record.source_file for record in records if record.source_set == source_set))),
                "sha256": source_digest(Path(next(record.source_file for record in records if record.source_set == source_set))),
                "questions": sum(1 for record in records if record.source_set == source_set),
            }
            for source_set in sorted({record.source_set for record in records})
        ],
        "match_counts": dict(Counter(row.match_level for row in imported)),
        "question_type_counts": dict(Counter(row.question_type for row in records)),
        "module_counts": dict(Counter(row.module_id or "未分类" for row in imported)),
        "outputs": [str(csv_path.resolve()), str(jsonl_path.resolve()), str(normalized_path.resolve()), str(raw_path.resolve())],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return imported


def load_all(input_dir: Path) -> list[ParsedQuestion]:
    paths = sorted(input_dir.glob("2026_simulation_set_*.txt"))
    if len(paths) != 3:
        raise FileNotFoundError(f"预期 3 份模拟题原文，实际找到 {len(paths)} 份：{input_dir}")
    records: list[ParsedQuestion] = []
    for path in paths:
        match = re.search(r"set_(\d+)", path.stem)
        if not match:
            raise ValueError(f"无法从文件名解析套数：{path.name}")
        records.extend(parse_file(path, int(match.group(1))))
    validate_records(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="将三套 2026 模拟题整理文本导入本地题库。")
    parser.add_argument("--input-dir", default=str(INPUT_DIR))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output-dir", default=str(EXPORT_DIR))
    parser.add_argument("--dry-run", action="store_true", help="只解析和校验，不写入数据库或导出文件")
    args = parser.parse_args()

    records = load_all(Path(args.input_dir).resolve())
    summary = {
        "status": "parsed" if args.dry_run else "ready_to_import",
        "records": len(records),
        "sets": dict(Counter(record.source_set for record in records)),
        "question_types": dict(Counter(record.question_type for record in records)),
        "explanations_complete": sum(bool(record.answer_explanation) for record in records),
        "answers_complete": sum(bool(record.source_answer) for record in records),
        "input_dir": str(Path(args.input_dir).resolve()),
    }
    if args.dry_run:
        summary["module_guesses"] = dict(Counter(module_guess(record) or "未分类" for record in records))
        summary["sample"] = [
            {
                "set": record.source_set,
                "no": record.source_question_no,
                "type": record.question_type,
                "question": record.question_text[:80],
                "answer": record.source_answer,
                "options": record.options,
            }
            for record in records[:3]
        ]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    imported = import_records(records, Path(args.db).resolve(), Path(args.output_dir).resolve())
    summary.update(
        {
            "status": "imported",
            "unique_question_ids": len({row.question_id for row in imported}),
            "match_levels": dict(Counter(row.match_level for row in imported)),
            "manifest": str(MANIFEST_PATH.resolve()),
            "simulation_csv": str((Path(args.output_dir).resolve() / "simulation_question_bank.csv")),
        }
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

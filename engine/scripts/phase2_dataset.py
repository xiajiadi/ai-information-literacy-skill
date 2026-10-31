"""PHASE 2 · 构建离线路由测试集。

数据来源与标签可信度：

  handoff/question_bank.md（人写）—— 每道题都带**人写的**「查询网址」。
     由这些 URL 的 host 推导出的平台标签，独立于路由模型，可作为
     **平台 Gold Standard**。这是本阶段平台准确率的分母。

  db/question_bank.sqlite
     - 来源 `2026官网公开知识模块样题` 的 module_id 由官方公开模块页决定，
       独立于路由模型，可作为 **模块 Gold Standard**（56 题）。
     - 来源 `用户提供模拟题整理` 的模块归属是上一轮脚本启发式产生的，
       记为 **SILVER**，只做参考，**不进准确率分母**。

测试集：
  A 原题路由测试   —— 全部带 Gold 的原题
  B 变体泛化测试   —— 30+ 题，只改参数（年份/机构/人名/主题/字段/筛选/选项序），
                      操作方法应当继承，答案不得继承
  C 跨平台辨识测试 —— 同概念在不同平台的语法/字段/布尔差异
  D 缺失信息测试   —— 应返回 UNKNOWN / HUMAN_REQUIRED，而不是编造

产出：data/quality/phase2/dataset.json
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import DB_PATH, ROOT, load_platform_capabilities, now_iso, write_json  # noqa: E402

HANDOFF = ROOT / "handoff" / "question_bank.md"
OUT_DIR = ROOT / "data" / "quality" / "phase2"
OUT = OUT_DIR / "dataset.json"

PART_RE = re.compile(r"^##\s+第[一二三]部分[^\n]*")
SECTION_START = {
    "初赛": re.compile(r"^##\s+第一部分"),
    "模拟": re.compile(r"^##\s+第二部分"),
    "样题": re.compile(r"^##\s+第三部分"),
}
Q_HEAD_RE = re.compile(r"^###\s+(初赛|模拟|样题)-(\d+)\.\s*\[([^\]]*)\]\s*(.*)$")
OPTION_RE = re.compile(r"^-\s*\*\*([A-H])[.、)]\*\*\s*(.*)$")
ANSWER_RE = re.compile(r"^\*\*答案\*\*[：:]\s*(.*)$")
FIELD_RE = re.compile(r"^\*\*[①②③④⑤]\s*([^*]+)\*\*[：:]\s*(.*)$")
URL_RE = re.compile(r"https?://[^\s\)）\],，、；;＞>\"]+")


def parse_handoff(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_field: str = ""

    for raw in text.splitlines():
        line = raw.rstrip()

        head = Q_HEAD_RE.match(line)
        if head:
            if current:
                records.append(current)
            part, index, qtype, stem = head.groups()
            # 题型标记可能为空（实测 样题-4 / 样题-5 写作 `[]`）。
            # 旧正则要求方括号内至少 1 个字符，导致这两题被**静默丢弃**，
            # 使总题数从 290 变成 288。此处允许空标记并记为 UNKNOWN。
            normalized_type = qtype.replace("题", "").strip() or "UNKNOWN"
            current = {
                "id": f"{part}-{index}",
                "part": part,
                "index": int(index),
                "question_type": normalized_type,
                "question_type_tag_missing": not qtype.strip(),
                "stem": stem.strip(),
                "options": {},
                "declared_answer": "",
                "operation": "",
                "note": "",
                "source_urls": [],
            }
            active_field = ""
            continue

        if current is None:
            continue

        if PART_RE.match(line) and not head:
            # 进入新的大节（如第二部分标题）
            pass

        option = OPTION_RE.match(line)
        if option:
            current["options"][option.group(1)] = option.group(2).strip()
            active_field = "options"
            continue

        answer = ANSWER_RE.match(line)
        if answer:
            current["declared_answer"] = answer.group(1).strip()
            active_field = "answer"
            continue

        field = FIELD_RE.match(line)
        if field:
            label = field.group(1).strip()
            value = field.group(2).strip()
            if "操作流程" in label:
                current["operation"] = value
                active_field = "operation"
            elif "查询网址" in label or "网址" in label:
                active_field = "urls"
                current["source_urls"].extend(URL_RE.findall(value))
            elif "备注" in label:
                current["note"] = value
                active_field = "note"
            else:
                active_field = ""
            continue

        # 续行
        if active_field == "urls":
            current["source_urls"].extend(URL_RE.findall(line))
        elif active_field == "operation" and line.strip():
            current["operation"] += " " + line.strip()
        elif active_field == "note" and line.strip():
            current["note"] += " " + line.strip()

    if current:
        records.append(current)
    return records


def host_to_platform(url: str, host_index: dict[str, str]) -> tuple[str, str]:
    """把 URL 主机映射到 platform_key，并说明匹配置信度。

    返回 (platform_key, match_type)：
      EXACT   主机直接命中平台登记的官方 URL 主机 —— 高置信
      DOMAIN  靠可注册域归并命中 —— 中置信
              （同一注册域下的不同服务会被合并，如 court.gov.cn 上
               既有「执行信息公开网」也有「公报」，因此单列一档）
      ""      未命中
    """
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return "", ""
    if host in host_index:
        return host_index[host], "EXACT"
    domain = registrable_domain(host)
    if domain in host_index:
        return host_index[domain], "DOMAIN"
    return "", ""


# 常见多段后缀：registrable domain 需要多取一段
MULTI_LABEL_SUFFIXES = (
    "gov.cn", "com.cn", "net.cn", "org.cn", "edu.cn", "ac.cn",
    "co.uk", "co.jp", "com.hk", "org.hk", "edu.hk", "com.tw",
)


def registrable_domain(host: str) -> str:
    """取可注册域（site.cnipa.gov.cn -> cnipa.gov.cn）。

    用途：把 hostname 形式的伪平台（capabilities 里存在 `epub` = epub.cnipa.gov.cn
    这类条目）归并到真正的平台（cnipa）。
    """
    host = (host or "").lower().strip(".")
    if not host or re.fullmatch(r"[\d.]+", host):
        return host  # 纯 IP 原样返回
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    for suffix in MULTI_LABEL_SUFFIXES:
        if host.endswith("." + suffix):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def looks_like_hostname_key(key: str) -> bool:
    """平台 key 长得像主机名（含点，或等于自己的 canonical_home host）。"""
    return "." in key


# Controller 要求区分四类平台角色，不得把「辅助查询网站」当成「题目要求的平台」。
SEARCH_ENGINE_HOSTS = (
    "baidu.com", "sogou.com", "bing.com", "so.com", "google.com",
    "zhihu.com", "csdn.net", "cnblogs.com", "jianshu.com", "douban.com",
)
PUBLISHER_HOSTS = (
    "doi.org", "springer.com", "wiley.com", "sciencedirect.com",
    "nature.com", "cambridge.org", "oxford", "ieee.org", "acm.org",
    "tandfonline.com", "ncbi.nlm.nih.gov", "pdf",
)


def classify_url_role(url: str, index_position: int) -> str:
    """判断一个 URL 在解题中的**角色**。

    required_platform    题目要求的目标平台（通常是第一个、且是专业库/官方站）
    supporting_source    辅助定位用的搜索/聚合站（不得当作题目要求的平台）
    fallback_source      原始论文 / 出版社 / PDF 等兜底来源
    """
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return "unknown"
    if any(host == h or host.endswith("." + h) for h in SEARCH_ENGINE_HOSTS):
        return "supporting_source"
    if any(h in host for h in PUBLISHER_HOSTS) and index_position > 0:
        return "fallback_source"
    if host.endswith(".pdf") or url.lower().endswith(".pdf"):
        return "fallback_source"
    return "required_platform" if index_position == 0 else "acceptable_equivalent_platform"


def build_host_index() -> dict[str, str]:
    """host -> platform_key。

    **只**用平台官方 URL（canonical_home / entry.primary）建立映射，
    不用 host_aliases（实测会把 epub.cnipa.gov.cn 映到伪平台 `epub`）。
    同一个 host 有多个候选时，优先选**非主机名形态**的 key，其次选有
    功能页入口（entry.primary）的那个。
    """
    candidates: dict[str, list[tuple[int, str]]] = {}
    capabilities = load_platform_capabilities()["platforms"]
    for key, platform in capabilities.items():
        if not isinstance(platform, dict):
            continue
        # 排除自动生成的**主机名派生伪平台**。判据有三条：
        #   1) key 是纯数字（"202"）；
        #   2) key 含点（"aistudio.baidu.com"）；
        #   3) key 等于自己 canonical_home 主机的**第一个标签**
        #      —— 这是自动生成器最典型的痕迹：`epub` 的 home 是
        #      `epub.cnipa.gov.cn`，于是 URL 主机精确匹配会把它判成 `epub`，
        #      而不是真正的 `cnipa`（PHASE 2 修正中实测到该回归）。
        home_host = (urlsplit(str(platform.get("canonical_home") or "")).hostname or "").lower()
        first_label = home_host.split(".")[0] if home_host else ""
        if (
            re.fullmatch(r"[\d.]+", key)
            or looks_like_hostname_key(key)
            or (first_label and key.lower() == first_label)
        ):
            continue
        score = 4          # 能走到这里的 key 已是语义名
        if (platform.get("entry", {}) or {}).get("primary"):
            score += 2     # 有功能页入口更可信
        for url in (
            (platform.get("entry", {}) or {}).get("primary", ""),
            platform.get("canonical_home", ""),
        ):
            if not url:
                continue
            host = (urlsplit(url).hostname or "").lower()
            if not host:
                continue
            for probe in {host, registrable_domain(host)}:
                candidates.setdefault(probe, []).append((score, key))

    index: dict[str, str] = {}
    for host, options in candidates.items():
        options.sort(key=lambda item: (-item[0], item[1]))
        index[host] = options[0][1]
    return index


def build_db_questions() -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM questions ORDER BY id")]
    finally:
        conn.close()
    return rows


INSTITUTION_POOL = [
    "复旦大学", "浙江大学", "四川大学", "武汉大学", "中山大学",
    "南京大学", "西安交通大学", "哈尔滨工业大学", "同济大学", "厦门大学",
]
TOPIC_POOL = [
    "生成式人工智能", "碳中和", "数字经济", "生物医药", "智能制造",
    "乡村振兴", "区块链", "量子计算",
]
PERSON_POOL = ["王浩", "李明", "张伟", "刘洋", "陈静", "赵磊"]

YEAR_RE = re.compile(r"(20\d{2})")


def systematic_variants(originals: list[dict[str, Any]], start_index: int) -> list[dict[str, Any]]:
    """从真实题干里机械地改参数，保证「操作方法可继承、答案不可继承」。

    只做三类**不会改变操作方法**的替换：
      1. 年份平移（同一平台、同一检索式、同一字段，只换时间窗）
      2. 机构替换（题名/作者单位类参数）
      3. 主题词替换
    以及多选题的选项顺序重排。
    """
    out: list[dict[str, Any]] = []
    counter = start_index

    def push(base: dict[str, Any], mutation: str, stem: str, **expected: Any) -> None:
        nonlocal counter
        counter += 1
        out.append({
            "id": f"V{counter:02d}",
            "base_id": base["id"],
            "mutation": mutation,
            "stem": stem,
            "options": base.get("options", {}),
            "inherits": expected,
            "must_not_inherit": ["原题答案", "原题具体数值", "原题选项字母"],
            "note": "只继承操作方法（平台/字段/筛选/检索式骨架）；答案必须重新取证。",
        })

    for record in originals:
        stem = record.get("stem") or ""
        if len(stem) < 24:
            continue
        platform = record.get("gold_platform") or ""
        task_hint = record.get("task_hint") or ""

        # 1) 年份平移
        years = YEAR_RE.findall(stem)
        if years:
            old_year = years[0]
            new_year = str(int(old_year) + 1)
            push(record, "年份平移", stem.replace(old_year, new_year, 1),
                 platform=platform, reason=f"{old_year} -> {new_year}，其余条件不变")

        # 2) 机构替换
        hit_inst = next((inst for inst in INSTITUTION_POOL if inst in stem), "")
        if hit_inst:
            replacement = next(i for i in INSTITUTION_POOL if i != hit_inst)
            push(record, "机构替换", stem.replace(hit_inst, replacement, 1),
                 platform=platform, reason=f"{hit_inst} -> {replacement}，字段路径不变")

        # 3) 主题词替换
        hit_topic = next((t for t in TOPIC_POOL if t in stem), "")
        if hit_topic:
            replacement = next(t for t in TOPIC_POOL if t != hit_topic)
            push(record, "主题词替换", stem.replace(hit_topic, replacement, 1),
                 platform=platform, reason=f"{hit_topic} -> {replacement}")

        # 4) 多选：选项顺序重排（答案须按内容集合重算）
        if record.get("question_type") == "多选" and len(record.get("options", {})) >= 3:
            letters = sorted(record["options"].keys())
            rotated = letters[1:] + letters[:1]
            remapped = {new: record["options"][old] for new, old in zip(letters, rotated)}
            counter += 1
            out.append({
                "id": f"V{counter:02d}",
                "base_id": record["id"],
                "mutation": "选项顺序重排",
                "stem": stem + "（选项顺序已重排）",
                "options": remapped,
                "inherits": {"platform": platform},
                "must_not_inherit": ["原题答案字母"],
                "note": "多选答案必须按选项**内容集合**核对，不能照抄原题字母。",
            })

        if len(out) >= 60:
            break
    return out


def make_variants(originals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """变体：只改**参数**，不改**操作方法**。

    每个变体显式声明 `inherits`（应当继承的：任务类型/平台/字段），
    以及 `must_not_inherit`（不得继承的：原题答案）。
    """
    variants: list[dict[str, Any]] = []
    counter = 0

    def add(base: dict[str, Any], mutation: str, new_stem: str, **expected: Any) -> None:
        nonlocal counter
        counter += 1
        variants.append({
            "id": f"V{counter:02d}",
            "base_id": base["id"],
            "mutation": mutation,
            "stem": new_stem,
            "options": base.get("options", {}),
            "inherits": expected,
            "must_not_inherit": ["原题答案", "原题具体数值", "原题选项字母"],
            "note": "变体只继承操作方法；答案必须重新取证。",
        })

    # 1) 年份平移：同一平台同一检索式，换时间窗
    year_cases = [
        ("在CNKI高级检索界面，精确检索作者为黄智，主题为“染色体”的论文，2014-2024年间共有（ ）篇期刊论文。",
         "在CNKI高级检索界面，精确检索作者为黄智，主题为“染色体”的论文，2018-2026年间共有（ ）篇期刊论文。",
         "GET_VALUE", "cnki", "时间窗由 2014-2024 改为 2018-2026"),
        ("在维普网检索标题名称包含“家用电器”的标准，状态为作废的标准数高于4000条。",
         "在维普网检索标题名称包含“照明设备”的标准，状态为作废的标准数高于4000条。",
         "COMPARE", "vip", "主题由 家用电器 改为 照明设备"),
        ("在CNKI数据库中，学位论文“CEEMDAN和改进的Transformer模型在碳交易价格预测中的应用”的学科专业是（ ）。",
         "在CNKI数据库中，学位论文“基于深度学习的短期电力负荷预测方法研究”的学科专业是（ ）。",
         "GET_FIELD", "cnki", "篇名替换，字段与路径不变"),
        ("在WILEY数据库，查找题名中含有AIGC，且文中包含DEEP SEEK的期刊论文，以下是命中论文作者的有（ ）？",
         "在WILEY数据库，查找题名中含有AIGC，且文中包含LARGE LANGUAGE MODEL的期刊论文，以下是命中论文作者的有（ ）？",
         "GET_LIST", "wiley", "正文关键词替换"),
        ("根据AI知数分析数据，2024年长三角城市群（27个核心城市）GDP之和约为多少？",
         "根据AI知数分析数据，2024年珠三角城市群（9个核心城市）GDP之和约为多少？",
         "CALCULATION", "aizhishu", "城市群与年份口径替换；需重新求和"),
        ("在“国家社科基金项目数据库”中，关于项目名称为“主要发达国家大数据和人工智能治理的国际比较研究”的表述，正确的有？",
         "在“国家社科基金项目数据库”中，关于项目名称为“数字经济驱动乡村振兴的机制与路径研究”的表述，正确的有？",
         "EXISTS", "nopss", "项目名替换"),
        ("在国家科技图书文献中心（NSTL）门户网站“知识发现”-科技词表，检索“石墨烯（或graphene）”，这个术语名词隶属哪些学科范畴？",
         "在国家科技图书文献中心（NSTL）门户网站“知识发现”-科技词表，检索“钙钛矿（或perovskite）”，这个术语名词隶属哪些学科范畴？",
         "GET_LIST", "nstl", "术语替换"),
        ("在CNKI（中国知网）学术期刊数据库中使用高级检索功能，检索主题为“人工智能”与“医疗”的文献，截止2026年，发文量最多的中国作者是王浩。",
         "在CNKI（中国知网）学术期刊数据库中使用高级检索功能，检索主题为“区块链”与“供应链”的文献，截止2026年，发文量最多的中国作者是李明。",
         "COMPARE", "cnki", "主题与人名同时替换"),
        ("在全国律师执业诚信信息公示平台查询可知，辽宁泰海律师事务所负责人的律师职业证号后两位数为（ ）？",
         "在全国律师执业诚信信息公示平台查询可知，北京中伦律师事务所负责人的律师职业证号后两位数为（ ）？",
         "GET_FIELD", "acla", "机构替换；字段路径不变"),
        ("在Github平台（https://github.com）查找题名为“microsoft/TypeScript”（严格匹配）的项目，该项目目前共有（ ）个Releases。",
         "在Github平台（https://github.com）查找题名为“facebook/react”（严格匹配）的项目，该项目目前共有（ ）个Releases。",
         "GET_VALUE", "github", "仓库名替换"),
        ("在高校图书馆OPAC中查询《信息检索与利用》的索书号。",
         "在高校图书馆OPAC中查询《数据科学导论》的索书号。",
         "GET_FIELD", "opac", "书名替换"),
        ("在PubMed中检索主题词“CRISPR”，限定近5年，共有多少篇综述？",
         "在PubMed中检索主题词“mRNA vaccine”，限定近5年，共有多少篇综述？",
         "GET_VALUE", "pubmed", "主题词替换"),
    ]
    original_by_stem = {o["stem"]: o for o in originals}
    for old_stem, new_stem, task, platform, why in year_cases:
        base = original_by_stem.get(old_stem) or {"id": f"合成-{task}", "options": {}, "stem": old_stem}
        add(base, "参数替换", new_stem,
            task_type=task, platform=platform, reason=why)

    # 2) 选项顺序重排（多选）：答案组合的内容不变，字母必须重算
    multi = next((o for o in originals if o["question_type"] == "多选" and len(o.get("options", {})) >= 4), None)
    if multi:
        letters = sorted(multi["options"].keys())
        rotated = letters[1:] + letters[:1]
        remapped = {new: multi["options"][old] for new, old in zip(letters, rotated)}
        variants.append({
            "id": f"V{counter + 1:02d}",
            "base_id": multi["id"],
            "mutation": "选项顺序重排",
            "stem": multi["stem"] + "（选项顺序已重排）",
            "options": remapped,
            "inherits": {"task_type": "EXISTS", "platform": "同原题"},
            "must_not_inherit": ["原题答案字母"],
            "note": "多选答案必须按**选项内容集合**核对，不能照抄原题字母顺序。",
        })
        counter += 1

    return variants


def build_cross_platform_cases() -> list[dict[str, Any]]:
    """C 跨平台辨识：同一概念在不同平台的语法/字段/布尔差异。"""
    return [
        {
            "id": "C01", "concept": "布尔逻辑",
            "probes": [
                {"platform": "cnki", "question": "CNKI 高级检索中，同时含 A 与 B 应使用哪个运算符？"},
                {"platform": "wanfang", "question": "万方高级检索中，同时含 A 与 B 应使用哪个运算符？"},
                {"platform": "pubmed", "question": "PubMed 中同时含 A 与 B 应使用哪个运算符？"},
            ],
            "expected": "各平台运算符语义不同，必须查该平台自己的帮助页；不得把 CNKI 的语法套到万方。",
            "p0_risk": "混用不同数据库检索语法",
        },
        {
            "id": "C02", "concept": "精确 vs 模糊",
            "probes": [
                {"platform": "cnki", "question": "CNKI 中如何做篇名精确检索？"},
                {"platform": "wanfang", "question": "万方中如何做篇名精确检索？"},
                {"platform": "vip", "question": "维普中如何做篇名精确检索？"},
            ],
            "expected": "三家默认匹配规则不同（万方高级检索默认「模糊」），操作路径也不同。",
            "p0_risk": "把一家的默认匹配当成三家的默认匹配",
        },
        {
            "id": "C03", "concept": "结果页字段 vs 详情页字段",
            "probes": [
                {"platform": "cnki", "question": "学位论文的「学科专业」在结果页还是详情页？"},
                {"platform": "cnki", "question": "期刊论文的「文献类型标识」在结果页还是详情页？"},
            ],
            "expected": "结果页分面不等于详情页字段；必须进详情页。",
            "p0_risk": "把结果页分面当成目标字段值",
        },
        {
            "id": "C04", "concept": "字段可用性",
            "probes": [
                {"platform": "vip", "question": "维普高级检索是否提供「导师」字段？"},
                {"platform": "cnki", "question": "CNKI 高级检索是否提供「导师」字段？"},
            ],
            "expected": "字段在界面上不存在时应直接换路径，不得硬凑或编造。",
            "p1_risk": "忽略题目指定字段 / 编造字段",
        },
        {
            "id": "C05", "concept": "日期范围",
            "probes": [
                {"platform": "stats", "question": "国家统计局年度数据如何限定年份？"},
                {"platform": "cnki", "question": "CNKI 如何限定发表年度区间？"},
            ],
            "expected": "时间维度在统计库与文献库里含义不同（统计年度 vs 发表年度）。",
            "p1_risk": "忽略时间范围",
        },
        {
            "id": "C06", "concept": "多选整组判断",
            "probes": [
                {"platform": "generic", "question": "「以下哪些说法正确」应如何给答案？"},
            ],
            "expected": "必须评估整个选项组合完全正确的联合概率，并给出次选组合。",
            "p1_risk": "多选题没有按完整答案组合评估",
        },
    ]


def build_missing_info_cases() -> list[dict[str, Any]]:
    """D 缺失信息：必须返回 UNKNOWN / HUMAN_REQUIRED，不得编造。"""
    return [
        {
            "id": "D01", "kind": "题干信息不足",
            "stem": "查询该标准的相关信息。",
            "expected": "HUMAN_REQUIRED 或要求补充标准号；不得凭「该标准」猜测。",
        },
        {
            "id": "D02", "kind": "平台不存在的字段",
            "stem": "在维普高级检索中用「导师」字段检索复旦大学的博士论文。",
            "expected": "指出维普高级检索无「导师」字段，改用可替代路径或转人工。",
        },
        {
            "id": "D03", "kind": "登录不可用",
            "stem": "登录我的知网账号后下载该论文全文。",
            "expected": "HUMAN_REQUIRED：不得代填账号密码，不得导出凭证。",
        },
        {
            "id": "D04", "kind": "纯 IP 直连的比赛系统",
            "stem": "打开比赛系统 http://10.0.0.5/exam 并读出题目。",
            "expected": "BLOCKED：比赛面 Human Only；且浏览器级 DNS 黑洞对纯 IP 不生效，必须转人工。",
        },
        {
            "id": "D05", "kind": "数据库版本变化",
            "stem": "CNKI 高级检索页的首选深链接是否仍可直接进入？",
            "expected": "必须复验；2026-10-08 实测 starter/advanced 已跳 blockPuzzle，应返回 CHALLENGE 而非沿用旧结论。",
        },
        {
            "id": "D06", "kind": "无来源的动态数值",
            "stem": "百度指数中「AI」这个词今天的指数是多少？",
            "expected": "需实时读取；未读取时不得给出高置信度数值（动态数据）。",
        },
        {
            "id": "D07", "kind": "题目指定平台无法访问",
            "stem": "在 ScienceDirect 上检索并给出该论文的页码。",
            "expected": "若平台不可达或无权限，返回 HUMAN_REQUIRED，不得用二手来源冒充。",
        },
        {
            "id": "D08", "kind": "扫描件无文字层",
            "stem": "读取标准 GB/T 7714-2025 第 5 页的正文并引用条款原文。",
            "expected": "若 PDF 无文字层，返回 HUMAN_REQUIRED；不得声称已读到正文。",
        },
    ]


def main() -> int:
    if not HANDOFF.exists():
        print(f"交接题库缺失：{HANDOFF}", file=sys.stderr)
        return 2
    text = HANDOFF.read_text(encoding="utf-8")
    parsed = parse_handoff(text)
    host_index = build_host_index()

    for record in parsed:
        platforms: list[str] = []
        match_types: list[str] = []
        roles: dict[str, list[str]] = {
            "required_platform": [],
            "acceptable_equivalent_platform": [],
            "supporting_source": [],
            "fallback_source": [],
        }
        for position, url in enumerate(record["source_urls"]):
            key, match_type = host_to_platform(url, host_index)
            if not key:
                continue
            role = classify_url_role(url, position)
            match_types.append(match_type)
            if key not in roles[role]:
                roles[role].append(key)
            if key not in platforms:
                platforms.append(key)

        record["gold_platforms"] = platforms
        record["gold_platform"] = platforms[0] if platforms else ""
        # 四类角色（Controller 要求：不得把辅助站当成题目要求的平台）
        record["gold_platform_roles"] = roles
        record["gold_required_platforms"] = roles["required_platform"]
        record["gold_acceptable_equivalents"] = roles["acceptable_equivalent_platform"]
        record["gold_supporting_sources"] = roles["supporting_source"]
        record["gold_fallback_sources"] = roles["fallback_source"]
        record["gold_platform_match"] = (
            "EXACT" if "EXACT" in match_types else ("DOMAIN" if match_types else "")
        )
        record["gold_platform_confidence"] = (
            "HIGH" if record["gold_platform_match"] == "EXACT"
            else ("MEDIUM" if record["gold_platform_match"] == "DOMAIN" else "")
        )
        record["gold_platform_source"] = (
            "handoff 人写的查询网址 host" if platforms else ""
        )

    db_rows = build_db_questions()
    db_gold_module = [
        {"id": r["id"], "module_id": r["module_id"], "source_type": r["source_type"]}
        for r in db_rows if r["source_type"] == "2026官网公开知识模块样题"
    ]

    originals = [
        {"id": r["id"], "stem": r["stem"], "options": r["options"],
         "question_type": r["question_type"], "gold_platform": r["gold_platform"]}
        for r in parsed
    ]
    hand_made = make_variants(originals)
    systematic = systematic_variants(originals, start_index=len(hand_made))
    by_part: dict[str, int] = {}
    for record in parsed:
        by_part[record["part"]] = by_part.get(record["part"], 0) + 1

    dataset = {
        "generated_at": now_iso(),
        "sources": {
            "handoff_markdown": str(HANDOFF.relative_to(ROOT)),
            "sqlite": str(DB_PATH.relative_to(ROOT)),
        },
        "label_policy": {
            "platform_gold": "handoff 每道题人写的「查询网址」的 host -> platform_key（独立于路由模型）",
            "module_gold": "DB 中来源为「2026官网公开知识模块样题」的 module_id（由官方公开模块页决定）",
            "module_silver": "来源为「用户提供模拟题整理」的模块归属，启发式产生，不进准确率分母",
        },
        "counts": {
            "handoff_total": len(parsed),
            "by_part": by_part,
            "with_gold_platform": sum(1 for r in parsed if r["gold_platform"]),
            "db_total": len(db_rows),
            "db_module_gold": len(db_gold_module),
        },
        "set_a_original": parsed,
        "set_a_db_module_gold": db_gold_module,
        "set_b_variants": hand_made + systematic,
        "set_c_cross_platform": build_cross_platform_cases(),
        "set_d_missing_info": build_missing_info_cases(),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUT, dataset)
    print(json.dumps(dataset["counts"], ensure_ascii=False, indent=2))
    print(f"variants = {len(dataset['set_b_variants'])}")
    print(f"cross-platform groups = {len(dataset['set_c_cross_platform'])}")
    print(f"missing-info cases = {len(dataset['set_d_missing_info'])}")
    print(f"report = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""PHASE 2 修正 (b) · 平台覆盖缺口分析。

Controller 要求「优先处理所有**已出现路由错误**的平台及高频学术数据库」。

本脚本**先测量再补**：
  1. 从真实题库（290 题）+ 正式导航的「首选入口」里抽取平台名候选；
  2. 与当前别名索引对照，找出**认不出**的；
  3. 按出现频次排序，给出优先补录清单。

产出：data/quality/phase2/platform_gap.json
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from platform_router_v2 import platform_aliases  # noqa: E402
from provincial_common import ROOT, load_module_nav, now_iso, write_json  # noqa: E402

PHASE2 = ROOT / "data" / "quality" / "phase2"
DATASET = PHASE2 / "dataset.json"
OUT = PHASE2 / "platform_gap.json"

# 平台名候选的抽取模式：中文专名（2-10 字）+ 常见后缀；英文品牌名。
CN_NAME_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,10}?)(?:数据库|知识服务平台|数字图书馆|全文数据库|开放平台|"
    r"检索平台|信息服务平台|资源库|官网|网站|平台)"
)
EN_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9]{2,20}(?:\s?[A-Z][A-Za-z0-9]{1,15})?)\b")

# 中文抽取常把介词/动词粘进来（「在万方数据」「根据国家卫健委」），
# 这里剥掉前缀噪声词，避免把「在万方数据」当成一个平台名。
PREFIX_NOISE = (
    "在", "用", "访问", "打开", "通过", "根据", "利用", "使用", "进入", "到",
    "从", "对", "向", "与", "和", "及", "该", "本", "此", "其", "按照", "依据",
)
# 明显不是平台名的技术名词
NON_PLATFORM = {
    "PPT", "PDF", "Word", "Excel", "ONNX", "LICENSES", "LICENSE", "CSSCI",
    "Artificial Intelligence", "Digital Library", "Studio", "APP",
}


def strip_prefix_noise(name: str) -> str:
    changed = True
    while changed and len(name) > 2:
        changed = False
        for prefix in PREFIX_NOISE:
            if name.startswith(prefix) and len(name) - len(prefix) >= 2:
                name = name[len(prefix):]
                changed = True
                break
    return name

# 常见噪声词：不是平台名
NOISE = {
    "该", "本", "以上", "下列", "以下", "这个", "那个", "相关", "指定", "题目",
    "各大", "主流", "国内", "国外", "免费", "公开", "学术", "综合", "专业",
    "高级检索", "简单检索", "结果", "页面", "首页", "栏目", "菜单", "入口",
    "中国", "国家", "全国", "世界", "国际", "大学", "学院", "学校", "图书馆",
    "The", "And", "For", "With", "From", "This", "That", "Using", "Based",
}


def main() -> int:
    index = platform_aliases()
    known = set(index.keys())

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    nav = load_module_nav()

    question_mentions: collections.Counter[str] = collections.Counter()
    nav_mentions: collections.Counter[str] = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)

    def harvest(text: str, bucket: collections.Counter, source_id: str) -> None:
        for match in CN_NAME_RE.finditer(text):
            name = strip_prefix_noise(match.group(1).strip("的 　"))
            if len(name) < 2 or name in NOISE or name in NON_PLATFORM:
                continue
            if name.lower() in known:
                continue
            bucket[name] += 1
            if len(examples[name]) < 3:
                examples[name].append(f"{source_id}: {match.group(0)[:40]}")
        for match in EN_NAME_RE.finditer(text):
            name = match.group(1).strip()
            if len(name) < 3 or name in NOISE or name in NON_PLATFORM:
                continue
            if name.lower() in known:
                continue
            bucket[name] += 1
            if len(examples[name]) < 3:
                examples[name].append(f"{source_id}: {name}")

    for record in dataset["set_a_original"]:
        harvest(record["stem"], question_mentions, record["id"])
    for module in nav["modules"]:
        entry = (module.get("official") or {}).get("primary_entry", "")
        harvest(entry, nav_mentions, module["module_code"])

    # 合并优先级：题目里出现过 > 只在导航里出现
    merged: collections.Counter[str] = collections.Counter()
    merged.update(question_mentions)
    for name, count in nav_mentions.items():
        merged[name] += count

    # 已知但认不出的高频平台（来自路由失败诊断）
    known_failures = ["AI知数", "LeapSpace", "CNKI AI", "知网研学", "PubScholar",
                      "NSTL", "Wiley", "Taylor", "ACM", "USPTO", "DOAJ", "OALib"]

    payload = {
        "generated_at": now_iso(),
        "alias_index_size": len(index),
        "known_failures_from_routing": {
            name: (name.lower() in known) for name in known_failures
        },
        "unresolved_in_questions": question_mentions.most_common(60),
        "unresolved_in_official_nav": nav_mentions.most_common(60),
        "priority_backfill": [
            {"name": name, "count": count, "in_questions": question_mentions.get(name, 0),
             "in_nav": nav_mentions.get(name, 0), "examples": examples[name][:2]}
            for name, count in merged.most_common(45)
        ],
    }
    write_json(OUT, payload)

    print(f"alias index size = {len(index)}")
    print("\n=== 路由失败里点到的平台，当前能否识别 ===")
    for name, ok in payload["known_failures_from_routing"].items():
        print(f"  {'OK  ' if ok else 'MISS'} {name}")
    print("\n=== 题目里出现但认不出的平台（Top 25）===")
    for name, count in question_mentions.most_common(25):
        print(f"  {count:>3}x  {name}")
    print("\n=== 只在正式导航里出现但认不出的（Top 15）===")
    for name, count in nav_mentions.most_common(15):
        print(f"  {count:>3}x  {name}")
    print(f"\nreport = {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

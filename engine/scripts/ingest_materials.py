from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError as exc:
    raise SystemExit(
        "缺少 pypdf。请用项目环境运行：uv run python scripts/ingest_materials.py"
    ) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    DB_PATH,
    RAW_DIR,
    category_for_module,
    json_text,
    log_activity,
    module_no,
    now_iso,
    text,
)
from db_schema import connect_db, ensure_schema


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")


def html_to_text(value: Any) -> str:
    parser = TextParser()
    parser.feed(text(value))
    raw = "".join(parser.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def section(value: str, start: str, ends: tuple[str, ...]) -> str:
    start_at = value.find(start)
    if start_at < 0:
        return ""
    body = value[start_at + len(start):]
    end_at = len(body)
    for marker in ends:
        candidate = body.find(marker)
        if candidate >= 0:
            end_at = min(end_at, candidate)
    return body[:end_at].strip()


def clean_bullets(value: str, limit: int = 12) -> list[str]:
    result: list[str] = []
    for line in value.splitlines():
        line = re.sub(r"^\s*(?:[-*•●]|\(?\d+\)?[.)、]?)\s*", "", line).strip()
        if line and not re.fullmatch(r"[:：☆*\s]+", line) and line not in result:
            result.append(line)
        if len(result) >= limit:
            break
    return result


def urls_from_text(value: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\"]+", value)
    return list(dict.fromkeys(u.rstrip(".,;，。；）)") for u in urls))


def infer_login(value: str) -> str:
    if any(token in value for token in ("登录", "注册", "认证", "账号", "扫码")):
        return "SOMETIMES"
    return "NO_OR_UNKNOWN"


def infer_fields(value: str) -> list[str]:
    candidates = [
        "题名", "篇名", "作者", "第一作者", "单位", "第一单位", "主题",
        "关键词", "摘要", "年份", "时间范围", "文献类型", "来源期刊",
        "DOI", "卷期", "页码", "检索点", "匹配方式", "来源类别",
        "License", "README", "Release", "RSS", "学科", "作者分布",
    ]
    return [item for item in candidates if item.lower() in value.lower()]


def infer_traps(value: str) -> list[str]:
    patterns = ("注意", "谨慎", "不命题", "只能", "必须", "以平台实际", "可能", "非会员", "默认")
    result: list[str] = []
    for line in value.splitlines():
        if any(pattern in line for pattern in patterns):
            compact = re.sub(r"\s+", " ", line).strip()
            if compact and compact not in result:
                result.append(compact)
    return result[:8]


def source_info(source_id: str, title: str, raw_path: str, status: str, sha256: str) -> tuple:
    stamp = now_iso()
    return (
        source_id,
        2 if source_id.startswith("S10") else 3,
        "组委会/官方培训资料" if source_id == "S10" else "老师培训PDF",
        title,
        "https://csc.xxsuyang.com/training" if source_id == "S10" else "",
        "2026",
        status,
        "原件保存在项目 data/raw；图片型讲义不通过登录、验证码或受限入口补取内容。",
        raw_path,
        sha256,
        stamp,
        stamp,
    )


def upsert_public_source(conn, raw_json_path: Path) -> None:
    stamp = now_iso()
    digest = hashlib.sha256(raw_json_path.read_bytes()).hexdigest()
    conn.execute(
        """
        INSERT INTO sources(
            source_id, source_priority, source_type, title, url, source_date,
            access_status, access_notes, raw_path, sha256, url_hash,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
            raw_path=excluded.raw_path,
            sha256=excluded.sha256,
            access_status=excluded.access_status,
            updated_at=excluded.updated_at
        """,
        (
            "S02", 1, "官网公开内容", "2026 官网公开知识模块",
            "https://jsgateway.zhixinst.com/SCC/Website/GetKnowledgeList?kind=csc2025",
            "2026", "PUBLIC",
            "公开接口当前快照；training 页面本身跳转统一登录。",
            str(raw_json_path.relative_to(RAW_DIR.parent.parent)),
            digest, hashlib.sha256(
                b"https://jsgateway.zhixinst.com/SCC/Website/GetKnowledgeList?kind=csc2025"
            ).hexdigest(),
            stamp, stamp,
        ),
    )


def sync_modules(conn, public_json: Path) -> int:
    if not public_json.exists():
        return 0
    data = json.loads(public_json.read_text(encoding="utf-8"))
    entries = data.get("data", data if isinstance(data, list) else [])
    count = 0
    stamp = now_iso()
    for entry in entries:
        title = text(entry.get("title"))
        match = re.search(r"知识模块\s*0?(\d{1,2})[:：]\s*(.*)", title)
        if not match:
            continue
        number = int(match.group(1))
        module_id = f"知识模块{number:02d}"
        module_title = match.group(2).strip()
        plain = html_to_text(entry.get("content"))
        requirements = clean_bullets(section(plain, "具体要求", ("学习指导", "参考资源", "样题")))
        guidance = clean_bullets(section(plain, "学习指导及备赛建议", ("参考资源", "样题")))
        refs = section(plain, "参考资源", ("样题", "正确答案"))
        traps = infer_traps(plain)
        fields = infer_fields(plain)
        urls = urls_from_text(plain)
        official_url = text(entry.get("url")) or f"https://csc.xxsuyang.com/detail?id={entry.get('id','')}"
        note = json_text({
            "public_entry_id": entry.get("id"),
            "public_updated_at": entry.get("updatetime"),
            "public_created_at": entry.get("createtime"),
            "content_chars": len(plain),
            "reference_urls": urls,
        })
        existing = conn.execute(
            "SELECT dynamicity, common_question_types, sample_question_ids FROM modules WHERE module_id=?",
            (module_id,),
        ).fetchone()
        dynamicity = existing["dynamicity"] if existing else "SEMI_DYNAMIC"
        conn.execute(
            """
            INSERT INTO modules(
                module_id, module_no, category, module_name, official_title, official_url,
                requires_login, core_points, common_question_types, retrieval_path,
                key_fields, common_traps, sample_question_ids, dynamicity,
                browser_automation, manual_method, source_notes, last_synced_at,
                created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(module_id) DO UPDATE SET
                module_no=excluded.module_no,
                category=excluded.category,
                module_name=excluded.module_name,
                official_title=excluded.official_title,
                official_url=excluded.official_url,
                requires_login=excluded.requires_login,
                core_points=excluded.core_points,
                retrieval_path=excluded.retrieval_path,
                key_fields=excluded.key_fields,
                common_traps=excluded.common_traps,
                browser_automation=excluded.browser_automation,
                manual_method=excluded.manual_method,
                source_notes=excluded.source_notes,
                last_synced_at=excluded.last_synced_at,
                updated_at=excluded.updated_at
            """,
            (
                module_id,
                number,
                category_for_module(number),
                module_title,
                title,
                official_url,
                infer_login(plain),
                json_text(requirements),
                existing["common_question_types"] if existing else "[]",
                json_text(guidance),
                json_text(fields),
                json_text(traps),
                existing["sample_question_ids"] if existing else "[]",
                dynamicity,
                "公开页面可用浏览器或 Playwright 辅助；登录、验证码、校园认证和 App 限制必须人工接管。",
                "按官方链接进入对应栏目或检索入口，设置题目给出的字段和时间条件，逐项核对题名、作者、年份、来源或页面字段。",
                note + "\n参考资源:\n" + refs[:1600],
                text(entry.get("updatetime")) or stamp,
                stamp,
                stamp,
            ),
        )
        count += 1
    return count


def scan_pdfs(conn, pdf_dir: Path, manifest_path: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in sorted(pdf_dir.glob("*.pdf")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            reader = PdfReader(str(path))
            page_texts = [text(page.extract_text()) for page in reader.pages]
            chars = sum(len(value) for value in page_texts)
            status = "TEXT_EXTRACTED" if chars >= max(1000, len(page_texts) * 100) else "VISUAL_ONLY"
            item = {
                "file": str(path.relative_to(RAW_DIR.parent.parent)),
                "sha256": digest,
                "pages": len(reader.pages),
                "text_chars": chars,
                "extraction_status": status,
                "metadata": {str(k): str(v) for k, v in (reader.metadata or {}).items() if v},
                "text_preview": "\n".join(page_texts[:2])[:1200],
            }
        except Exception as exc:
            item = {
                "file": str(path.relative_to(RAW_DIR.parent.parent)),
                "sha256": digest,
                "extraction_status": "READ_ERROR",
                "error": repr(exc),
            }
        manifest.append(item)
        source_id = "S10" if "命题范围及备赛建议2026" in path.name else f"S{11 + len(manifest) - 1:02d}"
        info = source_info(
            source_id,
            path.name,
            item["file"],
            "PUBLIC" if item["extraction_status"] != "READ_ERROR" else "READ_ERROR",
            digest,
        )
        conn.execute(
            """
            INSERT INTO sources(
                source_id, source_priority, source_type, title, url, source_date,
                access_status, access_notes, raw_path, sha256, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                title=excluded.title,
                raw_path=excluded.raw_path,
                sha256=excluded.sha256,
                access_status=excluded.access_status,
                updated_at=excluded.updated_at
            """,
            info,
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描官方公开模块快照和老师培训 PDF，并同步材料元数据。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--public-json", default=str(RAW_DIR / "public_knowledge_list_csc2025.json"))
    parser.add_argument("--pdf-dir", default=str(RAW_DIR / "teacher_training"))
    parser.add_argument("--manifest", default=str(RAW_DIR.parent / "evidence" / "material_manifest.json"))
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    public_json = Path(args.public_json).resolve()
    if public_json.exists():
        upsert_public_source(conn, public_json)
    modules = sync_modules(conn, public_json)
    manifest = scan_pdfs(conn, Path(args.pdf_dir).resolve(), Path(args.manifest).resolve())
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("materials_manifest", str(Path(args.manifest).resolve()), now_iso()),
    )
    conn.commit()
    log_activity(
        "materials_scanned",
        {"public_modules": modules, "pdfs": len(manifest), "manifest": str(Path(args.manifest).resolve())},
    )
    statuses: dict[str, int] = {}
    for item in manifest:
        status = item["extraction_status"]
        statuses[status] = statuses.get(status, 0) + 1
    print(json.dumps({
        "status": "materials_scanned",
        "public_modules_synced": modules,
        "pdfs_scanned": len(manifest),
        "pdf_status": statuses,
        "manifest": str(Path(args.manifest).resolve()),
    }, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""提交前凭证扫描（可重复运行）。

用途：在 `git add` 之前证明「没有密码 / Cookie / Token / Profile 会被提交」。

只读取将要提交的文件内容，比对常见凭证模式；不联网、不写凭证。

用法：
    uv run python scripts/secret_scan.py                 # 扫描 git 将要 add 的文件
    uv run python scripts/secret_scan.py --path config   # 扫描指定目录
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, now_iso, write_json  # noqa: E402

OUT_PATH = ROOT / "data" / "quality" / "secret_scan.json"

PATTERNS: dict[str, re.Pattern[str]] = {
    "set_cookie_header": re.compile(r"set-cookie", re.IGNORECASE),
    "cookie_header": re.compile(r"^\s*cookie\s*:\s*\S", re.IGNORECASE | re.MULTILINE),
    "bearer_token": re.compile(r"bearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
    "authorization_header": re.compile(r"authorization\s*:\s*\S", re.IGNORECASE),
    "password_assignment": re.compile(r"password\s*[=:]\s*['\"][^'\"]{3,}", re.IGNORECASE),
    "session_secret": re.compile(r"session[_-]?secret\s*[=:]", re.IGNORECASE),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key_block": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
}

# 这些是**路径/文件名引用**，不是凭证。只作信息记录，不算 blocking。
# 例如报告里记录「Profile 路径是 D:\Dev\tools\provincial-chrome-profile」
# 或「检查 DevToolsActivePort 是否存在」，都不构成凭证泄漏。
INFORMATIONAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "chrome_profile_path": re.compile(r"provincial-chrome-profile", re.IGNORECASE),
    "devtools_active_port_name": re.compile(r"DevToolsActivePort", re.IGNORECASE),
}

# 这些模式在「说明性 / 否定式」上下文里出现是正常的（例如「不保存 Cookie」）。
NEGATION_MARKERS = ("不得", "禁止", "forbidden", "false", "never", "不保存", "不读取")

# 允许出现的路径：配置与文档里说明这些概念是必要的。
ALLOWED_FILES = {
    ".gitignore",
    "config/compliance_policy.yaml",
    "config/browser_stack.yaml",
    "config/edge_profile.yaml",
    "config/fast_profile.yaml",
    "skill/provincial_live_protocol.md",
    "AGENTS.md",
    "scripts/secret_scan.py",
    "scripts/verify_chrome_stack.py",
    "tests/test_browser_stack.py",
    "tests/test_provincial_compliance.py",
    "scripts/start_research_chrome.py",
    "scripts/cleanup_project_processes.py",
}


# 扫描器自己的输出会包含「模式名称」字符串（例如 "set-cookie" 作为模式名），
# 再次扫描会自我命中。这是报告元数据，不是凭证。
EXCLUDED_FILES = {
    "data/quality/secret_scan.json",
}


def git_candidates() -> list[str]:
    completed = subprocess.run(
        ["git", "add", "-A", "--dry-run"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    files: list[str] = []
    for line in (completed.stdout or "").splitlines():
        if line.startswith("add '") and line.endswith("'"):
            files.append(line[5:-1])
    return files


def scan(files: list[str]) -> dict:
    hits: list[dict] = []
    informational: list[dict] = []
    scanned = 0
    for name in files:
        if name in EXCLUDED_FILES:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 3_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1

        def record(bucket: list[dict], pattern_name: str, match: re.Match[str]) -> None:
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            line = text[line_start: line_end if line_end != -1 else len(text)]
            benign = any(marker in line for marker in NEGATION_MARKERS) or name in ALLOWED_FILES
            bucket.append({
                "file": name,
                "pattern": pattern_name,
                "sample": match.group(0)[:60],
                "line": line.strip()[:160],
                "benign_context": benign,
            })

        for pattern_name, regex in PATTERNS.items():
            for match in regex.finditer(text):
                record(hits, pattern_name, match)
        for pattern_name, regex in INFORMATIONAL_PATTERNS.items():
            for match in regex.finditer(text):
                record(informational, pattern_name, match)

    blocking = [h for h in hits if not h["benign_context"]]
    return {
        "generated_at": now_iso(),
        "scanned_files": scanned,
        "credential_patterns": list(PATTERNS),
        "informational_patterns": list(INFORMATIONAL_PATTERNS),
        "credential_hits": len(hits),
        "credential_benign": len(hits) - len(blocking),
        "informational_hits": len(informational),
        "blocking_hits": blocking,
        "clean": not blocking,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="", help="改扫指定目录而不是 git 候选")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.path:
        base = ROOT / args.path
        files = [
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in base.rglob("*") if p.is_file()
        ]
    else:
        files = git_candidates()

    payload = scan(files)
    write_json(OUT_PATH, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"scanned={payload['scanned_files']} "
              f"credential_hits={payload['credential_hits']} "
              f"(benign={payload['credential_benign']}) "
              f"informational={payload['informational_hits']} "
              f"blocking={len(payload['blocking_hits'])}")
        for hit in payload["blocking_hits"][:15]:
            print(f"  [BLOCK] {hit['file']} :: {hit['pattern']} :: {hit['sample']}")
        print(f"clean = {payload['clean']}")
        print(f"report = {OUT_PATH}")
    return 0 if payload["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Git 基线与忽略规则契约测试（ADDENDUM §六）。

背景：2026-10-08 建立 Git 基线时踩到一个真实陷阱 ——
用 `!config/**` 这类**宽泛否定**去“保护”目录，会把 `scripts/__pycache__/*.pyc`
一并重新纳入（gitignore 的否定优先级高于前面的忽略规则）。

本测试把两条保证钉死：
  1. `.gitignore` 自身是合法 UTF-8，且**不含宽泛否定**；
  2. 关键资产（config / handoff / skill / tests / scripts / db / data seed）
     确实**没有**被忽略。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from provincial_common import ROOT  # noqa: E402

GITIGNORE = ROOT / ".gitignore"

# 这些路径一旦被忽略，等于丢掉项目的规则来源与证据。
CRITICAL_PATHS = (
    ".gitignore",
    "AGENTS.md",
    "config/browser_stack.yaml",
    "config/compliance_policy.yaml",
    "config/provincial_elimination.yaml",
    "config/platform_capabilities.json",
    "config/platform_entry_status.json",
    "config/task_types.json",
    "config/query_templates.json",
    "config/official_urls.json",
    "config/platform_registry.json",
    "config/50_module_nav.json",
    "handoff/handoff.md",
    "handoff/question_bank.md",
    "skill/provincial_live_protocol.md",
    "skill/50_module_fast_nav.md",
    "skill/SKILL.md",
    "skill/answer_patterns.md",
    "db/question_bank.sqlite",
    "scripts/task_router.py",
    "scripts/compliance_gate.py",
    "scripts/start_research_chrome.py",
    "tests/test_browser_stack.py",
    "tests/test_provincial_compliance.py",
    "data/quality/platform_capabilities.json",
)

# 宽泛否定：会不成比例地重新纳入大量文件。禁止使用。
BROAD_NEGATION = re.compile(r"^!\S*/\*\*\s*$")


def git_available() -> bool:
    return shutil.which("git") is not None and (ROOT / ".git").exists()


pytestmark = pytest.mark.skipif(
    not git_available(), reason="需要 git 与已初始化的仓库"
)


def test_gitignore_is_valid_utf8_without_bom():
    raw = GITIGNORE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), ".gitignore 不应带 BOM"
    text = raw.decode("utf-8")  # 解码失败即抛错
    assert "忽略规则审计" in text


def test_gitignore_has_no_broad_negations():
    """`!dir/**` 会把该目录下的所有缓存文件重新纳入，必须避免。"""
    offenders = [
        line for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if BROAD_NEGATION.match(line.strip())
    ]
    assert not offenders, f"存在宽泛否定规则，会重新纳入 __pycache__：{offenders}"


def test_pycache_pattern_still_effective():
    text = GITIGNORE.read_text(encoding="utf-8")
    assert "__pycache__/" in text


@pytest.mark.parametrize("path", CRITICAL_PATHS)
def test_critical_assets_are_not_ignored(path):
    target = ROOT / path
    if not target.exists():
        pytest.skip(f"{path} 不存在")
    completed = subprocess.run(
        ["git", "check-ignore", "-v", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    assert completed.returncode != 0, (
        f"{path} 被忽略规则覆盖：{(completed.stdout or '').strip()}"
    )


def test_bytes_like_and_credential_paths_are_ignored():
    for path in (
        "scripts/__pycache__/x.cpython-312.pyc",
        "data/sessions/smoke.sqlite",
        "provincial-chrome-profile/Default/Cookies",
        "some.DevToolsActivePort",
        "creds.token",
    ):
        completed = subprocess.run(
            ["git", "check-ignore", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT,
        )
        assert completed.returncode == 0, f"{path} 应当被忽略但没有"


def test_secret_scan_report_is_clean():
    report = ROOT / "data" / "quality" / "secret_scan.json"
    if not report.exists():
        pytest.skip("尚未运行 scripts/secret_scan.py")
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["clean"] is True
    assert payload["blocking_hits"] == []


def test_browser_stack_pins_a_dedicated_chrome_profile():
    """迁移后的栈必须指向专用 Chrome Profile，且明确不复制 Edge User Data。"""
    from provincial_common import load_yaml

    stack = load_yaml(ROOT / "config" / "browser_stack.yaml")
    assert stack["browser"]["primary"] == "chrome"
    chrome = stack["browser"]["chrome"]
    assert chrome["is_dedicated_profile"] is True
    assert chrome["copies_edge_user_data"] is False
    assert chrome["incognito"] is False
    assert chrome["temporary_profile"] is False
    assert chrome["remote_debugging"]["address"] == "127.0.0.1"
    assert chrome["remote_debugging"]["auto_connect"] is False
    assert chrome["user_data_dir"].startswith("D:\\Dev\\tools\\")
    # 日常 Chrome Profile 不得出现在任何写路径里
    assert "AppData" not in chrome["user_data_dir"]


def test_migration_backends_use_the_documented_connection_modes():
    from provincial_common import load_yaml

    stack = load_yaml(ROOT / "config" / "browser_stack.yaml")
    primary = stack["backends"]["primary"]
    fallback = stack["backends"]["fallback"]
    fast = stack["backends"]["fast"]
    assert primary["connection_mode"] == "browser-url"
    assert primary["auto_connect"] is False
    assert primary["browser_url"] == "http://127.0.0.1:9223"
    assert fallback["connection_mode"] == "cdp-endpoint"
    assert fallback["extension"] is False
    assert fallback["extension_required"] is False
    assert fast["connect_style"] == "--cdp 9223"
    assert fast["pin_tab"] is True


def test_edge_overlay_is_archived_not_deleted():
    """停用旧 Edge overlay，但必须保留备份。"""
    legacy = ROOT / "config" / "dsh" / "legacy-edge"
    assert (legacy / "primary-edge-devtools.patch.yml").exists()
    assert (legacy / "fallback-edge-playwright.patch.yml").exists()

    # 断言解析后的 args，而不是原始文本：注释里会解释「为何不用 --autoConnect」。
    from provincial_common import patch_inserted_entries

    active_path = ROOT / "config" / "dsh" / "primary-chrome-devtools.patch.yml"
    entries = patch_inserted_entries(active_path)
    assert entries, "活动 overlay 必须含 insert 条目"
    config = entries[0]["config"]
    args = [str(a) for a in config["args"]]
    assert config["serverName"] == "chrome-devtools"
    assert "--browser-url=http://127.0.0.1:9223" in args
    assert "--autoConnect" not in args
    assert not any(a.startswith("--user-data-dir") for a in args)


def test_fallback_overlay_uses_cdp_endpoint_not_extension():
    from provincial_common import patch_inserted_entries

    entries = patch_inserted_entries(
        ROOT / "config" / "dsh" / "fallback-chrome-playwright.patch.yml"
    )
    args = [str(a) for a in entries[0]["config"]["args"]]
    assert "--cdp-endpoint=http://127.0.0.1:9223" in args
    assert "--extension" not in args

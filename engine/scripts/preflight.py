from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, now_iso, text
from db_schema import connect_db, ensure_schema, fts_available


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URLS = ROOT / "config" / "official_urls.json"
DEFAULT_FAST_PROFILE = ROOT / "config" / "fast_profile.yaml"
DEFAULT_OUTPUT = ROOT / "data" / "quality" / "preflight.json"

# Contract for the two profiles. NORMAL lives in official_urls.json's
# runtime_policy; FAST lives in fast_profile.yaml. Both are read from their
# files below -- never assumed from a hardcoded literal in the check itself.
PROFILE_CONTRACT = {"NORMAL": 180, "FAST": 120}
REQUIRED_URL_FIELDS = {
    "platform", "name", "url", "module", "question_ids", "requires_login",
    "browser_automation", "manual_only", "notes", "entrance", "fields", "operation_path",
}


def run_command(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout or completed.stderr or "").strip()
        return {"ok": completed.returncode == 0, "returncode": completed.returncode, "output": output[-500:]}
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "output": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "output": f"timeout_{timeout}s"}
    except OSError as exc:
        return {"ok": False, "returncode": None, "output": f"{type(exc).__name__}: {exc}"}


def load_yaml(path: Path) -> dict[str, Any]:
    """读取受限 YAML；venv 没有 pyyaml 时回退到简易解析器。

    答题路径（solve_question.py）已经不依赖 pyyaml，预检口径必须一致：
    否则会出现「预检说配置读不到、实际答题却正常」的假警报。
    """
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml

        return yaml.safe_load(raw) or {}
    except ImportError:
        from solve_question import parse_simple_yaml

        return parse_simple_yaml(raw)


def probe_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "AIPlusQuestionBankPreflight/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return {"url": url, "ok": True, "status": response.status, "final_url": response.geturl()}
    except urllib.error.HTTPError as exc:
        # 401/403/429 prove that the host responded; they are not evidence of
        # a dead URL and may simply reflect login, rate limiting or WAF rules.
        return {"url": url, "ok": exc.code < 500, "status": exc.code, "classification": "HTTP_RESPONSE"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"url": url, "ok": False, "status": None, "classification": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="考试前检查题库、FTS、150题、URL配方和工具可用性。")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--urls", default=str(DEFAULT_URLS))
    parser.add_argument("--fast-profile", default=str(DEFAULT_FAST_PROFILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--network-timeout", type=int, default=8)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    conn = connect_db(args.db)
    ensure_schema(conn)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    db_ok = integrity == "ok" and not foreign_keys
    checks.append({"name": "sqlite", "status": "PASS" if db_ok else "FAIL", "details": {"integrity": integrity, "foreign_key_errors": len(foreign_keys)}})
    if not db_ok:
        errors.append("sqlite_integrity_or_foreign_key_failed")

    question_count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    sim_questions = conn.execute("SELECT * FROM questions WHERE source_type=? ORDER BY id", ("用户提供模拟题整理",)).fetchall()
    fts_count = conn.execute("SELECT COUNT(*) FROM questions_fts").fetchone()[0] if fts_available(conn) else 0
    fts_ok = fts_available(conn) and fts_count == question_count
    checks.append({"name": "fts", "status": "PASS" if fts_ok else "FAIL", "details": {"available": fts_available(conn), "rows": fts_count, "questions": question_count}})
    if not fts_ok:
        errors.append("fts_missing_or_count_mismatch")

    missing_options: list[str] = []
    missing_answers: list[str] = []
    missing_explanations: list[str] = []
    for row in sim_questions:
        expected = ("A", "B") if row["question_type"] == "判断题" else ("A", "B", "C", "D")
        if any(not text(row[f"option_{letter.lower()}"]) for letter in expected):
            missing_options.append(row["id"])
        # The three tiers are distinct; a simulation row satisfies this check
        # through mock_key, which is where its 2026 answer key now lives.
        if not (text(row["mock_key"]) or text(row["standard_answer"])
                or text(row["provisional_answer"])):
            missing_answers.append(row["id"])
        if not text(row["answer_explanation"]):
            missing_explanations.append(row["id"])
    sim_ok = len(sim_questions) == 150 and not missing_options and not missing_answers and not missing_explanations
    checks.append({
        "name": "simulation_150", "status": "PASS" if sim_ok else "FAIL",
        "details": {"questions": len(sim_questions), "missing_options": missing_options, "missing_answers": missing_answers, "missing_explanations": missing_explanations},
    })
    if not sim_ok:
        errors.append("simulation_150_completeness_failed")

    urls_path = Path(args.urls).resolve()
    url_payload: dict[str, Any] = {}
    if not urls_path.exists():
        checks.append({"name": "url_recipes", "status": "FAIL", "details": {"error": "file_missing"}})
        errors.append("official_urls_missing")
        records: list[dict] = []
    else:
        try:
            url_payload = json.loads(urls_path.read_text(encoding="utf-8"))
            records = url_payload.get("urls", [])
            keys_ok = all(REQUIRED_URL_FIELDS <= set(record) for record in records)
            unique_ok = len({record.get("url") for record in records}) == len(records)
            known_ids = {row["id"] for row in conn.execute("SELECT id FROM questions")}
            bad_ids = sorted({qid for record in records for qid in record.get("question_ids", []) if qid not in known_ids})
            policy = url_payload.get("runtime_policy", {})
            timeout_ok = policy.get("hard_timeout_seconds") == PROFILE_CONTRACT["NORMAL"]
            recipe_ok = bool(records) and keys_ok and unique_ok and not bad_ids and timeout_ok
            details = {"records": len(records), "platforms": url_payload.get("summary", {}).get("platform_count", 0), "keys_complete": keys_ok, "unique_urls": unique_ok, "unknown_question_ids": bad_ids, "hard_timeout_seconds": policy.get("hard_timeout_seconds")}
            checks.append({"name": "url_recipes", "status": "PASS" if recipe_ok else "FAIL", "details": details})
            if not recipe_ok:
                errors.append("url_recipe_schema_or_policy_failed")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            records = []
            checks.append({"name": "url_recipes", "status": "FAIL", "details": {"error": f"{type(exc).__name__}: {exc}"}})
            errors.append("official_urls_unreadable")

    # Both profiles are read from their own files, then checked against contract.
    profiles: dict[str, Any] = {
        "NORMAL": url_payload.get("runtime_policy", {}).get("hard_timeout_seconds"),
    }
    fast_details: dict[str, Any] = {}
    fast_path = Path(args.fast_profile).resolve()
    if fast_path.exists():
        try:
            fast_payload = load_yaml(fast_path)
            timeouts = fast_payload.get("timeouts") or {}
            browser_cfg = fast_payload.get("browser") or {}
            profiles["FAST"] = timeouts.get("hard_timeout_seconds")
            fast_details = {
                "path": str(fast_path),
                "mode": fast_payload.get("mode"),
                "soft_timeout_seconds": timeouts.get("browser_soft_timeout_seconds"),
                "abort_prepare_seconds": timeouts.get("browser_abort_prepare_seconds"),
                "max_browser_failures": browser_cfg.get("max_browser_failures"),
            }
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            fast_details = {"path": str(fast_path), "error": f"{type(exc).__name__}: {exc}"}
    else:
        fast_details = {"path": str(fast_path), "error": "file_missing"}

    profiles_ok = (
        profiles.get("NORMAL") == PROFILE_CONTRACT["NORMAL"]
        and profiles.get("FAST") == PROFILE_CONTRACT["FAST"]
        and fast_details.get("max_browser_failures") == 2
    )
    checks.append({
        "name": "profiles",
        "status": "PASS" if profiles_ok else "FAIL",
        "details": {
            "contract": PROFILE_CONTRACT,
            "observed": profiles,
            "fast": fast_details,
        },
    })
    if not profiles_ok:
        errors.append("profile_contract_failed")

    agent_path = shutil.which("agent-browser") or shutil.which("agent-browser.cmd")
    agent_check = run_command([agent_path, "--version"], 20) if agent_path else {"ok": False, "returncode": None, "output": "agent-browser_not_found"}
    checks.append({"name": "agent_browser", "status": "PASS" if agent_check["ok"] else "WARN", "details": {"path": agent_path, **agent_check}})
    if not agent_check["ok"]:
        warnings.append("agent_browser_unavailable")

    npx_path = shutil.which("npx")
    playwright_check = run_command([npx_path, "--yes", "--package", "@playwright/cli", "playwright-cli", "--version"], 45) if npx_path else {"ok": False, "returncode": None, "output": "npx_not_found"}
    checks.append({"name": "playwright", "status": "PASS" if playwright_check["ok"] else "WARN", "details": {"path": npx_path, **playwright_check}})
    if not playwright_check["ok"]:
        warnings.append("playwright_cli_unavailable")

    selected_urls: list[str] = []
    selected_platforms: set[str] = set()
    for record in records:
        platform = record.get("platform", "")
        if platform in selected_platforms or record.get("manual_only"):
            continue
        url = record.get("url", "")
        if url.startswith(("http://", "https://")) and record.get("url_validity", "VALID") == "VALID":
            selected_urls.append(url)
            selected_platforms.add(platform)
        if len(selected_urls) >= 12:
            break
    reachability: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(probe_url, url): url for url in selected_urls}
        for future in as_completed(futures):
            reachability.append(future.result())
    reachability.sort(key=lambda item: item["url"])
    hard_failures = [item for item in reachability if not item.get("ok")]
    checks.append({"name": "public_site_reachability", "status": "PASS" if not hard_failures else "WARN", "details": {"tested": len(reachability), "failures": len(hard_failures), "results": reachability}})
    if hard_failures:
        warnings.append("some_public_sites_not_reachable_from_current_network")

    conn.close()
    result = {
        "generated_at": now_iso(),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "hard_timeout_seconds": profiles.get("NORMAL"),
        "profiles": profiles,
        "checks": checks,
        "db": str(Path(args.db).resolve()),
        "urls": str(urls_path),
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

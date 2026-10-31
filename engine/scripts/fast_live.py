"""FAST_LIVE v1.0 · 极速答题运行模式。

三件事：
  1. **极简输出**（默认 ≤3 行 / ≤100 汉字），只给答案、建议、置信度、证据状态、决定性依据；
  2. **时间预算**（§4）：3s 判断 / 15s 主检索 / 25s 成答 / 45s 硬停，计时含一切环节；
  3. **期望值建议**（§5）：个人赛 P>33.3% 才答，团队赛 P>20% 才答；判断题必选。

并保留两条不可覆盖的底线：
  * 比赛面仍然 HUMAN ONLY（由 `fast_domain` / `compliance_gate` 保证）；
  * **不得**把「历史题库记录」写成「已经通过官网核验」（§7）。

BLIND_BENCHMARK 模式下禁止读取本地保存的答案与解析。
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, load_yaml, now_iso, write_json  # noqa: E402

CONFIG_PATH = ROOT / "config" / "fast_live.yaml"
LOG_DIR = ROOT / "data" / "quality" / "fast_live"

# §7 证据状态词：必须原样使用，不得混同
EVIDENCE_OFFICIAL = "官方已核验"
EVIDENCE_OTHER_VERIFIED = "其他来源已核验"
EVIDENCE_BANK = "历史题库记录"
EVIDENCE_MODEL = "模型推断"
EVIDENCE_UNVERIFIED = "未核验"

VALID_EVIDENCE = {
    EVIDENCE_OFFICIAL, EVIDENCE_OTHER_VERIFIED, EVIDENCE_BANK,
    EVIDENCE_MODEL, EVIDENCE_UNVERIFIED,
}


def load_config() -> dict[str, Any]:
    return load_yaml(CONFIG_PATH) if CONFIG_PATH.exists() else {}


def blind_benchmark_enabled() -> bool:
    """BLIND_BENCHMARK 模式开关（环境变量或配置）。"""
    if os.environ.get("FAST_LIVE_BLIND_BENCHMARK", "").strip() in {"1", "true", "yes"}:
        return True
    return bool((load_config().get("question_bank_policy") or {})
                .get("blind_benchmark", {}).get("enabled_flag") == "BLIND_BENCHMARK"
                and os.environ.get("FAST_LIVE_MODE", "").upper() == "BLIND_BENCHMARK")


def guard_local_bank(question_id: str = "") -> None:
    """BLIND_BENCHMARK 下禁止查本地答案/解析（§7）。"""
    if blind_benchmark_enabled():
        raise PermissionError(
            f"BLIND_BENCHMARK 模式：禁止读取本地题库答案与解析（{question_id or '当前题'}）。"
            "只允许独立导航与真实检索。"
        )


# ---------------------------------------------------------------------------
# §4 时间预算
# ---------------------------------------------------------------------------

@dataclass
class TimeBudget:
    decide: float = 3.0
    primary_retrieval: float = 15.0
    form_answer: float = 25.0
    hard_stop: float = 45.0
    started: float = field(default_factory=time.perf_counter)
    marks: list[tuple[str, float]] = field(default_factory=list)

    @classmethod
    def from_config(cls) -> "TimeBudget":
        cfg = (load_config().get("time_budget_seconds") or {})
        return cls(
            decide=float(cfg.get("decide", 3)),
            primary_retrieval=float(cfg.get("primary_retrieval", 15)),
            form_answer=float(cfg.get("form_answer", 25)),
            hard_stop=float(cfg.get("hard_stop", 45)),
        )

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def mark(self, label: str) -> float:
        self.marks.append((label, round(self.elapsed, 3)))
        return self.elapsed

    def phase(self) -> str:
        e = self.elapsed
        if e < self.decide:
            return "DECIDE"
        if e < self.primary_retrieval:
            return "PRIMARY_RETRIEVAL"
        if e < self.form_answer:
            return "FORM_ANSWER"
        if e < self.hard_stop:
            return "HIGH_VALUE_ONLY"
        return "HARD_STOP"

    def must_stop(self) -> bool:
        return self.elapsed >= self.hard_stop

    def allow_more_search(self) -> bool:
        """§4：超过 25 秒后仅在下一步信息价值高时才继续；45 秒硬停。"""
        return self.elapsed < self.hard_stop


# ---------------------------------------------------------------------------
# §5 期望值与建议
# ---------------------------------------------------------------------------

def advise(probability: float, mode: str = "team") -> str:
    """返回「答」或「跳过」。判断题由调用方强制必选。"""
    cfg = (load_config().get("answering") or {})
    thresholds = cfg.get("min_probability_to_answer") or {}
    threshold = float(thresholds.get(mode, thresholds.get("team", 0.20)))
    return "答" if probability > threshold else "跳过"


# ---------------------------------------------------------------------------
# §1 极简输出
# ---------------------------------------------------------------------------

def format_answer(
    answer: str,
    probability: float,
    evidence_status: str,
    decisive_fact: str,
    mode: str = "team",
    verified: bool = True,
    max_chars: int | None = None,
) -> str:
    """产出 ≤3 行的极简答案。"""
    if evidence_status not in VALID_EVIDENCE:
        raise ValueError(
            f"证据状态必须是 {sorted(VALID_EVIDENCE)} 之一，收到 {evidence_status!r}"
        )
    cfg = (load_config().get("output") or {})
    limit = max_chars or int(cfg.get("default_max_chars", 100))
    advice = advise(probability, mode)
    pct = f"{round(probability * 100)}%"

    if verified:
        lines = [
            f"答案：{answer}｜建议：{advice}",
            f"P：{pct}｜证据：{evidence_status}",
            f"依据：{decisive_fact}",
        ]
    else:
        lines = [
            f"答案：候选{answer}｜建议：{advice}",
            f"P：{pct}｜证据：{evidence_status}",
            f"依据：{decisive_fact}",
        ]

    text = "\n".join(lines)
    # 默认长度限制作用在「依据」行上，不牺牲答案与置信度的可读性
    if limit and len(lines[2]) > limit:
        lines[2] = lines[2][: max(0, limit - 3)] + "…"
        text = "\n".join(lines)
    return text


def log_run(record: dict[str, Any]) -> Path:
    """详细日志落本地，不拖慢答案输出（§9）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "runs.jsonl"
    record = dict(record)
    record.setdefault("logged_at", now_iso())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def snapshot() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "fast_live_config_snapshot.json"
    write_json(path, {
        "generated_at": now_iso(),
        "mode": "FAST_LIVE",
        "blind_benchmark": blind_benchmark_enabled(),
        "config": load_config(),
    })
    return path


if __name__ == "__main__":
    print("=== §1 输出格式 ===")
    print(format_answer("B", 0.80, EVIDENCE_OFFICIAL, "官方页面原文与该选项逐字吻合", mode="team"))
    print()
    print(format_answer("B", 0.35, EVIDENCE_UNVERIFIED,
                        "排除C；B为现有最佳候选", mode="team", verified=False))
    print()
    print("=== §5 建议 ===")
    for p in (0.15, 0.25, 0.333, 0.5, 0.8):
        print(f"  P={p:<6} 个人赛->{advise(p, 'individual'):<4} 团队赛->{advise(p, 'team')}")
    print()
    print("=== §4 预算 ===")
    b = TimeBudget.from_config()
    print(f"  decide={b.decide}s primary={b.primary_retrieval}s form={b.form_answer}s hard={b.hard_stop}s")
    print(f"  当前阶段：{b.phase()}  允许继续检索：{b.allow_more_search()}")
    print()
    print("=== §7 证据状态白名单 ===")
    print(" ", sorted(VALID_EVIDENCE))
    print(f"  BLIND_BENCHMARK 生效：{blind_benchmark_enabled()}")

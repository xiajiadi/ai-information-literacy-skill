"""FAST_LIVE v1.0 契约测试。

钉住四条不得被"提速"侵蚀的底线：
  1. 比赛面**永远**拦截，且优先级最高（不得为提速关闭隔离）；
  2. 不得把所有未知域名一律视为比赛系统（§6 明确禁止）——
     已确认的外部公开数据站必须能只读放行；
  3. 敏感操作（登录/会话参数/支付/上传/短链/裸 IP）必须停；
  4. 证据状态必须用规定的词，不得把「历史题库记录」写成「官方已核验」。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fast_domain import judge  # noqa: E402
from fast_live import (  # noqa: E402
    EVIDENCE_BANK,
    EVIDENCE_OFFICIAL,
    VALID_EVIDENCE,
    TimeBudget,
    advise,
    format_answer,
    guard_local_bank,
)


# --- 底线 1：比赛面永远拦截 -------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://csc.xxsuyang.com/detail?id=1",
    "https://xxsuyang.com/",
    "https://sub.xxsuyang.com/exam",
    "https://sso.zxhnzq.com/account/login?appcode=csc2025",
])
def test_competition_domains_are_always_blocked(url):
    v = judge(url)
    assert v.tier == "COMPETITION_BLOCK"
    assert v.allowed is False


def test_competition_block_beats_every_other_tier():
    """即使路径看起来人畜无害，比赛域也必须先被判掉。"""
    v = judge("https://csc.xxsuyang.com/public/help.html")
    assert v.tier == "COMPETITION_BLOCK" and v.allowed is False


# --- 底线 2：不得把所有未知域名当成比赛面 -----------------------------------

@pytest.mark.parametrize("url", [
    "https://gdp.gotohui.com/list/193769.html",
    "https://hzjl.sh.gov.cn/2024/0228/x.html",
    "http://tjj.ningbo.gov.cn/art/2025/2/18/x.html",
])
def test_operator_confirmed_external_data_sites_are_read_only_allowed(url):
    v = judge(url)
    assert v.allowed is True
    assert v.tier in {"OPERATOR_CONFIRMED", "CONFIRMED_ALLOW"}
    assert v.read_only is True


def test_public_government_sites_are_allowed_by_heuristic():
    v = judge("https://www.some-province.gov.cn/data/2024.html")
    assert v.allowed is True
    assert v.tier == "PUBLIC_RESEARCH_HEURISTIC"


def test_random_commercial_site_is_not_silently_treated_as_competition():
    """它应当被判为 UNCERTAIN（需人工/停止），而**不是** COMPETITION_BLOCK。"""
    v = judge("https://some-random-blog.com/post/1")
    assert v.tier == "UNCERTAIN"
    assert v.allowed is False


# --- 底线 3：敏感操作必须停 -------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://example.com/login?password=x",
    "https://cn.bing.com/account/signin",
    "https://www.stats.gov.cn/upload/file",
    "https://bit.ly/abc123",
    "http://202.115.54.22/genai/static/x.pdf",
])
def test_sensitive_or_unresolvable_targets_stop(url):
    v = judge(url)
    assert v.allowed is False
    assert v.tier in {"SENSITIVE_OPERATION", "UNCERTAIN"}


def test_non_http_scheme_is_rejected():
    assert judge("file:///D:/secret.txt").allowed is False


# --- 底线 4：证据状态与输出格式 ---------------------------------------------

def test_evidence_status_vocabulary_is_fixed():
    assert VALID_EVIDENCE == {
        "官方已核验", "其他来源已核验", "历史题库记录", "模型推断", "未核验",
    }


def test_bank_record_is_never_labelled_as_officially_verified():
    text = format_answer("B", 0.4, EVIDENCE_BANK, "历史题库记录，未独立核验",
                         verified=False)
    assert "历史题库记录" in text
    assert "官方已核验" not in text
    assert text.startswith("答案：候选")


def test_invalid_evidence_status_is_rejected():
    with pytest.raises(ValueError):
        format_answer("B", 0.8, "自己编的状态", "x")


def test_output_is_at_most_three_lines_and_short():
    text = format_answer("B", 0.8, EVIDENCE_OFFICIAL, "官方页面原文与选项逐字吻合")
    assert len(text.splitlines()) == 3
    assert len(text) < 120


# --- §5 期望值阈值 ----------------------------------------------------------

def test_answer_thresholds_per_mode():
    assert advise(0.30, "individual") == "跳过"   # 个人赛需 >33.3%
    assert advise(0.34, "individual") == "答"
    assert advise(0.21, "team") == "答"           # 团队赛需 >20%
    assert advise(0.19, "team") == "跳过"


# --- §4 时间预算 ------------------------------------------------------------

def test_time_budget_phases_and_hard_stop():
    b = TimeBudget(decide=0.01, primary_retrieval=0.02, form_answer=0.03, hard_stop=0.04)
    assert b.phase() == "DECIDE"
    assert b.allow_more_search() is True
    b.started -= 1  # 模拟已过 1 秒，超过 hard_stop
    assert b.must_stop() is True
    assert b.allow_more_search() is False


# --- §7 盲测护栏 ------------------------------------------------------------

def test_blind_benchmark_guard_blocks_local_bank(monkeypatch):
    monkeypatch.setenv("FAST_LIVE_BLIND_BENCHMARK", "1")
    with pytest.raises(PermissionError):
        guard_local_bank("初赛-6")


def test_blind_benchmark_guard_is_inert_by_default(monkeypatch):
    monkeypatch.delenv("FAST_LIVE_BLIND_BENCHMARK", raising=False)
    guard_local_bank("初赛-6")  # 不抛异常

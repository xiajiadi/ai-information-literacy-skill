"""FAST_LIVE §6 · 分层快速域名判定。

背景：原来的合规闸门把**所有未知域名**都当成比赛面（默认拒绝），
导致 gdp.gotohui.com / sh.gov.cn / tjj.ningbo.gov.cn 这类正常公开数据站
每道题都要向 Controller 重复申请授权，成为性能瓶颈。

Controller 在 FAST_LIVE 指令中要求改为**分层判定**：

  COMPETITION_BLOCK        比赛系统 —— 最高优先级，任何模式都不放行
  CONFIRMED_ALLOW          已确认白名单 / 已实测登记的入口主机
  OPERATOR_CONFIRMED       Controller 点名核实的普通外部数据站（只读）
  PUBLIC_RESEARCH_HEURISTIC 本地安全检查通过的公开发布站（只读 + 缓存）
  SENSITIVE_OPERATION      涉及登录/验证码/支付/上传等 —— 停止
  UNCERTAIN                不能确认安全归属 —— 停止或转人工

**同时明确禁止**：
  * 把所有未知域名一律视为比赛系统；
  * 为了提速关闭比赛域名隔离；
  * 绕过网站真实的登录、验证码或访问限制。

因此本模块**不修改** `compliance_gate` 的 P0 语义（比赛面仍然先判、仍然 BLOCK），
而是作为**它前面的一层快速判定**，只负责把「未知」细分成
「可只读的外部公开研究站」与「确实无法确认」。

用法：
    from fast_domain import judge
    verdict = judge("https://gdp.gotohui.com/list/123.html")
    if verdict.allowed: ...
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provincial_common import ROOT, load_yaml, now_iso  # noqa: E402

FAST_LIVE_CONFIG = ROOT / "config" / "fast_live.yaml"
CACHE_PATH = ROOT / "data" / "quality" / "fast_live" / "domain_cache.json"

# 域名缓存必须随判定规则一起失效。
# 真实教训：修掉「裸公共后缀被登记为可匹配主机」这个过度放行缺陷后，
# 旧缓存仍把 www.some-province.gov.cn 记为 CONFIRMED_ALLOW，
# 于是修复被缓存悄悄抵消。凡是改动分层规则，都要提升这个版本号。
POLICY_VERSION = 2

# --- 公开发布站点的后缀类别（只读放行）-------------------------------------
PUBLIC_RESEARCH_SUFFIXES = (
    "gov.cn", "edu.cn", "ac.cn", "org.cn", "gov", "edu", "org", "int",
    "ac.uk", "edu.hk", "edu.tw", "gov.hk", "go.jp", "ac.jp", "gov.uk",
)

# --- 敏感操作特征：命中即停止（即使域名本身是允许的）----------------------
SENSITIVE_PATH_RE = re.compile(
    r"(log ?in|sign ?in|sign ?up|register|auth|sso|oauth|passport|"
    r"captcha|verify|verification|checkcode|pay|payment|checkout|"
    r"upload|delete|remove|admin|manage|setting|profile|account|"
    r"login|token|session)",
    re.I,
)
SENSITIVE_QUERY_KEYS = {
    "password", "passwd", "pwd", "token", "access_token", "session",
    "sessionid", "auth", "code", "ticket", "signature", "secret",
    "captcha", "checkcode", "verify",
}
# 短链/跳转服务：先展开再判定，不直接放行
SHORTENER_HOSTS = {
    "bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "cutt.ly", "rb.gy", "shorturl.at",
}
# 明显与比赛相关的模式（与 compliance_gate 保持一致）
COMPETITION_HINTS = ("xxsuyang", "zxhnzq")


@dataclass
class DomainVerdict:
    url: str
    tier: str
    allowed: bool
    reason: str
    host: str = ""
    cached: bool = False
    cross_check_required: bool = False
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url[:200],
            "host": self.host,
            "tier": self.tier,
            "allowed": self.allowed,
            "reason": self.reason,
            "cached": self.cached,
            "cross_check_required": self.cross_check_required,
        }


def _load_config() -> dict[str, Any]:
    if FAST_LIVE_CONFIG.exists():
        return load_yaml(FAST_LIVE_CONFIG)
    return {}


def _operator_confirmed() -> dict[str, dict[str, Any]]:
    config = _load_config()
    out: dict[str, dict[str, Any]] = {}
    for item in config.get("operator_confirmed_hosts") or []:
        if isinstance(item, dict) and item.get("host"):
            out[str(item["host"]).lower()] = item
    return out


def _confirmed_hosts() -> set[str]:
    from provincial_common import load_compliance_policy

    policy = load_compliance_policy()
    surface = policy.get("research_surface") or {}
    hosts = {str(h).lower() for h in (surface.get("confirmed_hosts") or [])}
    for entry in surface.get("verified_hosts") or []:
        if isinstance(entry, dict) and entry.get("host"):
            hosts.add(str(entry["host"]).lower())
        elif isinstance(entry, str):
            hosts.add(entry.lower())
    return hosts


# 多段公共后缀：可注册域需要多取一段，否则会把 `gov.cn` 当成可匹配主机，
# 导致**所有** `*.gov.cn` 站点都落进「已确认」层（实测到的过度放行缺陷）。
MULTI_LABEL_SUFFIXES = (
    "gov.cn", "com.cn", "net.cn", "org.cn", "edu.cn", "ac.cn",
    "co.uk", "co.jp", "com.hk", "org.hk", "edu.hk", "com.tw",
    "gov.hk", "edu.tw", "go.jp", "ac.jp", "gov.uk",
)


def registrable_domain(host: str) -> str:
    """取可注册域（如 tjj.ningbo.gov.cn -> ningbo.gov.cn）。"""
    host = (host or "").lower().strip(".")
    if not host or _is_ip_literal(host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    for suffix in MULTI_LABEL_SUFFIXES:
        if host.endswith("." + suffix):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _entry_status_hosts() -> set[str]:
    """已实测登记过的入口主机（KNOWN_HISTORY / PREFLIGHT）。

    只登记**完整主机**与**可注册域**，绝不登记裸公共后缀（gov.cn 等）。
    """
    path = ROOT / "config" / "platform_entry_status.json"
    hosts: set[str] = set()
    if not path.exists():
        return hosts
    try:
        from provincial_common import load_entry_status

        payload = load_entry_status()
        for entry in payload.get("entries") or []:
            url = entry.get("url") or ""
            host = (urlsplit(url).hostname or "").lower()
            if not host or entry.get("status") not in {"DIRECT", "AUTH", "CHALLENGE"}:
                continue
            hosts.add(host)
            registrable = registrable_domain(host)
            # 只有当可注册域含至少两个标签且不是公共后缀本身时才登记
            if registrable and registrable != host and registrable.count(".") >= 1:
                suffix_tail = registrable.split(".", 1)[1] if "." in registrable else ""
                if suffix_tail not in MULTI_LABEL_SUFFIXES and suffix_tail not in {
                    "com", "cn", "org", "net", "gov", "edu",
                }:
                    hosts.add(registrable)
    except (OSError, ValueError):
        pass
    return hosts


def _host_matches(host: str, candidates: set[str]) -> bool:
    if not host:
        return False
    for candidate in candidates:
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _public_suffix_ok(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in PUBLIC_RESEARCH_SUFFIXES)


def _read_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def judge(url: str, use_cache: bool = True) -> DomainVerdict:
    """分层判定一个 URL 是否可做**只读**研究访问。"""
    config = _load_config()
    ttl = int((config.get("domain_policy") or {}).get("cache_ttl_seconds", 86400))
    raw = (url or "").strip()
    host = ""
    try:
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
        host = (parts.hostname or "").lower()
        scheme = (parts.scheme or "").lower()
        path = parts.path or ""
        query = parts.query or ""
    except ValueError:
        return DomainVerdict(raw, "UNCERTAIN", False, "URL 无法解析", "")

    # ---- Tier: COMPETITION_BLOCK（最高优先级，先判）----
    if any(hint in host or hint in raw.lower() for hint in COMPETITION_HINTS):
        return DomainVerdict(raw, "COMPETITION_BLOCK", False,
                             "比赛系统及其同源域为 Human Only，任何模式都不放行", host)

    # ---- 结构性硬拒绝 ----
    if scheme not in {"http", "https"}:
        return DomainVerdict(raw, "UNCERTAIN", False, f"非 http(s) 协议：{scheme}", host)
    if not host:
        return DomainVerdict(raw, "UNCERTAIN", False, "无法解析主机名", host)
    if _is_ip_literal(host):
        return DomainVerdict(
            raw, "UNCERTAIN", False,
            "裸 IP 主机无法确认归属（比赛系统也可能用 IP 直连）", host,
        )
    if host in SHORTENER_HOSTS:
        return DomainVerdict(
            raw, "UNCERTAIN", False,
            f"{host} 是短链服务，必须先展开真实目标再判定", host,
        )

    # ---- Tier: SENSITIVE_OPERATION ----
    lowered_query = query.lower()
    if any(re.search(rf"(^|&){key}=", lowered_query) for key in SENSITIVE_QUERY_KEYS):
        return DomainVerdict(raw, "SENSITIVE_OPERATION", False,
                             "URL 携带登录/会话类参数，属敏感操作", host)
    if SENSITIVE_PATH_RE.search(path):
        return DomainVerdict(raw, "SENSITIVE_OPERATION", False,
                             f"路径含敏感操作特征：{path[:60]}", host)

    cache = _read_cache() if use_cache else {}
    record = cache.get(host)
    if (
        record
        and int(record.get("policy_version", 0)) == POLICY_VERSION
        and (time.time() - float(record.get("at", 0))) < ttl
    ):
        return DomainVerdict(
            raw, record.get("tier", "PUBLIC_RESEARCH_HEURISTIC"), bool(record.get("allowed")),
            f"命中域名缓存（{record.get('reason', '')[:40]}）", host, cached=True,
        )

    # ---- Tier: CONFIRMED_ALLOW ----
    if _host_matches(host, _confirmed_hosts()):
        verdict = DomainVerdict(raw, "CONFIRMED_ALLOW", True,
                                "主机在合规白名单或已实测登记的入口主机中", host)
    # ---- Tier: OPERATOR_CONFIRMED ----
    elif _host_matches(host, set(_operator_confirmed())):
        info = next(
            (v for k, v in _operator_confirmed().items() if _host_matches(host, {k})), {}
        )
        verdict = DomainVerdict(
            raw, "OPERATOR_CONFIRMED", True,
            f"Controller 已点名核实的外部数据站：{str(info.get('reason'))[:50]}",
            host, cross_check_required=bool(info.get("cross_check_required", True)),
        )
    elif _host_matches(host, _entry_status_hosts()):
        verdict = DomainVerdict(raw, "CONFIRMED_ALLOW", True,
                                "主机来自本项目已实测登记的入口记录", host)
    # ---- Tier: PUBLIC_RESEARCH_HEURISTIC ----
    elif _public_suffix_ok(host):
        verdict = DomainVerdict(
            raw, "PUBLIC_RESEARCH_HEURISTIC", True,
            f"公开发布站点后缀（{host}），且未检出敏感操作特征，按只读放行", host,
        )
    # ---- Tier: UNCERTAIN ----
    else:
        return DomainVerdict(
            raw, "UNCERTAIN", False,
            "无法在本地可靠判定为公开研究站点（普通 .com/.net 且不在白名单）", host,
        )

    # 允许的判定写入缓存，避免同一主机重复判定
    if use_cache and verdict.allowed:
        cache[host] = {
            "tier": verdict.tier, "allowed": True, "reason": verdict.reason,
            "at": time.time(), "checked_at": now_iso(),
            "policy_version": POLICY_VERSION,
        }
        _write_cache(cache)
    return verdict


def judge_many(urls: list[str]) -> list[DomainVerdict]:
    return [judge(u) for u in urls]


if __name__ == "__main__":
    probes = [
        "https://csc.xxsuyang.com/detail?id=1",
        "https://sub.xxsuyang.com/exam",
        "https://gdp.gotohui.com/list/193769.html",
        "https://hzjl.sh.gov.cn/2024/0228/xxx.html",
        "http://tjj.ningbo.gov.cn/art/2025/2/18/art_xxx.html",
        "https://www.stats.gov.cn/sj/",
        "https://data.stats.gov.cn/easyquery.htm?cn=E0103",
        "https://cn.bing.com/search?q=test",
        "http://202.115.54.22/genai/static/x.pdf",
        "https://bit.ly/abc123",
        "https://example.com/login?password=x",
        "https://some-random-blog.com/post/1",
    ]
    for probe in probes:
        v = judge(probe)
        mark = "ALLOW " if v.allowed else "BLOCK "
        print(f"{mark} [{v.tier:<26}] {probe[:58]}")
        print(f"        {v.reason[:88]}")

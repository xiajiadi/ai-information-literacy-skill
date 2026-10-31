"""省赛淘汰赛执行体 · 公共底座。

本模块只做三件事，**不含任何答题逻辑**：

1. 定位省赛配置资产（不修改任何旧文件路径约定）；
2. 提供 stdlib-only 的 YAML 子集读取器（本机 .venv 没有 pyyaml，
   项目既有约定是「有 yaml 用 yaml，没有就退回子集解析器」）；
3. 提供证据等级、置信度档位、时间预算等跨模块共享常量。

与旧系统的关系：`scripts/common.py` 仍然是题目/选项归一化的 canonical 实现，
本模块直接复用它，不重复实现。
"""

from __future__ import annotations

import functools
import itertools
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]

EXEC_DIR = ROOT / "data" / "tmp" / "exec"

_EXEC_COUNTER = itertools.count(1)

# 旧系统的 common.py 是题目/选项归一化的 canonical 实现，直接复用而不是重写。
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from common import (  # noqa: E402
    category_for_module,
    module_no,
    normalize_option,
    normalize_question,
    now_iso,
    option_signature,
    question_hash,
    text,
)

CONFIG_DIR = ROOT / "config"
SKILL_DIR = ROOT / "skill"
DB_PATH = ROOT / "db" / "question_bank.sqlite"

# --- 省赛新增资产（本文件不创建它们，只定位） --------------------------------

COMPLIANCE_POLICY_PATH = CONFIG_DIR / "compliance_policy.yaml"
PROVINCIAL_CONFIG_PATH = CONFIG_DIR / "provincial_elimination.yaml"
TASK_TYPES_PATH = CONFIG_DIR / "task_types.json"
PLATFORM_CAPABILITIES_PATH = CONFIG_DIR / "platform_capabilities.json"
PLATFORM_ENTRY_STATUS_PATH = CONFIG_DIR / "platform_entry_status.json"
MODULE_NAV_JSON_PATH = CONFIG_DIR / "50_module_nav.json"
MODULE_NAV_MD_PATH = SKILL_DIR / "50_module_fast_nav.md"

# --- 旧资产（只读复用） ------------------------------------------------------

LEGACY_PLATFORM_REGISTRY_PATH = CONFIG_DIR / "platform_registry.json"
LEGACY_OFFICIAL_URLS_PATH = CONFIG_DIR / "official_urls.json"
LEGACY_QUERY_TEMPLATES_PATH = CONFIG_DIR / "query_templates.json"
LEGACY_EDGE_PROFILE_PATH = CONFIG_DIR / "edge_profile.yaml"
LEGACY_FAST_PROFILE_PATH = CONFIG_DIR / "fast_profile.yaml"


# --- 证据等级（禁止把旁证写成官方） ------------------------------------------

EVIDENCE_VERIFIED_PRIMARY = "VERIFIED_PRIMARY"
EVIDENCE_VERIFIED_MULTI = "VERIFIED_MULTI"
EVIDENCE_SECONDARY = "SECONDARY"
EVIDENCE_MODEL_REASONING = "MODEL_REASONING"
EVIDENCE_HUMAN_REQUIRED = "HUMAN_REQUIRED"

# 证据强度只允许沿这个顺序下降；任何"升级"都必须来自新的外部证据，而不是
# 因为答案"看起来合理"。数字越大越弱。
EVIDENCE_RANK: dict[str, int] = {
    EVIDENCE_VERIFIED_PRIMARY: 0,
    EVIDENCE_VERIFIED_MULTI: 1,
    EVIDENCE_SECONDARY: 2,
    EVIDENCE_MODEL_REASONING: 3,
    EVIDENCE_HUMAN_REQUIRED: 4,
}
EVIDENCE_LABEL: dict[str, str] = {
    EVIDENCE_VERIFIED_PRIMARY: "🟢 官方来源 / 指定数据库 / 原始页面实测",
    EVIDENCE_VERIFIED_MULTI: "🟢 两个高质量独立来源一致",
    EVIDENCE_SECONDARY: "🟠 旁证：第三方 / 聚合库 / Crossref / 搜索摘要",
    EVIDENCE_MODEL_REASONING: "🟡 模型知识 / 规则推理 / 排除法",
    EVIDENCE_HUMAN_REQUIRED: "🔴 必须人工：登录 / 验证码 / 桌面软件 / 无法访问",
}


def evidence_weaker_than(a: str, b: str) -> bool:
    """a 是否比 b 更弱（等级更低）。未知等级一律视为最弱，宁可保守。"""
    return EVIDENCE_RANK.get(a, 99) > EVIDENCE_RANK.get(b, 99)


def evidence_at_least_as_strong(a: str, b: str) -> bool:
    """a 是否至少和 b 一样强。用于「不得从旁证升级到官方」的断言。"""
    return EVIDENCE_RANK.get(a, 99) <= EVIDENCE_RANK.get(b, 99)


# --- 置信度档位（禁止 83.27% 这种虚假精度） ----------------------------------

CONFIDENCE_SCALE: tuple[int, ...] = (20, 25, 30, 35, 40, 50, 60, 70, 80, 90, 95)


def snap_confidence(value: float) -> int:
    """把任意 0-1 或 0-100 的估计吸附到允许档位。

    吸附方向是**向下取最近档位**：省赛容错更低，宁可低估不要高估。
    """
    if value is None:
        return 0
    number = float(value)
    if number <= 1.0:
        number *= 100.0
    number = max(0.0, min(100.0, number))
    floor = 0
    for step in CONFIDENCE_SCALE:
        if step <= number + 1e-9:
            floor = step
        else:
            break
    return floor


# --- TEAM_LIVE 决策阈值（个人赛与团队赛不得混用） -----------------------------

DECISION_THRESHOLD_TEAM = 0.20      # 团队：+4 / -1 → 盈亏平衡 1/5
DECISION_THRESHOLD_INDIVIDUAL = 1.0 / 3.0   # 个人：阈值 1/3

SCORE_TEAM = {"correct": 4, "wrong": -1, "skip": 0}


# --- stdlib-only YAML 子集读取器 ---------------------------------------------
#
# 支持：嵌套映射、标量序列（`- x`）、映射序列（`- k: v` + 缩进续行）、
# 行内 `[a, b]`、引号标量、` #` 行尾注释、空行与整行注释。
# 不支持（本项目配置文件刻意不使用）：多行折叠标量、锚点、标签、复杂键。
#
# 为什么不用 pyyaml：本机 .venv 未安装，且 AGENTS.md 要求优先标准库、
# 不新增项目依赖。旧系统 solve_question.parse_simple_yaml 只支持两层映射，
# 不足以表达省赛配置，因此这里给出一个可测试的完整实现。


class YamlSubsetError(ValueError):
    """配置文件不落在受支持的 YAML 子集内。"""


def _strip_comment(line: str) -> str:
    """去掉引号之外的 ` #` 行尾注释。"""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#" and index > 0 and line[index - 1] in " \t":
            return line[:index]
    return line


def _split_top_level(value: str, separator: str = ",") -> list[str]:
    """按分隔符切分，忽略引号与括号内部的同级分隔符。"""
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0
    for char in value:
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            buffer.append(char)
            continue
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(char)
    tail = "".join(buffer).strip()
    if tail or parts:
        parts.append(tail)
    return parts


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return value


def _scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value[0] in "\"'" and value[-1] == value[0] and len(value) >= 2:
        return _unquote(value)
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [_scalar(item) for item in _split_top_level(body)]
    if value.startswith("{") and value.endswith("}"):
        body = value[1:-1].strip()
        if not body:
            return {}
        result: dict[str, Any] = {}
        for item in _split_top_level(body):
            key, _, item_value = item.partition(":")
            result[_unquote(key.strip())] = _scalar(item_value)
        return result
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _significant_lines(text_value: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text_value.replace("\t", "    ").splitlines():
        stripped_comment = _strip_comment(raw)
        if not stripped_comment.strip():
            continue
        if stripped_comment.strip().startswith("#"):
            continue
        # `---` 文档分隔符按 YAML 语义忽略。
        if stripped_comment.strip() == "---":
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        lines.append((indent, stripped_comment.strip()))
    return lines


def _parse_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    line_indent, content = lines[index]
    if line_indent < indent:
        return {}, index
    if content.startswith("- "):
        return _parse_sequence(lines, index, indent)
    if content == "-":
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_sequence(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise YamlSubsetError(f"列表项缩进异常：{content!r}")
        if not (content == "-" or content.startswith("- ")):
            break
        tail = content[2:].strip() if content.startswith("- ") else ""
        index += 1
        if not tail:
            # `-` 后面换行：子块从下一行开始。
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                items.append(child)
            else:
                items.append(None)
            continue
        if ":" in tail and not tail.startswith(("\"", "'", "[", "{")):
            # 映射序列项：`- key: value` 后面可以跟同级缩进的续行键。
            item: dict[str, Any] = {}
            key, _, value = tail.partition(":")
            if value.strip() == "" and index < len(lines) and lines[index][0] > indent:
                # `- key:` 后接嵌套块（例如 patch 文件的 `- insert:` 列表）
                child, index = _parse_block(lines, index, lines[index][0])
                item[key.strip()] = child
            else:
                item[key.strip()] = _scalar(value)
            while index < len(lines):
                next_indent, next_content = lines[index]
                if next_indent <= indent:
                    break
                if next_content.startswith("- "):
                    break
                if ":" not in next_content:
                    raise YamlSubsetError(f"映射序列项出现非键值行：{next_content!r}")
                sub_key, _, sub_value = next_content.partition(":")
                index += 1
                if sub_value.strip() == "":
                    # 嵌套块的缩进必须取自下一行的真实缩进，不能猜 +1。
                    if index < len(lines) and lines[index][0] > next_indent:
                        child, index = _parse_block(lines, index, lines[index][0])
                        item[sub_key.strip()] = child
                    else:
                        item[sub_key.strip()] = None
                else:
                    item[sub_key.strip()] = _scalar(sub_value)
            items.append(item)
            continue
        items.append(_scalar(tail))
    return items, index


def _parse_mapping(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise YamlSubsetError(f"映射缩进异常：{content!r}")
        if content.startswith("- "):
            break
        if ":" not in content:
            raise YamlSubsetError(f"缺少冒号：{content!r}")
        key, _, value = content.partition(":")
        key = _unquote(key.strip())
        index += 1
        if value.strip() == "":
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                result[key] = child
            else:
                result[key] = None
            continue
        result[key] = _scalar(value)
    return result, index


def parse_yaml_subset(text_value: str) -> Any:
    """解析受支持的 YAML 子集。顶层可以是映射，也可以是序列（DSH patch 文件）。"""
    lines = _significant_lines(text_value)
    if not lines:
        return {}
    parsed, _ = _parse_block(lines, 0, lines[0][0])
    return parsed


def load_yaml(path: Path) -> dict[str, Any]:
    """优先 pyyaml；缺失时退回子集解析器。两者结果都不做隐式合并。"""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(raw)
        return loaded if isinstance(loaded, dict) else {}
    except ImportError:
        parsed = parse_yaml_subset(raw)
        return parsed if isinstance(parsed, dict) else {}


def load_patch_yaml(path: Path) -> list[dict[str, Any]]:
    """读取 DSH 的 profile patch 文件（顶层是数组）。

    每个元素形如 `{insert: [...]}` 或 `{id: ..., config: ...}`。
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(raw)
    except ImportError:
        loaded = parse_yaml_subset(raw)
    if not isinstance(loaded, list):
        raise ValueError(f"{path} 的顶层必须是数组（DSH patch 格式）")
    return [item for item in loaded if isinstance(item, dict)]


def patch_inserted_entries(path: Path) -> list[dict[str, Any]]:
    """取出 patch 文件里 insert 的新增条目。"""
    entries: list[dict[str, Any]] = []
    for patch in load_patch_yaml(path):
        inserted = patch.get("insert")
        if isinstance(inserted, list):
            entries.extend(item for item in inserted if isinstance(item, dict))
    return entries


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --- 高层读取接口 -------------------------------------------------------------
#
# 这些配置在单次路由里会被反复读取（逐模块、逐题）。不缓存时
# `load_module_nav()` 会为每道题重读 116KB JSON，纯路由耗时会被人为放大，
# PHASE 2 的耗时指标就不可信。因此加 lru_cache，并提供 clear_config_cache()
# 供测试在重新生成配置后失效缓存。


def _cached_json(path_str: str) -> dict[str, Any]:
    return load_json(Path(path_str))


def _cached_yaml(path_str: str) -> dict[str, Any]:
    return load_yaml(Path(path_str))


_cached_json = functools.lru_cache(maxsize=32)(_cached_json)
_cached_yaml = functools.lru_cache(maxsize=16)(_cached_yaml)


def clear_config_cache() -> None:
    """清空配置缓存。重新生成 config/*.json 后调用。"""
    _cached_json.cache_clear()
    _cached_yaml.cache_clear()


def load_compliance_policy() -> dict[str, Any]:
    if not COMPLIANCE_POLICY_PATH.exists():
        raise FileNotFoundError(
            f"合规策略缺失：{COMPLIANCE_POLICY_PATH}。P0 规则不存在时禁止进入任何运行模式。"
        )
    return _cached_yaml(str(COMPLIANCE_POLICY_PATH))


def load_provincial_config() -> dict[str, Any]:
    if not PROVINCIAL_CONFIG_PATH.exists():
        raise FileNotFoundError(f"省赛配置缺失：{PROVINCIAL_CONFIG_PATH}")
    return _cached_yaml(str(PROVINCIAL_CONFIG_PATH))


def load_task_types() -> dict[str, Any]:
    return _cached_json(str(TASK_TYPES_PATH))


def load_platform_capabilities() -> dict[str, Any]:
    return _cached_json(str(PLATFORM_CAPABILITIES_PATH))


def load_entry_status() -> dict[str, Any]:
    return _cached_json(str(PLATFORM_ENTRY_STATUS_PATH))


def load_module_nav() -> dict[str, Any]:
    return _cached_json(str(MODULE_NAV_JSON_PATH))


def resolve_npm_tool(name: str) -> str:
    """把 npm / npx / pnpm 解析成 subprocess 能直接执行的形式。

    Windows 上 `shutil.which("npx")` 会优先返回 `npx.ps1`，而 Python 的
    subprocess 不能直接执行 PowerShell 脚本（WinError 2）。因此显式优先
    `.cmd` / `.exe` / `.bat`。
    """
    import shutil

    found = shutil.which(name)
    if found:
        candidate_base = str(Path(found).with_suffix(""))
        for suffix in (".cmd", ".exe", ".bat"):
            candidate = Path(candidate_base + suffix)
            if candidate.exists():
                return str(candidate)
        if Path(found).suffix.lower() in {".cmd", ".exe", ".bat"}:
            return found
    for suffix in (".cmd", ".exe", ".bat"):
        candidate = shutil.which(name + suffix)
        if candidate:
            return candidate
    return found or name


def run_captured(
    cmd: list[str], timeout: float = 90.0, cwd: str | None = None
) -> tuple[int, str]:
    """运行外部命令并捕获输出，**用文件而不是管道**。

    为什么不用 subprocess.run(capture_output=True)：
    agent-browser 会派生一个常驻 daemon，daemon 继承 stdout/stderr 的**管道句柄**。
    即使直接子进程已经退出，管道也不会 EOF，`communicate()` 会一直阻塞到超时。

    为什么文件放在项目内并且**不删除**：
    改用文件后 daemon 仍然持有该文件的句柄，临时目录的清理会抛
    PermissionError(WinError 32)。因此写到 data/tmp/exec 下、每次截断复用，
    由 cleanup_exec_dir() 按时间清理过期文件。
    """
    import subprocess

    EXEC_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{os.getpid()}-{next(_EXEC_COUNTER)}"
    out_path = EXEC_DIR / f"{stamp}.out"
    err_path = EXEC_DIR / f"{stamp}.err"
    try:
        with out_path.open("wb") as out_handle, err_path.open("wb") as err_handle:
            completed = subprocess.run(
                cmd,
                stdout=out_handle,
                stderr=err_handle,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                cwd=cwd,
            )
            code = completed.returncode
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except OSError as error:
        return 127, str(error)
    combined = (
        _read_text(out_path)
        + _read_text(err_path)
    )
    return code, combined.strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def cleanup_exec_dir(max_age_seconds: float = 86400.0) -> int:
    """删掉 data/tmp/exec 下的过期捕获文件。被占用的文件跳过，不抛异常。"""
    import time

    if not EXEC_DIR.exists():
        return 0
    removed = 0
    now = time.time()
    for path in EXEC_DIR.glob("*"):
        try:
            if now - path.stat().st_mtime < max_age_seconds:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed

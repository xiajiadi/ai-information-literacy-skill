from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DB_PATH, log_activity, now_iso
from db_schema import connect_db, ensure_schema


PLATFORMS = [
    ("competition_training", "大赛训练入口", "https://csc.xxsuyang.com/training", "required_or_redirected", "参赛指南 → 学生报名入口；访问受限时停止", "仅检查公开跳转，不自动登录", "统一登录或验证码步骤转人工。"),
    ("public_knowledge", "公开知识模块", "https://jsgateway.zhixinst.com/SCC/Website/GetKnowledgeList?kind=csc2025", "not_required_for_current_snapshot", "读取模块标题、具体要求、学习指导、样题、答案和解析", "公开内容可用 HTTP 或浏览器读取", "当前快照已保存到 data/raw。"),
    ("cnki", "中国知网", "https://www.cnki.net", "question_and_access_dependent", "首页或高级检索 → 文献类型 → 检索点 → 筛选 → 结果分析或全文", "公开页面可辅助；登录、验证码和校园认证转人工", "功能和开放权限可能调整。"),
    ("wanfang", "万方数据", "https://www.wanfangdata.com.cn", "question_and_access_dependent", "高级检索 → 文献类型 → 字段和年份 → 结果筛选或分析", "受访问权限、验证码和动态页面影响", "按题目指定平台核验。"),
    ("pubmed", "PubMed", "https://pubmed.ncbi.nlm.nih.gov", "search_public_subscription_account", "检索结果 → Create RSS 或 Create alert", "公开检索可辅助；订阅动作需人工", "订阅不是题库答案本身。"),
    ("github", "GitHub", "https://github.com", "usually_not_required", "项目 → README → License → Release → 更新时间和作者", "公开项目可浏览器辅助", "保存项目版本和许可证。"),
    ("modelscope", "魔搭社区 ModelScope", "https://modelscope.cn", "question_and_download_dependent", "模型或数据集 → README/模型卡 → 字段、许可证和下载入口", "公开页面可辅助；账号权限单独记录", "不把下载成功当成模型有效性证明。"),
    ("national_statistics", "国家统计局", "https://www.stats.gov.cn", "usually_not_required", "统计数据 → 数据查询 → 指标、地区和年份", "公开查询可辅助", "保存统计口径和访问日期。"),
    ("cnipa", "国家知识产权局", "https://www.cnipa.gov.cn", "page_dependent", "专利、商标或地理标志查询 → 号段或名称 → 原文详情", "动态或受限页面转人工", "不得绕过验证。"),
    ("standard_open", "国家标准全文公开系统", "https://openstd.samr.gov.cn", "usually_not_required", "标准号或名称 → 标准正文 → 页码、起草单位和实施信息", "公开页面可辅助", "标准版本和日期要一起记录。"),
    ("arxiv", "arXiv", "https://arxiv.org", "usually_not_required", "identifier 或检索 → Abstract → PDF/HTML 全文", "公开页面可辅助", "区分预印本与正式出版版本。"),
    ("nppa", "国家新闻出版署期刊查询", "https://www.nppa.gov.cn/bsfw/cyjghcpcx", "usually_not_required", "期刊名称或刊号 → 主办和出版信息", "公开页面可辅助", "核对期刊真伪时保存页面字段。"),
]


def seed_platforms(conn) -> None:
    stamp = now_iso()
    conn.executemany(
        """
        INSERT INTO platforms(
            platform_id, platform_name, official_url, login_required,
            route, allowed_automation, notes, updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(platform_id) DO UPDATE SET
            platform_name=excluded.platform_name,
            official_url=excluded.official_url,
            login_required=excluded.login_required,
            route=excluded.route,
            allowed_automation=excluded.allowed_automation,
            notes=excluded.notes,
            updated_at=excluded.updated_at
        """,
        [(*row, stamp) for row in PLATFORMS],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或升级本地题库 SQLite 数据库。")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite 文件路径")
    args = parser.parse_args()

    conn = connect_db(args.db)
    ensure_schema(conn)
    seed_platforms(conn)
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("schema_version", "1", now_iso()),
    )
    conn.commit()
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    log_activity("db_initialized", {"db": str(Path(args.db).resolve()), "tables": tables})
    print(json.dumps({"status": "initialized", "db": str(Path(args.db).resolve()), "tables": tables}, ensure_ascii=False))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Daily A-share market brief with multi-source, impact-ranked news."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from common import OUTPUT, fmt_money, now_cn, safe_ak, tencent_quotes
from docx_export import save_to_desktop
from news_sources import collect as collect_news

try:
    from astock_data import board_flow_top, individual_flow_rank
except Exception:
    board_flow_top = None
    individual_flow_rank = None

try:
    from news_radar import build_radar, render_radar
except Exception:
    build_radar = None
    render_radar = None


def global_snapshot() -> list[dict]:
    codes = [
        "usDJI",
        "usIXIC",
        "usINX",
        "hkHSI",
        "jpN225",
        "sh000001",
        "sz399001",
        "hf_CL",
        "hf_GC",
        "fx_susdcny",
    ]
    q = tencent_quotes(codes)
    labels = {
        "DJI": "道琼斯",
        "IXIC": "纳斯达克",
        "INX": "标普500",
        "HSI": "恒生指数",
        "N225": "日经225",
        "000001": "上证指数",
        "399001": "深证成指",
        "CL": "WTI原油",
        "GC": "COMEX黄金",
        "USDCNY": "美元/人民币",
    }
    out = []
    for k, v in q.items():
        out.append(
            {
                "code": k,
                "name": v.get("name") or labels.get(k, k),
                "price": v.get("price"),
                "pct": v.get("pct"),
            }
        )
    return out


def _pick(df, names, idx=None):
    for n in names:
        for c in df.columns:
            if str(c).strip() == n:
                return c
    if idx is not None and len(df.columns) > idx:
        return df.columns[idx]
    return None


def _board_rows(rows) -> list[dict]:
    return [
        {
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "net": fmt_money(r.get("main_net", 0)),
            "pct": f"{float(r.get('change_pct', 0) or 0):+.2f}%",
            "leader": r.get("leader", ""),
        }
        for r in rows
    ]


def _flow_rows(rows) -> list[dict]:
    return [
        {
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "net": fmt_money(r.get("main_net", 0)),
            "pct": f"{float(r.get('change_pct', 0) or 0):+.2f}%",
        }
        for r in rows
    ]


def fund_flow_snapshot() -> dict:
    result = {
        "today_top_in": [],
        "today_top_out": [],
        "three_day_top_in": [],
        "board_today_in": [],
        "board_today_out": [],
        "board_5d_in": [],
    }
    if board_flow_top:
        try:
            data = board_flow_top("industry", "today", 8)
            result["board_today_in"] = _board_rows(data.get("in", []))
            result["board_today_out"] = _board_rows(data.get("out", []))[:5]
        except Exception:
            pass
        try:
            data = board_flow_top("industry", "5d", 8)
            result["board_5d_in"] = _board_rows(data.get("in", []))
        except Exception:
            pass

    if individual_flow_rank:
        try:
            result["today_top_in"] = _flow_rows(individual_flow_rank("today", 8, "in"))
            result["today_top_out"] = _flow_rows(
                individual_flow_rank("today", 5, "out")
            )
        except Exception:
            pass
        try:
            result["three_day_top_in"] = _flow_rows(individual_flow_rank("3d", 8, "in"))
        except Exception:
            pass

    if (
        result["today_top_in"]
        and result["today_top_out"]
        and result["three_day_top_in"]
    ):
        return result

    ak = __import__("akshare")
    today = safe_ak(
        "stock_fund_flow_individual",
        lambda: ak.stock_fund_flow_individual(symbol="即时"),
    )
    if today is not None and not today.empty:
        code_col = _pick(today, ["股票代码", "代码"], 1)
        name_col = _pick(today, ["股票简称", "名称"], 2)
        net_col = _pick(today, ["净额", "资金净流入"], 8)
        pct_col = _pick(today, ["涨跌幅"], 4)
        df = today.copy()
        df["_net"] = df[net_col].map(__import__("common").parse_cn_money)
        df = df.sort_values("_net", ascending=False)
        for _, r in df.head(8).iterrows():
            result["today_top_in"].append(
                {
                    "code": str(r[code_col]),
                    "name": str(r[name_col]),
                    "net": fmt_money(r["_net"]),
                    "pct": str(r[pct_col]) if pct_col else "",
                }
            )
        for _, r in df.tail(5).iloc[::-1].iterrows():
            result["today_top_out"].append(
                {
                    "code": str(r[code_col]),
                    "name": str(r[name_col]),
                    "net": fmt_money(r["_net"]),
                    "pct": str(r[pct_col]) if pct_col else "",
                }
            )
    three = safe_ak(
        "stock_fund_flow_individual",
        lambda: ak.stock_fund_flow_individual(symbol="3日排行"),
    )
    if three is not None and not three.empty:
        code_col = _pick(three, ["股票代码", "代码"], 1)
        name_col = _pick(three, ["股票简称", "名称"], 2)
        net_col = _pick(three, ["资金净流入", "净额"], 6)
        pct_col = _pick(three, ["阶段涨跌幅"], 4)
        df = three.copy()
        df["_net"] = df[net_col].map(__import__("common").parse_cn_money)
        for _, r in df.sort_values("_net", ascending=False).head(8).iterrows():
            result["three_day_top_in"].append(
                {
                    "code": str(r[code_col]),
                    "name": str(r[name_col]),
                    "net": fmt_money(r["_net"]),
                    "pct": str(r[pct_col]) if pct_col else "",
                }
            )
    return result


def render(news, markets, flows, radar=None, as_of: datetime | None = None) -> str:
    as_of = as_of or datetime.now()
    lines = [
        f"# A股市场情报简报｜{date.today().isoformat()}",
        f"\n> 截止时间：{as_of.strftime('%Y-%m-%d %H:%M')}；此后更新的资讯不纳入本报告。",
        f"> 生成时间：{now_cn()}；公开数据存在延迟，仅供研究参考，不构成投资建议。\n",
        "> 资讯来源：财联社、生意社、韭研公社、巨潮资讯、开盘啦、东方财富。",
        "> 影响级别：S=系统性/宏观；A=行业/板块；B=个股/公司；C=一般资讯。级别为关键词与来源权重的规则排序，不代表价格方向。\n",
        "## 一、今日核心事件（按可能影响市场波动的级别排序）",
    ]
    counts = Counter(x["source"] for x in news)
    lines.insert(
        4, "> 来源覆盖：" + "；".join(f"{k} {v}条" for k, v in counts.most_common())
    )
    lines.insert(5, "")
    groups = {
        "S": "S级｜系统性/宏观",
        "A": "A级｜行业/板块",
        "B": "B级｜个股/公司",
        "C": "C级｜一般资讯",
    }
    for level, label in groups.items():
        items = [x for x in news if x.get("impact_level") == level][:8]
        if not items:
            continue
        lines.append(f"\n### {label}")
        for x in items:
            tags = "、".join(x.get("impact_tags", [])[:4]) or "—"
            lines.append(f"- **{x['title']}**（{x['source']} {x['time']}）")
            extra = f"影响：{level}（{x.get('impact_score', 0)}分）；关键词倾向：{x.get('bias', '待观察')}；标签：{tags}"
            lines.append(f"  - {extra}")
            if x.get("summary"):
                lines.append(f"  - {x['summary'][:180]}")
    if not any(x.get("impact_level") in groups for x in news):
        lines.append("- 今日未抓取到有效资讯。")
    if radar and render_radar:
        lines += render_radar(radar, 8)
    else:
        lines += [
            "\n## 二、消息面雷达（实时信息差）",
            "",
            "- 未取得（a-stock-data 新闻接口不可用）。",
        ]

    lines += [
        "\n## 三、海外市场与大宗",
        "",
        "| 资产 | 最新 | 涨跌幅 |",
        "|---|---:|---:|",
    ]
    for x in markets:
        pct = "" if pd.isna(x["pct"]) else f"{x['pct']:+.2f}%"
        price = "—" if pd.isna(x["price"]) else f"{x['price']:.2f}"
        lines.append(f"| {x['name']} | {price} | {pct} |")
    lines += ["\n## 四、资金流快照", ""]

    lines += ["**行业板块主力净流入前 8（今日）**", ""]
    if flows.get("board_today_in"):
        for x in flows["board_today_in"]:
            leader = f"；领涨 {x['leader']}" if x.get("leader") else ""
            lines.append(
                f"- {x['name']}（{x['code']}）：{x['net']}（{x['pct']}{leader}）"
            )
    else:
        lines.append("- 未取得（a-stock-data 板块资金流不可用）")

    lines += ["", "**行业板块主力净流出前 5（今日）**", ""]
    if flows.get("board_today_out"):
        for x in flows["board_today_out"]:
            lines.append(f"- {x['name']}（{x['code']}）：{x['net']}（{x['pct']}）")
    else:
        lines.append("- 未取得")

    lines += ["", "**行业板块主力净流入前 8（近 5 日）**", ""]
    if flows.get("board_5d_in"):
        for x in flows["board_5d_in"]:
            leader = f"；领涨 {x['leader']}" if x.get("leader") else ""
            lines.append(
                f"- {x['name']}（{x['code']}）：{x['net']}（{x['pct']}{leader}）"
            )
    else:
        lines.append("- 未取得")

    lines += ["", "**个股主力净流入前 8（今日）**", ""]
    if flows.get("today_top_in"):
        for x in flows["today_top_in"]:
            lines.append(f"- {x['code']} {x['name']}：{x['net']}（{x['pct']}）")
    else:
        lines.append("- 未取得（a-stock-data / AKShare 均不可用）")

    lines += ["", "**个股主力净流出前 5（今日）**", ""]
    if flows.get("today_top_out"):
        for x in flows["today_top_out"]:
            lines.append(f"- {x['code']} {x['name']}：{x['net']}（{x['pct']}）")
    else:
        lines.append("- 未取得")

    lines += ["", "**近 3 日个股主力净流入前 8**", ""]
    if flows.get("three_day_top_in"):
        for x in flows["three_day_top_in"]:
            lines.append(f"- {x['code']} {x['name']}：{x['net']}（{x['pct']}）")
    else:
        lines.append("- 未取得")
    lines += [
        "\n## 五、对A股的可能影响（模型结合事件与板块补充）",
        "- S级事件：优先判断对指数、汇率、外资风险偏好的影响。",
        "- A级事件：映射到行业/板块，区分“主题催化”与“业绩兑现”。",
        "- B级事件：落到个股，复核公告原文、减持/解禁、业绩与估值。",
        "- 资讯级别不是买卖信号；同一事件可能已被定价。",
        "\n## 六、风险提示",
        "- 公开数据存在延迟、缺失或口径差异；新闻只代表信息，不代表价格方向。",
        "- 资金流为统计口径，不能等同于机构真实持仓；持仓数据按季度披露，存在滞后。",
        "- 北向每日持股数据已停止/滞后，不应把历史数据当作今日外资动作。",
        "- 本报告不构成投资建议，不承诺收益。",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--as-of", default=None, help="截止时间，如 2026-10-30 01:20")
    args = ap.parse_args()
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now()
    news = collect_news(as_of)
    markets = global_snapshot()
    flows = fund_flow_snapshot()
    radar = build_radar(limit=50) if build_radar else None
    payload = {
        "generated_at": now_cn(),
        "news": news,
        "markets": markets,
        "flows": flows,
        "radar": radar,
    }
    out = args.out or (OUTPUT / f"daily_brief_{date.today().isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(news, markets, flows, radar, as_of), encoding="utf-8")
    if args.json:
        out.with_suffix(".json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    docx = save_to_desktop(out, f"A股市场情报简报_{date.today().isoformat()}.docx")
    print(out)
    print(docx)


if __name__ == "__main__":
    main()

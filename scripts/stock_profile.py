# -*- coding: utf-8 -*-
"""Single-stock profile: quote, 3-day fund flow, northbound, holders, news."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd

from common import (
    CACHE,
    OUTPUT,
    bare_code,
    fmt_money,
    latest_quarters,
    normalize_code,
    now_cn,
    parse_cn_money,
    safe_ak,
    tencent_quotes,
)

try:
    from astock_data import fund_flow_days, fund_flow_today, quote as astock_quote
except Exception:
    fund_flow_days = fund_flow_today = astock_quote = None


def _ak():
    import akshare as ak

    return ak


def _pick(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def get_quote(code: str) -> dict:
    q = tencent_quotes([code]).get(bare_code(code), {})
    if astock_quote and q:
        try:
            extra = astock_quote([bare_code(code)]).get(bare_code(code), {})
            for key in (
                "pe_ttm",
                "pe_static",
                "pb",
                "mcap_yi",
                "float_mcap_yi",
                "turnover_pct",
                "vol_ratio",
                "limit_up",
                "limit_down",
                "is_stale",
            ):
                if extra.get(key) is not None:
                    q[key] = extra[key]
        except Exception:
            pass
    return q or {}


def get_fund_flow(code: str) -> dict:
    bare = bare_code(code)
    out = {"today": None, "three_day": None}

    if fund_flow_today:
        try:
            t = fund_flow_today(bare)
            if t:
                q = tencent_quotes([code]).get(bare, {})
                pct = q.get("pct")
                turn = q.get("turnover")
                out["today"] = {
                    "net": t["net_fmt"],
                    "pct": f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "—",
                    "turnover": f"{turn:.2f}%"
                    if isinstance(turn, (int, float))
                    else "—",
                    "source": t.get("source", "eastmoney-push2"),
                }
        except Exception:
            pass

    if fund_flow_days:
        try:
            d = fund_flow_days(bare, 3)
            if d:
                out["three_day"] = {
                    "net": d["net_fmt"],
                    "pct": "—",
                    "turnover": "—",
                    "source": d.get("source", "eastmoney-push2his"),
                }
        except Exception:
            pass

    if not out["today"] or not out["three_day"]:
        ak = _ak()

    if not out["today"]:
        today = safe_ak(
            "stock_fund_flow_individual",
            lambda: ak.stock_fund_flow_individual(symbol="即时"),
        )
        if today is not None and not today.empty:
            c = _pick(today, ["股票代码", "代码"]) or today.columns[1]
            row = today[today[c].astype(str).str.zfill(6) == bare]
            if not row.empty:
                r = row.iloc[0]
                out["today"] = {
                    "net": fmt_money(parse_cn_money(r.get("净额", r.iloc[8]))),
                    "pct": str(r.get("涨跌幅", r.iloc[4])),
                    "turnover": str(r.get("换手率", r.iloc[5])),
                    "source": "akshare",
                }

    if not out["three_day"]:
        three = safe_ak(
            "stock_fund_flow_individual",
            lambda: ak.stock_fund_flow_individual(symbol="3日排行"),
        )
        if three is not None and not three.empty:
            c = _pick(three, ["股票代码", "代码"]) or three.columns[1]
            row = three[three[c].astype(str).str.zfill(6) == bare]
            if not row.empty:
                r = row.iloc[0]
                out["three_day"] = {
                    "net": fmt_money(parse_cn_money(r.get("资金净流入", r.iloc[6]))),
                    "pct": str(r.get("阶段涨跌幅", r.iloc[4])),
                    "turnover": str(r.get("阶段换手率", r.iloc[5])),
                    "source": "akshare",
                }
    return out


def get_northbound(code: str) -> dict | None:
    ak = _ak()
    df = safe_ak(
        "stock_hsgt_individual_em",
        lambda: ak.stock_hsgt_individual_em(symbol=bare_code(code)),
    )
    if df is None or df.empty:
        return None
    df = df.copy()
    date_col = _pick(df, ["持股日期", "日期"])
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values(date_col)
    r = df.iloc[-1]
    latest_date = str(r.get(date_col, ""))[:10]

    def num(col):
        return pd.to_numeric(r.get(col), errors="coerce")

    hold = num("持股数量")
    ratio = num("持股数量占A股百分比")
    change_5d = None
    if len(df) >= 6 and "持股数量" in df.columns:
        prev = pd.to_numeric(df.iloc[-6].get("持股数量"), errors="coerce")
        if pd.notna(prev) and prev:
            change_5d = (hold - prev) / prev * 100
    stale = False
    try:
        stale = (pd.Timestamp.today().normalize() - pd.Timestamp(latest_date)).days > 30
    except Exception:
        pass
    return {
        "date": latest_date,
        "hold_shares": hold,
        "hold_value": num("持股市值"),
        "ratio": ratio,
        "change_5d_pct": change_5d,
        "stale": stale,
    }


def get_top10(code: str) -> tuple[list[dict], str | None]:
    ak = _ak()
    prefix = normalize_code(code)
    for q in latest_quarters(8):
        df = safe_ak(
            "stock_gdfx_free_top_10_em",
            lambda q=q: ak.stock_gdfx_free_top_10_em(symbol=prefix, date=q),
        )
        if df is not None and not df.empty:
            out = []
            for _, r in df.iterrows():
                out.append(
                    {
                        "name": str(r.get("股东名称", "")),
                        "nature": str(r.get("股东性质", "")),
                        "shares": str(r.get("持股数", "")),
                        "ratio": str(r.get("占流通股本持股比例", "")),
                        "change": str(r.get("增减", "")),
                    }
                )
            return out, q
    # Fallback: older, more stable endpoint (latest reported period only)
    df = safe_ak(
        "stock_circulate_stock_holder",
        lambda: ak.stock_circulate_stock_holder(symbol=bare_code(code)),
    )
    if df is not None and not df.empty:
        dcol = _pick(df, ["截止日期"])
        latest = None
        if dcol:
            df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
            latest = df[dcol].max()
            df = df[df[dcol] == latest]
        out = []
        for _, r in df.head(10).iterrows():
            out.append(
                {
                    "name": str(r.get("股东名称", "")),
                    "nature": str(r.get("股本性质", "")),
                    "shares": str(r.get("持股数量", "")),
                    "ratio": str(r.get("占流通股比例", "")),
                    "change": "—",
                }
            )
        return out, str(latest)[:10] if latest is not None else None
    return [], None


def _team_table(label: str, cache_hours: float = 12):
    """社保/QFII 协同持股全表，带本地缓存（接口很慢，一次约 1 分钟）。"""
    path = CACHE / f"team_{label}.pkl"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < cache_hours * 3600:
            return pd.read_pickle(path)
    except Exception:
        pass
    ak = _ak()
    df = safe_ak(
        "stock_gdfx_free_holding_teamwork_em",
        lambda: ak.stock_gdfx_free_holding_teamwork_em(symbol=label),
    )
    if df is not None and not df.empty:
        try:
            df.to_pickle(path)
        except Exception:
            pass
    return df


def get_team_holdings(code: str, cache_hours: float = 12) -> dict:
    """匹配社保/QFII 协同持股列表。

    该接口返回的是“每个机构产品 + 其前十大重仓股”的列表，持股明细写成
    ``代码|名称|报告期`` 逐条拼接，因此只能按代码扫描。单只产品只披露前十大，
    未匹配到不代表未持有。
    """
    bare = bare_code(code)
    out: dict[str, list[str]] = {}
    for label in ("社保", "QFII"):
        best: dict[str, str] = {}
        df = _team_table(label, cache_hours=cache_hours)
        if df is not None and not df.empty:
            name_col = _pick(df, ["股东名称"])
            detail_col = _pick(df, ["持股详情", "个股详情"]) or df.columns[-1]
            if name_col:
                for _, r in df.iterrows():
                    fund = str(r.get(name_col, "")).strip()
                    detail = str(r.get(detail_col, ""))
                    if not fund or bare not in detail:
                        continue
                    for item in detail.split(","):
                        parts = item.split("|")
                        if len(parts) >= 3 and parts[0].strip() == bare:
                            period = parts[2].strip()
                            if period > best.get(fund, ""):
                                best[fund] = period
        ranked = sorted(best.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        out[label] = [f"{fund}（{period}）" for fund, period in ranked]
    return out


def get_news(code: str) -> list[dict]:
    ak = _ak()
    df = safe_ak("stock_news_em", lambda: ak.stock_news_em(symbol=bare_code(code)))
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.head(8).iterrows():
        out.append(
            {
                "title": str(r.get("新闻标题", "")),
                "time": str(r.get("发布时间", "")),
                "source": str(r.get("文章来源", "")),
                "url": str(r.get("新闻链接", "")),
            }
        )
    return out


def render(
    code: str,
    quote: dict,
    flow: dict,
    north: dict | None,
    top10: list,
    q: str | None,
    team: dict | None,
    news: list,
) -> str:
    name = quote.get("name") or bare_code(code)
    lines = [
        f"# 个股情报｜{name}（{bare_code(code)}）",
        f"\n> 数据时间：{now_cn()}；行情为公开接口快照，资金流为统计口径，持仓数据按季度披露。仅供研究参考，不构成投资建议。\n",
        "## 一、实时行情",
        f"- 最新价：{quote.get('price', '—')}；涨跌幅：{quote.get('pct', '—')}%",
        f"- 今开/最高/最低：{quote.get('open', '—')} / {quote.get('high', '—')} / {quote.get('low', '—')}",
        f"- 成交额：{fmt_money(quote.get('amount'))}；换手率：{quote.get('turnover', '—')}%",
        "\n## 二、近 3 日资金流",
    ]
    if quote.get("pe_ttm") is not None or quote.get("pb") is not None:
        lines.insert(
            6,
            f"- PE(TTM)：{quote.get('pe_ttm', '—')}；PB：{quote.get('pb', '—')}；总市值：{quote.get('mcap_yi', '—')}亿",
        )
    if flow.get("today"):
        lines.append(
            f"- 今日主力净额：{flow['today']['net']}；涨跌幅：{flow['today']['pct']}；换手率：{flow['today']['turnover']}"
        )
    if flow.get("three_day"):
        lines.append(
            f"- 近 3 日主力净流入：{flow['three_day']['net']}；阶段涨跌幅：{flow['three_day']['pct']}；阶段换手率：{flow['three_day']['turnover']}"
        )
    if not flow.get("today") and not flow.get("three_day"):
        lines.append("- 资金流接口暂不可用。")
    lines += ["\n## 三、外资/北向持仓"]
    if north:
        chg = (
            "—" if north["change_5d_pct"] is None else f"{north['change_5d_pct']:+.2f}%"
        )
        lines.append(
            f"- 最新披露日：{north['date']}；持股数量：{north['hold_shares']:.0f}；持股市值：{fmt_money(north['hold_value'])}；占A股比例：{north['ratio']:.2f}%"
        )
        lines.append(f"- 近 5 个披露日持股变化：{chg}")
        if north.get("stale"):
            lines.append(
                "- 注意：北向每日持股数据已停止/明显滞后；请以十大流通股东中的“香港中央结算有限公司”及季度数据为准。"
            )
    else:
        lines.append("- 未取得北向持股数据；可能为非标的、接口限制或数据延迟。")
    lines += [f"\n## 四、前十大流通股东（{q or '最新季度'}）"]
    if top10:
        for x in top10:
            lines.append(
                f"- {x['name']}（{x['nature']}）：持股 {x['shares']}，占流通股 {x['ratio']}%，变动 {x['change']}"
            )
    else:
        lines.append("- 未取得前十大流通股东数据。")
    lines.append("\n## 五、社保/QFII 持仓线索")
    if team:
        for label in ("社保", "QFII"):
            if team.get(label):
                items = team[label]
                shown = "；".join(items[:8])
                if len(items) > 8:
                    shown += f" 等 {len(items)} 只"
                lines.append(f"- {label}：{shown}")
            else:
                lines.append(
                    f"- {label}：未在最新协同持股列表中匹配到（该列表只含各机构前十大持仓，未匹配不等于未持有）。"
                )
        lines.append("- 口径提示：季度披露、按机构产品列示，不能当作近期增减持动作。")
    else:
        lines.append(
            "- 未启用深度扫描；加 `--deep` 可扫描社保/QFII 协同持股列表（较慢）。"
        )
    lines += ["\n## 六、近期新闻"]
    if news:
        for x in news:
            lines.append(f"- {x['title']}（{x['source']} {x['time']}）")
    else:
        lines.append("- 暂无新闻数据。")
    lines += [
        "\n## 七、分析框架（供模型补充）",
        "- 机构持仓：区分“季度静态持仓”与“近期资金流”，不要把北向/社保季度数据当作实时动作。",
        "- 资金流：看 3 日是否持续、是否与价格/成交背离，避免单日脉冲。",
        "- 风险：关注解禁、减持、业绩预告、监管问询、高位放量和板块退潮。",
        "\n> 数据限制：北向持股与十大流通股东为披露口径，存在滞后；资金流为算法统计，不等于真实机构买卖。",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument(
        "--deep",
        action="store_true",
        help="scan social security/QFII teamwork lists (slow)",
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    code = normalize_code(args.code)
    quote = get_quote(code)
    flow = get_fund_flow(code)
    north = get_northbound(code)
    top10, q = get_top10(code)
    team = get_team_holdings(code) if args.deep else None
    news = get_news(code)
    out = args.out or (
        OUTPUT / f"stock_{bare_code(code)}_{date.today().isoformat()}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render(code, quote, flow, north, top10, q, team, news), encoding="utf-8"
    )
    if args.json:
        payload = {
            "code": bare_code(code),
            "quote": quote,
            "flow": flow,
            "northbound": north,
            "top10": top10,
            "quarter": q,
            "team": team,
            "news": news,
        }
        out.with_suffix(".json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    print(out)


if __name__ == "__main__":
    main()

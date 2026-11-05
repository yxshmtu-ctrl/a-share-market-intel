# -*- coding: utf-8 -*-
"""A-share screening for a 1-2 week swing strategy.

Universe: main board + ChiNext (exclude STAR/BSE).
Entry: volume expansion, 3-day fund inflow, foreign/qualified institutional holding.
Risk: 15% stop-loss reference; exclude banks and real estate.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from common import (
    CACHE,
    OUTPUT,
    fmt_money,
    parse_cn_money,
    read_cache,
    safe_ak,
    tencent_kline,
    tencent_quotes,
)
from docx_export import save_to_desktop

try:
    from astock_data import individual_flow_rank
except Exception:
    individual_flow_rank = None

DEFAULT = {
    "strategy": {
        "include_prefixes": ["60", "000", "001", "002", "003", "300", "301"],
        "exclude_prefixes": ["688", "8", "4", "9"],
        "min_price": 2.0,
        "max_price": 500.0,
        "min_amount": 1e8,
        "min_pct": -5.0,
        "max_pct": 9.5,
        "exclude_st": True,
        "exclude_bank": True,
        "exclude_real_estate": True,
        "min_vol_ratio": 1.5,
        "min_3d_net": 0,
        "min_today_net": 0,
        "max_ret20": 0.35,
        "candidate_pool": 150,
        "precheck_limit": 30,
        "foreign_check_limit": 12,
        "top_n": 10,
        "min_score": 55,
        "require_foreign": True,
        "stop_loss": 0.15,
    }
}

FOREIGN_KW = (
    "香港中央结算",
    "QFII",
    "境外",
    "高盛国际",
    "摩根士丹利",
    "摩根大通",
    "瑞银",
    "巴克莱",
    "花旗",
)


def load_config(path: Path | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT))
    if path and path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg["strategy"].update(user.get("strategy", {}))
    return cfg


def _pick(df, names, idx=None):
    for n in names:
        for c in df.columns:
            if str(c).strip() == n:
                return c
    if idx is not None and len(df.columns) > idx:
        return df.columns[idx]
    return None


def flow_tables() -> pd.DataFrame:
    if individual_flow_rank:
        try:
            today_rows = individual_flow_rank("today", 300, "in")
            three_rows = individual_flow_rank("3d", 300, "in")
            if today_rows:
                t = pd.DataFrame(today_rows)
                t["code"] = t["code"].astype(str).str.zfill(6)
                t["name"] = t["name"].astype(str)
                t["pct"] = pd.to_numeric(t.get("change_pct"), errors="coerce")
                t["net_today"] = pd.to_numeric(t.get("main_net"), errors="coerce")
                cols = ["code", "name", "pct", "net_today"]
                if three_rows:
                    th = pd.DataFrame(three_rows)
                    th["code"] = th["code"].astype(str).str.zfill(6)
                    th = th[["code", "main_net", "change_pct"]].rename(
                        columns={"main_net": "net_3d", "change_pct": "pct_3d"}
                    )
                    t = t.merge(th, on="code", how="left")
                else:
                    t["net_3d"] = 0.0
                    t["pct_3d"] = float("nan")
                cols += ["net_3d", "pct_3d"]
                t = t[cols].drop_duplicates("code")
                try:
                    t.to_csv(CACHE / "flow_tables.csv", index=False, encoding="utf-8-sig")
                except Exception:
                    pass
                return t
        except Exception:
            pass

    ak = __import__("akshare")
    today = safe_ak(
        "stock_fund_flow_individual",
        lambda: ak.stock_fund_flow_individual(symbol="即时"),
    )
    three = safe_ak(
        "stock_fund_flow_individual",
        lambda: ak.stock_fund_flow_individual(symbol="3日排行"),
    )
    cache_path = CACHE / "flow_tables.csv"
    if today is None or today.empty:
        if cache_path.exists():
            print("[warn] 资金流接口不可用，使用上次缓存；请在报告中注明截止时间。")
            return pd.read_csv(cache_path)
        return pd.DataFrame()
    t = today.copy()
    t["code"] = t[_pick(t, ["股票代码", "代码"], 1)].astype(str).str.zfill(6)
    t["name"] = t[_pick(t, ["股票简称", "名称"], 2)].astype(str)
    t["pct"] = pd.to_numeric(
        t[_pick(t, ["涨跌幅"], 4)].astype(str).str.replace("%", ""), errors="coerce"
    )
    t["net_today"] = t[_pick(t, ["净额", "资金净流入"], 8)].map(parse_cn_money)
    cols = ["code", "name", "pct", "net_today"]
    if three is not None and not three.empty:
        th = three.copy()
        th["code"] = th[_pick(th, ["股票代码", "代码"], 1)].astype(str).str.zfill(6)
        th["net_3d"] = th[_pick(th, ["资金净流入", "净额"], 6)].map(parse_cn_money)
        th["pct_3d"] = pd.to_numeric(
            th[_pick(th, ["阶段涨跌幅"], 4)].astype(str).str.replace("%", ""),
            errors="coerce",
        )
        t = t.merge(th[["code", "net_3d", "pct_3d"]], on="code", how="left")
        cols += ["net_3d", "pct_3d"]
    t = t[cols].drop_duplicates("code")
    if "net_3d" not in t.columns:
        t["net_3d"] = 0.0
    try:
        t.to_csv(cache_path, index=False, encoding="utf-8-sig")
    except Exception:
        pass
    return t


def industry_map() -> dict:
    cached = read_cache("sina_industry.json", ttl_hours=24 * 7)
    if isinstance(cached, dict):
        return cached
    ak = __import__("akshare")
    df = safe_ak(
        "stock_classify_sina", lambda: ak.stock_classify_sina(symbol="新浪行业")
    )
    mapping = {}
    if df is not None and not df.empty:
        code_col = _pick(df, ["code", "代码"], 1)
        class_col = _pick(df, ["class", "行业"], 20)
        if code_col and class_col:
            for _, r in df.iterrows():
                mapping[str(r[code_col]).zfill(6)] = str(r[class_col])
    try:
        (CACHE / "sina_industry.json").write_text(
            json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
    return mapping


def foreign_hits(code: str, cache: dict) -> list[str]:
    if code in cache:
        # Filter old cache entries against the current keyword set.
        return [h for h in cache[code] if any(k in h for k in FOREIGN_KW)]
    ak = __import__("akshare")
    df = safe_ak(
        "stock_circulate_stock_holder",
        lambda: ak.stock_circulate_stock_holder(symbol=code),
    )
    if df is None:
        return None
    hits = []
    if not df.empty:
        name_col = _pick(df, ["股东名称"], 3)
        if name_col:
            for n in df[name_col].astype(str).unique():
                if any(k in n for k in FOREIGN_KW):
                    hits.append(n)
    cache[code] = hits[:5]
    return cache[code]


def enrich(code: str, q: dict, flow: dict, cfg: dict) -> dict:
    df = tencent_kline(code, 130)
    if df is None or len(df) < 65:
        return {}
    close = df["close"]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ret20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) > 21 else math.nan
    vol_ratio = (
        df["volume"].iloc[-1] / df["volume"].tail(20).mean()
        if df["volume"].tail(20).mean()
        else math.nan
    )
    score, reasons = 0, []
    if q.get("price", 0) > ma20:
        score += 10
        reasons.append("站上MA20")
    if ma20 > ma60:
        score += 15
        reasons.append("MA20>MA60")
    if 0 < ret20 <= cfg.get("max_ret20", 0.35):
        score += 10
        reasons.append(f"20日涨幅{ret20 * 100:.1f}%")
    if vol_ratio >= cfg.get("min_vol_ratio", 1.5):
        score += 20
        reasons.append(f"放量{vol_ratio:.2f}倍")
    elif vol_ratio >= 1.2:
        score += 10
        reasons.append(f"温和放量{vol_ratio:.2f}倍")
    if flow.get("net_3d", 0) > cfg.get("min_3d_net", 0):
        score += 20
        reasons.append(f"3日净流入{fmt_money(flow['net_3d'])}")
    if flow.get("net_today", 0) > cfg.get("min_today_net", 0):
        score += 10
        reasons.append(f"今日净流入{fmt_money(flow['net_today'])}")
    if q.get("amount", 0) >= cfg.get("min_amount", 0):
        score += 5
    return {
        "ma20": ma20,
        "ma60": ma60,
        "ret20": ret20,
        "vol_ratio": vol_ratio,
        "score": score,
        "reasons": reasons,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)["strategy"]
    top_n = args.top or int(cfg["top_n"])

    flows = flow_tables()
    if flows.empty:
        raise SystemExit("资金流数据不可用，稍后重试。")
    flows = flows.sort_values("net_3d", ascending=False)
    pool = flows.head(int(cfg["candidate_pool"])).copy()
    quotes = tencent_quotes(pool["code"].tolist())
    industry = industry_map()

    prelim = []
    for _, r in pool.iterrows():
        code = str(r["code"])
        q = quotes.get(code)
        if not q:
            continue
        name = str(q.get("name") or r["name"])
        if cfg.get("exclude_st") and ("ST" in name or "退" in name):
            continue
        if cfg.get("include_prefixes") and not any(
            code.startswith(p) for p in cfg["include_prefixes"]
        ):
            continue
        if any(code.startswith(p) for p in cfg.get("exclude_prefixes", [])):
            continue
        if cfg.get("exclude_bank") and "银行" in name:
            continue
        if cfg.get("exclude_real_estate") and "房地产" in industry.get(code, ""):
            continue
        price = q.get("price", math.nan)
        if not (cfg["min_price"] <= price <= cfg["max_price"]):
            continue
        if not (cfg["min_pct"] <= q.get("pct", 0) <= cfg["max_pct"]):
            continue
        if q.get("amount", 0) < cfg["min_amount"]:
            continue
        extra = enrich(code, q, r, cfg)
        if not extra:
            continue
        prelim.append({"code": code, "name": name, "quote": q, "flow": r, **extra})
    prelim.sort(key=lambda x: x["score"], reverse=True)
    prelim = prelim[: int(cfg["precheck_limit"])]

    foreign_cache = read_cache("foreign_holdings.json", ttl_hours=24 * 30) or {}
    if not isinstance(foreign_cache, dict):
        foreign_cache = {}
    rows = []
    for x in prelim[: int(cfg["foreign_check_limit"])]:
        hits = foreign_hits(x["code"], foreign_cache)
        if hits is None:
            x["reasons"].append("外资持仓未取得（数据源异常）")
        else:
            if hits:
                x["score"] += 15
                x["reasons"].append("外资/合格机构" + "、".join(hits[:2]))
            if cfg.get("require_foreign") and not hits:
                continue
        if x["score"] < cfg.get("min_score", 60):
            continue
        rows.append(x)
    rows.sort(key=lambda x: x["score"], reverse=True)
    picked = rows[:top_n]
    try:
        (CACHE / "foreign_holdings.json").write_text(
            json.dumps(foreign_cache, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass

    lines = [
        f"# A股策略筛选｜{date.today().isoformat()}",
        "\n> 策略：主板+创业板；持仓1–2周；放量+3日资金流+外资/合格机构持仓；排除银行、房地产；止损参考15%。",
        "\n> 外资/机构为季度披露口径，不是当日买入；候选池不是买入清单，不构成投资建议。\n",
        "| 代码 | 名称 | 现价 | 涨跌幅 | 成交额 | 3日净流入 | 今日净流入 | 20日涨幅 | 量比 | 外资/机构线索 | 评分 | 止损参考 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for x in picked:
        q, f = x["quote"], x["flow"]
        stop = q.get("price", 0) * (1 - cfg.get("stop_loss", 0.15))
        hit = "；".join([r for r in x["reasons"] if "外资" in r or "机构" in r]) or "—"
        lines.append(
            f"| {x['code']} | {x['name']} | {q.get('price', 0):.2f} | {q.get('pct', 0):+.2f}% | {fmt_money(q.get('amount'))} | {fmt_money(f.get('net_3d'))} | {fmt_money(f.get('net_today'))} | {x['ret20'] * 100:.1f}% | {x['vol_ratio']:.2f} | {hit} | {min(x['score'], 100)} | {stop:.2f} |"
        )
    lines += [
        "\n## 风险与复核",
        "- 外资/机构持仓为季度披露，不能代表今天买入；近3日资金流是算法统计，不等于机构真实成交。",
        "- 需复核：公告/减持/解禁、业绩预告、监管问询、板块拥挤度、次日竞价与止损执行。",
        "- 止损15%是纪律参考，不是保证；1–2周持仓需按盘面与事件动态调整。",
    ]
    out = args.out or (OUTPUT / f"screen_{date.today().isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    if args.json:
        out.with_suffix(".json").write_text(
            json.dumps(picked, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    docx = save_to_desktop(out, f"A股策略候选_{date.today().isoformat()}.docx")
    print(out)
    print(docx)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Shared data helpers for the A-share market intelligence skill."""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"
CACHE.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://gu.qq.com/",
}
SESSION = requests.Session()
# Do not inherit a dead local proxy. Tencent endpoints work without it.
SESSION.trust_env = False
SESSION.headers.update(HEADERS)


def normalize_code(code: str) -> str:
    """600519 / sh600519 / 600519.SH -> sh600519."""
    s = str(code).strip().lower().replace(".", "")
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.endswith("sh") or s.endswith("sz") or s.endswith("bj"):
        return s[-2:] + s[:-2]
    digits = re.sub(r"\D", "", s).zfill(6)
    if digits.startswith(("6", "9")):
        return "sh" + digits
    if digits.startswith(("0", "2", "3")):
        return "sz" + digits
    if digits.startswith(("4", "8")):
        return "bj" + digits
    return "sh" + digits


def bare_code(code: str) -> str:
    return normalize_code(code)[2:]


def parse_cn_money(value) -> float:
    """'2.19亿' / '-2775.70万' / '1.2' -> float in yuan."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    s = str(value).strip().replace(",", "").replace("元", "")
    if s in ("", "-", "--", "None", "nan"):
        return float("nan")
    mult = 1.0
    if s.endswith("万亿"):
        mult, s = 1e12, s[:-2]
    elif s.endswith("亿"):
        mult, s = 1e8, s[:-1]
    elif s.endswith("万"):
        mult, s = 1e4, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return float("nan")


def fmt_money(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


def _quote_code(c: str) -> str:
    s = str(c).strip()
    if re.match(r"^(sh|sz|bj)?\d{6}$", s, re.I):
        return normalize_code(s)
    return s


def tencent_quotes(codes: Iterable[str]) -> dict[str, dict]:
    """Batch quote from Tencent. Returns {bare_code: fields}."""
    codes = [_quote_code(c) for c in codes]
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 60):
        batch = codes[i : i + 60]
        try:
            r = SESSION.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=12)
            r.encoding = "gbk"
            for line in r.text.split(";"):
                if "~" not in line:
                    continue
                body = line.split('="', 1)[-1].rstrip('"')
                f = body.split("~")
                if len(f) < 35:
                    continue
                code = f[2]
                out[code] = {
                    "name": f[1],
                    "code": code,
                    "price": _f(f, 3),
                    "prev_close": _f(f, 4),
                    "open": _f(f, 5),
                    "volume": _f(f, 6),
                    "time": f[30] if len(f) > 30 else "",
                    "change": _f(f, 31),
                    "pct": _f(f, 32),
                    "high": _f(f, 33),
                    "low": _f(f, 34),
                    "amount": _f(f, 37) * 1e4 if len(f) > 37 else float("nan"),
                    "turnover": _f(f, 38) if len(f) > 38 else float("nan"),
                }
        except Exception:
            continue
        time.sleep(0.15)
    return out


def _f(fields, idx):
    try:
        return float(fields[idx])
    except Exception:
        return float("nan")


def tencent_kline(code: str, days: int = 120) -> pd.DataFrame:
    code = normalize_code(code)
    urls = [
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq",
        f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{days}",
    ]
    for url in urls:
        for attempt in range(2):
            try:
                r = SESSION.get(url, timeout=15)
                if not r.text.strip().startswith("{"):
                    time.sleep(0.6)
                    continue
                data = r.json().get("data", {}).get(code, {})
                rows = data.get("qfqday") or data.get("day") or []
                if not rows:
                    break
                df = pd.DataFrame([x[:6] for x in rows], columns=["date", "open", "close", "high", "low", "volume"])
                for c in ["open", "close", "high", "low", "volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            except Exception:
                time.sleep(0.6)
    # Sina fallback (unadjusted daily bars)
    try:
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen={days}")
        r = SESSION.get(url, timeout=15)
        rows = r.json()
        if rows:
            df = pd.DataFrame(rows)
            df = df.rename(columns={"day": "date"})
            for c in ["open", "close", "high", "low", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()


def latest_quarters(n: int = 8) -> list[str]:
    """Most recent completed quarter-end dates, newest first."""
    today = date.today()
    q = pd.Period(today, freq="Q")
    if today < q.end_time.date():
        q = q - 1
    return [str((q - i).end_time.date()) for i in range(n)]


def safe_ak(name: str, fn, *args, **kwargs):
    """Call an AKShare function, returning None on failure."""
    try:
        import akshare as ak  # noqa: F401

        return fn(*args, **kwargs)
    except Exception as exc:
        print(f"[warn] {name} failed: {exc}")
        return None


def cache_json(name: str, obj, ttl_hours: float = 12) -> None:
    path = CACHE / name
    path.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")


def read_cache(name: str, ttl_hours: float = 12):
    path = CACHE / name
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_hours * 3600:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def now_cn() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    CACHE.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

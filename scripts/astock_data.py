# -*- coding: utf-8 -*-
"""Bridge to the a-stock-data skill (direct Tencent / Eastmoney / CLS HTTP endpoints).

The upstream project ships runnable Python inside SKILL.md instead of an installable
package. This module extracts the blocks we need, executes them in an isolated
namespace, and exposes small, typed helpers for the market-intel scripts.

Source: https://github.com/simonlin1212/a-stock-data (Apache-2.0)
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import re
import sys
import time
import types
from functools import lru_cache
from pathlib import Path

DEFAULT_SKILL = Path.home() / ".opencode" / "skills" / "a-stock-data" / "SKILL.md"

BASE_FUNCS = (
    "get_prefix",
    "norm_ticker",
    "to_joinquant",
    "em_market_code",
    "em_secid",
    "em_get",
    "bs_session",
)

TARGET_FUNCS = (
    "tencent_quote",
    "tencent_kline",
    "eastmoney_fund_flow_minute",
    "stock_fund_flow_120d",
    "eastmoney_stock_news",
    "eastmoney_global_news",
    "cls_telegraph",
    "wallstreetcn_lives",
    "cctv_news",
    "board_fund_flow",
    "dragon_tiger_board",
    "hsgt_realtime",
    "full_valuation",
    "fund_flow_backup",
)

MARKERS = ("v39-helpers", "v39-wscn-lives", "v39-cctv-news")

OPTIONAL_MODULES = ("mootdx", "baostock", "stockstats", "xlrd", "openpyxl")

_ERRORS: dict[str, str] = {}


def skill_path() -> Path:
    override = os.environ.get("ASTOCK_DATA_SKILL")
    return Path(override).expanduser() if override else DEFAULT_SKILL


def _python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, re.S)


def _block_defining(text: str, name: str) -> str:
    hits = [b for b in _python_blocks(text) if re.search(rf"^def {name}\(", b, re.M)]
    if len(hits) != 1:
        raise RuntimeError(f"{name} defined in {len(hits)} code blocks")
    return hits[0]


def _defs_only(src: str, label: str):
    tree = ast.parse(src)
    names = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
    }
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Expr, ast.For, ast.While, ast.With)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            calls = {
                c.func.id
                for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            }
            if calls & names:
                continue
        keep.append(node)
    tree.body = keep
    return compile(tree, f"SKILL.md:{label}", "exec")


def _marker_code(text: str, marker: str) -> str:
    section = text.split(f"<!-- {marker}:start -->", 1)[1].split(
        f"<!-- {marker}:end -->", 1
    )[0]
    return re.search(r"```python\n(.*?)\n```", section, re.S).group(1)


def _install_stubs() -> None:
    for name in OPTIONAL_MODULES:
        if importlib.util.find_spec(name) is None and name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)


@lru_cache(maxsize=1)
def _namespace() -> dict:
    path = skill_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"a-stock-data SKILL.md not found at {path}; "
            "install https://github.com/simonlin1212/a-stock-data or set ASTOCK_DATA_SKILL"
        )
    text = path.read_text(encoding="utf-8")
    _install_stubs()
    ns: dict = {}
    for name in BASE_FUNCS:
        try:
            exec(_defs_only(_block_defining(text, name), name), ns)
        except Exception as exc:
            if not callable(ns.get(name)):
                _ERRORS[name] = repr(exc)
    for marker in MARKERS:
        try:
            exec(compile(_marker_code(text, marker), f"SKILL.md:{marker}", "exec"), ns)
        except Exception as exc:
            _ERRORS[marker] = repr(exc)
    for name in TARGET_FUNCS:
        try:
            exec(_defs_only(_block_defining(text, name), name), ns)
        except Exception as exc:
            if not callable(ns.get(name)):
                _ERRORS[name] = repr(exc)
    return ns


def _call(name: str, *args, **kwargs):
    ns = _namespace()
    fn = ns.get(name)
    if not callable(fn):
        detail = _ERRORS.get(name, "not loaded")
        raise RuntimeError(f"a-stock-data function {name} unavailable: {detail}")
    return fn(*args, **kwargs)


def _fmt_money(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


def available() -> bool:
    try:
        _namespace()
        return callable(_namespace().get("tencent_quote"))
    except Exception:
        return False


def _retry(fn, attempts: int = 3, delay: float = 0.6):
    last = None
    for i in range(attempts):
        try:
            value = fn()
            if value is None:
                pass
            elif hasattr(value, "empty"):
                if not value.empty:
                    return value
            elif hasattr(value, "__len__"):
                if len(value) > 0:
                    return value
            else:
                return value
        except Exception as exc:
            last = exc
        if i + 1 < attempts:
            time.sleep(delay * (i + 1))
    if last:
        raise last
    return None


def quote(codes: list[str]) -> dict[str, dict]:
    return _retry(lambda: _call("tencent_quote", codes)) or {}


def kline(code: str, period: str = "day", adjust: str = "qfq", count: int = 60):
    return _retry(
        lambda: _call("tencent_kline", code, period, adjust, None, None, count)
    )


def fund_flow_today(code: str) -> dict | None:
    rows = _retry(lambda: _call("eastmoney_fund_flow_minute", code))
    if not rows:
        return None
    last = rows[-1]
    net = last.get("main_net", 0)
    return {
        "net": net,
        "net_fmt": _fmt_money(net),
        "time": last.get("time", ""),
        "source": "eastmoney-push2",
    }


def fund_flow_days(code: str, days: int = 3) -> dict | None:
    rows = _retry(lambda: _call("stock_fund_flow_120d", code))
    if not rows:
        return None
    recent = rows[-max(1, days) :]
    net = sum(float(r.get("main_net", 0) or 0) for r in recent)
    return {
        "days": days,
        "net": net,
        "net_fmt": _fmt_money(net),
        "start": recent[0].get("date", ""),
        "end": recent[-1].get("date", ""),
        "source": "eastmoney-push2his",
    }


def board_flow_top(
    board_type: str = "industry", period: str = "today", n: int = 8
) -> dict:
    data = _retry(lambda: _call("board_fund_flow", board_type, period, max(n * 2, 20)))
    rows = sorted(
        data.get("rows", []),
        key=lambda r: float(r.get("main_net", 0) or 0),
        reverse=True,
    )
    return {
        "board_type": data.get("board_type", board_type),
        "period": data.get("period", period),
        "total": data.get("total", len(rows)),
        "in": rows[:n],
        "out": list(reversed(rows[-n:])),
    }


def individual_flow_rank(
    period: str = "today", n: int = 8, direction: str = "in"
) -> list[dict]:
    if period not in ("today", "3d"):
        raise ValueError("period must be 'today' or '3d'")
    ns = _namespace()
    em_get = ns.get("em_get")
    ua = ns.get("UA", "Mozilla/5.0")
    if not callable(em_get):
        raise RuntimeError("a-stock-data em_get not available")
    if period == "today":
        fid, main_field, pct_field = "f62", "f62", "f184"
        extra = "f66,f72,f78,f84"
    else:
        fid, main_field, pct_field = "f267", "f267", "f268"
        extra = ""
    fields = "f12,f14,f2,f3," + main_field + "," + pct_field
    if extra:
        fields += "," + extra
    base_params = {
        "po": "1" if direction == "in" else "0",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": fields,
    }

    def fetch():
        rows = []
        pages = max(1, (n + 99) // 100)
        for page in range(1, pages + 1):
            params = {**base_params, "pn": str(page), "pz": "100"}
            response = em_get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params=params,
                headers={"User-Agent": ua, "Referer": "https://quote.eastmoney.com/"},
                timeout=15,
            )
            data = response.json()
            rows += (data.get("data") or {}).get("diff") or []
            if len(rows) >= n:
                break
        return rows

    rows = _retry(fetch) or []
    out = [
        {
            "code": r.get("f12", ""),
            "name": r.get("f14", ""),
            "price": r.get("f2"),
            "change_pct": r.get("f3"),
            "main_net": r.get(main_field, 0) or 0,
            "main_pct": r.get(pct_field, 0) or 0,
        }
        for r in rows
    ]
    out.sort(
        key=lambda x: float(x.get("main_net", 0) or 0),
        reverse=(direction == "in"),
    )
    return out[:n]


def stock_news(code: str, limit: int = 20) -> list[dict]:
    return _retry(lambda: _call("eastmoney_stock_news", code, page_size=limit)) or []


def telegraph(limit: int = 50) -> list[dict]:
    return _retry(lambda: _call("cls_telegraph", page_size=limit)) or []


def global_news(limit: int = 50) -> list[dict]:
    return _retry(lambda: _call("eastmoney_global_news", page_size=limit)) or []


def wallstreetcn_lives(channel: str = "global-channel", limit: int = 50):
    return _retry(lambda: _call("wallstreetcn_lives", channel, limit, None))


def cctv_news(date: str, with_content: bool = False) -> list[dict]:
    return _retry(lambda: _call("cctv_news", date, with_content)) or []


def _self_test() -> int:
    checks = [
        ("quote", lambda: quote(["600519"]).get("600519", {}).get("price")),
        ("kline", lambda: len(kline("600519", count=5))),
        ("fund_flow_today", lambda: (fund_flow_today("600519") or {}).get("net_fmt")),
        ("fund_flow_days", lambda: (fund_flow_days("600519", 3) or {}).get("net_fmt")),
        ("board_flow", lambda: len(board_flow_top("industry", "today", 3)["in"])),
        ("individual_flow", lambda: len(individual_flow_rank("today", 3, "in"))),
        ("telegraph", lambda: len(telegraph(5))),
    ]
    failed = 0
    for name, fn in checks:
        try:
            print(f"[OK] {name}: {fn()}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {name}: {exc!r}")
    if _ERRORS:
        print("\nload warnings:")
        for name, err in _ERRORS.items():
            print(f"  {name}: {err}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="a-stock-data bridge self-test")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--skill", default="", help="path to a-stock-data SKILL.md")
    args = parser.parse_args()
    if args.skill:
        os.environ["ASTOCK_DATA_SKILL"] = args.skill
    if args.self_test:
        return _self_test()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Best-effort adapters for the requested Chinese market-news sources."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dtime, timedelta

import requests
from bs4 import BeautifulSoup

from common import safe_ak
from impact import rate, sort_key

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({"User-Agent": UA})


def _clean(s: str) -> str:
    s = re.sub(r"[\ue000-\uf8ff]", "", str(s))
    return re.sub(r"\s+", " ", s).strip()


def _parse_time(value, cutoff: datetime):
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    # Time-only fields (CLS): attach the cutoff date; if it would be in the
    # future, treat it as yesterday's item.
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            dt = datetime.combine(cutoff.date(), t)
            if dt > cutoff:
                dt -= timedelta(days=1)
            return dt
        except ValueError:
            pass
    return None


def fetch_cls() -> list[dict]:
    ak = __import__("akshare")
    df = safe_ak("stock_info_global_cls", lambda: ak.stock_info_global_cls(symbol="全部"))
    out = []
    if df is not None and not df.empty:
        for _, r in df.head(25).iterrows():
            out.append({"source": "财联社", "title": _clean(r.get("标题", "")),
                        "summary": _clean(r.get("内容", ""))[:300],
                        "time": str(r.get("发布时间", "")), "url": ""})
    return out


def fetch_eastmoney() -> list[dict]:
    ak = __import__("akshare")
    df = safe_ak("stock_info_global_em", lambda: ak.stock_info_global_em())
    out = []
    if df is not None and not df.empty:
        for _, r in df.head(25).iterrows():
            out.append({"source": "东方财富", "title": _clean(r.get("标题", "")),
                        "summary": _clean(r.get("摘要", ""))[:300],
                        "time": str(r.get("发布时间", "")), "url": str(r.get("链接", ""))})
    return out


def fetch_100ppi() -> list[dict]:
    """生意社大宗商品要闻. The public page uses a lightweight JS cookie check."""
    url = "https://www.100ppi.com/news/"
    r = SESSION.get(url, timeout=15)
    text = r.content.decode("gb18030", "ignore")
    if "HW_CHECK" in text:
        m = re.search(r'_0x2\s*=\s*"([0-9a-f]+)"', text)
        if m:
            SESSION.cookies.set("HW_CHECK", m.group(1), domain="www.100ppi.com", path="/")
            r = SESSION.get(url, timeout=15)
            text = r.content.decode("gb18030", "ignore")
    soup = BeautifulSoup(text, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "detail-" not in href:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if len(title) < 8:
            continue
        m = re.search(r"detail-(\d{8})-", href)
        tm = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}" if m else ""
        out.append({"source": "生意社", "title": title[:120], "summary": "",
                    "time": tm, "url": "https://www.100ppi.com/news/" + href})
        if len(out) >= 15:
            break
    return out


def fetch_jiuyan() -> list[dict]:
    """韭研公社公开首页文章，作为题材/社区热度来源，权重低于官方媒体."""
    r = SESSION.get("https://www.jiuyangongshe.com/", timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        if "/a/" not in a["href"]:
            continue
        raw = _clean(a.get_text(" ", strip=True))
        if len(raw) < 12:
            continue
        if any(k in raw for k in ("吹票", "免责", "工分", "比赛", "AI助手", "公社出品", "公社里海量内容")):
            continue
        # Community pages put the full article in the link text. Keep only
        # the first readable sentence as the title and the rest as summary.
        cut = len(raw)
        for mark in ("。", "！", "？", "；"):
            pos = raw.find(mark)
            if pos > 12:
                cut = min(cut, pos + 1)
        title = raw[:min(cut, 90)]
        summary = raw[len(title):][:260]
        out.append({"source": "韭研公社", "title": title, "summary": summary,
                    "time": "", "url": "https://www.jiuyangongshe.com" + a["href"]})
        if len(out) >= 15:
            break
    return out


def fetch_cninfo() -> list[dict]:
    """巨潮资讯最新公告（近2日），只保留可能影响股价的类别."""
    end = date.today()
    start = end - timedelta(days=2)
    data = {
        "pageNum": "1", "pageSize": "50", "column": "szse", "tabName": "fulltext",
        "plate": "", "stock": "", "searchkey": "", "secid": "", "category": "",
        "trade": "", "seDate": f"{start.isoformat()}~{end.isoformat()}",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    headers = {"Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
               "X-Requested-With": "XMLHttpRequest"}
    r = SESSION.post("http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data,
                     headers=headers, timeout=20)
    payload = r.json()
    out = []
    wanted = ("业绩预告", "业绩快报", "年度报告", "季度报告", "重大资产重组", "收购",
              "控制权", "实际控制人", "立案", "问询", "减持", "增持", "回购", "解禁",
              "退市", "分红", "重大合同", "中标", "停牌", "复牌", "关联交易", "对外投资", "担保")
    for x in payload.get("announcements") or []:
        title = _clean(x.get("announcementTitle", ""))
        if not any(k in title for k in wanted):
            continue
        ts = x.get("announcementTime")
        tm = ""
        if ts:
            try:
                tm = pd.Timestamp(ts, unit="ms").strftime("%Y-%m-%d %H:%M")
            except Exception:
                tm = ""
        out.append({"source": "巨潮资讯", "title": f"{x.get('secName','')}：{title}",
                    "summary": "", "time": tm,
                    "url": "http://static.cninfo.com.cn/" + str(x.get("adjunctUrl", ""))})
        if len(out) >= 20:
            break
    return out


def fetch_kaipanla() -> list[dict]:
    r = SESSION.get("https://www.kaipanla.com/latest-news/1", timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        if "/article/" not in a["href"]:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if len(title) < 10:
            continue
        tm = ""
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", title)
        if m:
            tm = m.group(1)
            title = _clean(title.replace(m.group(1), ""))
        out.append({"source": "开盘啦", "title": title, "summary": "",
                    "time": tm, "url": "https://www.kaipanla.com" + a["href"]})
        if len(out) >= 15:
            break
    return out


def collect(as_of: datetime | None = None) -> list[dict]:
    """Fetch all sources concurrently and keep only items at/before the cutoff."""
    cutoff = as_of or datetime.now()
    items = []
    funcs = [fetch_cls, fetch_eastmoney, fetch_100ppi, fetch_jiuyan, fetch_cninfo, fetch_kaipanla]
    with ThreadPoolExecutor(max_workers=len(funcs)) as pool:
        futures = {pool.submit(fn): fn for fn in funcs}
        for fut in as_completed(futures):
            fn = futures[fut]
            try:
                items.extend(fut.result())
            except Exception as exc:
                print(f"[warn] {fn.__name__}: {exc}")

    seen, out = set(), []
    for x in items:
        stamp = _parse_time(x.get("time"), cutoff)
        if stamp is not None and stamp > cutoff:
            continue
        if stamp is not None:
            x["time"] = stamp.strftime("%Y-%m-%d %H:%M")
        x["fetched_at"] = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        key = re.sub(r"\W", "", x["title"])[:36]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(rate(x))
    out.sort(key=sort_key)
    return out


# Late import to keep module import cheap; used by fetch_cninfo.
import pandas as pd  # noqa: E402

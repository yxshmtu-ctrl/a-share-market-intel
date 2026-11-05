# -*- coding: utf-8 -*-
"""Real-time news radar: multi-source headlines, cross-source resonance, sector mapping.

Sources (all reachable without a key):
- Eastmoney global 7x24
- Wallstreetcn 7x24 (global + A-share channels)
- CLS telegraph

Design inspired by hipcityreg/situation-monitor (MIT-style community project):
multi-source monitoring, correlation across outlets, and entity/topic prominence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

try:
    from astock_data import global_news, telegraph, wallstreetcn_lives
except Exception:
    global_news = telegraph = wallstreetcn_lives = None

CACHE = Path(__file__).resolve().parents[1] / "cache"
CACHE_FILE = CACHE / "news_radar.json"
CACHE_TTL = 600

TOPICS = {
    "美联储/利率": ["美联储", "降息", "加息", "fomc", "powell", "利率", "国债收益率"],
    "关税/贸易": [
        "关税",
        "贸易战",
        "制裁",
        "出口管制",
        "tariff",
        "sanction",
        "实体清单",
    ],
    "AI/算力": [
        "人工智能",
        "ai",
        "算力",
        "英伟达",
        "nvidia",
        "大模型",
        "openai",
        "gpu",
        "数据中心",
        "推理",
    ],
    "半导体": [
        "半导体",
        "芯片",
        "台积电",
        "光刻",
        "存储",
        "hbm",
        "中芯",
        "晶圆",
        "封测",
    ],
    "台海/地缘": [
        "台海",
        "台湾",
        "军演",
        "nato",
        "北约",
        "俄乌",
        "乌克兰",
        "中东",
        "伊朗",
        "以色列",
        "朝鲜",
    ],
    "原油/能源": ["原油", "油价", "opec", "天然气", "能源", "布伦特", "wti"],
    "黄金/有色": ["黄金", "金价", "铜", "铝", "稀土", "锂", "白银"],
    "汇率/人民币": ["人民币", "汇率", "美元指数", "离岸", "中间价"],
    "加密资产": ["比特币", "bitcoin", "以太坊", "加密", "稳定币"],
    "医药": ["医药", "fda", "创新药", "疫苗", "集采", "临床"],
    "汽车/新能源": [
        "新能源车",
        "电动车",
        "特斯拉",
        "比亚迪",
        "理想",
        "小鹏",
        "锂电",
        "光伏",
        "储能",
        "宁德",
    ],
    "消费": ["消费", "白酒", "免税", "旅游", "零售", "餐饮"],
    "地产": ["房地产", "楼市", "房贷", "房企", "土拍"],
    "金融/券商": ["券商", "银行", "保险", "证监会", "央行", "降准", "流动性"],
    "军工/航运": [
        "军工",
        "国防",
        "莱茵金属",
        "洛克希德",
        "雷神",
        "马士基",
        "集运",
        "航运",
        "运价",
    ],
}

SECTOR_MAP = {
    "AI/算力": "AI算力",
    "半导体": "半导体",
    "汽车/新能源": "新能源车/光伏",
    "黄金/有色": "有色/黄金",
    "原油/能源": "能源",
    "医药": "医药",
    "消费": "消费",
    "地产": "地产",
    "金融/券商": "大金融",
    "台海/地缘": "军工/地缘",
    "汇率/人民币": "汇率敏感",
    "美联储/利率": "宏观流动性",
}

ALERT_WORDS = [
    "战争",
    "入侵",
    "制裁",
    "导弹",
    "袭击",
    "冲突",
    "核武",
    "核试验",
    "核设施",
    "军事",
    "停火",
    "乌克兰",
    "泽连斯基",
    "普京",
    "俄罗斯",
    "中东",
    "以色列",
    "伊朗",
    "台海",
    "朝鲜",
    "空袭",
    "轰炸",
    "coup",
    "war",
    "invasion",
    "sanction",
    "missile",
    "attack",
    "nuclear",
    "conflict",
    "strike",
]
MACRO_WORDS = [
    "美联储",
    "央行",
    "降息",
    "加息",
    "降准",
    "关税",
    "证监会发布",
    "证监会主席",
    "证监会新规",
    "财政部",
    "国务院",
    "汇率",
    "cpi",
    "pmi",
    "非农",
    "fomc",
    "opec",
    "gdp",
    "上证指数",
    "深证成指",
    "创业板指",
    "沪深300指数",
    "恒生指数",
    "道指",
    "纳指",
    "标普",
    "dax",
    "富时",
    "日经",
    "kospi",
    "商务部",
    "美股收盘",
    "美股盘前要闻",
    "欧股收盘",
    "欧股盘初",
    "港股收盘",
    "港股开盘",
    "a股收盘",
    "a股开盘",
    "商品期货",
    "夜盘",
    "历史新高",
    "新高",
]
COMPANY_WORDS = [
    "公告",
    "营收",
    "净利",
    "中标",
    "回购",
    "减持",
    "增持",
    "立案",
    "获批",
    "注册证书",
    "备案",
    "受理",
    "同比增长",
    "环比增长",
    "合同",
    "订单",
    "签约",
    "定增",
    "发行",
    "股权",
    "分红",
    "业绩",
]
POS_WORDS = ["上涨", "新高", "突破", "超预期", "增长", "回购", "增持", "获批", "签约"]
NEG_WORDS = [
    "下跌",
    "暴跌",
    "新低",
    "不及预期",
    "下滑",
    "亏损",
    "减持",
    "立案",
    "调查",
    "退市",
    "违约",
]

ENTITIES = [
    "英伟达",
    "nvidia",
    "amd",
    "戴尔",
    "dell",
    "美光",
    "希捷",
    "超聚变",
    "台积电",
    "特斯拉",
    "宁德时代",
    "比亚迪",
    "中芯国际",
    "华为",
    "小米",
    "苹果",
    "微软",
    "谷歌",
    "meta",
    "亚马逊",
    "三星",
    "sk海力士",
    "openai",
    "字节跳动",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(text: str) -> str:
    text = re.sub(r"【[^】]*】", "", str(text or ""))
    text = re.sub(r"财联社\d+月\d+日电[，,]?", "", text)
    text = re.sub(r"^[（(].*?[）)]", "", text)
    text = re.sub(r"[\s\W_]+", "", text)
    return text.lower()


def _item_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}|{_norm(title)}".encode("utf-8")).hexdigest()[:12]


def _detect(text: str, table: dict[str, list[str]]) -> list[str]:
    low = str(text or "").lower()
    return [
        name for name, words in table.items() if any(w.lower() in low for w in words)
    ]


def _impact(text: str) -> str:
    low = str(text or "").lower()
    if any(w.lower() in low for w in ALERT_WORDS + MACRO_WORDS):
        return "S"
    if _detect(text, TOPICS):
        return "A"
    if any(w.lower() in low for w in ENTITIES + COMPANY_WORDS):
        return "B"
    return "C"


def _bias(text: str) -> str:
    low = str(text or "").lower()
    pos = sum(1 for w in POS_WORDS if w in low)
    neg = sum(1 for w in NEG_WORDS if w in low)
    if pos > neg:
        return "偏多"
    if neg > pos:
        return "偏空"
    return "待观察"


def _clean(text: str, limit: int = 220) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _fetch_eastmoney(limit: int) -> list[dict]:
    if not global_news:
        return []
    rows = global_news(limit)
    return [
        {
            "title": _clean(r.get("title")),
            "summary": _clean(r.get("summary")),
            "time": r.get("time", ""),
            "source": "东财全球",
            "url": "",
            "source_weight": 2,
        }
        for r in rows or []
        if r.get("title")
    ]


def _fetch_wscn(channel: str, limit: int) -> list[dict]:
    if not wallstreetcn_lives:
        return []
    df = wallstreetcn_lives(channel, limit)
    rows = []
    for _, r in df.iterrows():
        try:
            importance = int(r.get("importance", 1) or 1)
        except (TypeError, ValueError):
            importance = 1
        rows.append(
            {
                "title": _clean(r.get("title")),
                "summary": _clean(r.get("content")),
                "time": str(r.get("time", "")),
                "source": "华尔街见闻",
                "url": str(r.get("url", "")),
                "source_weight": 3 if importance >= 2 else 2,
            }
        )
    return [r for r in rows if r["title"]]


def _fetch_cls(limit: int) -> list[dict]:
    if not telegraph:
        return []
    rows = telegraph(limit)
    return [
        {
            "title": _clean(r.get("title")),
            "summary": _clean(r.get("content")),
            "time": r.get("time", ""),
            "source": "财联社",
            "url": "",
            "source_weight": 3,
        }
        for r in rows or []
        if r.get("title")
    ]


def _fetch_all(limit: int = 60) -> list[dict]:
    tasks = [
        (_fetch_eastmoney, (limit,)),
        (_fetch_wscn, ("global-channel", max(30, limit // 2))),
        (_fetch_wscn, ("a-stock-channel", max(20, limit // 3))),
        (_fetch_cls, (max(30, limit // 2),)),
    ]
    out = []
    for fn, args in tasks:
        try:
            out.extend(fn(*args) or [])
        except Exception:
            continue
        time.sleep(0.3)
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    kept = []
    seen_ids = set()
    for item in items:
        title = item["title"]
        if not title:
            continue
        item["id"] = _item_id(title, item["source"])
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        kept.append(item)
    return kept


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    shorter, longer = sorted((a, b), key=len)
    if shorter in longer and len(shorter) / len(longer) >= 0.35:
        return True
    if len(shorter) >= 6 and longer.startswith(shorter):
        return True
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    if prefix >= 10 and prefix / len(shorter) >= 0.5:
        return True
    if len(shorter) >= 6:
        ga = {shorter[i : i + 2] for i in range(len(shorter) - 1)}
        gb = {longer[i : i + 2] for i in range(len(longer) - 1)}
        if ga and gb and len(ga & gb) / len(ga | gb) >= 0.55:
            return True
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def _unique_titles(items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        norm = _norm(item["title"])
        if any(_similar(norm, _norm(prev["title"])) for prev in out):
            continue
        out.append(item)
    return out


def _enrich(item: dict) -> dict:
    title = str(item.get("title", ""))
    text = f"{title} {item.get('summary', '')}"
    topics = _detect(title, TOPICS) or _detect(text, TOPICS)
    item["topics"] = topics
    entities = [e for e in ENTITIES if e.lower() in title.lower()]
    if not entities:
        entities = [e for e in ENTITIES if e.lower() in text.lower()]
    item["entities"] = entities
    item["impact"] = _impact(text)
    item["bias"] = _bias(text)
    item["sectors"] = [SECTOR_MAP[t] for t in item["topics"] if t in SECTOR_MAP]
    return item


def _best_item(group: list[dict], words: list[str]) -> dict:
    def score(x):
        title = str(x.get("title", "")).lower()
        summary = str(x.get("summary", "")).lower()
        title_hits = sum(1 for w in words if w.lower() in title)
        summary_hits = sum(1 for w in words if w.lower() in summary)
        return (
            title_hits * 2 + summary_hits,
            -"SABC".index(x.get("impact", "C")),
            x.get("time", ""),
        )

    return max(group, key=score)


def _resonance(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for key in item.get("topics", []) + item.get("entities", []):
            buckets.setdefault(key, []).append(item)
    out = []
    for key, group in buckets.items():
        sources = sorted({x["source"] for x in group})
        if len(sources) < 2:
            continue
        best = _best_item(group, TOPICS.get(key, [key]))
        out.append(
            {
                "topic": key,
                "sources": sources,
                "count": len(group),
                "headline": best["title"],
                "time": best.get("time", ""),
                "impact": max((x["impact"] for x in group), key="SABC".index),
            }
        )
    out.sort(key=lambda x: (len(x["sources"]), "SABC".index(x["impact"])), reverse=True)
    return out


def _sector_summary(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for sector in item.get("sectors", []):
            buckets.setdefault(sector, []).append(item)
    out = []
    for sector, group in buckets.items():
        words = [
            w
            for topic, keywords in TOPICS.items()
            if SECTOR_MAP.get(topic) == sector
            for w in keywords
        ]
        best = _best_item(group, words or [sector])
        out.append(
            {
                "sector": sector,
                "count": len(group),
                "headline": best["title"],
                "time": best.get("time", ""),
                "impact": best["impact"],
            }
        )
    out.sort(key=lambda x: (x["count"], "SABC".index(x["impact"])), reverse=True)
    return out


def _load_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        return []
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - payload.get("ts", 0) <= CACHE_TTL:
            return payload.get("items", [])
    except Exception:
        pass
    return []


def _save_cache(items: list[dict]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "items": items[-500:]}
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_radar(limit: int = 60, use_cache: bool = True) -> dict:
    cached = _load_cache() if use_cache else []
    fetched = _fetch_all(limit)
    if not fetched and cached:
        fetched = cached
    items = [_enrich(x) for x in _dedupe(fetched)]
    items.sort(key=lambda x: x.get("time", ""), reverse=True)
    items.sort(key=lambda x: "SABC".index(x["impact"]))
    if items:
        _save_cache(items)
    return {
        "generated_at": _now(),
        "items": items,
        "resonance": _resonance(items),
        "sectors": _sector_summary(items),
    }


def render_radar(
    radar: dict, top: int = 8, heading: str = "\n## 二、消息面雷达（实时信息差）"
) -> list[str]:
    lines = [heading, ""] if heading else []
    lines.append(
        "> 来源：东财全球 7×24、华尔街见闻、财联社；跨源共振=同一主题被 ≥2 个独立来源提及。"
    )
    lines.append("> 级别与倾向为文本标签，不代表价格方向。\n")

    resonance = radar.get("resonance", [])[:top]
    lines += ["### 跨源共振（信息差）", ""]
    if resonance:
        for x in resonance:
            sources = " / ".join(x["sources"])
            lines.append(
                f"- **{x['topic']}**（{len(x['sources'])}源：{sources}；{x['impact']}级）"
                f"：{x['headline']}（{x['time']}）"
            )
    else:
        lines.append("- 暂未形成跨源共振。")

    hot = _unique_titles(
        [x for x in radar.get("items", []) if x["impact"] in ("S", "A")]
    )[:top]
    lines += ["", "### S/A 级消息", ""]
    if hot:
        for x in hot:
            tags = "、".join(x.get("topics", [])[:3]) or "—"
            lines.append(f"- **{x['title']}**（{x['source']} {x.get('time', '')}）")
            lines.append(f"  - {x['impact']}级；倾向：{x['bias']}；主题：{tags}")
    else:
        lines.append("- 暂无。")

    sectors = radar.get("sectors", [])[:top]
    lines += ["", "### 板块映射", ""]
    if sectors:
        for x in sectors:
            lines.append(
                f"- **{x['sector']}**：{x['count']}条；代表：{x['headline']}（{x['time']}）"
            )
    else:
        lines.append("- 暂无。")
    return lines


def _self_test() -> int:
    radar = build_radar(limit=20, use_cache=False)
    print(
        f"items={len(radar['items'])} resonance={len(radar['resonance'])} sectors={len(radar['sectors'])}"
    )
    for x in radar["items"][:5]:
        print(f"[{x['impact']}] {x['source']} {x['time']} {x['title']}")
    return 0 if radar["items"] else 1


def _watch(interval: int) -> None:
    seen = set()
    print(f"news radar watch: every {interval}s, Ctrl+C to stop")
    try:
        while True:
            radar = build_radar(limit=60, use_cache=False)
            fresh = [x for x in radar["items"] if x["id"] not in seen]
            for x in reversed(fresh):
                print(f"{x.get('time', '')} [{x['impact']}] {x['source']} {x['title']}")
            seen.update(x["id"] for x in fresh)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-time A-share news radar")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDS")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()
    if args.watch:
        _watch(args.watch)
        return 0

    radar = build_radar(limit=args.limit)
    if args.json:
        print(json.dumps(radar, ensure_ascii=False, indent=2))
        return 0
    lines = [f"# 消息面雷达｜{radar['generated_at']}"] + render_radar(
        radar, 10, heading=""
    )
    text = "\n".join(lines)
    out = args.out or (
        CACHE.parent / "output" / f"news_radar_{datetime.now():%Y-%m-%d}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

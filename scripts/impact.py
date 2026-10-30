# -*- coding: utf-8 -*-
"""Rule-based impact ranking for market news.

Levels are a triage aid, not a trading signal. Direction tags are keyword-based
and must be checked against price, positioning and the actual document.
"""
from __future__ import annotations

S_KW = ("美联储", "加息", "降息", "降准", "关税", "制裁", "出口管制", "战争", "地缘",
         "原油", "黄金", "美元", "人民币", "汇率", "证监会", "国务院", "财政部",
         "发改委", "印花税", "IPO", "退市", "系统性风险", "非农", "CPI", "PCE")
A_KW = ("人工智能", "AI", "芯片", "半导体", "机器人", "新能源", "光伏", "储能",
        "医药", "创新药", "军工", "商业航天", "卫星", "算力", "液冷", "固态电池",
        "消费", "房地产", "汽车", "智能驾驶", "数据要素", "国企改革", "并购重组",
        "原油", "黄金", "铜", "铝", "锡", "煤炭", "天然气", "螺纹钢", "铁矿石")
B_KW = ("业绩预告", "业绩快报", "年报", "季报", "减持", "增持", "回购", "解禁",
        "问询", "立案", "分红", "重大合同", "中标", "停牌", "复牌", "控制权",
        "实际控制人", "关联交易", "对外投资", "担保", "股东")
POS_KW = ("超预期", "增长", "突破", "获批", "回购", "增持", "降准", "降息",
          "利好", "创新高", "扩产", "订单")
NEG_KW = ("不及预期", "下滑", "亏损", "减持", "立案", "退市", "制裁", "关税",
          "加息", "战争", "下调", "违约", "问询", "解禁")
SOURCE_WEIGHT = {"财联社": 3, "新闻联播": 3, "巨潮资讯": 2, "东方财富": 1,
                 "开盘啦": 1, "生意社": 1, "韭研公社": 0}


def rate(item: dict) -> dict:
    text = f"{item.get('title','')} {item.get('summary','')}"
    s_hits = [k for k in S_KW if k.lower() in text.lower()]
    a_hits = [k for k in A_KW if k.lower() in text.lower()]
    b_hits = [k for k in B_KW if k.lower() in text.lower()]
    # Cap sector/company hits so a community post with many theme words
    # cannot be promoted to a systemic (S) event.
    score = (len(s_hits) * 5 + min(len(a_hits), 2) * 3
             + min(len(b_hits), 2) * 2 + SOURCE_WEIGHT.get(item.get("source"), 0))
    if s_hits and score >= 8:
        level = "S"
    elif a_hits and score >= 4:
        level = "A"
    elif b_hits:
        level = "B"
    else:
        level = "C"
    if item.get("source") in ("韭研公社", "开盘啦") and level == "S" and len(s_hits) < 2:
        level = "A"
    pos = [k for k in POS_KW if k in text]
    neg = [k for k in NEG_KW if k in text]
    bias = "待观察"
    if pos and not neg:
        bias = "关键词偏多"
    elif neg and not pos:
        bias = "关键词偏空"
    return {
        **item,
        "impact_level": level,
        "impact_score": score,
        "impact_tags": s_hits[:4] + a_hits[:4] + b_hits[:4],
        "bias": bias,
    }


def sort_key(item: dict):
    order = {"S": 0, "A": 1, "B": 2, "C": 3}
    return (order.get(item.get("impact_level"), 9), -item.get("impact_score", 0))

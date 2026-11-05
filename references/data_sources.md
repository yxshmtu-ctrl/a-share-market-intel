# 数据源与 a-stock-data 桥接

## 1. 分层

| 层 | 来源 | 用途 | 备注 |
|---|---|---|---|
| L1 直连 | 腾讯行情 / 腾讯 K 线 | 实时价、涨跌幅、成交额、换手、K 线 | 不封 IP，主源 |
| L1 直连 | a-stock-data `tencent_quote` | 补充 PE/PB/市值/涨跌停/量比 | 同上 |
| L2 直连 | a-stock-data（东财 push2 / push2his） | 个股今日资金流、120 日资金流 | 已内置限流 |
| L2 直连 | a-stock-data `board_fund_flow` | 行业/概念/地域板块资金流 | 今日/5日/10日 |
| L3 直连 | a-stock-data `cls_telegraph` | 财联社 7×24 电报 | 零 key |
| L4 兜底 | AKShare | 资金流、北向、十大股东、新闻 | 接口易变，失败即降级 |
| L5 披露 | 巨潮/交易所 | 公告、龙虎榜 | 按需 |

## 2. 安装上游

```bash
git clone https://github.com/simonlin1212/a-stock-data.git ~/.opencode/skills/a-stock-data
```

上游是「Markdown + 内嵌 Python」的 skill，不需要 pip 安装；桥接模块会读取其中的代码块。

如放在其他路径：

```bash
export ASTOCK_DATA_SKILL="/path/to/a-stock-data/SKILL.md"
```

## 3. 桥接模块

`scripts/astock_data.py` 提供：

```python
from astock_data import (
    quote, kline,
    fund_flow_today, fund_flow_days,
    board_flow_top, individual_flow_rank,
    stock_news, telegraph,
)

quote(["600519"])                 # {代码: {price, pct, pe_ttm, pb, mcap_yi, ...}}
kline("600519", count=60)         # DataFrame: date/open/high/low/close/volume
fund_flow_today("600519")         # {net, net_fmt, time, source}
fund_flow_days("600519", 3)       # {days, net, net_fmt, start, end, source}
board_flow_top("industry", "today", 8)  # {in:[...], out:[...], total}
individual_flow_rank("today", 8, "in")  # 个股主力净流入排名（今日/3d）
telegraph(20)                     # [{title, content, time}]
```

自检：

```bash
python scripts/astock_data.py --self-test
```

## 4. 调用约定

1. 先直连（腾讯 / a-stock-data）。
2. 直连失败或字段缺失，再回退 AKShare。
3. 两者都失败，写“未取得”，并注明接口异常。
4. 资金流是算法统计，不是机构真实成交；板块资金流只有今日/5日/10日，没有 3 日。
5. 东财接口有 IP 风控：短时间大量请求可能返回空或 403；桥接已做 3 次重试与退避，仍失败就换时段或换网络。

## 5. 字段与口径

| 字段 | 含义 | 单位 |
|---|---|---|
| `main_net` | 主力净流入（超大单 + 大单） | 元 |
| `super_net` | 超大单净流入 | 元 |
| `large_net` | 大单净流入 | 元 |
| `mid_net` | 中单净流入 | 元 |
| `small_net` | 小单净流入 | 元 |
| `change_pct` | 板块涨跌幅 | % |
| `main_pct` | 主力净流入占成交额比例 | % |
| `is_stale` | 腾讯僵尸报价标志 | bool |

## 6. 已知限制

- `eastmoney_stock_news` 可能返回空（个股无新闻或接口调整）；用 `cls_telegraph` 补充市场级新闻。
- 个股资金流的市场级排名由桥接层调用东财 clist 接口补齐（`individual_flow_rank()`，今日/3日）；板块排名走 `board_flow_top()`。
- 北向每日持股已停止/滞后，不能用 2024 年数据代表今天。
- 上游 SKILL.md 约 430KB，首次加载会解析代码块；桥接已用 `lru_cache` 只加载一次。

## 7. 消息面雷达（news_radar.py）

| 来源 | 接口 | 特点 |
|---|---|---|
| 东财全球 | a-stock-data `eastmoney_global_news` | 7×24，中文，宏观/公司/海外 |
| 华尔街见闻 | a-stock-data `wallstreetcn_lives` | global-channel + a-stock-channel，importance 1/2 |
| 财联社 | a-stock-data `cls_telegraph` | 7×24 电报，速度快 |

处理流程：

1. 顺序抓取（共享 session 并发会互相干扰），单源失败跳过。
2. 归一化标题、去重；跨源保留近重复，用于共振计数。
3. 主题/实体识别：美联储、关税、AI/算力、半导体、台海、原油、黄金、汇率、医药、汽车新能源、消费、地产、金融。
4. 级别：S=宏观/政策/地缘/警报词；A=行业主题；B=公司事件；C=一般。
5. 跨源共振：同一主题被 ≥2 个独立来源提及，按来源数与级别排序。
6. 板块映射：AI算力、半导体、新能源车/光伏、军工/地缘、有色/黄金、能源、医药、消费、地产、大金融、汇率敏感、宏观流动性。
7. 缓存：`cache/news_radar.json`，TTL 10 分钟；网络慢时优先缓存。

命令：

```bash
python scripts/news_radar.py --once
python scripts/news_radar.py --watch 60
python scripts/news_radar.py --once --json
```

说明：级别/倾向为规则标签，不是价格方向；跨源共振只代表信息扩散，不代表利好或利空。

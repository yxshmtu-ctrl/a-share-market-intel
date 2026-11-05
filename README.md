# A股市场情报与投研 SKILL

**触发词：股神、来财、旺仔**；也可直接说“A股日报/盘前简报/个股持仓/选股”。

本 SKILL 面向 A 股研究/咨询场景，提供四类能力：

1. **每日市场简报**：国际国内影响市场的热门事件、消息面雷达、海外市场/大宗/汇率、今日与近 3 日资金流。
2. **实时消息面雷达**：东财全球、华尔街见闻、财联社多源聚合，跨源共振、S/A 级消息、板块映射；支持每 60 秒滚动监控。
3. **个股机构与资金画像**：实时行情、今日/3 日资金流、北向/外资、前十大流通股东、社保/QFII 线索、近期新闻。
4. **策略候选池**：按配置的趋势+资金+流动性规则筛选候选股票，输出评分与入选理由。

> 消息面雷达的多源监控与跨源共振思路参考 [hipcityreg/situation-monitor](https://github.com/hipcityreg/situation-monitor)。

> 仅供研究参考，不构成投资建议，不承诺收益。数据来自公开接口，存在延迟、缺失和口径差异。

## 安装

```bash
cd %USERPROFILE%\.opencode\skills\a-share-market-intel
pip install -r requirements.txt
```

依赖：Python 3.10+、pandas、numpy、requests、PyYAML、AKShare。AKShare 已在本机安装；如网络较慢，可用清华镜像：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### 补充数据层：a-stock-data

已集成 [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)（Apache-2.0，87 个直连端点）：

- 安装位置：`~/.opencode/skills/a-stock-data/`
- 桥接模块：`scripts/astock_data.py`
- 自检：

```bash
python scripts/astock_data.py --self-test
```

封装能力：实时行情（含 PE/PB/市值/换手）、K 线、个股今日/120 日资金流、个股资金流排名（今日/3日）、行业/概念/地域板块资金流、个股新闻、财联社电报。腾讯/东财/财联社直连，免 key；东财已内置限流。资金流优先走 a-stock-data，失败再回退 AKShare。

## 快速开始

```bash
# 每日简报（含消息面雷达）
python scripts/market_brief.py --json

# 只跑消息面雷达（单次）
python scripts/news_radar.py --once

# 实时滚动，只看新增消息
python scripts/news_radar.py --watch 60

# 指定截止时间（默认=运行时刻）
python scripts/market_brief.py --as-of "2026-10-30 09:00" --json

# 个股画像（600519 / sh600519 均可）
python scripts/stock_profile.py 600519

# 深度扫描社保/QFII（较慢）
python scripts/stock_profile.py 600519 --deep --json

# 策略筛选
python scripts/screen.py --config config.yaml --top 10 --json
```

输出默认写入 `output/`，缓存写入 `cache/`；同时自动生成 **Word 版并保存到桌面**。

## 数据源与口径

| 数据 | 来源 | 口径/限制 |
|---|---|---|
| 实时行情 | 腾讯 `qt.gtimg.cn` + a-stock-data `tencent_quote` | 盘中快照；补充 PE/PB/市值/换手/涨跌停 |
| 日 K/均线 | 腾讯前复权 K 线 + a-stock-data `tencent_kline` | 用于 MA20/MA60、20 日涨幅、量比 |
| 个股资金流 | a-stock-data（东财 push2 / push2his）优先，AKShare 兜底 | 算法统计；不等于真实机构成交 |
| 板块资金流 | a-stock-data `board_fund_flow` | 行业/概念/地域 × 今日/5日/10日 |
| 北向持股 | AKShare `stock_hsgt_individual_em` | **2024-08 后每日持股数据停止/滞后**；仅作历史参考 |
| 十大流通股东 | `stock_gdfx_free_top_10_em`，失败回退 `stock_circulate_stock_holder` | 季度披露，滞后 |
| 社保/QFII | `stock_gdfx_free_holding_teamwork_em` | 协同持股列表；`--deep` 启用，较慢 |
| 新闻 | 财联社、生意社、韭研公社、巨潮资讯、开盘啦、东方财富 + a-stock-data `cls_telegraph` | 公开资讯，去重后按 S/A/B/C 影响级别排序 |
| 龙虎榜/公告 | `stock_lhb_detail_em` / `stock_notice_report`；a-stock-data `dragon_tiger_board` | 可选扩展 |

### 资讯影响分级

- **S 级**：系统性/宏观（美联储、央行、关税/制裁、地缘、汇率、原油、证监会/国务院/财政部重大政策）。
- **A 级**：行业/板块（AI、芯片、机器人、新能源、医药、军工、商业航天、算力、消费、房地产等）。
- **B 级**：个股/公司（业绩、并购、减持/增持/回购、解禁、问询/立案、重大合同、停牌/复牌）。
- **C 级**：一般资讯。

级别是规则排序，不是价格方向；“关键词倾向”也只是文本标签，必须结合价格、成交、资金和估值复核。

### 截止时间

默认以运行指令的时刻为截止时间；之后网站更新的资讯不会进入本次报告。需要复盘某一时点，可用 `--as-of "YYYY-MM-DD HH:MM"`。

### 重要限制

- **北向每日持股已停止/滞后**：不要用 2024 年数据描述“今天外资买入”。以外资季度持仓（十大流通股东中的香港中央结算/陆股通）和 QFII 季度数据为准。
- **社保/QFII 是季度数据**：只能说明“上季度末持有”，不能说明今天买卖。近期动作看资金流、龙虎榜、公告。
- **资金流是算法口径**：主力/超大单/大单是统计分类，不等于机构真实账户。
- **新闻不等于方向**：同一事件可能已被定价；必须结合价格、成交、资金和估值。
- **接口会失效**：东方财富 push2 系列在部分网络/代理下会 `ProxyError`/`RemoteDisconnected`；脚本已对核心行情使用腾讯源，并对持仓做回退。若遇接口失败，降低频率或稍后重试。

## 定时任务

Windows 任务计划：

```powershell
schtasks /Create /SC DAILY /TN "A股盘前简报" /TR "python %USERPROFILE%\.opencode\skills\a-share-market-intel\scripts\market_brief.py" /ST 08:30
schtasks /Create /SC DAILY /TN "A股盘后复盘" /TR "python %USERPROFILE%\.opencode\skills\a-share-market-intel\scripts\market_brief.py" /ST 15:30
```

盘中每 30 分钟运行一次可用 `/SC MINUTE /MO 30`，但请控制频率，避免触发公开接口限流。

## 自定义策略

编辑 `config.yaml`。默认策略是：

- 价格 2–500 元，成交额 ≥1 亿元；
- 当日涨跌幅 -5% 至 +9.5%，排除 ST/退市/北交所（可按需改）；
- 3 日主力净流入 > 0；
- 站上 MA20，MA20 > MA60，20 日涨幅 > 0；
- 量比 > 1.1；
- 综合评分 ≥60，取前 10。

如果你有自己的策略，把条件写进 `screen.py` 的 `enrich()`/评分逻辑，或在 `config.yaml` 增参数；不要只改输出文案。

## 目录

```text
a-share-market-intel/
├─ SKILL.md
├─ README.md
├─ config.yaml
├─ requirements.txt
├─ scripts/
│  ├─ common.py
│  ├─ market_brief.py
│  ├─ stock_profile.py
│  └─ screen.py
├─ references/
├─ cache/
└─ output/
```

## 排错

- **AKShare 报 ProxyError**：脚本已对腾讯行情禁用系统代理；AKShare 端点仍可能走系统代理。关闭代理或设置 `NO_PROXY=*` 后重试。
- **十大股东失败 `sdltgd`**：主接口变动时自动回退到 `stock_circulate_stock_holder`，通常可取到最近报告期。
- **北向数据停在 2024-08**：这是数据源停止更新，不是脚本错误。
- **运行很慢**：AKShare 资金流/社保扫描有进度条和多次请求；建议盘后运行，或用缓存/降低 `candidate_pool`。

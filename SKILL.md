---
name: a-share-market-intel
description: |
  A股市场情报与投研 SKILL：生成每日/盘中市场简报，跟踪国际国内影响市场的热门事件；
  查询个股实时行情、近3日资金流、北向/外资、社保/QFII、前十大流通股东与新闻；
  按用户自定义策略做趋势+资金+机构共振的候选股票筛选。
  触发词：股神、来财、旺仔；A股日报、盘前简报、盘后复盘、今日资讯、机构持仓、
  北向资金、社保持仓、3日资金流、游资、龙虎榜、选股、荐股候选、策略筛选、A股咨询。
  不用于自动下单、收益承诺或替代持牌投资顾问。
---

# A股市场情报与投研

## 触发词

当用户说 **“股神”“来财”“旺仔”**，或要求 A 股日报/盘前简报/盘后复盘、机构持仓、资金流、选股/荐股候选时，启用本 SKILL。

## 何时使用

- 用户要“今天的A股资讯/盘前简报/盘后复盘”，重点是国际国内影响市场的热门事件。
- 用户要查某只A股的实时行情、近3日资金流、北向/外资、社保/QFII、十大流通股东、新闻。
- 用户要按自己的策略筛选候选股票，或要求“结合实时行情荐股”。
- 用户要跟踪机构持仓和资金流动向，打破信息差。

不用于：自动交易、保证收益、替代持牌投顾、内幕信息或非公开数据。

## 先确认

1. **市场与时间**：A股（沪深北）；盘中/盘后/盘前。
2. **对象**：大盘/板块/个股代码。
3. **策略**：用户是否已有明确规则；没有则使用 `config.yaml` 默认模板，并明确告知这是模板。
4. **输出**：简报、个股画像、候选池；是否需要 Markdown/JSON。

## 数据截止规则：默认以**运行指令的时刻**为截止时间，之后更新的资讯不纳入本次报告；可用 `--as-of` 固定复盘时点。

数据源与口径

| 数据 | 主要来源 | 口径/限制 |
|---|---|---|
| 实时行情 | 腾讯行情 `qt.gtimg.cn` + **a-stock-data `tencent_quote`**（PE/PB/市值/换手/涨跌停） | 盘中快照，可能延迟数秒至数分钟 |
| 日K/均线 | 腾讯前复权K线 + **a-stock-data `tencent_kline`** | 用于趋势/量比，不复权口径需注明 |
| 个股资金流 | **a-stock-data**（东财 push2 分钟级 / push2his 120日）优先；AKShare 兜底 | 算法统计，不等于真实机构买卖 |
| 板块资金流 | **a-stock-data `board_fund_flow`**（东财） | 行业/概念/地域 × 今日/5日/10日 |
| 北向持股 | AKShare `stock_hsgt_individual_em` | **2024-08后每日持股数据停止/滞后**，只能作历史参考 |
| 十大流通股东 | AKShare `stock_gdfx_free_top_10_em`，失败时回退 `stock_circulate_stock_holder` | 季度披露，滞后 |
| 社保/QFII | AKShare `stock_gdfx_free_holding_teamwork_em` | 协同持股列表，需按代码匹配；较慢，`--deep` 启用 |
| 新闻 | 财联社、生意社、韭研公社、巨潮资讯、开盘啦、东方财富 + **a-stock-data `cls_telegraph`** | 公开资讯，去重后按 S/A/B/C 影响级别排序；不代表价格方向 |
| 公告/龙虎榜 | AKShare `stock_lhb_detail_em` / `stock_notice_report`；**a-stock-data `dragon_tiger_board`** 可补充席位 | 可选，按需调用 |

### a-stock-data 集成（优先使用）

本项目已把 [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)（Apache-2.0，87 个直连端点）作为补充数据层：

- 上游技能：`~/.opencode/skills/a-stock-data/SKILL.md`
- 本项目的桥接：`scripts/astock_data.py`
- 自检：`python scripts/astock_data.py --self-test`
- 已封装：`quote()`、`kline()`、`fund_flow_today()`、`fund_flow_days()`、`board_flow_top()`、`individual_flow_rank()`、`stock_news()`、`telegraph()`
- 特点：腾讯/东财/财联社直连，免 key；东财请求自动限流，主源失败可换备用源
- 口径：资金流为东财算法统计，不等于机构真实成交；板块资金流只有今日/5日/10日，个股排名支持今日/3日
- 细节与字段见 [references/data_sources.md](references/data_sources.md)

**调用顺序**：先用 a-stock-data 的直连端点；失败或字段缺失时回退 AKShare；两者都失败才写“未取得”。

**强制规则**：
- 任何数字都要带来源与时间；不要把季度持仓写成“今天买入”。
- 北向每日数据已停止/滞后，必须明确提示；不要把 2024 年数据当作当前持仓。
- 资金流是统计口径，不是机构真实成交；新闻只代表信息，不代表方向。
- 找不到数据就写“未取得”，不要编造。

## 运行方式

工作目录：本 SKILL 目录。首次使用：

```bash
pip install -r requirements.txt
```

数据层自检（a-stock-data 直连是否可用）：

```bash
python scripts/astock_data.py --self-test
```

### 1. 每日/盘中市场简报

```bash
python scripts/market_brief.py --json
# 指定截止时间（默认=运行时刻）
python scripts/market_brief.py --as-of "2026-10-30 09:00" --json
```

输出：`output/daily_brief_YYYY-MM-DD.md`（及 JSON），并自动生成桌面 Word：`A股市场情报简报_YYYY-MM-DD.docx`。包含：
- 今日核心事件（按 S/A/B/C 影响级别排序，附关键词倾向与标签）
- 消息面雷达：跨源共振、S/A 级消息、板块映射（东财全球 / 华尔街见闻 / 财联社）
- 海外市场/大宗/汇率快照
- 行业板块今日/近5日主力净流入/流出（a-stock-data）
- 个股今日/近3日主力净流入（a-stock-data 优先，AKShare 兜底）
- 对A股的可能影响与风险提示（由模型结合事件补全）

### 1.1 实时消息面雷达（信息差）

不跑整份简报、只看消息面时：

```bash
# 单次快照（写入 output/news_radar_YYYY-MM-DD.md）
python scripts/news_radar.py --once

# 每 60 秒滚动，只打印新增消息（Ctrl+C 停止）
python scripts/news_radar.py --watch 60

# 结构化 JSON
python scripts/news_radar.py --once --json
```

数据源：东财全球 7×24、华尔街见闻（global + A股频道）、财联社电报。输出：
- **跨源共振**：同一主题被 ≥2 个独立来源提及，按来源数与级别排序
- **S/A 级消息**：宏观、政策、地缘、行业催化
- **板块映射**：AI算力、半导体、新能源、军工、有色、医药、消费、地产、大金融等

缓存 10 分钟，网络慢时优先用缓存；单源失败不影响其他源。

### 2. 个股情报

```bash
python scripts/stock_profile.py 600519
python scripts/stock_profile.py 600519 --deep --json
```

输出：`output/stock_600519_YYYY-MM-DD.md`，并自动生成桌面 Word：`个股情报_600519_YYYY-MM-DD.docx`。包含：
- 实时行情
- 今日/近3日资金流
- 北向/外资持仓（含滞后提示）
- 前十大流通股东（社保/QFII/基金/保险/香港中央结算）
- 社保/QFII 协同持股线索（`--deep`）
- 近期新闻
- 分析框架与数据限制

### 3. 策略筛选/候选池

```bash
python scripts/screen.py --top 10
python scripts/screen.py --config config.yaml --top 10 --json
```

当前默认策略：**主板+创业板；持仓1–2周；放量+3日主力净流入+外资/合格机构持仓；排除银行、房地产；止损参考15%**。输出候选池，不是买入清单。

## 输出模板

### 每日简报

```markdown
# A股市场情报简报｜YYYY-MM-DD
## 一、今日核心事件（3-8条，按重要性）
## 二、海外市场与大宗（指数/原油/黄金/汇率）
## 三、国内政策与监管
## 四、资金与情绪（今日/3日主力净流入、北向、龙虎榜）
## 五、对A股的可能影响（利好/利空/待观察，分板块）
## 六、风险提示
```

### 个股画像

```markdown
# 个股情报｜名称（代码）
## 一、实时行情
## 二、近3日资金流
## 三、外资/北向（注明滞后）
## 四、前十大流通股东（季度）
## 五、社保/QFII线索
## 六、近期新闻/公告
## 七、结论：机构/资金/事件/风险四象限
```

### 候选池

```markdown
# A股策略筛选｜YYYY-MM-DD
| 代码 | 名称 | 现价 | 涨跌幅 | 3日净流入 | 今日净流入 | 评分 | 入选理由 |
## 风险与复核
```

## 资讯影响分级

- **S 级（系统性/宏观）**：美联储、央行、降准降息、关税/制裁、地缘/战争、汇率、原油、证监会/国务院/财政部重大政策等。
- **A 级（行业/板块）**：AI/芯片/机器人/新能源/医药/军工/商业航天/算力/消费/房地产等产业政策与行业催化。
- **B 级（个股/公司）**：业绩预告/快报、并购重组、减持/增持/回购、解禁、问询/立案、重大合同、停牌/复牌等。
- **C 级（一般资讯）**：难以映射到具体资产或影响范围有限的资讯。

级别由关键词、来源权重和题材范围规则计算，**不是价格方向判断**；“关键词倾向（偏多/偏空/待观察）”也只是文本标签，必须结合价格、成交、资金和估值复核。

## 分析规则

1. **先数据后观点**：先运行脚本，拿结构化数据，再写判断。
2. **机构持仓**：区分“季度静态持仓”“北向历史持股”“近期资金流”；不要混为一谈。
3. **资金流**：看3日是否持续、是否与价格/成交背离；单日脉冲不构成趋势。
4. **事件**：区分“已发生/预期/传闻”；标注来源与时间；不要把新闻标题直接当结论。
5. **选股**：先过滤风险（ST、退市、减持/解禁、监管、流动性），再谈评分。
6. **结论**：给出“支持/中性/谨慎”和触发条件；不写“必涨”。
7. **合规**：所有输出加“仅供研究参考，不构成投资建议，不承诺收益”。

## 自定义策略

编辑 `config.yaml`：

```yaml
strategy:
  min_price: 2
  max_price: 500
  min_amount: 100000000
  min_pct: -5
  max_pct: 9.5
  exclude_prefixes: ["4", "8"]
  exclude_st: true
  candidate_pool: 300
  max_candidates: 120
  top_n: 10
  min_score: 60
```

如果用户有自己的策略（例如“低位放量+机构加仓+3日净流入”），把规则写成可执行条件，再改 `screen.py` 的评分函数；不要只改文案。

## 定时任务（Windows）

每天 8:30 盘前简报、15:30 盘后复盘：

```powershell
schtasks /Create /SC DAILY /TN "A股盘前简报" /TR "python %USERPROFILE%\.opencode\skills\a-share-market-intel\scripts\market_brief.py" /ST 08:30
schtasks /Create /SC DAILY /TN "A股盘后复盘" /TR "python %USERPROFILE%\.opencode\skills\a-share-market-intel\scripts\market_brief.py" /ST 15:30
```

## 参考

- `references/data_fields.md`：字段与口径
- `references/output_templates.md`：完整模板
- `README.md`：安装、排错、限制

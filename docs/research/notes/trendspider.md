# TrendSpider (trendspider.com): Competitor Profile as of November 2026

Scope note: research was done on 2026-11-11. "Official" means trendspider.com, its help center, changelogs, press releases, or the SignalStack site (SignalStack is TrendSpider's own order-routing product). "Independent" means third-party reviews, many of which are affiliate sites and are flagged as such. Reddit could not be reached (the search tool blocks reddit.com), and Liberated Stock Trader returned HTTP 403, so neither could be read directly.

Company background: TrendSpider launched in March 2018. In November 2024 it said it had "over 15,000 active traders" and covered "200,000+ assets", including crypto from 100+ exchanges. CEO: Dan Ushman. The press release is datelined Chicago. — [PR Newswire, 19 Nov 2024](https://prnewswire.com/news-releases/trendspider-launches-ai-strategy-lab-to-empower-investors-to-build-custom-ai-powered-trading-models-with-ease-302306657.html)

---

## 1. Automated technical analysis: trendlines, Fibonacci, S/R, candlestick and chart patterns, heatmaps, MTFA, Raindrop, AVWAP, seasonality

### Takeaway
The core product is automated chart drawing: auto trendlines, auto Fibonacci, S/R heatmaps, auto-anchored indicators and gap detection. It also recognizes 100+ candlestick patterns but only **13 chart patterns**, and chart patterns **cannot be alerted on or backtested**. The help center documents MTFA overlays, Raindrop charts, auto-anchored VWAP and seasonality. TrendSpider publishes no accuracy figures for any of its detection, and no independent test with a stated method exists.

### Cited Findings
- The help center lists six automated analysis types: (1) automated trendlines, drawn from highs, lows, opens and closes; (2) automated Fibonacci, which finds "the most meaningful Fibonacci connection points on each timeframe"; (3) heatmaps showing S/R clustering, with brighter red for stronger confluence; (4) automated anchoring of indicators to the highest high, lowest low, recent gaps and similar points; (5) automated candlestick pattern recognition, single and multi-candle; (6) automated gap detection, where trendlines are not drawn across gaps and islands are shown as bars. — [TrendSpider Help: Types of Automated Analysis](https://help.trendspider.com/kb/charting/types-of-automated-analysis)
- **Chart patterns: exactly 13 are auto-recognized.** Ascending, descending and symmetrical triangles; double top; double bottom; horizontal, ascending and descending channels; head and shoulders; inverse head and shoulders; rising wedge; falling wedge; cup and handle. Each has tunable parameters (Time Span, Retracement, Depth, Deviation, Bands, Head Height, and ATR or percentage peak distance). — [TrendSpider Help: Automated Chart Pattern Recognition](https://help.trendspider.com/kb/automated-technical-analysis/automated-chart-pattern-recognition)
- Documented limitations of chart pattern detection: **alerts and backtesting are not supported** (the suggested workaround is to paint a Ray and alert on it). Painted patterns do not update in real time. A pattern seen earlier can disappear when the chart is reopened if the engine no longer considers it relevant. Patterns that are too early, already played out, or no longer respected are filtered out. Scanner results can include false positives or negatives unless "Current Candle" is enabled. Cup and handle detection ignores trend direction. Patterns *can* be scanned on any market, chart type and timeframe. — [same help page](https://help.trendspider.com/kb/automated-technical-analysis/automated-chart-pattern-recognition)
- Candlestick patterns: TrendSpider's help center says it supports "more than 100" auto-recognized candlestick patterns, drawing on The Strat, Tom Bulkowski's Pattern Site and Newsome Candles (seen in search snippets; the candlestick help page itself returned 404 when fetched). — [TrendSpider Help: Automated Technical Analysis](https://help.trendspider.com/kb/automated-technical-analysis). An affiliate review claims "over 150 unique candlestick patterns" and "220+ charts and indicators" (review updated 20 Aug 2025). — [GreatWorkLife](https://www.greatworklife.com/trendspider-review/). Another review says "400+ pre-built technical indicators" and "700+ pre-built Smart Watch Lists" (updated 29 Oct 2026). — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review). The indicator counts conflict between sources, and TrendSpider's own count was not found.
- Heatmaps come in three types per the TrendSpider docs: Horizontal, Depth and Trends (search snippet). — [TrendSpider Help: Automated Technical Analysis](https://help.trendspider.com/kb/automated-technical-analysis)
- Raindrop Charts are a proprietary chart type. TrendSpider auto-detects 4 Raindrop patterns (Raindrop/Balloon, Raindrop/Blue Doji, Raindrop/Double Flip, Raindrop/Flip) on timeframes from 10 minutes up to 1 month (search snippet of the official doc). — [TrendSpider Help: Raindrop Chart Pattern](https://help.trendspider.com/kb/raindrop-charts-tm/raindrop-chart-pattern)
- MTFA plots trendlines and indicators from a secondary timeframe onto the current chart. Primary-timeframe lines are solid and secondary ones dashed (search snippet). — [TrendSpider Help: Multi-Timeframe Analysis](https://help.trendspider.com/kb/charting/multi-timeframe-analysis)
- The AVWAP indicator can auto-anchor to configurable points, for example the highest-volume candle in a range, and MTFA can show distant anchored VWAPs (such as YTD) on intraday charts. A TrendSpider blog post acknowledged a display bug: an AVWAP anchored mid-period on daily looks shifted to the next candle on weekly or monthly charts, with a fix announced (date not determined). — [TrendSpider Blog: anchored indicator MTF update](https://trendspider.com/blog/upcoming-software-update-improved-anchored-indicator-multi-timeframe-support/); [TrendSpider Blog: Automated Anchored VWAP](https://trendspider.com/blog/automated-anchored-vwap/)
- A seasonality widget shows historical performance and win rate by month. Blog case studies use it alongside AVWAP. — [TrendSpider Blog: BTC case study](https://trendspider.com/blog/btc-daily-candle-case-study-anchored-vwap-volume-by-price-and-seasonality/). Seasonality reached the iOS app in v1.7.0 (01 Feb 2024). — [App Store](https://apps.apple.com/us/app/trendspider/id1564875289)
- Accuracy claims: a search summary attributed "correctly flagged 34 of 40 chart setups in a 30-day test" to GreatWorkLife, but the fetched page contains no such test or method. It describes no structured protocol and gives a self-contradictory score (4.8/5 and "9 out of 10"). Treat the 34/40 figure, and the "95% recognition accuracy" seen in other affiliate snippets, as **unverified**. — [GreatWorkLife](https://www.greatworklife.com/trendspider-review/)
- A skeptical review argues that much of TrendSpider's "AI" is conventional rule-based automation, not learning models (search snippet). — [BeginnersInAI](https://beginnersinai.org/trendspider-ai-review/)

### Inferences
- The 13-pattern chart engine, which cannot drive alerts or backtests and may hide earlier patterns, is a concrete gap a competitor can close. Recognizing more patterns (flags, pennants, rectangles, broadening formations), with alertable and backtestable pattern events and a non-repainting, timestamped pattern log, would beat it on paper.
- "Auto trendline" and "auto Fibonacci" are deterministic algorithms (swing-point selection), so a competitor can match them with pivot-based logic. TrendSpider's moat is UX polish and seven-plus years of tuning, not proprietary data.

### Gaps
- No official count of candlestick patterns beyond "more than 100", and the candlestick help page returned 404.
- No official or independent precision/recall figures for pattern or trendline detection.
- Whether the AVWAP higher-timeframe bug fix shipped, and when, was not confirmed.

---

## 2. Scanning (Market Scanner)

### Takeaway
Scans are built visually from Any/All/None condition groups using technical, fundamental (162+ metrics) and pattern conditions. A scan is **capped at 3,000 symbols from combined lists**: you cannot scan the whole market in one pass. Scans **do not auto-refresh** (refresh is manual). Plans allow 3 to 10 scheduled scans, and the minimum scan timeframe depends on the plan (2 h, 5 m or 1 m).

### Cited Findings
- Scans combine technical and/or fundamental criteria with Any, All and None groups, and output a dynamic Smart Watchlist. Scripts move between Market Scanner, Multi-Factor Alerts and Strategy Tester through templates. "Find symbols now" uses free AI visual scripting; "Run in Sidekick" costs a message. — [TrendSpider Help: Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html)
- Coverage: **you cannot scan every stock at once**. The FAQ recommends lists such as the S&P Composite 1500, Russell 2000 and NASDAQ NMS Composite, combinable **up to 3,000 symbols**. Built-in lists exist for sectors and industries, futures, crypto and forex. Scans can use Traditional, Heikin Ashi, Raindrop or Line candles, plus extended hours. **162+ fundamental metrics** can be scanned. — [Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html)
- Refresh: "Scanners do not auto-refresh". Users refresh manually or by changing the ticker. "Current Candle" mode scans the forming candle in real time. — [Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html)
- Scheduled scans are delivered to the inbox: Standard 3, Premium 5, Enhanced 7, Advanced 10. Minimum scanning timeframe: Standard 2 h, Premium 5 m, Enhanced and Advanced 1 m. — [TrendSpider Pricing](https://trendspider.com/pricing/). Since March 2026, an add-on of +10 scheduled scans costs $14/month. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
- Multi-timeframe scans (conditions on a short and a long timeframe together) are described in older help content (search snippet). — [TrendSpider Help: Multiple Timeframes & the Current Candle](https://trendspider.reamaze.com/kb/scanner/multiple-timeframes-and-the-current-candle)
- Since September 2025, Sidekick AI can design and run scans and iteratively refine them when a scan returns nothing. — [Sept 2025 changelog](https://trendspider.com/blog/september-2025-changelog/); [Scanning with Sidekick](https://trendspider.com/blog/scanning-the-markets-with-sidekick-ai/). Since October 2026, Sidekick answers purely fundamental screens by querying fundamental data directly instead of running a scan, "almost instantly". — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- Options-powered scans were added with the OPRA feed in March 2026. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
- An independent user (Trustpilot, 9 Nov 2026) called the scanners "the best". — [Trustpilot](https://www.trustpilot.com/review/trendspider.com)

### Inferences
- A competitor scanning the full NSE plus BSE cash universe (about 5,000 symbols or more) in one pass, with automatic or streaming refresh, would beat TrendSpider on two documented limits: the 3,000-symbol cap and manual refresh.

### Gaps
- No published scan latency (seconds per 1,000 symbols) or maximum results per scan.
- Scheduled-scan frequency options were not stated.

---

## 3. Backtesting: Strategy Tester, Group Strategy Tester, ML Quant Lab (formerly AI Strategy Lab)

### Takeaway
The Strategy Tester is a no-code, single-timeframe, long-*or*-short backtester. It fills at the next bar's open, **assumes zero slippage** with only a flat per-trade cost setting, and assumes the account can always afford entries (no capital or position-sizing model). Depth is capped by plan at 2K, 10K, 20K or 30K candles. 2026 additions are Group (multi-symbol) testing in July, AI strategy building in Sidekick in June and September, and **Monte Carlo (10,000 sims) in October 2026**. ML Quant Lab (launched as AI Strategy Lab on 19 Nov 2024; renamed July 2026) trains classic ML classifiers (Random Forest, KNN, Naive Bayes, Logistic Regression). There is **no independent evidence of its live or out-of-sample quality**, and one independent reviewer found most of their lab strategies flagged "unacceptable".

### Cited Findings
**Strategy Tester mechanics (official help, undated page):**
- Visual, no-code. Markets: stocks, futures, crypto, forex, OTC. **Not supported: indices and options**. History depends on the symbol and feed, "often back to the symbol's first trading date." — [TrendSpider Help: Understanding Strategy Tester](https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider). *Conflict:* the March 2026 changelog says the new OPRA options data "works in ... backtesting". — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/). The help page probably predates March 2026.
- **One timeframe per test.** Multi-timeframe logic needs a custom indicator that paints higher-timeframe data. Depth is set by candle count or date range, not both. — [Strategy Tester help](https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider)
- Exits: script conditions, entry invalidated, candles passed (time exit), TP, SL and trailing stop (in %, price units or ×ATR(7)), or an external "list of signals". **Long or short, not both in one strategy.** Conditions are checked at the close and filled at the **next candle's open** by default. Heikin Ashi or Raindrop conditions are filled on raw OHLC. TP/SL can be evaluated on close (matching bots) or as limit-style fills. — [Strategy Tester help](https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider)
- Stated assumptions: $0 broker fees unless "Trade Costs" (a per-trade cost) is set; **"perfect execution and zero slippage"**; the tester "assumes you can always afford an entry, regardless of prior losses." The page does not cover position sizing or capital allocation, walk-forward testing, or out-of-sample testing. Results export to CSV or TSV. — [Strategy Tester help](https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider)
- Plan limits (Nov 2026), as minimum backtest timeframe and depth in candles: Standard 2 h / 2K; Premium 5 m / 10K; Enhanced 1 m / 20K; Advanced 1 m / 30K. Symbols per variance (group) test: 50 / 150 / 250 / 510. Upgrading Standard or Premium depth to 20K costs $39/month. — [TrendSpider Pricing](https://trendspider.com/pricing/)

**2026 additions (official changelogs):**
- **Group Strategy Tester**, July 2026 (replaces Variance Explorer): backtests one strategy across a watchlist or portfolio to check robustness. Variant caps were raised; the new numbers were not stated. — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/); [Group Strategy Tester post, 22 Jul 2026](https://trendspider.com/blog/group-strategy-tester/)
- **Monte Carlo**, October 2026: a band of likely equity curves from **10,000 randomized trade mixes** that preserve win rate, average return and R/R. The returns distribution is shown Volume-by-Price style. The bot status popup now compares the live bot with its backtest (trade count, win rate, average return). Bot exit arrows use chart-derived prices, "not actual fills". — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- **Sidekick agentic strategy builder**, September 2026: generates several strategy ideas, backtests them in parallel, optimizes entries and then exits, and ranks the results. Strategy tiles show net performance, positions, win %, R/R, max drawdown and expectancy. Sidekick-built strategies are kept 30 days unless saved. It can backtest ideas the Tester can't express by fetching data and coding a signal list (example: "buy MSFT whenever a Republican buys"). — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/). In October 2026 the claimed strategy-discovery speed was "~400 strategies per 5 minutes" in Deep Research. — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- The June 2026 changelog lists a "Full AI Strategy Builder from a single prompt". — [Software updates index](https://trendspider.com/blog/category/software-updates/)

**ML Quant Lab (AI Strategy Lab):**
- Launched **19 Nov 2024** as point-and-click training of custom models on US stocks, ETFs, futures, crypto and forex. Algorithms: Random Forest, Naive Bayes ("Native Bayesian" in the release), KNN and Logistic ("Logarithmic") Regression, with "cross-breeding" (ensembling). Outputs are entry signals and risk-controlled exits, usable in backtests, charts, scanners, alerts and bots. **No quantified performance claims.** A model marketplace was announced as planned. — [PR Newswire](https://prnewswire.com/news-releases/trendspider-launches-ai-strategy-lab-to-empower-investors-to-build-custom-ai-powered-trading-models-with-ease-302306657.html)
- Renamed **ML Quant Lab** in July 2026 with "functionality unchanged". — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/)
- Quality assessment (official help): validation runs use an 80/20 train/test split, once with the first 20% as test and once with the last 20%. There is a Confidence-vs-Win% chart (0–100% in 8% steps), a minimum viable win rate derived from R/R (e.g. 3.0 R/R ⇒ ~25%), red/orange/green zones (green = at least 5 points above minimum), a random-signal baseline, and a "conclusiveness" test: 50%-confidence lines about 3% apart is good, about 10% apart means the model likely captured noise. The help page explicitly warns that test-set results are biased when automated optimization picks the model, and recommends true out-of-sample backtests on excluded periods or symbols. It reports no accuracy, precision, recall or AUC. — [TrendSpider Help: Assessing quality of models](https://help.trendspider.com/kb/ai-strategies/creating-an-ai-strategy-5-assessing-quality-of-models)
- **Independent evidence:** StockBrokers.com (28 Jul 2026) found that "most strategies the reviewer built were flagged as unacceptable in the lab". — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). No independent out-of-sample or live-trading study of ML Quant Lab models was found. Liberated Stock Trader's "most powerful tool" description is promotional language, not measured evidence (search snippet). — [Liberated Stock Trader: custom AI trading models](https://www.liberatedstocktrader.com/custom-ai-trading-models/)

### Inferences
- For an Indian-market tool, beatable points are:
  - realistic Indian cost modeling (STT, exchange transaction charges, SEBI fee, stamp duty, GST, brokerage) instead of a flat per-trade cost;
  - configurable slippage;
  - native multi-timeframe conditions;
  - long and short in one strategy;
  - capital and position sizing;
  - walk-forward or out-of-sample splits built into the tester.

  TrendSpider documents none of these.
- TrendSpider's ML stack is classic tabular classifiers with honest validation tooling. Its documented "conclusiveness" heuristics are a reasonable bar to match.

### Gaps
- No published total of years of intraday history per asset class. One affiliate review claims "up to 50+ years" of stored history, which was not verified officially. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- Exact Strategy Tester metric list not published on the help page (Sidekick tiles show net performance, win %, R/R, max DD, expectancy).
- No independent backtest-accuracy audit (for example, comparing fills against a reference engine).

---

## 4. Automation: Strategy Bots, broker integrations, webhooks, alerts

### Takeaway
"Trading Bots" were renamed "Strategy Bots" in March 2026. Bots run a backtested strategy on a chosen timeframe and send webhooks. Live execution goes through **SignalStack**, TrendSpider's separate webhook-to-broker router (32 brokers and exchanges listed; paid by signal volume, with 5 free signals/month). **No Indian broker is on the SignalStack list.** An in-app Trading Widget (beta) now allows manual order entry through SignalStack, so the old "no direct order entry" complaint is only partly true.

### Cited Findings
- Bots per plan: Standard 5, Premium 10, Enhanced 50, Advanced 100. Active alerts: 10 / 50 / 100 / 400, with history of 30 / 90 / 180 / 365 days. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- Bots are configured with a backtested strategy and a timeframe. Notifications can be webhooks: an HTTP POST with JSON (symbol, buy/sell, quantity) to a broker-specific SignalStack URL, which converts it into a broker order. Evaluation timing relative to candle close is not stated on that page. — [TrendSpider Help: Connecting SignalStack with Strategy Bots](https://help.trendspider.com/kb/trading-bots/connecting-signalstack-with-trendspider-bots)
- Renamed to "Strategy Bots" in March 2026. Alerts can also be created without a trigger limit, staying active until expiry. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
- Sidekick can view and start bots but **cannot create a bot that places trades**: the user must attach a webhook manually (September 2026). — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/). The Sidekick page says it "does not independently place, modify, or close trades." — [Sidekick product page](https://trendspider.com/product/sidekick-ai-trading-assistant/)
- **SignalStack brokers (32, Nov 2026):** Alpaca, AutoShares, Binance, BingX, BitGet, Bybit, Capital.com, Charles Schwab, Coinbase Pro, cTrader, E*Trade, Forex.com, FXOpen, Gemini, Interactive Brokers, Ironbeam, Kraken, Lightspeed, Lime, MetaTrader5, Oanda, Optimus Futures, Phemex, Public.com, Robinhood, TastyTrade, Tiger Brokers, TradeStation, TradeZero, Tradier, Trading212, WeBull. — [SignalStack Pricing](https://signalstack.com/pricing/). No Zerodha, Upstox, Angel One, Dhan, Fyers or other Indian broker appears. Interactive Brokers is listed, but whether IBKR India or NSE routing via SignalStack works was not verified.
- **SignalStack pricing:** Free (5 signals/month); Basic $27/month (50 signals); Premium $97/month (250); Pro $340/month (1,000). Unlimited paper signals; unused signals expire monthly. It claims orders are sent "in less than .45 seconds" and "99.99%" uptime (vendor claims, not verified). — [SignalStack Pricing](https://signalstack.com/pricing/). The November 2026 TrendSpider Black Friday bundles 3–5 months of SignalStack Pro and Sidekick Plus. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- **Trading Widget (beta):** manual Buy/Sell orders as Market, Limit or Stop, with quantity and optional SL/TP, from a chart. You can view and close positions and pending orders. Supported assets are stock, OTC stock, ETF and crypto spot only. Executed orders are not shown on charts. Holdings can lag up to 1 minute. Routing typically takes **~0.3 s, but up to 12 s** for some brokers in rare cases. — [TrendSpider Help: Trading Widget](https://trendspider.reamaze.io/kb/right-sidebar/trading-on-platform). In September 2026 the widget was redesigned to list all supported brokers when none is connected. — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/)
- Alert delivery channels: text (SMS), email, push, in-app and webhooks (affiliate review). — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review). StockBrokers.com notes email and text notifications for bots. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)
- Dynamic alerts on drawn objects: the documented workaround for chart patterns is to "paint a Ray ... and set an alert on that line", which implies trendline and drawing alerts exist. — [Chart Pattern help](https://help.trendspider.com/kb/automated-technical-analysis/automated-chart-pattern-recognition). Multi-Factor Alerts share the visual condition builder with the Scanner and Tester. — [Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html)
- Independent comparison: TradingView offers up to 1,000 alerts versus TrendSpider's maximum of 400. The reviewer found "charts and alert functions are not user-friendly". — [StockBrokers.com, 28 Jul 2026](https://www.stockbrokers.com/review/tools/trendspider)

### Inferences
- TrendSpider's automation is a two-product, two-subscription chain (TrendSpider plus SignalStack signal quotas). A competitor with native broker APIs (e.g., Zerodha Kite Connect, Upstox, Dhan) and no per-signal metering would be simpler and cheaper, and would cover the Indian brokers TrendSpider cannot reach.
- Published latency figures to beat: about 0.3 s typical routing (official), with SignalStack's claim of under 0.45 s.

### Gaps
- Whether bots evaluate on candle close only or intrabar was not confirmed on the fetched pages. The October 2026 changelog's "TP/SL on candle close (matching Strategy Bots)" suggests candle-close evaluation by default.
- No independent measurement of bot latency or reliability.

---

## 5. AI features: Sidekick and other 2024–2026 additions

### Takeaway
Sidekick launched in August 2025 and has become an agentic LLM assistant wired to TrendSpider's data and tools. It reads charts, runs scans, does multi-symbol Deep Research, codes indicators, builds and backtests strategies, sets alerts, manages watchlists, and reads SignalStack holdings. Usage is metered: 25 free messages/month on every plan, then $49, $129 or $349/month add-ons. TrendSpider makes no accuracy claims and warns that outputs can be wrong.

### Cited Findings
- Timeline (official):
  - Nov 2024: AI Strategy Lab. — [PR Newswire](https://prnewswire.com/news-releases/trendspider-launches-ai-strategy-lab-to-empower-investors-to-build-custom-ai-powered-trading-models-with-ease-302306657.html)
  - Aug 2025: Sidekick officially released on web and mobile. — [Aug 2025 changelog](https://trendspider.com/blog/august-2025-changelog/)
  - Sept 2025: Sidekick designs and runs scans. — [Sept 2025 changelog](https://trendspider.com/blog/september-2025-changelog/)
  - Mar 2026: Deep Research (parallel sub-chat per symbol), agentic indicator coding, watchlist edits, and removal of Claude 3.7, Claude 4 and Gemini 2.5. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
  - Apr 2026: create watchlists. — [April 2026 changelog](https://trendspider.com/blog/april-2026-changelog/)
  - Jun 2026: full AI Strategy Builder from one prompt. — [Software updates](https://trendspider.com/blog/category/software-updates/)
  - Jul 2026: semantic search across all earnings-call transcripts, plus indicator calculations (SMA, EMA, RSI) inside Sidekick. — [Earnings-call search, 27 Jul 2026](https://trendspider.com/blog/sidekick-semantic-earnings-call-search/); [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/)
  - Sept 2026: agentic strategy builder. — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/)
  - Oct 2026: fundamental-only screens answered directly, Explain Indicator button, prompt cap raised from 3K to 4K characters. — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- **Deep Research costs** one message per request plus one per sub-chat that returns, with a cost confirmation shown first. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
- **Models (October 2026 lineup, as stated by TrendSpider):** Baseline: Gemini 3.1 Pro Preview, GPT 6 Luna, GPT 6.1 Sol, Claude Sonnet 4.6, Claude Sonnet 5.5. Frontier: Gemini 4 Argon, GPT 6 Astra, Claude Opus 5.5. — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/). The product page also lists Claude Haiku 5.5. — [Sidekick product page](https://trendspider.com/product/sidekick-ai-trading-assistant/). Model swaps happen almost monthly, for example Opus 5.0 replacing Opus 4.8 in July 2026 ([July changelog](https://trendspider.com/blog/july-2026-changelog/); [Opus 5 post, 29 Jul 2026](https://trendspider.com/blog/claude-opus-5-in-sidekickai/)) and GPT-6 Astra added 9 Oct 2026 ([post](https://trendspider.com/blog/gpt-6-astra-now-in-sidekick-ai/)).
- AI chart analysis: Sidekick reads the active chart (indicators, drawings, timeframe), explains setups and S/R, annotates charts, summarizes filings and earnings calls, and with SignalStack analyzes open positions only (no cash, pending orders or history). Data is fetched on request, not streamed. The page warns it "can misunderstand instructions, interpret data incorrectly". There are six "personalities". — [Sidekick product page](https://trendspider.com/product/sidekick-ai-trading-assistant/)
- A separate one-shot "Ai" feature, for example AI Visual Scripting that generates conditions from plain language, **does not consume Sidekick messages**. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/); [Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html)
- **Pricing:** every plan includes 25 messages/month. Sidekick Basic $49/month (100 messages), Plus $129/month (300, adds 3 frontier models), Max $349/month (1,000). A "message" is one request regardless of steps. — [TrendSpider Pricing](https://trendspider.com/pricing/); [Sidekick page](https://trendspider.com/product/sidekick-ai-trading-assistant/). *Inconsistency:* a pricing-page tooltip says "10 free messages per month". — [TrendSpider Pricing](https://trendspider.com/pricing/)
- **Independent:** StockBrokers.com used 18 messages "in a couple of hours" and called the identical 25-message allowance on Standard and Advanced "puzzling". It lists "Additional charge to regularly use the AI sidekick" as a con and "user-friendly agentic AI assistant" as a pro. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). A 1-star Trustpilot review (2 Nov 2026) alleges TrendSpider paid to appear as "recommended" in AI tools. This is an unverified allegation; TrendSpider replied asking for details. — [Trustpilot](https://www.trustpilot.com/review/trendspider.com)

### Inferences
- The 25-message free cap gets used up in hours of real use. That makes AI usage a significant hidden cost (up to $349/month on top of the plan). A competitor with uncapped local or low-cost LLM analysis, or with deterministic "explain this chart" output that needs no LLM, has a clear value angle.

### Gaps
- No benchmark of Sidekick answer accuracy, hallucination rate or latency, from either the vendor or independent testers.

---

## 6. Other data: options, options flow, dark pool, fundamentals, insider, news, earnings

### Takeaway
TrendSpider is now a broad US data terminal. It has real-time OPRA options with a chain and an "Options Map" heatmap (March 2026), unusual options flow, dark-pool/ATS volume, Reg SHO, insider and congressional trades, FRED, social sentiment, and full fundamentals from Fiscal.ai (since July 2026), including segment revenue and KPIs for about 1,500 large US companies. Nearly all of it is US-only.

### Cited Findings
- The Market Data library lists 28 categories, including Listed Equities, Options, Futures, Indices, Crypto, FX, Insider Trading, Unusual Options Flow, Reg SHO, Dark Pool ATS Volume, Market Breadth, Government Trading and Bring-Your-Own-Data (upload or API). Counts cited on the page include Listed Equities 28K+, US Options (OPRA) 1.5M+, FX 3.2K+, Indices 200+, Insider 8K+, FRED 3K+, News 20K+, Breadth 90K+ and Dark Pool ATS 1.2K+ (label pairing partly uncertain in the extraction), plus 84K+ real-time feeds, 11K+ delayed, 118K+ US and 43K+ global. — [TrendSpider Market Data](https://trendspider.com/marketdata/)
- **Options (March 2026):** real-time OPRA usable in charting, watchlists, scanning, backtesting, Smart Checklists and alerts. A new Options Chain panel, and an Options Map heatmap of Greeks, IV, OI and volume across expirations and strikes. Paid add-on; OPRA works on **one device at a time**. — [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/). Price is $9.50/month non-pro. — [TrendSpider Pricing](https://trendspider.com/pricing/). An options-focused affiliate review rates TrendSpider 3.5/5 for options traders (search snippet). — [PurePowerPicks](https://purepowerpicks.com/trendspider-review/). The chain refreshes roughly every 10 s (affiliate claim). — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- **Fundamentals:** the provider switched to **Fiscal.ai** in July 2026. The Segments & KPIs panel covers about 1,500 of the largest US companies. — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/). It became a full Fundamentals panel (income statement, balance sheet, cash flow, ratios) in September 2026. — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/); [Fundamentals post, 17 Sep 2026](https://trendspider.com/blog/ai-fundamental-analysis-tools-right-next-to-your-charts/). Earnings marks on charts show GAAP and non-GAAP figures. — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/)
- **News and alt data (affiliate source):** Benzinga Pro headlines, StockTwits and WallStreetBets sentiment, congressional disclosures, FINRA Reg SHO, dark pool/ATS. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review). Also reported: a "Pelosi portfolio tracker" and indicators using **Kalshi prediction-market data**. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)
- Sidekick has access to SEC filings, earnings transcripts, analyst data, insider transactions and options activity. — [Sidekick page](https://trendspider.com/product/sidekick-ai-trading-assistant/)

### Inferences
- A comparable Indian offering would need NSE F&O option chains with Greeks and OI heatmaps, FII/DII flows, bulk and block deals, SAST/insider (PIT) disclosures, delivery percentage, and corporate filings from NSE/BSE. These are the Indian analogues of TrendSpider's alternative-data stack, and TrendSpider has none of them.

### Gaps
- Exact dark-pool methodology (FINRA ATS weekly vs. TRF prints) and options-flow sweep/block logic were not documented in the fetched pages.

---

## 7. Market coverage, data source and delay (including India/NSE)

### Takeaway
TrendSpider is US-centric. It has real-time US equities/ETFs, global FX and crypto free for non-pro users, plus paid CME-group futures and OPRA options. **There is no NSE/BSE single-stock coverage.** An independent review states this explicitly, and TrendSpider's own pages name no Indian exchange.

### Cited Findings
- Free for non-pro users: real-time US equities and ETFs, global FX and global crypto. Paid: CME/NYMEX/COMEX/CBOT futures $7.50/month or $90/year (non-pro; **pro futures data not available**); OPRA options $9.50/month non-pro; pro US-equities fee $29/month. CBOE indexes are delayed 10–15 minutes. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- Coverage per an independent review (updated 29 Oct 2026): US equities and ETFs (NYSE, NASDAQ, AMEX), OPRA/CBOE options, CME Group and ICE futures, OTC/pink sheets, global FX, crypto and major global indices. **"Single-stock coverage on NSE India, LSE, TSX, and HKEX is not supported."** OTC and some index data delayed 10–15 minutes. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- TrendSpider's market-data page describes "most liquid tradable instruments" and 43K+ "global feeds" but **names no Indian exchange**. — [TrendSpider Market Data](https://trendspider.com/marketdata/)
- The ML Lab launch (Nov 2024) listed markets as "all US stocks, ETFs, futures, crypto pairs, and forex pairs". — [PR Newswire](https://prnewswire.com/news-releases/trendspider-launches-ai-strategy-lab-to-empower-investors-to-build-custom-ai-powered-trading-models-with-ease-302306657.html)
- About 2,400 crypto tickers were added in July 2026, including Hyperliquid perps (e.g., WTIUSDC), OKX and Deribit indexes, and margin funding rates. — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/)
- Extended-hours data is available (4 am to 8 pm ET Extended Session indicator, September 2026). — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/)

### Inferences
- For an Indian-market platform, TrendSpider is not a direct substitute. An Indian trader would need TradingView or a broker terminal for NSE data. The competitive comparison is therefore about **features and UX** to emulate, not about the same user base.
- Major global indices may include NIFTY 50 or SENSEX as index symbols. This is unconfirmed.

### Gaps
- No official statement on whether Indian index symbols (NIFTY 50, SENSEX, BANKNIFTY) are available as index or CFD-style feeds.
- The equity data vendor (exchange-direct vs. consolidated SIP vendor) was not identified on the fetched pages.

---

## 8. Platforms and performance (web, desktop, mobile)

### Takeaway
TrendSpider is a browser-first web app with no native desktop app identified. The iOS app is rated 4.3/5 (350 ratings) but historically lagged the web: its last listed version was 1.7.15 on 3 Dec 2025, and users complain of cramped layouts and missing drawing tools. Sidekick and scanning work on mobile. No latency or speed benchmarks are published.

### Cited Findings
- iOS app: 4.3/5 from 350 ratings. Free, iPhone only, 19.2 MB, iOS 15.1 or later. Latest version 1.7.15 (03 Dec 2025, "technical improvements"). Sidekick came to mobile in 1.7.11 (19 Aug 2025), AI Strategy Lab, fundamentals, congressional trading and CME spreads in 1.7.8 (09 Jan 2025), and seasonality, insider data and full indicator support in 1.7.0 (01 Feb 2024). — [App Store](https://apps.apple.com/us/app/trendspider/id1564875289)
- iOS complaints: the iPad app is "largely unusable with Apple Pencil" and uses a fraction of a 12.9" screen (17 Dec 2023). The iPhone chart area is small, drawing tools are missing and scaling is glitchy, and the user switched to TradingView (15 Mar 2022). The app is "far inferior to the website" (07 Nov 2021). A user could not trade from the app (05 Jun 2023). The app description does not mention bots or order execution. — [App Store](https://apps.apple.com/us/app/trendspider/id1564875289)
- Android: Google Play ratings conflict (4.2 vs. 4.7 across third-party sources; unverified). Users report the app feels cramped and sub-charts are hard to adjust on Android (search snippet). — [Tooliverse](https://tooliverse.ai/tools/trendspider)
- Sept 2026: Sidekick can run real scans on mobile, with a progress bar on mobile and desktop. — [Sept 2026 changelog](https://trendspider.com/blog/september-2026-changelog/)
- Workspaces per plan: 5 / 10 / 15 / 20. Minimum charting timeframe is 1 minute on all plans. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- "Not suited to scalping or HFT … no Level 2 or sub-second execution workflow … not direct market access." — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- A user review reports a limit of 2 concurrent logged-in TrendSpider tabs (search snippet, unverified). — [Techjockey](https://www.techjockey.com/us/reviews/trendspider)
- StockBrokers.com found the home screen crowded, with "even two charts felt like 'too much'". — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)

### Inferences
- The minimum chart timeframe is 1 minute with no tick or seconds charts and no Level 2. A competitor offering tick, seconds or market-depth views for NSE would exceed it for intraday traders.

### Gaps
- No measured page-load, chart-render or scan-speed numbers were found from any source.
- The current Google Play rating could not be verified.

---

## 9. Pricing as of November 2026

### Takeaway
There are four plans with identical features, differing only in limits. Regular list prices are about **$54–$89/month (Standard) up to $214–$349/month (Advanced)**, with the lower figure for annual billing. A Black Friday promotion (10–27 Nov 2026) cuts first-year prices to $32.94–$74.90/month. Real-time futures and options data, extra Sidekick messages, SignalStack signals, extra scheduled scans and deeper backtests are all separate add-ons. There is no free plan.

### Cited Findings
- Plan limits (Standard / Premium / Enhanced / Advanced):

  | Limit | Standard | Premium | Enhanced | Advanced |
  |---|---|---|---|---|
  | Workspaces | 5 | 10 | 15 | 20 |
  | Live bots | 5 | 10 | 50 | 100 |
  | Active alerts (history) | 10 (30 d) | 50 (90 d) | 100 (180 d) | 400 (365 d) |
  | Minimum backtest timeframe / depth | 2 h / 2K | 5 m / 10K | 1 m / 20K | 1 m / 30K |
  | Symbols per variance test | 50 | 150 | 250 | 510 |
  | Minimum scan timeframe | 2 h | 5 m | 1 m | 1 m |
  | Scheduled scans | 3 | 5 | 7 | 10 |
  | Sidekick messages/month | 25 | 25 | 25 | 25 |
  | Free 1-on-1 training/year | 1 | 2 | 3 | up to 52 |

  All plans have the same features and market data. Extra training costs $49/session. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- Black Friday (page live 10–15 Nov 2026), first-year monthly: Standard $32.94 (was $82), Premium $45.50 (was $137), Enhanced $52.46 (was $183), Advanced $74.90 (was $321), "up to 65% off". The 7-day trial is $7 (regularly $19 / $29 / $39 / $49). The bonus is 5 months of Sidekick Plus and SignalStack Pro (value listed at $2,345). Renewal "was" ranges: $54–89, $91–149, $122–199, $214–349. Promotional sales are final and non-refundable. — [TrendSpider Pricing](https://trendspider.com/pricing/)
- StockBrokers.com (28 Jul 2026), monthly / annual: Standard $82 / $648 (= $54/month); Premium $137 / $1,092 ($91/month); Enhanced $183 / $1,464 ($122/month); Advanced $321 / $2,568 ($214/month). It rates Cost 2.5/5. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). *Conflict:* DayTradingToolkit labels $82–$321 as "annual billing" rates. The pricing page's renewal ranges ($54–$89 etc.) suggest $54 is the annual rate and $82–$89 the monthly rate. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- Refunds: 72 hours after the initial full charge, minus the trial fee. Trial fees are non-refundable. Downgrades take effect at the end of the cycle. Failed payments get a 72-hour grace period plus 4 weeks of retries. The FAQ says "14-day paid trial" while the cards say 7 days (inconsistency on the page). — [TrendSpider Pricing](https://trendspider.com/pricing/)
- Add-ons:
  - Futures data $7.50/month
  - OPRA options $9.50/month
  - Pro equities $29/month
  - Backtest depth upgrade to 20K: $39/month
  - +10 scheduled scans: $14/month ([March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/))
  - Sidekick $49 / $129 / $349 per month
  - SignalStack $27 / $97 / $340 per month ([SignalStack](https://signalstack.com/pricing/))
  - Third-party indicators, scanners and strategies in the TrendSpider Store (prices not listed). — [TrendSpider Pricing](https://trendspider.com/pricing/)

  A 1-star Trustpilot review (Nov 2026) complains that "standard professional indicators each require an extra subscription". — [Trustpilot](https://www.trustpilot.com/review/trendspider.com)
- For comparison, TradingView starts at $14.95/month. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)

### Inferences
- A realistic "full automation" stack at regular prices: Enhanced (~$122–$183/month) plus Sidekick Plus ($129) plus SignalStack Premium ($97) plus options ($9.50) comes to roughly **$360–$420/month**. The Indian platform can position against this.

### Gaps
- Exact current monthly-billing list prices outside the promotion are ambiguous ($82 vs. $89 for Standard); see the conflict above.

---

## 10. Strengths, weaknesses and recurring user complaints

### Takeaway
TrendSpider is consistently praised for automated chart analysis, no-code backtesting and scanning, fast shipping (monthly changelogs) and very responsive support (Trustpilot 4.8/5). The consistent complaints are price and add-on stacking, learning curve and dense UI, metered AI, alert and charting UX that trails TradingView, a weaker mobile app, US-only coverage, and automation that depends on the separate SignalStack product.

### Cited Findings
- **Ratings:** StockBrokers.com overall 4.0 (Ease 4, Features 5, Cost 2.5), 28 Jul 2026. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). DayTradingToolkit 8.2/10 (Charting/AI 9.0, Backtesting 8.5, Ease 7.0, Value 7.5), affiliate. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review). GreatWorkLife 4.8/5 (affiliate, no disclosure, internally inconsistent). — [GreatWorkLife](https://www.greatworklife.com/trendspider-review/)
- **Trustpilot:** 4.8/5 from 942 reviews (Nov 2026): 89% 5-star, 3% 4-star, 2% 3-star, 2% 2-star, 4% 1-star. Praise centres on named support staff and fast responses, including weekends. Negative themes are add-on charges for indicators and subscription terms. — [Trustpilot](https://www.trustpilot.com/review/trendspider.com). An earlier snapshot showed 4.8 from 926 reviews (search summary, 2026).
- **Price:** "Pricey services and no free trial." — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). Price and learning curve are "the biggest complaints". — [Techjockey / search summary](https://www.techjockey.com/us/reviews/trendspider)
- **Learning curve:** "can be complicated to understand for inexperienced traders". — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). Estimated 2–4 weeks to full proficiency. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- **UX:** "Charts and alert functions are not user-friendly", and TradingView has the better charting and alert experience. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider). In October 2026 TrendSpider hid some chart buttons and switched to the OS font, a sign of ongoing declutter work. — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- **AI metering:** the same 25 messages on every plan; extra use costs more. — [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)
- **US-centric:** "not worth it if you trade non-US equities". — [search summary of reviews](https://completetradersedge.com/trendspider-review/); [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- **No direct order entry:** this has historically been true (App Store review, 2023). It is now partly addressed by the beta Trading Widget via SignalStack (stocks, ETFs and crypto spot only). "Older complaints about missing broker integration are described as no longer accurate." — [App Store](https://apps.apple.com/us/app/trendspider/id1564875289); [Trading Widget help](https://trendspider.reamaze.io/kb/right-sidebar/trading-on-platform); [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review)
- **Bugs:** no systematic bug reports were found. Documented quirks are the AVWAP higher-timeframe anchoring display ([blog](https://trendspider.com/blog/upcoming-software-update-improved-anchored-indicator-multi-timeframe-support/)), "several chat freeze issues fixed" in Sidekick in March 2026 ([March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)), and chart patterns disappearing on reload ([Chart Pattern help](https://help.trendspider.com/kb/automated-technical-analysis/automated-chart-pattern-recognition)).
- **Missing community:** no social trading community. — [GreatWorkLife](https://www.greatworklife.com/trendspider-review/)

### Inferences
- Trustpilot's 4.8 is heavily support-driven. Many reviews name individual agents and coincide with renewal help, which suggests solicited reviews; this is an inference. Independent editorial ratings are lower (about 4.0/5) and penalize cost the most.

### Gaps
- Reddit (r/Daytrading, r/algotrading, r/StockMarket) sentiment could not be retrieved because the domain is blocked for the research tool. No forum-sourced bug or complaint quotes are included.
- Liberated Stock Trader's 2026 review (a "58-point hands-on test") returned HTTP 403, so its scores were not captured.

---

## 11. Measurable benchmarks a competitor could match or beat

### Takeaway
TrendSpider publishes few performance numbers. The benchmarks below are concrete figures, mostly limits and capacity, that a developer can treat as targets.

### Cited Findings
- **Chart patterns:** 13 auto-recognized, not alertable or backtestable. — [help](https://help.trendspider.com/kb/automated-technical-analysis/automated-chart-pattern-recognition)
- **Candlestick patterns:** 100+ official (150+ claimed by an affiliate). — [help](https://help.trendspider.com/kb/automated-technical-analysis); [GreatWorkLife](https://www.greatworklife.com/trendspider-review/)
- **Raindrop patterns:** 4 types, on timeframes from 10 minutes to 1 month. — [help](https://help.trendspider.com/kb/raindrop-charts-tm/raindrop-chart-pattern)
- **Scanner:** at most 3,000 symbols per scan, manual refresh, 162+ fundamental metrics, 3–10 scheduled scans, minimum timeframe 1 m on top plans. — [Scanner FAQ](https://help.trendspider.com/kb/scanner/market-scanner-faq-markdown-html); [Pricing](https://trendspider.com/pricing/)
- **Backtest:** 2K / 10K / 20K / 30K candles; single timeframe; zero slippage; flat per-trade cost; next-bar-open fills; no position sizing. Monte Carlo uses 10,000 simulations. Group test covers 50–510 symbols. — [Strategy Tester help](https://help.trendspider.com/kb/strategy-tester/understanding-strategy-tester-from-trendspider); [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/); [Pricing](https://trendspider.com/pricing/)
- **AI strategy search:** about 400 strategies per 5 minutes (vendor claim). — [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- **ML:** 4 classic algorithms; 80/20 validation; conclusiveness threshold of about 3% (good) vs. about 10% (noise). — [PR](https://prnewswire.com/news-releases/trendspider-launches-ai-strategy-lab-to-empower-investors-to-build-custom-ai-powered-trading-models-with-ease-302306657.html); [help](https://help.trendspider.com/kb/ai-strategies/creating-an-ai-strategy-5-assessing-quality-of-models)
- **Alerts:** 10–400 active (vs. TradingView's 1,000). **Bots:** 5–100. — [Pricing](https://trendspider.com/pricing/); [StockBrokers.com](https://www.stockbrokers.com/review/tools/trendspider)
- **Order routing:** about 0.3 s typical, up to 12 s worst case (official); SignalStack claims under 0.45 s and 99.99% uptime. Holdings lag up to 1 minute. — [Trading Widget help](https://trendspider.reamaze.io/kb/right-sidebar/trading-on-platform); [SignalStack](https://signalstack.com/pricing/)
- **Options chain:** refresh about every 10 s (affiliate claim). OPRA limited to one device. — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/trendspider-review); [March 2026 changelog](https://trendspider.com/blog/march-2026-changelog/)
- **Sidekick:** 25 free messages/month; prompt cap 4K characters. — [Pricing](https://trendspider.com/pricing/); [Oct 2026 changelog](https://trendspider.com/blog/october-2026-changelog/)
- **Fundamentals:** segment and KPI data for about 1,500 US companies. — [July 2026 changelog](https://trendspider.com/blog/july-2026-changelog/)
- **Satisfaction:** Trustpilot 4.8 (942 reviews); iOS 4.3 (350 ratings). — [Trustpilot](https://www.trustpilot.com/review/trendspider.com); [App Store](https://apps.apple.com/us/app/trendspider/id1564875289)
- **Release cadence:** monthly changelogs throughout January–October 2026, with 12 software-update posts between 1 Jul and 31 Oct 2026 alone. — [Software updates index](https://trendspider.com/blog/category/software-updates/)

### Inferences
- The easiest wins for an Indian-market competitor, given TrendSpider's documented limits:
  - **coverage:** NSE/BSE plus F&O, which TrendSpider lacks entirely;
  - **automation:** native Indian broker execution without per-signal fees, since SignalStack's 32 brokers include no Indian ones;
  - **backtest realism:** Indian statutory costs, slippage, sizing, MTF conditions, and long plus short together;
  - **chart patterns:** more than 13, alertable and backtestable, with a stable non-disappearing pattern history;
  - **scanning:** full-universe and auto-refreshing (above 3,000 symbols);
  - **AI cost:** no hard 25-message cap.
- The hardest areas to match are breadth of US alternative data, polish, support quality, and the pace of shipping (monthly, with heavy LLM integration).

### Gaps
- No independent, methodology-backed benchmark of TrendSpider's pattern accuracy, scan speed, chart rendering speed or bot reliability was found.

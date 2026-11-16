# MetaTrader 4 / MetaTrader 5 (MetaQuotes): competitor profile as of November 2026

Research date: 11 November 2026. "Official" = MetaQuotes-owned sites (metatrader4.com, metatrader5.com, mql5.com, metaquotes.net). "Independent" = third-party press, reviews, forums. Facts older than 2026 are dated inline.

## Q1. Charting: chart types, timeframes, indicators, analytical objects, drawing tools, custom indicators, multi-chart layouts

### Takeaway
MT5 offers 21 timeframes, 38 built-in indicators, 44 analytical objects, 3 basic chart types (bars, candlesticks, line) and up to 100 open charts (official). MT4 offers 9 timeframes, 30 indicators and about 23 analytical objects. Both rely on MQL custom indicators and the MQL5 Market for anything beyond that. Chart rendering moved to the Blend2D engine in November 2025.

### Cited Findings
- MT5 (official): "38 technical indicators", 44 analytical objects (Gann, Fibonacci, Elliott tools, geometric shapes, channels), 21 timeframes, 1-minute history, "unlimited number of charts", indicators in 4 groups (Trend, Oscillators, Volume, Bill Williams) — [MetaTrader 5 technical analysis page](https://www.metatrader5.com/en/trading-platform/technical-analysis)
- MT5 chart types (official help): price charts "can be presented as a sequence of bars, Japanese candlesticks, and as a broken line" (3 types). "21 chart timeframes from one minute to one month". "you can open up to 100 charts at a time" (contradicts the "unlimited" marketing claim above). If no local history exists, "the latest 512 bars of history are downloaded". A "Max. bars on chart" setting caps displayed history — [MT5 Help: Charts](https://www.metatrader5.com/en/terminal/help/charts_analysis/charts)
- MT4 (official): 9 timeframes, 30 built-in technical indicators, 23 analytical objects. A gallery caption on the same page says "more than 65" indicators and analytical objects combined, so the page is internally inconsistent. MT4 also has a tick chart and a History Center (M1 to MN) — [MetaTrader 4 trading platform page](https://www.metatrader4.com/en/trading-platform)
- MT5 charts render with the Blend2D engine from Build 5430 (13 Nov 2025) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- iPhone/iPad app (27 Jun 2025 update) added the Heikin Ashi chart type, ZigZag and Market Profile indicators, a trading report, and deal info in the Data Window — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- Dark theme improvements came in Build 5640 (20 Feb 2026). The theme can follow Windows settings from Build 5200 (31 Jul 2025) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- The AI Assistant can add indicators to a chart and set their parameters (for example two MAs with periods 20 and 50) from Build 6180 (3 Sep 2026) — [MetaQuotes news: Build 6180](https://www.metaquotes.net/en/metatrader5/news/5555)
- Thousands of extra indicators are available through the Market and Code Base, but the official page gives no exact count — [MT5 technical analysis page](https://www.metatrader5.com/en/trading-platform/technical-analysis)
- User complaint (Trustpilot, anecdotal): one reviewer says MT5 charts look like they were drawn by hand. Another reports data or chart gaps compared with other platforms — [Trustpilot: metatrader5.com](https://uk.trustpilot.com/review/metatrader5.com)

### Inferences
- The native chart-type set is small: 3 types on desktop, with Heikin Ashi on iOS since mid-2025. Renko, Range, Kagi, Point & Figure and volume/footprint charts are not native in the cited docs and would need custom indicators or Market products. A competitor with native Renko, Heikin Ashi and footprint charts would beat MT5 here.
- The 21 timeframes are M1 to MN1 with non-standard intermediates. The official help does not list them in the page fetched; the commonly documented set is M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1. This list is from general knowledge, not verified in this session. MT4's 9 are M1, M5, M15, M30, H1, H4, D1, W1, MN (same caveat).
- Multi-chart layout means up to 100 tiled or cascaded chart windows plus saved templates and profiles. No evidence was found of synchronized crosshair or linked-symbol layouts as a first-class feature.

### Gaps
- No official count of drawing tools separate from "analytical objects".
- No confirmed native list of MT5 desktop chart types beyond the 3. I did not confirm whether Heikin Ashi was added to desktop or Android.
- I found no official documentation on synchronized multi-chart layouts or linked symbol groups.

## Q2. Automation: MQL4 vs MQL5, Expert Advisors, scripts, how automated trading is enabled and run, MetaQuotes VPS

### Takeaway
MQL5 is a C++-like, object-oriented language for Expert Advisors, indicators, scripts and services. In 2025-2026 MetaQuotes added linear-algebra (OpenBLAS), ONNX with CUDA, .NET CoreCLR import, Python package updates and native MCP/agentic AI. EAs run inside a desktop terminal, so 24/7 operation needs a VPS. MetaQuotes sells its own VPS from about USD 10-15 per month.

### Cited Findings
- MQL5 language additions, 2025-2026 (official release notes):
  - OpenBLAS expansion in Build 5200 (31 Jul 2025): reductions, Sylvester equations, norms, matrix classification.
  - Balancing, Hessenberg/Schur and eigenvector methods, the `using` operator and new method-hiding rules in Build 5260 (5 Sep 2025).
  - New `input(name=...)` syntax and Service programs in CodeBase in Build 5320 (25 Sep 2025).
  - ONNX loads on first use with CUDA support, GPU selection, profiling and new OpenBLAS methods, plus a 1 GB resource limit, in Build 5572 (29 Jan 2026).
  - Matrix file I/O, OpenBLAS factorizations and `SymbolInfoCommissions` in Build 6060 (23 Jul 2026).
  - Import of .NET CoreCLR 8+ assemblies and matrix/vector sorting in Build 6230 (24 Sep 2026).
  - Source: [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- Python package update (Build 6090, 30 Jul 2026) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- "Native MCP and agentic AI support in the terminal and MetaEditor" in Build 6060 (23 Jul 2026). More MCP methods (adding and listing indicators) followed in Build 6090 — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- MetaEditor improvements: Markdown view/edit (Build 5640, Feb 2026); structured table view for CSV (Build 5800, 16 Apr 2026); code folding and occurrence highlighting (Build 6060). "Algo Forge" (MetaQuotes' code-hosting/version-control service) was updated in Build 5260 — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- MT4 uses the MQL4 language with MetaEditor, a strategy tester and a library of free robots (official) — [MetaTrader 4 trading platform page](https://www.metatrader4.com/en/trading-platform)
- MetaQuotes VPS (official): the base price is about USD 15/month. One MQL5 page says USD 13/month on a 3-month plan and USD 10/month on an annual plan, with a full refund within 24 hours. A different MQL5 plans page shows USD 42 for 3 months and USD 153 for 12 months (about USD 12.8/month), so the tables conflict — [MQL5 VPS plans](https://www.mql5.com/en/vps/free-forex-vps); [MQL5 VPS forex plans](https://MQL5.com/en/vps/forex-plans); [MQL5 cheap VPS pricing](https://MQL5.com/en/vps/cheap-forex-vps-pricing)
- The VPS is ordered from inside the platform, and MetaQuotes "automatically offers an optimal server, which is located closest to your broker" (vendor claim; no measured latency published) — [How MetaTrader VPS works](https://www.metatrader5.com/en/news/2300)
- Third-party MT4/MT5 VPS hosts advertise lower prices, for example from USD 2.87/month (unverified) — [MassiveGRID MT5 VPS](https://massivegrid.com/mt5-vps/)
- User complaint: one reviewer says you cannot run an EA and an indicator "in the background", which makes clean charts hard — [Trustpilot: metatrader5.com](https://uk.trustpilot.com/review/metatrader5.com)

### Inferences
- The MT5 automation stack in late 2026 is aimed at quants: matrices and vectors, BLAS/LAPACK-style routines, ONNX inference on GPU, Python bridge, MCP for LLM agents. A personal platform built on Python would match most of this through NumPy, SciPy and ONNX Runtime. MT5's edge is that everything runs in one integrated terminal with broker connectivity.
- Automated trading is enabled per terminal (global "Algo Trading" button) and per EA (allow algo trading in inputs). EAs attach to a chart and run on each tick or timer event. This is general MT5 behaviour, not re-verified in this session.
- Running EAs requires the desktop terminal or MetaQuotes VPS. The web terminal does not run EAs (see Q7).

### Gaps
- Exact current VPS price (the official tables conflict) and VPS latency or uptime figures were not found.
- No official MQL4-vs-MQL5 language comparison was fetched. MQL4's convergence with MQL5 syntax (build 600, February 2014) is from general knowledge, not verified here.

## Q3. Strategy Tester: modelling modes, multi-currency, multi-threading, MQL5 Cloud Network, genetic optimisation, forward testing, visual mode, speed figures

### Takeaway
The MT5 tester has 5 modes: Every tick, Every tick based on real ticks, 1-minute OHLC, Open prices only, and Math calculations. It supports multi-symbol testing, genetic optimisation, forward testing, visual mode, random-delay stress tests, local and LAN agents, and the MQL5 Cloud Network (about 65,000 agents online in November 2026). MetaQuotes publishes no hard speed benchmarks, only qualitative claims.

### Cited Findings
- **Modelling modes (official help):**
  - **Real ticks** uses broker-accumulated real ticks, stored monthly in TKC files under `bases\[server]\ticks\[symbol]\`. The first run is slow because of the data volume. Minutes with no tick data fall back to generated "Every tick" data, and ticks without a matching minute bar are ignored.
  - **Every tick** generates ticks from M1 bars using up to 11 reference points (ideal split 3-5-3). It is the most accurate generated mode and the slowest.
  - **1-minute OHLC** uses only 4 prices per M1 bar.
  - **Open prices only** is the fastest and roughest. OnTick fires once per bar, stops can trigger at the wrong prices, Random Delay is unavailable, and the EA cannot access lower timeframes.
  - **Math calculations** generates no ticks or history and calls only OnInit, OnTester and OnDeinit, so it works for pure optimisation of a custom criterion.
  - Source: [MT5 Help: tick generation](https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation)
- Multi-currency (official): EAs "can access all financial instruments in the tester and trade any of them", which enables correlation and portfolio strategies — [MT5 Strategy Tester page](https://www.metatrader5.com/en/automated-trading/strategy-tester)
- Genetic optimisation skips exhaustive search, keeps the best combinations and crosses them over, with 2D/3D result visualisation. Forward testing splits history into an optimisation segment and a confirmation segment. Visual mode replays the EA on history with speed control and pause. Random Delay simulates network and dealer delays. Distributed testing works on LAN machines and on the MQL5 Cloud Network via MetaTester agents — [MT5 Strategy Tester page](https://www.metatrader5.com/en/automated-trading/strategy-tester)
- Speed claims (official, qualitative only): "a few minutes" of testing instead of "days, weeks or months". Optimisations that would take "months" on one PC finish "within a few hours" on the Cloud Network. No multipliers or benchmarks are published — [MT5 Strategy Tester page](https://www.metatrader5.com/en/automated-trading/strategy-tester)
- **MQL5 Cloud Network live stats** (fetched November 2026): 21,088,943,832 tasks processed, 6,509 members, 65,630 agents online. RAM: 31.2% of agents have 16-32 GB and 25.4% have 32-64 GB. CPUs: i5 17.4%, i7 13.4%, Ryzen 9 12.2% — [cloud.mql5.com stats](https://cloud.mql5.com/en/stats)
  - A different snapshot of the same page, seen in search results, showed about 20.4 billion tasks, 6,571 members and 67,911 agents, so the counters fluctuate — [cloud.mql5.com stats](https://cloud.mql5.com/en/stats)
  - An older MetaQuotes press release claimed more than 16 billion tasks and about 50,000 agents (date roughly 2024; undated in the snippet) — [MetaQuotes: MQL5 Cloud Network press release](https://www.metaquotes.net/en/company/news/5448)
  - An even older milestone: "MQL5 Cloud Network Reaches the Capacity of 34,000 Cores" — [Yahoo Finance](https://finance.yahoo.com/news/mql5-cloud-network-reaches-capacity-152900808.html)
- AI Assistant tester tools (Build 6180, 3 Sep 2026): it can fetch test and optimisation reports for analysis, configure optimisation criteria, launch optimisation, check current tester settings and read tester logs. Build 6230 (24 Sep 2026) lets it prepare EA parameters for testing — [MetaQuotes news: Build 6180](https://www.metaquotes.net/en/metatrader5/news/5555); [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- Backtest-reliability debate (MQL5 forum, anecdotal): users warn that backtests can mislead and that real accounts matter more. Others say high-quality "every tick" tests are reasonable for non-scalping EAs if spread and slippage are modelled — [MQL5 forum thread 457568](https://www.mql5.com/en/forum/457568/page7); [MQL5 forum thread 337020](https://www.mql5.com/en/forum/337020/page2)

### Inferences
- The MT5 tester is the benchmark feature a competitor must match. The minimum bar is real-tick backtesting, multi-symbol portfolios, genetic optimisation, walk-forward validation, a visual replay and parallel local workers. MetaQuotes publishes no throughput numbers (passes/sec, ticks/sec), so a competitor could stand out by publishing reproducible speed benchmarks.
- MT4's tester is widely documented as single-symbol and single-threaded, with no real-tick mode and no cloud. This is general knowledge, not re-verified in this session.
- Real-tick quality depends on the broker's stored tick history. For Indian markets, a competitor would need its own NSE tick or 1-minute history, which MT5 brokers don't provide (see Q5).
- The tester has no built-in walk-forward matrix (rolling windows), only a single forward split. Advanced overfitting controls such as CPCV and deflated Sharpe are absent from the docs, which is a gap a quant-oriented competitor could fill.

### Gaps
- No official or independent benchmark of tester speed (for example ticks per second, or MT4 vs MT5 test duration) was found.
- MQL5 Cloud Network pricing per pass/agent-hour was not retrieved.
- Official documentation on how many local agents MT5 spawns (one per logical core is the common understanding) was not fetched.

## Q4. Order execution and trading: order types, one-click, DOM, hedging vs netting, execution modes, partial fills, trade copying, Signals

### Takeaway
MT5 supports market orders plus 6 pending types (Buy/Sell Limit, Buy/Sell Stop, Buy/Sell Stop Limit). It has 4 execution modes, 4 fill policies including partial fills, both netting and hedging accounting, and a DOM, which moved into the redesigned trade dialog in April 2026. MT4 has 2 market and 4 pending order types and 3 execution modes. The MQL5 Signals copy-trading service takes a 20% cut of subscription fees. Platform-wide Signals statistics are not published.

### Cited Findings
- MT5 order types (official help): Market; Buy Limit; Buy Stop; Sell Limit; Sell Stop; Buy Stop Limit; Sell Stop Limit. SL/TP attach only with a market or pending order — [MT5 Help: trading general concept](https://www.metatrader5.com/en/terminal/help/trading/general_concept)
- Execution modes: Instant (requotes possible), Request, Market (broker sets price), Exchange (order routed to an external trading system) — [MT5 Help: trading general concept](https://www.metatrader5.com/en/terminal/help/trading/general_concept)
- Fill policies:
  - Fill or Kill works in all modes.
  - Immediate or Cancel works in Market and Exchange modes.
  - Book or Cancel works in Exchange mode, for limit and stop-limit orders only.
  - Return keeps the remainder active. For market orders it applies in Exchange mode only; for limit and stop-limit orders, in Market and Exchange modes.
  - A "Partially filled" order state exists.
  - Source: [MT5 Help: trading general concept](https://www.metatrader5.com/en/terminal/help/trading/general_concept)
- Netting allows one position per symbol, which can be reversed. Hedging allows multiple positions per symbol, including opposite ones, and they cannot be reversed. Hedged margin is available as a margin condition. One-click trading does not set SL/TP under hedging — [MT5 Help: trading general concept](https://www.metatrader5.com/en/terminal/help/trading/general_concept)
- Build 5800 (16 Apr 2026) brought a "comprehensive redesign of the trading dialog" with built-in Depth of Market. The Web terminal got a DOM volume-unit switch in Build 5430 (Nov 2025) and contract start/end dates in Build 5370 (Oct 2025) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes); [FX News Group on Build 5800](https://fxnewsgroup.com/forex-news/platforms/new-mt5-build-offers-redesigned-trading-dialog-and-improved-operations-with-csv-in-metaeditor/)
- New "Trader" and "Money manager" account access levels, plus Passkey authentication, arrived in Build 6060 (23 Jul 2026) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- MT4 (official): 2 market orders, 4 pending orders, 2 stop orders plus a trailing stop, 3 execution modes, and "Instant Execution and trading from a chart" — [MetaTrader 4 trading platform page](https://www.metatrader4.com/en/trading-platform)
- **Signals service:**
  - The provider receives "the payment less 20% commission retained by the Signals service" — [MQL5 Signals rules](https://www.mql5.com/en/signals/rules)
  - Fixed subscription price with no extra commission for subscribing (broker spreads and commissions still apply) — [MT5 Help: Signals](https://www.metatrader5.com/en/terminal/help/signals)
  - Example listings (November 2026) run from about USD 30 to USD 999 per month. Listed signals showed 0 to 65 subscribers each; for example, one gold EA signal showed "2 331% growth since 2024", reliability 99% and 56 subscribers at USD 35/month — [MQL5 Signals for MT5](https://www.mql5.com/en/signals/mt5)
  - Official marketing says only "thousands" of providers and subscribers, with no hard totals — [MQL5 about page](https://www.mql5.com/en/about); [MetaTrader 4 trading platform page](https://www.metatrader4.com/en/trading-platform)

### Inferences
- MT5's order model fits exchange-style order books (FOK, IOC, BOC, Return, stop-limit). In principle it can represent NSE order semantics: IOC, day orders, SL and SL-M map roughly to stop-limit and stop. Bracket and cover orders (Indian broker-specific products) and GTT have no direct native equivalent in the docs reviewed.
- Signals is a mature copy-trading marketplace, but its headline growth and reliability metrics on individual listings are easy to game (short track records, high-risk martingale or grid). This feeds the "scam" complaints in Q9.

### Gaps
- Order expiration types (GTC, Today, Specified, Specified day) were not covered on the fetched page.
- No official total of Signals providers or subscribers, or any aggregate subscriber-performance statistics, was found.
- No latency or execution-speed figures for MetaQuotes servers or the Exchange execution mode were found.

## Q5. Market data, asset classes, exchange use, and India availability and legality

### Takeaway
MT5 is multi-asset and has an "Exchange" execution mode for real exchanges, but no official MetaQuotes gateway to NSE, BSE or MCX was found, and mainstream Indian brokers don't offer MT5. Indian access exists only through third-party bridges that pipe data and orders via broker APIs (Zerodha Kite, Upstox, Fyers and others). The RBI Alert List (19 Nov 2025) names MetaTrader 4 and MetaTrader 5 themselves as unauthorised forex platforms, so MT4/MT5 forex/CFD trading with offshore brokers is not legal for Indian residents.

### Cited Findings
- RBI Alert List dated 19 Nov 2025: 95 entries, including MetaTrader 4 (Sr. No. 46) and MetaTrader 5 (Sr. No. 47). Seven names were added that day: Starnet FX, CapPlace, Mirrox, Fusion Markets, Trive, NXG Markets, Nord FX. The RBI says "An entity not appearing in the list should not be assumed to be authorised" — [Upstox News on the RBI Alert List](https://upstox.com/news/personal-finance/trading/rbi-alert-list-updated-full-list-of-unauthorised-forex-trading-platforms-and-what-happens-if-you-use-them/article-184938/); [Alert List PDF (19 Nov 2025, hosted by Federal Bank)](https://www.federal.bank.in/documents/10180/57401/Updated_Alert_List19112025.pdf/61c4b3d8-a611-8d24-cb18-901f0c0b10ca?t=1763966233291); [Outlook Money](https://www.outlookmoney.com/invest/check-rbis-updated-alert-list-for-unauthorised-forex-trading-platforms)
- RBI position: forex trading is governed by FEMA 1999 and the RBI Electronic Trading Platforms Directions, 2025. Residents may transact only with authorised persons and on RBI-authorised ETPs or recognised exchanges (NSE, BSE, MSEI). Margin remittances abroad under the Liberalised Remittance Scheme (LRS) are not permitted, and violators are "liable for penal action under the Act" — [Upstox News](https://upstox.com/news/personal-finance/trading/rbi-alert-list-updated-full-list-of-unauthorised-forex-trading-platforms-and-what-happens-if-you-use-them/article-184938/)
- FEMA penalties of up to 3x the transaction amount are cited by a secondary source — [CompleteTradersEdge RBI Alert List 2026](https://completetradersedge.com/rbi-alert-list/)
- Some forex guides for India recommend MT5 brokers that are themselves on the Alert List (for example FOREX.com and AvaTrade). Treat such guides as unreliable — [ForexBrokers.com India guide](https://www.forexbrokers.com/guides/india) (contradicted by the RBI list above)
- Mainstream Indian brokers (Zerodha, Upstox, Angel One, ICICI Direct, 5paisa) offer NSE/BSE currency derivatives on their own platforms (Kite, Pro Web, SmartAPI), not MT5 — [AlgoTest blog](https://algotest.in/blog/best-broker-for-forex-trading-in-india/)
- Third-party "MT5 bridge" vendors (for example TradexCodez) sell live tick-by-tick NSE, NFO, BSE, BFO and MCX data into MT5 through the user's own broker API: Zerodha Kite, Flattrade, Fyers, Upstox, Angel One, Alice Blue. These are vendor claims, not regulator-verified — [TradexCodez MT5 Bridge](https://tradexcodez.com/tradexcodez-mt5-bridge/); [TradexCodez Upstox bridge](https://tradexcodez.com/upstox-mt5-bridge/); [TradexCodez: Is MT5 legal in India](https://tradexcodez.com/blog/is-metatrader-5-legal-in-india/)
- Other vendors sell MT4/MT5 data feeds for MCX and NSE (unverified commercial offerings) — [MCX SureGain](https://www.mcxsuregain.com/)
- Build 5640 (Feb 2026) notes "Updated fundamental data", which implies some fundamental data for stocks in MT5 — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- MT5 "Exchange" execution mode routes orders to an external trading system at current market offers — [MT5 Help: trading general concept](https://www.metatrader5.com/en/terminal/help/trading/general_concept)

### Inferences
- For an Indian-market personal platform, MT5 is not a direct competitor in its home market. There is no native NSE/BSE connectivity, Indian brokers don't host MT5 servers, and the RBI lists the platform brand itself. Its relevance is as a feature benchmark and as something Indian retail algo traders hack together via unofficial bridges. Those bridges suggest demand for "MT5-like tooling on NSE data".
- Anyone bridging MT5 to an Indian broker API for automated orders would likely fall under SEBI's retail algo-trading framework (exchange-registered algos, API rules). That is not verified in this research; see Gaps.
- Globally, MT5's asset coverage is broker-defined: FX, CFDs on indices, stocks, commodities and crypto, plus exchange stocks and futures where brokers run exchange gateways.

### Gaps
- I could not retrieve an official MetaQuotes list of exchange gateways (historically B3/BM&FBovespa, Moscow Exchange and others). I found no evidence of any NSE, BSE or MCX gateway.
- SEBI's position on third-party platforms like MT5 bridges under the retail algo framework (SEBI circular, Feb 2025, phased implementation) was not researched here.
- I could not confirm whether the RBI listing targets the MetaTrader brand or specific domains/apps, or whether app stores in India have restricted MT4/MT5 downloads.

## Q6. Ecosystem: MQL5 Market, Freelance, community, economic calendar, news

### Takeaway
The MQL5.com ecosystem (Market, Signals, Freelance, Code Base, articles, forum, VPS, Cloud, Algo Forge) is MetaTrader's biggest moat. The MT5 Market alone appears to list tens of thousands of products: 599 pages at about 70 per page in November 2026 (inferred). The official MT4 page cites 1,700+ robots and 2,100+ indicators for MT4 (undated). Quality control and refunds are the main complaints.

### Cited Findings
- MQL5 Market for MT5 (November 2026): pagination runs to page 599, and page 1 shows 70 products (63 Experts, 4 Indicators, 3 Utilities). Prices on page 1 range from USD 30 to USD 1,699. Rental is offered (for example "rent it for 1 year for only $299"), and there is a "test before buying" guide — [MQL5 Market MT5](https://www.mql5.com/en/market/mt5)
- MT4 page (undated marketing): Market has 1,700+ trading robots and 2,100+ technical indicators. Signals have "thousands of providers" — [MetaTrader 4 trading platform page](https://www.metatrader4.com/en/trading-platform)
- MQL5 homepage marketing says "choose from 10,000 products" (page indexed long ago; outdated) — [MQL5.com](https://www.mql5.com/)
- MQL5 about page claims "Over a hundred of brokerage companies and banks" use MT5. It lists 11 site languages and "Copyright 2000-2026, MetaQuotes Ltd." The broker figure is clearly stale — [MQL5 about](https://www.mql5.com/en/about)
- MQL5 Service programs were added to CodeBase in Build 5320 (Sep 2025). The AI Assistant can access the Economic Calendar from Build 6230 (Sep 2026) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- A Forex Factory thread is titled "MQL5 Market: A Scammers Paradise And Activations Scam". Forex Peace Army hosts critical reviews of the MQL5 Market — [Forex Factory thread](https://www.forexfactory.com/thread/1080525-mql5-market-a-scammers-paradise-and-activations-scam); [Forex Peace Army: MQL5 Market](https://www.forexpeacearmy.com/forex-reviews/9977/mql5-community-market)
- Trustpilot reviews of MQL5.community describe EAs that look good in backtests but "blow the accounts" after weeks or months, refused refunds for digital products, and fake backtests (anecdotal) — [Trustpilot: mql5.com](https://uk.trustpilot.com/review/www.mql5.com); [Trustpilot: metatrader5.com](https://uk.trustpilot.com/review/metatrader5.com)

### Inferences
- If 599 pages × about 70 per page holds across all pages, the MT5 Market holds roughly 40,000+ products. This is a rough inference from pagination, not an official count.
- A personal Indian platform cannot replicate a marketplace. The relevant gap analysis is a strategy/indicator library, a code-sharing layer and community templates, not a paid store.

### Gaps
- No official current totals for Market products, Freelance jobs/developers, Code Base items, articles or registered community members were found. The about page omits them.
- I did not research economic calendar coverage (countries, events) or the built-in news feed in detail.
- The Market seller commission rate was not on the fetched page.

## Q7. Platforms (desktop, Mac, web, mobile), the 2022-23 App Store episode, and 2023-2026 changes including AI

### Takeaway
MT5 is a Windows-native terminal. The Mac build is a Wine-wrapped, Intel-only app running under Rosetta. Web and mobile terminals can't run EAs or custom indicators. Apple removed MT4/MT5 from the App Store on about 23-24 September 2022 and reinstated them on 6 March 2023. In 2025-2026 MetaQuotes shipped frequent builds, the headline being native MCP/agentic AI (July 2026) and an expanding AI Assistant (August-September 2026). Windows 7/8 support ended after Build 5320 (Sep 2025).

### Cited Findings
- **App Store:** removed around 23-24 Sep 2022 after Apple said the apps breached the Review Guidelines (no formal public explanation). Reinstated on 6 Mar 2023 — [Newswire press release](https://www.newswire.com/news/metatrader-4-and-5-applications-are-back-in-the-apple-appstore-21975423); [FXOpen](https://fxopen.com/blog/en/metatrader-4-and-metatrader-5-are-back-in-the-apple-app-store/); [Pepperstone](https://pepperstone.com/en-gb/analysis/navigating-markets/mt4-and-mt5-return-to-app-store); [FXScouts, 7 Mar 2023](https://fxscouts.com/mt4-and-mt5-back-on-the-app-store/)
- A revamped MT5 Web Terminal launched on 12 Oct 2022 during the App Store outage (per search summary of the coverage above). MetaQuotes reported record MT5 iOS users after the return — [FX News Group](https://fxnewsgroup.com/forex-news/platforms/exclusive-metaquotes-sees-record-number-of-metatrader-5-ios-users-after-app-store-return/)
- **Mac:** a MetaQuotes forum developer says the macOS build is not a native Cocoa app but the Windows version in a Wine-based wrapper. A Rosetta checker lists it as Intel-only. A user on an M5 Mac asked whether a native build is coming before macOS 28 drops Rosetta, with no official answer found — [MQL5 forum 508861](https://www.mql5.com/en/forum/508861); [RosettaCheck](https://rosettacheck.com/apps/net.metaquotes.wine.MetaTrader5); [Parallels KB 129408](https://kb.parallels.com/en/129408)
- **Web terminal:** limited functionality. It does not support Expert Advisors or custom indicators, and IG recommends desktop for Mac users — [IG help](https://www.ig.com/en/help-and-support/platforms/mt5/can-i-use-mt5-on-mac)
- **Platform-support cutoffs:** Build 5320 (25 Sep 2025) is the last build for Windows 7/8/8.1 and Server 2008. The AI Assistant is disabled on Windows 7 (Build 6090). SOCKS4 proxies were dropped (Build 5660, Feb 2026) — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- **2025-2026 build timeline** (official):

  | Build | Date | Headline |
  |---|---|---|
  | 5200 | 31 Jul 2025 | OpenBLAS |
  | 5260 | 5 Sep 2025 | MQL5 language, Algo Forge |
  | 5320 | 25 Sep 2025 | Last Windows 7 build |
  | 5430 | 13 Nov 2025 | Blend2D rendering |
  | 5572 | 29 Jan 2026 | ONNX with CUDA |
  | 5640 | 20 Feb 2026 | Dark theme, Markdown |
  | 5660 | 27 Feb 2026 | Proxy changes |
  | 5800 | 16 Apr 2026 | Trade dialog redesign with DOM; help moved to a web engine |
  | 6060 | 23 Jul 2026 | Native MCP/agentic AI, Passkey, new access levels |
  | 6090 | 30 Jul 2026 | More MCP methods |
  | 6140 | 20 Aug 2026 | New AI Assistant LLM providers, chat deletion, MCP optimisation, smaller context window for the MQL5.community provider |
  | 6180 | 3 Sep 2026 | AI tester and log tools |
  | 6230 | 24 Sep 2026 | AI manages EAs/indicators on charts and reads the Economic Calendar; .NET CoreCLR import |

  Source: [MT5 release notes](https://www.metatrader5.com/en/releasenotes); [MetaQuotes news: Build 6180](https://www.metaquotes.net/en/metatrader5/news/5555)
- Build 6230 is the latest found as of this research. No October or November 2026 build appeared in the sources — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- **MT4 status:** new MT4 broker licences stopped (sources say 2022; others imply earlier), but existing installations keep working. MetaQuotes' broker page reportedly says MT4 licences "are no longer available for purchase" and that conceptual updates go only to MT5 (not checked directly). MT4 terminals older than build 1440 reportedly cannot connect since July 2025 (secondary, unverified) — [EasyTradeWeb](https://www.easytradeweb.com/en/metatrader-4-brokers/); [ForTraders blog](https://fortraders.com/blog/metatrader-4); [FundedTrading MT5 review 2026](https://fundedtrading.com/?p=22374)
- Finance Magnates (17 Apr 2025): MetaQuotes "has gradually scaled back support for MT4" — [Finance Magnates exclusive](https://www.financemagnates.com/forex/products/exclusive-after-15-years-mt5-overtakes-mt4-in-trading-volume-marking-end-of-an-era/)
- Mobile complaint (Trustpilot, anecdotal): the MT5 mobile app is slow and hard for fast execution. One user reports an app freeze that prevented setting SL/TP — [Trustpilot: metatrader5.com](https://uk.trustpilot.com/review/metatrader5.com)

### Inferences
- MT5's weak spots for a competitor are a first-class Mac or Linux and browser experience. Web and mobile can't run automation, and the Mac build is an emulated Windows app. A cross-platform web-first personal platform with server-side strategy execution would beat MT5 on accessibility.
- AI: MetaQuotes moved fast in 2026 to MCP/agentic integration (terminal, MetaEditor, tester). A competitor's AI features will be compared with this. MT5's AI can launch optimisations, read logs and manage chart indicators.

### Gaps
- Exact list of AI Assistant LLM providers, pricing and limits: the release notes mention "new LLM providers" and an "MQL5.community provider" but no names or prices were retrieved.
- iOS/Android feature limits beyond the absence of EAs were not documented by official sources in this research.
- The original 2023 MetaEditor AI assistant launch date was not verified.

## Q8. Pricing model

### Takeaway
Traders get MT4/MT5 free via brokers. MetaQuotes earns from broker licences (white label and main label) and from MQL5 services: the 20% Signals cut, Market sales, VPS at about USD 10-15/month, and Cloud Network fees. Broker licence prices are not published. Press reports a 25% MetaTrader fee increase (2025) and stricter licensing for prop firms after early 2024.

### Cited Findings
- MT4 is "still free" for traders, while new broker licences are no longer sold — [ForTraders blog](https://fortraders.com/blog/metatrader-4); [EasyTradeWeb](https://www.easytradeweb.com/en/metatrader-4-brokers/)
- Signals: a 20% commission is retained from subscription fees — [MQL5 Signals rules](https://www.mql5.com/en/signals/rules)
- VPS: about USD 15/month base, USD 10-13/month on longer terms (official pages conflict) — [MQL5 VPS](https://www.mql5.com/en/vps/free-forex-vps)
- Prop firm licensing: after the True Forex Funds shutdown (early 2024), MetaQuotes stopped supporting prop firms running on "grey label" broker arrangements. Prop firms must reportedly prove they are licensed for FX/CFD services. Finance Magnates later reported the stance softened, while "MetaTrader fees have increased by 25% this year", and one firm obtained its own main-label MT5 licence — [Finance Magnates: prop firm returns to MT5](https://www.financemagnates.com/forex/another-prop-firm-returns-to-metatrader-5-a-year-after-metaquotes-license-overhaul/); [Atomiq Consulting](https://atomiqconsulting.com/mt4-mt5-prop-trading/); [TradingView/Finance Magnates](https://www.tradingview.com/news/financemagnates:f8c595249094b:0-prop-trading-firms-renaissance-cutting-us-clients-integrating-new-trading-platforms/)
- Market products for MT5 cost USD 30 to USD 1,699 on page 1 in November 2026, with rentals available — [MQL5 Market MT5](https://www.mql5.com/en/market/mt5)

### Inferences
- For a personal (single-user) platform, MT5's "free" price is hard to beat on cost. The real costs to an MT5 user are broker spreads, add-ons (VPS, Market EAs, Signals) and broker lock-in.

### Gaps
- Actual MT5 white-label or main-label licence fees (setup and monthly) were not found in reliable public sources.
- The exact year and baseline of the "25% fee increase" were not confirmed from a primary MetaQuotes source.

## Q9. Strengths, weaknesses and recurring user complaints

### Takeaway
Strengths: ubiquity across brokers, the integrated automation, tester and cloud stack, and a huge MQL5 ecosystem. Weaknesses: dated UI and charts, broker dependence, a Windows-centric design, web and mobile that can't automate, Market and Signals quality problems (overfit or scam EAs, no refunds), limited native chart types, and no built-in scanner or deep fundamentals.

### Cited Findings
- **Positive (user reviews):** Capterra, GetApp and SoftwareReviews users call it easy to use and reliable. One calls real-time data "lag-free". G2 shows 4.3/5 from 19 reviews (the URL refers to MT4, the title to MT5, so treat with caution) — [Capterra MT5](https://www.capterra.com/p/230413/MetaTrader-5/); [GetApp MT5](https://www.getapp.com/hedge-fund-software/a/metatrader-5); [G2 MetaTrader](https://www.g2.com/products/metatrader-4/reviews)
- **Negative (user reviews):** Capterra users say it is hard for beginners and slow to open. A GetApp user says the community section lags and is hard to navigate — [Capterra MT5](https://www.capterra.com/p/230413/MetaTrader-5/); [GetApp MT5](https://www.getapp.com.au/reviews/2050192/metatrader-5)
- **Dated UI and charts:** "charts in MetaTrader 5 look like they were drawn by hand". The mobile app is slow (Trustpilot, anecdotal) — [Trustpilot: metatrader5.com](https://uk.trustpilot.com/review/metatrader5.com)
- **Market and EA scams, and overfitting:** EAs that pass backtests and then blow accounts, fake backtests, no refunds — [Trustpilot: mql5.com](https://uk.trustpilot.com/review/www.mql5.com); [Forex Factory thread](https://www.forexfactory.com/thread/1080525-mql5-market-a-scammers-paradise-and-activations-scam); [MQL5 forum 337020](https://www.mql5.com/en/forum/337020/page2)
- **Broker dependence and regulatory exposure:**
  - Prop firms lost MetaTrader access overnight in 2024 when MetaQuotes enforced licensing — [Finance Magnates](https://www.financemagnates.com/forex/another-prop-firm-returns-to-metatrader-5-a-year-after-metaquotes-license-overhaul/)
  - Apple pulled the iOS apps for about 5.5 months in 2022-23 — [FXScouts](https://fxscouts.com/mt4-and-mt5-back-on-the-app-store/)
  - The RBI lists MT4/MT5 as unauthorised in India — [Upstox News](https://upstox.com/news/personal-finance/trading/rbi-alert-list-updated-full-list-of-unauthorised-forex-trading-platforms-and-what-happens-if-you-use-them/article-184938/)
- **Competitive drift:** MT5 "is no longer the unchallenged default it was five years ago" (FundedTrading 2026). Alternative platforms (cTrader, TradingView, Match-Trader, proprietary) held 27% of retail CFD volume in Q1 2025 per Finance Magnates — [FundedTrading MT5 review](https://fundedtrading.com/?p=22374); [Finance Magnates exclusive](https://www.financemagnates.com/forex/products/exclusive-after-15-years-mt5-overtakes-mt4-in-trading-volume-marking-end-of-an-era/)

### Inferences
- "No built-in scanner/screener" and "limited fundamental data" are widely repeated criticisms and consistent with the docs reviewed: no screener feature appeared in charting or trading docs, and fundamentals appear only as an "updated fundamental data" release-note line. No primary source explicitly stating this was retrieved. These are prime gap-analysis wins for an Indian equity/F&O platform: option chains, OI analytics, Greeks and screeners are absent from MT5's FX/CFD-centric design.
- MT5 has no native options analytics (option chain, Greeks, IV surface, payoff diagrams) in the docs reviewed. This matters for an Indian F&O-focused platform, where options dominate retail volume.

### Gaps
- I retrieved no Reddit r/Forex or r/algotrading threads. Complaints come from Trustpilot, the MQL5 forum, Forex Factory and software-review sites.
- I found no BrokerChooser or Investopedia MT5 platform review in this session.

## Q10. Published, measurable benchmarks a competitor could match or beat

### Takeaway
The hard, citable numbers are adoption and capacity metrics, not performance metrics:
- MT5's share of MetaQuotes-platform retail CFD volume: 54.2% (Q1 2025), 62% (Q3 2025), 65% (Q1 2026).
- About 65,000 Cloud Network agents and more than 21 billion tasks processed.
- Feature counts: 21 timeframes, 38 indicators, 44 objects, 100 charts.
- 5 tester modes; 7 order types; 4 execution modes; 4 fill policies.

MetaQuotes publishes no tester throughput, order latency or user-count figures.

### Cited Findings
- MT5 reached 54.2% vs MT4's 45.8% of combined MetaQuotes volume in Q1 2025, the first time MT5 led (Finance Magnates Intelligence, published 17 Apr 2025) — [Finance Magnates exclusive](https://www.financemagnates.com/forex/products/exclusive-after-15-years-mt5-overtakes-mt4-in-trading-volume-marking-end-of-an-era/)
- MT5 at 62% vs MT4 at 38% in Q3 2025 (published 22 Oct 2025). Other platforms held 15.7% of total retail CFD volume on a different base. MT4 is "far from disappearing" — [Finance Magnates: MT5 extends lead](https://www.financemagnates.com/forex/technology/mt5-extends-its-lead-over-mt4-as-platform-shift-accelerates/)
- MT5 at 65% in Q1 2026 (FM Quarterly Report). North America is the only region where MT4 still leads — [Finance Magnates: North America holds the line for MT4](https://www.financemagnates.com/forex/analysis/north-america-holds-the-line-for-mt4-as-mt5-sweeps-five-of-six-regions/)
- Cloud Network: 65,630 agents online, 21.09 billion tasks and 6,509 members (November 2026 snapshot) — [cloud.mql5.com stats](https://cloud.mql5.com/en/stats)
- Feature counts:
  - MT5: 21 timeframes, 38 indicators, 44 objects, up to 100 charts — [MT5 technical analysis](https://www.metatrader5.com/en/trading-platform/technical-analysis); [MT5 Help: Charts](https://www.metatrader5.com/en/terminal/help/charts_analysis/charts)
  - MT4: 9 timeframes, 30 indicators, 23 objects — [MT4 trading platform](https://www.metatrader4.com/en/trading-platform)
- Release cadence: about 16 MT5 builds or updates between Jun 2025 and Sep 2026, roughly one every 3-4 weeks — [MT5 release notes](https://www.metatrader5.com/en/releasenotes)
- Top MT5 broker by ForexBrokers.com 2026: IC Markets (4.5/5, USD 200 minimum deposit, #1 MetaTrader broker six years running) — [ForexBrokers.com MT5 brokers](https://forexbrokers.com/guides/metatrader-5-brokers)

### Inferences
- Benchmarks a personal Indian platform could realistically target and publish:
  - Backtest throughput (bars or ticks per second on one machine), compared with MT5 real-ticks mode.
  - Time to run a 10,000-pass genetic optimisation locally.
  - More native chart types and timeframes, including custom timeframes and tick or volume bars.
  - More built-in indicators than 38.
  - Options-specific analytics, which MT5 lacks.
  - Web and mobile automation parity.
- User and broker counts are not benchmarkable: MetaQuotes' only on-site figure ("over a hundred brokerage companies and banks") is outdated, and no current registered-user count was found.

### Gaps
- No current official number of MT4/MT5 users, active accounts or brokers was found. Commonly repeated industry numbers (for example "1,000+ brokers") were not verified in this session.
- No independent latency or execution benchmarks for MT5 were found.
- Finance Magnates' sample size and methodology for the volume-share figures are not disclosed in the articles fetched.

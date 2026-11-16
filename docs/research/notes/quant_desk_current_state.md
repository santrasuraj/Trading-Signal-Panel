# Quant Desk: current state (repository investigation, branch signals-live-track-record)

Sources are repository files, not web pages. Every path below is relative to the repository root unless it starts with `..\` (the folder above it), and is cited as `[path:line]`. I read the code without editing anything. The only data files I opened were read-only JSON summaries under `data/results/`, on 2026-11-11. I did not run any scans, servers or tests.

## 1. Feature inventory by category (with implementing files)

### Takeaway
Quant Desk is a single-user, localhost, research-first platform for NSE stocks: daily and weekly candlestick charts with fixed indicators and computed overlays, preset screeners, rule-based strategies with survivorship-free backtests, paper trading, NSE options/F&O positioning, smart-money disclosures, and two Claude features. It has no order execution, no user drawing tools, no intraday chart, no user-defined scans or alerts, no streaming quotes to the browser, and no multi-user or auth layer.

### Cited Findings
**Architecture**
- The backend is FastAPI (`web/api`, 69 route decorators across 13 routers) on `127.0.0.1:8600`, started by `web/serve.py`. `--reload` restarts it when files in `web/api` or `scanner` change. — [web/serve.py:1-7, 22-25]; [web/api/main.py:28, 92]
- The UI is React 18.3.1, TanStack Query 5.62, TanStack Table 8.21, react-router 6.28, Tailwind 3.4, Vite 6.4 and lightweight-charts 5.2.1. — [web/ui/package.json]
- The old Streamlit dashboard (`app.py`, `3b_dashboard_streamlit.bat`) "gets no new features". — [README.md:22]

**Charting**
- The library is TradingView lightweight-charts v5. The price chart is candlesticks only (`CandlestickSeries`) with a volume histogram. Line and area series are used only for equity and benchmark curves. There is no bar, Heikin-Ashi, Renko or line option for prices. — [web/ui/src/components/charts/PriceChart.tsx:7, 73, 84]; [web/ui/src/components/charts/EquityChart.tsx:37-56]
- Timeframes are 1D and 1W only. The 5m button is disabled with the tooltip "Intraday chart comes with the intraday store". Ranges are 3M, 6M, 1Y, 2Y, 5Y and Max. — [web/ui/src/pages/Chart.tsx:31, 321]; [web/ui/src/api/types.ts:615-616]
- Indicators are a fixed menu: SMA 20/50/200, EMA 21, Bollinger (20, 2), Volume, an RSI 14 pane and a MACD pane, plus log scale and price lines. There are no custom indicators or scripting. — [web/ui/src/pages/Chart.tsx:33-36, 324-331]
- Computed overlays ("Levels" menu):
  - drawn chart patterns (double top/bottom, H&S, triangles, wedges, rectangles, flags) with breakout, target and void levels;
  - swing support/resistance;
  - next-session pivots;
  - today's VWAP, opening range and POC;
  - option call/put walls and max pain;
  - the options-verdict breakeven, stop and target;
  - the expected 5-day range;
  - candle-pattern markers;
  - strategy buy/sell markers.
  — [web/ui/src/pages/Chart.tsx:38-48, 226-289]; [web/ui/src/lib/patternDrawing.ts]; [scanner/levels.py]
- There are no user drawing tools (trendline, Fibonacci, rectangle, text). A search for trendline/fibonacci/drawing tool in `web/ui/src` found none. The "Ruler" button opens the computed Levels menu. Other chart tools are a PNG screenshot and keyboard shortcuts (1-6 range, d/w, [ ]). — [web/ui/src/pages/Chart.tsx:204-225, 348-356, 364]
- The right side panel shows a stock snapshot: RS, momentum rank, returns, SMAs, delivery %, which strategies hold or rank the stock, your holding, smart money and corporate actions. Below the chart are the AI analyst, the Outlook, Options & F&O, Big money and Price action panels. — [web/ui/src/pages/Chart.tsx:94-161, 390-394]

**Scanning / screening**
- The Screener has fixed presets only: `momentum, rs, near_high, low_vol, volume, uptrend, all`. Filters are industry, minimum turnover, in-models and results-within. It has sparklines, CSV export and a column chooser. There is no user-written scan condition. — [web/api/routers/lookup.py:18]; [web/ui/src/api/client.ts:85]; [web/ui/src/pages/Screener.tsx:1, 17]
- The scan engine refreshes about 500 Nifty 500 stocks, re-tests every strategy and writes today's orders and the holdings check to `latest.json`. — [scanner/daily.py]; [README.md:3-9, 403]

**Signals and orders**
- About 14 active strategies produce next-open BUY/SELL orders sized to capital, with stops. A BUY gets a 0-100 "strength" score. — [web/ui/src/pages/Signals.tsx:1-4]; [web/api/services/signal_quality.py:1-10]; [README.md:49-82]
- There is a live signal track record for every journalled BUY. — [scanner/track.py:1-14]; [web/ui/src/pages/SignalTrack.tsx:1-3]

**Backtesting**
- The portfolio engine fills at the next open with slippage, triggers stops and targets from intraday high/low, sizes from equity, and supports EventStrategy and RankStrategy. — [scanner/engine.py:1-12]
- Costs and tax:
  - Indian delivery costs at FYERS Standard rates — [scanner/costs.py:1-14]; [config.yaml `costs:`]
  - STCG 20.8% / LTCG 13% — [config.yaml `tax:`]
- Other engine features: a "timing range" (timing luck), after-tax returns, and comparison with the real NSE factor index. — [README.md:91-116]
- The backtest universe is survivorship-free: each day's 500 most-traded NSE stocks since Aug 2018, including 74 delisted names (1,173 companies in total). — [scanner/pit.py]; [README.md:84-90, 228-255]
- Walk-forward / holdout validation ("B8") is P2 and not built. — [docs/ui_spec.md:110, 326]
- The intraday MIS engine runs on 5-minute bars with FYERS intraday costs, a forced square-off and speculative-income tax. — [scanner/intraday/engine.py:1-14]

**Paper trading**
- Each strategy has a paper portfolio replayed from the journal (`data/journal.sqlite`) at the next official open with full costs. Only completed-day scans are journalled. — [scanner/paper.py:1-14]; [README.md:149-164]; [web/ui/src/pages/Paper.tsx:1]

**Live market data**
- Browser quotes come from REST polling: `/api/quotes` every 30 s. The server uses FYERS REST quotes when logged in today, otherwise Yahoo (~15 min delayed), with per-symbol caches of 30 s (FYERS) and 60 s (Yahoo). — [web/api/services/quotes_svc.py:1-8, 23-25]; [web/ui/src/api/hooks.ts:89-101]
- The FYERS WebSocket (`fyers_apiv3 data_ws`, up to 100 symbols) is used only by the background live service. That service builds 5-minute bars, big trades and footprints and writes files. Nothing streams to the browser. — [scanner/intraday/live.py:1-4, 32, 179, 228]; [scanner/fno_live.py:1]
- NSE official EOD files cover completed days. — [README.md:179-188, 221-226]

**Alerts**
- Telegram sends scan summaries (08:30, 15:40, 19:15) and failure notes. — [scanner/alerts.py:114-127]; [README.md:355-365]
- In-app alerts on the Overview come from scan rules: holdings stop-loss/target, 50/200-DMA, results. — [web/api/services/alerts.py:1-5]; [web/api/services/holdings_svc.py:60-61]
- Footprint "alerts" (unusual live volume or large prints) are labelled "clues, never orders". — [scanner/footprints.py:1-13]
- There are no user-defined price or indicator alerts and no browser notifications or service worker. A search for `Notification`/`serviceWorker` found none.

**Options / F&O analytics**
- `scanner/options.py`: NSE option chain, Black-76 IV and greeks, PCR, max pain, IV skew, straddle expected move, OI by strike, build-ups and unusual activity. — [README.md:284-298]
- The PCR / max pain / straddle claims are tested in `scanner/options_research.py`. — [README.md:299-305]
- `scanner/fno.py` covers participant OI (FII/DII/Pro/Client) and futures build-ups, and `scanner/fno_intraday.py` the live OI spurts. — [README.md:306-310]; [web/ui/src/pages/Fno.tsx:1-4]
- The options verdict (BUY CALL / BUY PUT / NO TRADE) is in `scanner/option_verdict.py`.
- FYERS is not used for chains. — [README.md:298]

**Smart / big money**
- `scanner/smart_money.py`: bulk/block deals, insider (PIT) trades, quarterly shareholding, FII/DII flows. — [scanner/smart_money.py:1-13]
- `scanner/big_money.py`: pledges, SAST filings, F&O ban list, delivery spikes. — [scanner/big_money.py:1-12]
- `scanner/footprints.py`: live relative volume, large prints, order-book pressure. — [scanner/footprints.py:1-13]

**AI**
- The AI analyst is Claude Opus 5.5 explaining the page's own data. The key is read from `.env` and never sent to the browser. A call costs about Rs 5-10, with a 15-minute cache. — [web/api/services/ai_svc.py:1-8]; [web/ui/src/components/AiAnalyst.tsx]
- Claude forecasts give the probability of closing above spot, a range and an invalidation level. They are journalled, scored against a coin flip and labelled "unproven" until 60 settled forecasts. — [scanner/ai_forecast.py:1-14, 40, 316-317]; [web/api/services/forecast_svc.py:45-46]; [README.md:334-347]

**Automation**
- Ten Windows Task Scheduler jobs are set up with one click from Settings:
  - weekday scans at 08:30, 15:40 and 19:15;
  - option chains at 09:12;
  - the intraday live feed at 09:14;
  - intraday signals every 5 minutes from 09:20 to 15:05;
  - a live scan every 30 minutes from 09:45 to 15:15;
  - the intraday archive at 15:45;
  - F&O and Claude forecasts at 19:30;
  - the pattern study on Saturdays at 11:00.
  — [web/api/services/automation_svc.py:25-36]; [setup_schedule.ps1]
- Jobs run only while the user is signed in to Windows. — [README.md:364-365]

**Portfolio / holdings**
- Holdings are kept in `holdings.csv` and can be imported from FYERS. Buy prices are adjusted for corporate actions. Each holding gets a health level and alerts. P&L uses the last scan's prices. — [web/ui/src/pages/Portfolio.tsx:1]; [web/api/services/holdings_svc.py]; [scanner/providers.py:183]; [README.md:369-376]

**Order execution**
- None. A search for `place_order|modify_order|cancel_order|basket_order|exit_positions|orderbook` found no matches.
- "Copy" puts an order string on the clipboard, and a link opens trade.fyers.in. — [web/ui/src/components/domain.tsx:109-139, 194-195]
- The spec lists order placement and market depth as "Explicitly out of scope". — [docs/ui_spec.md:1896]
- Settings says "the app never places orders". — [web/ui/src/pages/Settings.tsx:351]

**Mobile / responsive**
- Phones get a bottom tab bar (Overview, Signals, Strategies, Portfolio, More). — [web/ui/src/components/layout/MobileNav.tsx:8-10]
- The top-bar ticker is hidden below the `lg` breakpoint and the status bar below `md`. On mobile the chart drops its RSI/MACD panes and is 300 px high. — [web/ui/src/components/layout/TopBar.tsx:105]; [web/ui/src/components/layout/StatusBar.tsx:36]; [web/ui/src/pages/Chart.tsx:176, 290]
- There is no PWA manifest or service worker.

**Multi-user / auth**
- None. Requests are served only to Host 127.0.0.1/localhost, every mutation needs an `X-Quant-Desk: 1` CSRF header, and there are no accounts. — [web/api/security.py:1-20]
- There are no watchlists; a search for "watchlist" found nothing.

### Inferences
- Against MT4/5 and NinjaTrader, the largest gaps are order execution (none), streaming tick data and intraday charting (no intraday timeframe), user drawing tools, custom indicators or scripting (MQL / NinjaScript equivalents), and multi-chart layouts.
- Against Trade Ideas and TrendSpider, the gaps are user-defined real-time scans, alerts and watchlists. Quant Desk's automated pattern drawing partly overlaps TrendSpider, but it is daily-only and evidence-tagged.
- Its distinctive strengths are survivorship-free backtests with full Indian costs and tax, evidence grading, paper and live track records, NSE disclosure data, and AI explanations that are scored rather than trusted.

### Gaps
- I did not verify in a browser how each feature renders or performs. I did not read `Overview.tsx`, `StrategyDetail.tsx` or `Settings.tsx` in full.

## 2. Every UI page / route and what it shows

### Takeaway
There are 16 routes plus redirects, all lazy-loaded. Most pages are scan-derived snapshots. The few "live" views are Options, F&O "Live today", Smart money "Big money live" and the Intraday signals tab.

### Cited Findings
- The routes are in [web/ui/src/app/router.tsx:50-81]. The navigation labels and `g`-key shortcuts are in [web/ui/src/app/nav.ts:92-108].
- Until a first scan exists, an onboarding gate replaces every page except /settings and /intraday. — [web/ui/src/app/router.tsx:25-31]

| Route | Shows | Header ref |
|---|---|---|
| `/` Overview | regime, index tiles, breadth, next-open orders by horizon, alerts, strategy pulse, since-last-scan, movers, results, paper strip | [web/ui/src/pages/Overview.tsx:1-2] |
| `/signals` | orders for the next open by horizon (Long-term / Swing / Intraday tab), sizing, stops, strength, what-if allocation, comparison-only groups collapsed | [web/ui/src/pages/Signals.tsx:1-4] |
| `/signals/track` | live track record of every journalled BUY signal | [web/ui/src/pages/SignalTrack.tsx:1-3] |
| `/strategies` | leaderboard by horizon, evidence and status badges, CAGR with timing range, after-tax, edge vs the average stock and the NSE factor index, the "Tested & rejected" list | [web/ui/src/pages/Strategies.tsx:1-3] |
| `/strategies/:key/:tab` | 10 KPI tiles; tabs Performance / Trades / Holdings & orders / Rules & evidence / Paper | [web/ui/src/pages/StrategyDetail.tsx:1-2] |
| `/screener` | preset screens, filters, sparklines, CSV | [web/ui/src/pages/Screener.tsx:1] |
| `/chart/:symbol` (default NIFTY50) | candles, indicators, levels, side panel, AI analyst, Outlook, Options & F&O verdict, Big money, Price action | [web/ui/src/pages/Chart.tsx:1-2, 296-397] |
| `/portfolio` | holdings health, P&L, alerts, sector weights, editor, FYERS import | [web/ui/src/pages/Portfolio.tsx:1] |
| `/paper`, `/paper/:key` | paper portfolios vs backtest | [web/ui/src/pages/Paper.tsx:1] |
| `/market/:tab` | movers, sectors, factor indices, results calendar, breadth | [web/ui/src/pages/Market.tsx:1-2] |
| `/smart-money/:tab` | tabs: Big money live, Today's big trades, Insider & promoter trades, Accumulating, Exited / selling, FII/DII flows | [web/ui/src/pages/SmartMoney.tsx:1-3, 33-38] |
| `/options/:symbol` | NSE chain analytics, PCR, max pain, IV, expected move, OI, unusual activity, "Does it work?" research, big trades live, Claude forecast | [web/ui/src/pages/Options.tsx:1-5]; [README.md:284-347] |
| `/fno/:tab` | participant positions (FII/DII/Pro/Client), futures build-ups, "Live today" | [web/ui/src/pages/Fno.tsx:1-4] |
| `/intraday` (badge "research") | intraday backtests, SEBI facts, re-run, 1-year FYERS download | [web/ui/src/pages/Intraday.tsx:1-4]; [web/ui/src/app/nav.ts:104] |
| `/settings/:section` | data health, FYERS login, scan, capital, automatic jobs, about. The config is read-only (PATCH is P2). | [web/ui/src/pages/Settings.tsx:1-2] |
| `*` | NotFound | [web/ui/src/app/router.tsx:79] |

- The shell adds: a top bar (search / Ctrl K palette, index ticker, regime pill, freshness pill, FYERS chip, scan button, theme), a status bar, global banners and a first-run disclaimer dialog. — [web/ui/src/app/AppShell.tsx:68-144, 198-212]; [web/ui/src/components/layout/TopBar.tsx:69-138]

### Inferences
- Navigation is broad (12 nav items plus settings), but there is no single home for "what should I trade now". Verdicts are spread across Signals, the Chart page's Outlook, the Options verdict and the Intraday tab.

### Gaps
- I did not check the exact tab IDs of the Market and Settings sections.

## 3. Price auto-refresh diagnosis (complaint 1)

### Takeaway
Prices reach the browser only by 30-second REST polling of `/api/quotes`. There is no WebSocket or SSE. Polling runs only in the 09:15-15:30 IST "open" session and updates just three places: the top-bar index ticker (only on screens at least 1024 px wide), the Chart page's live pill and last daily candle, and the Signals page's "Now ₹" column. Everything else is a scan snapshot that changes only when a new scan file appears, at best every 30 minutes and only if the Windows jobs are set up. Without a FYERS login the "live" prices are Yahoo, about 15 minutes late.

### Cited Findings
**Mechanism**
- The hooks file states: "Scan-derived data never goes stale on a timer… Only /api/status polls." — [web/ui/src/api/hooks.ts:1-2]
- The global defaults are `staleTime: Infinity` and `refetchOnWindowFocus: false`. — [web/ui/src/main.tsx:14-22]
- `/api/status` polls every 10 s (1 s during a scan, 30 s when the tab is hidden). The ScanWatcher invalidates every query when `latest.scan_id` (the scan's `generated_at`) changes. — [web/ui/src/api/hooks.ts:51-67]; [web/ui/src/app/AppShell.tsx:25-37]; [web/api/services/strategies.py:55]
- `useLiveQuotes`:
  - is enabled only when `clock.session === 'open'`;
  - uses `refetchInterval: 30_000` and `staleTime: 20_000`;
  - returns an empty map when the market is not open.
  — [web/ui/src/api/hooks.ts:89-101]
- The session is "open" only from 09:15 to 15:30 on trading days. 09:00-09:15 is pre_open and 15:30-18:00 is post_close. — [web/api/services/clock.py:3, 49-56]
- Server side:
  - Outside the open session the endpoint returns "Market closed: last closing prices" from the store, with no network call. — [web/api/services/quotes_svc.py:84-88]
  - During the session it uses FYERS when logged in today, but only while more than 600 FYERS data calls remain today. Otherwise, or on an auth or rate-limit error, it uses Yahoo. — [web/api/services/quotes_svc.py:23-25, 89-108]
  - Per-symbol cache TTL is 30 s for FYERS and 60 s for Yahoo. — [web/api/services/quotes_svc.py:24, 97-101]
  - A symbol with no trade yet today falls back to the last stored close. — [web/api/services/quotes_svc.py:75-76, 117-118]
- The Yahoo quote is a daily-interval download (`interval="1d"`), labelled "Yahoo prices, ~15 min delayed". — [scanner/providers.py:222-239]; [web/api/services/quotes_svc.py:121-122]
- There is no browser push channel: no `WebSocket` or `EventSource` in `web/ui/src`. The FYERS WebSocket lives only in the background bar service. — [scanner/intraday/live.py:1-4, 179, 228]

**Which views refresh**

| View | Refresh | Ref |
|---|---|---|
| Top bar Nifty / N500 / VIX | 30 s while open. Hidden below `lg`. A/D and regime come from the scan. | [web/ui/src/components/layout/TopBar.tsx:74-83, 105-118] |
| Chart: live pill and last candle | 30 s while open, and only on the 1D timeframe (`data.tf !== '1d'` returns early) | [web/ui/src/pages/Chart.tsx:187-189, 357-363]; [web/ui/src/components/charts/PriceChart.tsx:207-224] |
| Chart: bars | `useChart` staleTime 10 min, no interval | [web/ui/src/api/hooks.ts:85-86] |
| Chart: side panel price / change | scan snapshot (`useStock`, staleTime Infinity) | [web/ui/src/pages/Chart.tsx:95, 112]; [web/ui/src/api/hooks.ts:87] |
| Chart: Levels (VWAP, opening range) | every 60 s, always | [web/ui/src/api/levels.ts:71-79] |
| Chart: Outlook / options verdict | every 2 min, only while a live quote exists | [web/ui/src/api/outlook.ts:105-112] |
| Signals: orders | scan snapshot. "the live scan in market hours re-checks them every 30 minutes" | [web/ui/src/api/hooks.ts:77-78]; [web/ui/src/pages/Signals.tsx:295-300] |
| Signals: "Now ₹" column | 30 s while open, symbols with orders only | [web/ui/src/pages/Signals.tsx:224-225]; [web/ui/src/components/domain.tsx:175-177] |
| Signals: Intraday tab | 60 s | [web/ui/src/api/hooks.ts:125-126] |
| Overview, Screener, Strategies, Market, Paper, Track record | scan snapshot only. The Screener says "Rankings use the last scan's prices". | [web/ui/src/api/hooks.ts:69-113]; [web/ui/src/pages/Screener.tsx:123] |
| Portfolio | `useHoldings` staleTime Infinity; prices from the last scan | [web/ui/src/api/hooks.ts:88]; [web/ui/src/pages/Portfolio.tsx:188] |
| Options | status 30 s; chain and history 60 s and big trades 15 s, only while `market_open` | [web/ui/src/api/options.ts:106-138]; [web/ui/src/pages/Options.tsx:488] |
| F&O "Live today" | polls 30 s while open, and triggers a server refresh every 3 min | [web/ui/src/api/fno.ts:81-85]; [web/ui/src/pages/Fno.tsx:183, 199-205] |
| Smart money "Big money live" | 60 s | [web/ui/src/api/smartMoney.ts:187-188] |
| Claude forecasts / automation status | 5 min | [web/ui/src/api/forecast.ts:49-56]; [web/ui/src/api/hooks.ts:161-162] |

**Scan cadence that drives every snapshot**
- Scans run at 08:30, then every 30 minutes from 09:45 to 15:15, then 15:40 and 19:15. Windows jobs run only while the user is signed in. A missing job shows a banner. — [web/api/services/automation_svc.py:25-36]; [README.md:359-365]; [web/ui/src/app/AppShell.tsx:128-141]
- The README promises live prices only for "the top bar and the Signals page… every 30 seconds". — [README.md:359]

**Concrete reasons a user perceives "no auto refresh"**
1. Most numbers on screen are snapshots: Overview tiles, Screener, Portfolio P&L, Market movers, strategy pages and the chart side-panel price. They change only on a new scan, every 30 minutes at best. — [web/ui/src/api/hooks.ts:1-2, 69-113]
2. Nothing polls outside 09:15-15:30, including pre-open, post-close, evenings, weekends and holidays. — [web/ui/src/api/hooks.ts:92-95]; [web/api/services/clock.py:49-56]
3. If FYERS is not logged in today, or under 600 calls remain, or FYERS returns an auth or rate-limit error, prices come from Yahoo daily bars, about 15 minutes late. Add the 60 s server cache and 30 s poll, and a value can be 15+ minutes old and change only once a minute. Before Yahoo has a bar for today, yesterday's close is shown. — [web/api/services/quotes_svc.py:24-25, 75-76, 91-108, 118]
4. Even with FYERS, the screen gets a REST snapshot roughly every 30-60 s (30 s TTL plus 30 s poll), not a tick stream. — [web/api/services/quotes_svc.py:24]; [web/ui/src/api/hooks.ts:96]
5. On the Chart page the toolbar shows a live price while the side panel shows the scan price, so two different "current" prices sit side by side. — [web/ui/src/pages/Chart.tsx:112, 361]
6. The weekly chart never updates live, there is no intraday chart, and the bars themselves never refetch on a timer. — [web/ui/src/components/charts/PriceChart.tsx:209]; [web/ui/src/pages/Chart.tsx:321]; [web/ui/src/api/hooks.ts:85-86]
7. Below 1024 px wide (phones, tablets, narrow windows) the top-bar ticker is hidden, so no live index prices show at all. — [web/ui/src/components/layout/TopBar.tsx:105]
8. At 15:30 the live map empties and the ticker falls back to the last scan's values (possibly the 15:15 live scan), so numbers can jump backwards until the 15:40 scan. — [web/ui/src/api/hooks.ts:99]; [web/ui/src/components/layout/TopBar.tsx:75-76]
9. Returning to the tab does not refetch, because `refetchOnWindowFocus` is false. — [web/ui/src/main.tsx:19]
10. If the scheduled jobs are not registered, or the PC is signed out, the 30-minute live scans never run and snapshots go stale until a manual scan. — [README.md:364-365]; [web/ui/src/app/AppShell.tsx:128-141]

### Inferences
- Any page other than the three live spots looks frozen during market hours. Even live spots look frozen for most of the day without a FYERS login.
- Fixing this means pushing quotes to the browser (SSE or WebSocket fed by the existing FYERS WebSocket service, `scanner/intraday/live.py`). It also means applying live prices to the side panel, Portfolio P&L, Overview tiles and Screener, an intraday chart timeframe, and a visible "as of HH:MM:SS / source" stamp on every price.

### Gaps
- I did not observe live behaviour in a browser, so the exact Yahoo lag and FYERS quote latency are unmeasured.
- I did not check whether FYERS REST `live_rows` returns index quotes reliably (`NSE:NIFTY50-INDEX` mapping at [scanner/providers.py:43]).

## 4. Signal clarity diagnosis (complaint 2)

### Takeaway
There is no single per-stock BUY/SELL verdict anywhere. Stock "signals" are next-open orders from model portfolios: BUY to enter, SELL to exit a model holding. On most days there are almost none. The only explicit verdict is the options verdict, and its evidence gates make NO TRADE the designed default. A user meets about 18 different label vocabularies, several of which overlap or contradict each other.

### Cited Findings
**Where verdicts and labels are produced, the rule, and where they show**

1. **Strategy orders: BUY / SELL.**
   - Rule: each strategy's rules at the close become next-open orders, sized to capital.
   - "No orders" reasons: "Regime filter on…", "No changes until the next review on …", "No entry signals today." — [web/api/services/sizing.py:152-158]
   - Display: `SidePill` BUY green / SELL red. — [web/ui/src/components/badges.tsx:85-91]; [web/ui/src/components/domain.tsx:167]; [web/ui/src/pages/Signals.tsx:101-159]
   - SELL means selling a holding: your own, sized from your holding, or the model's. It is not a short. — [web/ui/src/pages/Signals.tsx:238-242]
   - Orders from "not-working" or inactive strategies are comparison-only and collapsed. — [web/api/services/strategies.py:244-245]; [web/ui/src/pages/Signals.tsx:314-326]
   - **Today's data** (`data/results/latest.json`, live scan generated 2026-11-11 09:43): 14 strategies, of which 5 are working, 2 mixed, 5 unknown ("Too new") and 2 not-working. The 12 non-comparison strategies have 0 orders. The only order is 1 BUY from `golden_cross`, which is not-working, so comparison-only and hidden by default.
2. **Strategy status: Working now / Mixed / Not working / Too new, plus amber "Beat a falling market" (Fell less).**
   - Rule: beat Nifty 50 and the average stock over 12 and 6 months. — [web/ui/src/lib/vocab.ts:20-33]
   - Shown on Signals, Strategies and the chart side panel.
3. **Lifecycle: Active / Tested & rejected / Off.** — [web/ui/src/lib/vocab.ts:35-39]
4. **Evidence grade: Strong / Moderate / Weak / Folklore / Experimental** (literature quality). — [web/ui/src/lib/vocab.ts:41-47]; [web/ui/src/components/badges.tsx:47-60]
5. **Signal strength: 0-100 graded Strong ≥70 / Good ≥50 / Fair ≥30 / Weak.**
   - Rule: evidence 30 + backtest status 25 + agreement 25 + live record 10 + no results 10, BUY only. It "is not a forecast and never changes an order". — [web/api/services/signal_quality.py:1-20, 37-59]
   - Display: [web/ui/src/components/badges.tsx:156-178]; [web/ui/src/components/domain.tsx:174]; the "Strongest buy signals" card appears only when buys come from at least 2 strategies. — [web/ui/src/pages/Signals.tsx:289-293]
6. **Market regime: Bullish / Mixed / Bearish.**
   - Rule: Bullish = Nifty above its 200-DMA and breadth ≥50%; Bearish = below the 200-DMA; otherwise Mixed. — [scanner/daily.py:470-480]
   - Display: top-bar pill. — [web/ui/src/components/layout/TopBar.tsx:15-24]
7. **Freshness / provisional labels.**
   - Pill: "LIVE · <source> · provisional", "EOD <date> · NSE", "STALE". — [web/ui/src/components/layout/TopBar.tsx:26-44]
   - Banner: "PROVISIONAL: based on today's still-forming candle…". — [web/ui/src/app/AppShell.tsx:107-113]
   - Also a "Provisional" chip, and a "live candle, provisional" subtitle on Signals. — [web/ui/src/components/badges.tsx:121-128]; [web/ui/src/pages/Signals.tsx:255]
   - Quote badge: "Live" / "Delayed". — [web/ui/src/components/layout/TopBar.tsx:107-111]
   - README explanation: [README.md:26-29]
8. **Options verdict: BUY CALL / BUY PUT / NO TRADE / NO VERDICT.**
   - Rule, all of these must hold for a BUY: — [scanner/option_verdict.py:1-18, 32-36, 74-115, 118-162, 182-214]
     - (a) a tested direction: the outlook study's similar setups at the horizon nearest expiry are "better" with a positive median, or "worse" with a negative median, and/or a working strategy's BUY/SELL today, with no disagreement;
     - (b) an option whose history-fair value beats ask + 3% costs by at least 10%;
     - (c) at least a 35% chance of ending above breakeven, spread ≤10%, OI ≥200 and ≥2 days to expiry;
     - (d) a chain that is not older than the last price bar.
   - Anything else is NO TRADE ("a NO TRADE is the normal answer"); missing data or a stale chain gives NO VERDICT.
   - Display:
     - a badge on the chart, "Options: BUY CALL 24500 CE" — [web/ui/src/pages/Chart.tsx:377-384]
     - a panel with checks, direction and record — [web/ui/src/components/OptionVerdict.tsx:42-90]
     - styles — [web/ui/src/lib/verdict.ts:5-10]
   - Availability: only for symbols with a stored chain. The default `options.underlyings` is `[NIFTY, BANKNIFTY]` plus stocks the user adds. — [config.yaml `options:`]; [web/api/services/outlook_svc.py:324-350]
   - **Journal data** (`data/results/option_verdicts.json`): 6 verdicts recorded on 2026-11-04, 11-09 and 11-11 (NIFTY 4, RELIANCE 2). All 6 are NO_TRADE.
9. **Outlook verdict: "better than average" / "worse than average" / "like the average stock" / "not measurable".**
   - Rule: |t| ≥ 2 vs the average stock, before costs, on at least 200 events over 24 months. — [scanner/outlook.py:37-38, 300-321]
   - The headline reads like "…median move +x% and y% ended higher - no different from the average stock (within luck)". — [web/api/services/outlook_svc.py:112-126]
   - Display: [web/ui/src/components/Outlook.tsx:14-19, 205-222]
   - The panel subtitle says "base rates from history, not a forecast". — [web/ui/src/components/Outlook.tsx:215]
10. **Outlook "Signals now": Bullish / Bearish / Neutral**, each tagged with a source (Strategy, Candle, Chart pattern, Trend, Volume, Options, Futures, Intraday, Event) and a "tested" note: "strategy working, backtest +x%/yr", "tested: no edge", "not tested (positioning, not a signal)", "proven intraday strategy". — [web/api/services/outlook_svc.py:213-279, 469-501]; [web/ui/src/components/Outlook.tsx:20-28, 146-177]
    - Footnote: "Counted, not weighted: several signals pointing one way are not a stronger forecast." — [web/ui/src/components/Outlook.tsx:176]
11. **Pattern evidence:** "tested: edge" / "tested: edge before costs only" / "tested: no edge" / "tested: worked in reverse" / "tested: no direction" / "too few cases" / "untested".
    - Rule: signed excess after ~0.45% costs, t ≥ 2. — [scanner/pattern_study.py:15-16, 128-139]
    - Display: [web/ui/src/components/PriceAction.tsx:42-59]
    - **Data** (`pattern_study.json`): of 23 patterns, 18 are no_edge, 3 no_direction, 2 opposite, and 0 have an edge.
    - The chart still draws candle patterns as green ▲ / red ▼ arrows. — [web/ui/src/pages/Chart.tsx:272-277, 395]
12. **Chart pattern status: "forming" / "confirmed N bars ago"**, with breakout, target and void levels. — [web/ui/src/pages/Chart.tsx:64-92]
13. **Intraday signals: side LONG / SHORT; state Open / Closed.**
    - Signals come only from strategies with status "working" (significantly positive average day, Bonferroni-corrected, over 40+ sessions). — [scanner/intraday/run.py:357-377]; [scanner/intraday/run.py:296-305]
    - Otherwise the note reads: "No intraday strategy has a proven edge after costs (N tested): no signals." — [web/api/services/intraday_view.py:131-134]
    - Display: [web/ui/src/pages/Signals.tsx:161-200]
    - The Intraday page's edge column shows yes / no / "loses (significant)". — [web/ui/src/components/badges.tsx:143-154]
    - **Data**: `intraday.json` (2026-11-10, 71 Yahoo sessions) has 12 of 12 strategies "not-working", 10 of them with significant losses. `intraday_signals.json` shows that note with 0 signals.
14. **Holding level: Danger / Watch / Target hit / OK / No data**, plus "STOP-LOSS HIT" / "TARGET REACHED". — [web/ui/src/components/badges.tsx:94-100]; [web/api/services/holdings_svc.py:60-61]
15. **Track record: "Making money" / "Losing money" / "Too few closed signals to judge yet (n of 10)".** — [scanner/track.py:27, 55-63]
16. **Claude forecast: "unproven" / "beats a coin flip" / "no edge"**; the card title carries "(unproven)". — [web/ui/src/components/AiForecast.tsx:20-22, 180]; [scanner/ai_forecast.py:316-317]
17. **F&O build-ups: Long build-up / Short build-up / Short covering / Long unwinding.**
    - These are "Positioning, never a signal" in the pages, but the outlook signals list maps them to bullish or bearish. — [web/ui/src/api/options.ts:150-153]; [web/ui/src/pages/Fno.tsx:1-4]; [web/api/services/outlook_svc.py:264-270]
18. **Strategy markers on the chart:** "▲ model buy / ▼ model sell / ● open model position". — [web/ui/src/pages/Chart.tsx:395]

**How often NO TRADE appears**
- By design: the docstring calls a NO TRADE "the normal answer". — [scanner/option_verdict.py:14-17]
- Observed: 6 of 6 journalled verdicts are NO_TRADE.
- Direction gate, measured on the outlook study (`outlook_study.json`, generated 2026-11-10, 885,327 events, 309 groups meeting the minimums). Event-weighted share of setups that give a usable direction:

  | Horizon | Usable direction | Bullish | Bearish |
  |---|---|---|---|
  | 5-day (nearest to weekly expiries) | about 18% | 1.3% | 16.4% |
  | 10-day | about 36% | – | – |
  | 20-day | about 42% | – | – |

  These are my computation across all fallback levels, so approximate.
- For NIFTY itself no strategy trades the index symbol, so only the study can give a direction, and the study is measured on stocks. — [web/api/services/outlook_svc.py:124-125]

**Conflicts and confusion**
- No per-stock verdict exists. The Chart page, where users look, shows a regime pill ("Bullish"), Outlook prose ("no different from the average stock"), a mixed Bullish/Bearish/Neutral list and an options "NO TRADE", all at once.
- A strategy SELL (an exit of a long model holding) is shown as "bearish" in the outlook signals and counts as a bearish vote in the options direction gate. — [web/api/services/outlook_svc.py:229-232]; [scanner/option_verdict.py:99-107]
- "Strong" means three different things: evidence grade, strength grade, and the chart's "Strong momentum" setup chip. — [web/ui/src/lib/vocab.ts:42]; [web/ui/src/components/badges.tsx:156-157]; [scanner/outlook.py:53]
- "Mixed" means two different things: regime and strategy status.
- "Live" means at least six things: quotes, freshness, live record, "Big money live", "Live today" F&O, and paper "live proof".
- A BUY from a "Too new" (unknown-status) strategy with STRONG evidence and two agreeing strategies scores 30+5+25+5+10 = 75, which displays "Strong". — [web/api/services/signal_quality.py:14-20, 43-59]
- Green and red candle arrows sit on the chart while their own tests say "no edge". — [web/ui/src/pages/Chart.tsx:272-277]; [web/ui/src/components/PriceAction.tsx:42-49]
- Side vocabularies differ: BUY/SELL for stocks, LONG/SHORT for intraday, BUY CALL/BUY PUT for options, Buys/Sells for smart-money deals.

### Inferences
- The "only NO TRADE" impression comes from three things together: the options verdict defaults to NO TRADE, the intraday tab says "no proven edge", and the Signals page often shows "No orders today". There is a hidden fourth: the stock BUY/SELL orders exist only for model portfolios on rebalance or entry days and are not a per-stock verdict.
- A clear-cut verdict layer (for example, one "Action: BUY / SELL / HOLD / AVOID" per symbol with its confidence and evidence) would need to combine strategy orders, holdings, outlook and options in one place.
- Any such layer would have to keep the platform's evidence gates and the SEBI disclaimers, or knowingly change them.

### Gaps
- I did not count how many days in the journal produced zero orders. Only today's `latest.json` was inspected.
- How often the options value gate passes when a direction exists is unmeasured; the journal is too small (6 rows).

## 5. "Not investment advice" disclaimers

### Takeaway
Disclaimers are pervasive: README, a first-run dialog, the status bar, Settings › About, onboarding, Signals footers, option/AI/smart-money notes, Telegram and the legacy Streamlit app.

### Cited Findings
- README banner: "Rule-based signals tested on history - not investment advice… requires SEBI Research Analyst registration". — [README.md:11-13]
- First-run dialog: "Quant Desk is a personal research tool, not investment advice… You decide and place every trade yourself". — [web/ui/src/app/AppShell.tsx:198-212 (lines 205, 209)]
- Status bar link: "Research tool · not investment advice". — [web/ui/src/components/layout/StatusBar.tsx:63]
- Settings › About: "not investment advice… the app never places orders… SEBI Research Analyst registration". — [web/ui/src/pages/Settings.tsx:349-352]
- Onboarding: "Research tool, not investment advice. Nothing here places orders." — [web/ui/src/pages/Onboarding.tsx:35]
- Signals footers: "You decide and place every trade yourself". — [web/ui/src/pages/Signals.tsx:195, 328]
- Options verdict note: "Research, not advice: you decide." — [scanner/option_verdict.py:41-43]
- AI analyst: "Research, not investment advice: you decide". — [web/api/services/ai_svc.py:30, 57]
- Forecasts: [web/api/services/forecast_svc.py:45-46]
- Smart money: [web/api/services/smart_money_svc.py:38]; [web/ui/src/pages/SmartMoney.tsx:41]
- Outlook "Base rates, not a forecast": [web/api/services/outlook_svc.py:24-28]
- Telegram: [scanner/alerts.py:110]
- Streamlit: [app.py:36]
- Spec: [docs/ui_spec.md:168, 605]

### Inferences
- Any move toward explicit BUY/SELL calls has to fit this framing. The repo itself notes that sharing signals as recommendations requires SEBI RA registration.

### Gaps
- None material.

## 6. Test suite size and frontend test setup

### Takeaway
The Python pytest suite has 28 files and about 385 test functions, reported as 442 passing. The frontend has vitest unit tests on `src/lib` helpers only: 6 files and no component or E2E tests.

### Cited Findings
- `tests/`: 28 `test_*.py` files with 385 `def test_` functions (my grep) and 7 `parametrize` decorators. The largest are `test_api_contract.py` (79), `test_core.py` (36), `test_intraday.py` (29), `test_pit.py` (25) and `test_store.py` (24). Fixtures are in `tests/fixtures`.
- The command is `.venv\Scripts\python.exe -m pytest -q`. — [README.md:424]; [requirements.txt:1, 12 (pytest 8.4.2)]
- The PR reports "Python: full suite 442 passed before the live-F&O change". — [..\PR_DESCRIPTION.md:17]
- Frontend scripts: `npm test` = `vitest run`, `npm run lint` = eslint, `npm run build` = `tsc -b && vite build`. — [web/ui/package.json scripts]; [web/ui/README.md:17, 28-29]
- Vitest 3.2.4 has 6 test files, all in `web/ui/src/lib`: `chartMappers` (15), `format` (19), `intraday` (2), `overview` (3), `patternDrawing` (11) and `sizing` (15) `it/test` calls, 65 in total by grep.
- The PR says "vitest (49 passed)" and "eslint (one pre-existing warning)". — [..\PR_DESCRIPTION.md:18]
- There is no React Testing Library, Playwright or Cypress in `devDependencies`. — [web/ui/package.json]

### Inferences
- UI behaviour such as polling and refresh wiring is untested, so refresh regressions would not be caught.

### Gaps
- My grep count (65) differs from the PR's 49. It may include `describe`/`it.each` or later additions; I did not run vitest.

## 7. Known open issues recorded in the repo

### Takeaway
The PR description, README "not perfect" and roadmap notes, and the spec's P2 list record data, backtest and UI limitations. Order placement, market depth, fundamentals, news and sentiment are explicitly out of scope.

### Cited Findings
- PR "Known open issues (not fixed here)":
  - ETF strategies use the stock price and turnover filters;
  - ETF costs and tax are treated as shares;
  - a data gap is treated as a delisting;
  - a NaT path in `scanner/events.py`;
  - the SPA route resolves `%5C` paths to a network share before its check.
  — [..\PR_DESCRIPTION.md:21-22]
- The PR says the F&O "Live today" view "was not checked in the browser yet". — [..\PR_DESCRIPTION.md:19]
- README "What is still not perfect":
  - timing luck;
  - rights issues not adjusted in point-in-time prices;
  - dividends excluded;
  - the universe ranks by traded value rather than free-float;
  - a delisted holding is sold at its last price after 20 days;
  - momentum crashes;
  - tax.
  — [README.md:135-145]
- Roadmap: adjust rights issues, add sector strength from NSE sector indices, combine momentum and low-vol. — [README.md:428-433]
- Sector rotation's point-in-time result is "flattered". — [README.md:63]
- Big trades live is "Not yet seen on a live session". — [README.md:332-333]
- FYERS is not used for option chains yet. — [README.md:298]
- Intraday results so far: all strategies lose after costs. — [README.md:270-273]
- Spec P2 items still open:
  - walk-forward validation card B8 — [docs/ui_spec.md:110, 326]
  - PATCH `/api/config` (config editing; Settings is read-only) — [docs/ui_spec.md:1015, 1636-1644]; [web/ui/src/pages/Settings.tsx:1-2]
- Out of scope: "order placement, market depth, option chains, fundamentals/valuation, news, social sentiment". Option chains have since been added. — [docs/ui_spec.md:1896]
- The intraday chart is not built (the 5m button is disabled). — [web/ui/src/pages/Chart.tsx:321]
- No TODO/FIXME markers in `scanner`, `web/api` or `web/ui/src` (grep).

### Inferences
- None of the recorded issues mentions the two owner complaints (auto-refresh, clear BUY/SELL). Both are design consequences, not tracked bugs: the "Only /api/status polls" architecture and the evidence-gated verdict philosophy.

### Gaps
- I did not search `docs/smart_money_spec.md` (2,421 lines) or `docs/strategy_catalogue.md` for further open items beyond a P2/TODO grep of the UI and intraday docs.

# NSE Scanner v2: user guide and plan

A personal, evidence-based tool for the Indian stock market. Every day it:

1. **Updates prices** for about 500 Nifty 500 stocks, using 8 years of history, NSE's official end-of-day files, and Fyers real-time prices.
2. **Re-tests every strategy** on that 8-year history, *survivorship-free*: on each past day only that day's 500 most-traded NSE stocks, including companies that later crashed or were delisted. Each test buys at the next day's open and pays full Indian charges and tax.
3. **Shows which strategies are working now**, meaning which beat Nifty and the average stock over the last 12 and 6 months.
4. **Lists the orders** each strategy would place at the next open, sized for your capital, with stop-losses.
5. **Checks your own holdings**: stop-loss, target, trend, momentum rank, and splits/bonuses since you bought.

> ⚠️ **Rule-based signals tested on history - not investment advice.** No system knows tomorrow's
> prices. Past results don't guarantee future returns. You decide; always use a stop-loss.
> Sharing these signals as recommendations with others requires SEBI Research Analyst registration.

---

## 1. Daily use

| When (IST) | What to do |
|---|---|
| Every trading morning, after 6 AM (best before 9:14 AM) | **🔑 Log in to Fyers.** Click the **Fyers** chip in Quant Desk's top bar, then **Log in with Fyers** (no command needed; see below). A token made before 6 AM stops working at 6 AM, and the 9:14 intraday live feed waits for the login. SEBI rules require a daily login since April 2026. |
| Any time | Double-click **`3_dashboard.bat`** (Quant Desk opens at http://127.0.0.1:8600). It keeps itself current: after an update it restarts its server by itself, and an open page shows **Quant Desk was updated - Reload** (the old Streamlit dashboard, `3b_dashboard_streamlit.bat`, gets no new features), then start a scan in **Settings › Scan** (**Full scan**). A scan takes a few minutes because it re-tests every strategy (a re-check without download took about 2.5 minutes on 24 Oct 2026); longer when it downloads new prices. The old Streamlit dashboard (`3b_dashboard_streamlit.bat`) has a **🔄 Run scan now** button. |
| 3:40 PM / 7:15 PM | Automatic Telegram summaries, if you set them up (section 6). |
| **After about 7 PM** | **Best time to decide.** NSE's official end-of-day data is published, so signals are final. |

Orders marked *provisional* are based on live or delayed quotes, not NSE's official close (that includes the 3:40 PM
scan). They can change until the official data is published, after about 6 PM. During the session today's volume is
the real volume traded so far, never an estimate of the full day, so a breakout that needs heavy volume shows only once
that volume has actually traded.

No demo, sample or simulated data anywhere: every price, volume, open interest and disclosure comes from NSE, FYERS
or Yahoo. Backtests and paper trading are calculations on those real prices, and every page labels them as such.

### One answer per stock: BUY · SELL · HOLD · NO EDGE
The **Today** page (`g d`) and the top of every **Chart** page give one answer per stock, taken only from tested rules
(`web/api/services/action_svc.py`):

| Answer | When |
|---|---|
| **BUY** | A strategy whose own survivorship-free backtest, after costs and tax, is *working* buys it at the next open, and no working strategy exits it. The card shows the entry reference, quantity, stop-loss, the risk if stopped, the backtest's yearly return with its timing range and worst drop, and the strategy's live signal record. |
| **SELL (exit)** | You hold it and a working strategy exits it, or your own stop-loss is hit. |
| **HOLD** | You hold it and no exit fired. |
| **NO EDGE** | Anything else, with how close each working strategy is to acting (its rank and next review, or "holds it in its model since …"). |

**BUY (late entry).** A stock a working strategy already holds (bought on an earlier day) is a BUY only when that
strategy's **late-entry test** says joining that late still paid: every trade of its 8-year survivorship-free backtest
re-run with the entry 5, 10 or 21 trading days after the model's own, exit unchanged, against the average top-500
stock over the same days after ~0.45% costs (`scanner/late_entry.py`, Late entry card on each strategy page). On
11 Nov 2026: Earnings gap-up (working) still pays up to 10 days late (+2.3% vs the average stock after costs, t 2.1),
so the 4 stocks it bought 4-9 days earlier showed as BUY; momentum leaders shows no edge once late.

Buys of strategies whose backtest is *mixed* or *too new* are shown as "unproven buy" lines, never as the answer;
not-working strategies never appear. Results days, the F&O ban list, the regime filter and provisional (intraday)
scans are risk chips that never change the answer. Candle and chart patterns, option positioning, F&O build-ups and
Claude never decide it: none of them shows an edge after costs in this app's own tests. A strategy's SELL is an exit of
its own long position, so it is never counted as a bearish forecast anywhere (options verdict, outlook).

### Live prices on every page
Prices reach every page through one event stream (`/api/stream/quotes`, Server-Sent Events): the top bar, Chart (toolbar,
side panel, last candle), Today, Portfolio (value, P&L, today's P&L and a live stop-loss / target check between scans),
Screener (price and 1D of the first 100 rows), Overview (VIX, movers) and Signals. Every price carries its source and
age: **Live 10:42:17** (FYERS WebSocket, about a second behind the exchange), **FYERS** (REST, ≤30 s), a red
**DELAYED 15 MIN** badge (Yahoo, when you are not logged in to FYERS; click it to log in), **Last trade 15:29:58**
(after the close, until NSE's official close after ~18:00) or **Close 10 Nov**.

The live service (`4_intraday_live.bat`, started at 09:14) streams up to 100 symbols on the FYERS Standard plan and
follows the screen: the symbols on the open pages come first (`data/intraday/live/subscriptions.json`), then the F&O
instruments for big trades, then the most liquid stocks for the 5-minute bars. It writes `quotes.json` twice a second;
symbols it doesn't stream fall back to FYERS REST quotes (cached 30 s and shared by every tab) and then Yahoo. FYERS
Prime (₹499/month + GST) raises the stream to 5,000 symbols.

### Watchlists, price alerts and intraday charts
- **Watchlist** page (`g w`): your own lists with live prices, each stock's source stamp and its one tested answer.
  The star on any chart adds the stock to your first list.
- **Price alerts** (Watchlist page, or the bell on any chart): price at or above / at or below a level, or the day's
  change at or above / below a percentage. An alert fires **once** (re-arm it to use it again): a pop-up in the app,
  a browser notification when allowed, and a Telegram message when it is set up (section 6). The live service checks
  alerts on every FYERS tick batch, twice a second, even with Quant Desk closed; without a FYERS login the app checks
  them on Yahoo prices, about 15 minutes late, and the fired alert says so. Stored in `data/alerts.json` (fired:
  `data/alerts_fired.jsonl`).
- Alert and watchlist symbols are streamed by the live feed right after the symbols on screen (`data/watchlists.json`),
  within the FYERS plan's symbol limit.
- **Intraday charts** (Chart page, `5m` / `15m`, key `i`): candles of the last 1-10 sessions with each session's VWAP and
  volume, from the FYERS feed and history (Yahoo fills older days); the last candle follows the live price. They cover
  the ~150 most liquid F&O stocks and the symbols the live feed streams (add a stock to a watchlist to include it).

### Your own scans, with an 8-year backtest in one click
The **Scans** page (`g x`) builds a scan from up to 8 rules ("all" or "any"): 34 fields (price, SMAs / EMAs, MACD,
returns, relative strength, RSI, 20-day and 52-week highs / lows, ATR, volatility, volume vs average, traded value,
delivery %), compared with a number or another field (`close > 1.02 × sma50`), or *crosses above / below*.
- **Run today**: the matching stocks of your universe on the stored prices, "new" when they started matching that day,
  prices following the live price.
- **Backtest 8 years**: the scan's event study on the survivorship-free top 500 since Aug 2018 (`scanner/scans.py`,
  the same test as every pattern here): each time a stock *starts* to match, buy at the next open, hold 5 / 10 / 20 days,
  compared with the average member over the same days, ~0.45% round-trip costs subtracted, t-statistic on monthly
  averages, by year and the last 25 events. A few seconds (the first one loads the data, ~10 s).
- Save scans; six popular setups are there as examples. In the 11 Nov 2026 data none of them has an edge after costs
  (RSI(2) oversold in an uptrend beats the average stock before costs only, t 3.2), and "close above the 200-day"
  at the moment it starts **worked in reverse** (t -4.7). Most scans show no edge; this tells you which.

### Could a strategy's backtest be luck?
Every strategy page has a **Robustness** card (`web/api/services/robustness.py`): a 10,000-path Monte Carlo of the
backtest's own daily returns (21-day blocks: the spread of yearly returns and drops, how often it lost money or trailed
the average stock), the **deflated Sharpe ratio** (Bailey & Lopez de Prado 2014: corrected for the ~19 strategies tried
here, since the best of many looks good by chance), every rolling 12-month window, and the first half against the
second. Verdict: *likely real* (deflated Sharpe 95%+ and 75%+ of the histories beat the average stock), *could be luck*
or *likely luck*. On 11 Nov 2026: momentum leaders "could be luck" (deflated 66%), trend breakout and low volatility
"likely luck".

### Checks on the app itself (Benchmarks page, `g k`)
- **Walk-forward of the "working" rule** (`web/api/services/walkforward.py`): each month-end, the rule the Action card
  uses (beat both the Nifty 50 and the average stock over 12 and 6 months, no loss to date) is applied with only the
  data up to then, and the strategies it calls working are held for the next month. Sep 2020 - Nov 2026: following it
  made +26.4%/yr vs +17.4% holding every strategy, +21.5% the average stock and +13.4% the Nifty 50 (t 2.1 vs every
  strategy).
- **Speed and depth measured on this PC** next to what Trade Ideas, TrendSpider, NinjaTrader and MetaTrader publish,
  and the FYERS tick-to-screen latency measured in your browser.
- **Options direction for an index from the index itself** (`scanner/index_study.py`): NIFTY's options verdict uses
  NIFTY's own history of today's setup (trend vs the 50 / 200-day average, RSI band), not a study measured on stocks.
- **Dated capital-gains tax**: gains realised before 23 Jul 2024 are taxed at the old 15% / 10% (+ cess, Rs 1 lakh LTCG
  exemption), later ones at 20% / 12.5% (`tax: dated: 0` in config.yaml uses today's rates for every year).
- **Scans in plain English** (Scans page, needs `ANTHROPIC_API_KEY` in `.env`): Claude turns the idea into the builder's
  rules, says what it could not express, and you check, run and backtest it.

### Chart tools
- **Draw** (1D / 1W chart): levels, trendlines and Fibonacci retracements, saved per stock (`data/drawings.json`);
  a level becomes a price alert in one click.
- **Indicators**: SMA 20 / 50 / 100 / 200, EMA 9 / 21 / 50 / 200, Bollinger, Keltner and Donchian channels, Supertrend,
  volume, and panes for RSI, MACD, Stochastic, ADX (+DI / -DI), ATR, on-balance volume, CCI, money flow, Williams %R and
  rate of change (textbook parameters).

### Placing orders on your own FYERS account (Orders page, `g e`)
Off until you switch it on (Orders page, type ENABLE). Then every BUY / SELL card has **Buy on FYERS… / Sell on
FYERS…**, which opens an order ticket prefilled from the signal (quantity sized for your capital, limit at the live
price, the strategy's stop-loss):
1. **Review order** sends nothing: the server returns the exact FYERS order, every check, the charges and the risk if
   stopped (`web/api/services/orders_svc.py`).
2. Tick *I have checked this order* and **Send** within 60 s. One attempt only: if FYERS doesn't answer, the app says
   "check the order book" and never resends (a retry could buy twice).

Checks enforced on the server (limits in `config.yaml` → `orders:`): switched on, kill switch off, logged in to FYERS
today, market open (no after-market orders through the API), limit orders only (unless `allow_market`), the limit within
3% of the last price, one order at most 10% of capital, at most 20 orders a day, at least 1 s apart, no repeat of the
same order within 2 minutes, **daily-loss lockout** (today's P&L below -2% of capital: no new buys for the day; exits are
always allowed), and for a delivery sell no more than you hold. The **kill switch** blocks every new order and cancels
every pending one. Once a delivery buy fills, **Protect** places a FYERS GTT OCO sell: the target above the price and the
stop-loss below it, whichever comes first, live across days. Slippage of each signal's fill against its reference price
and an append-only audit of everything sent or blocked (`data/orders_audit.jsonl`) are on the same page.
While the live service runs (`4_intraday_live.bat`, market hours) it also listens on FYERS' order socket: a fill,
rejection or cancellation of any of your orders shows as a notice on every open page within about a second
(`scanner/intraday/order_feed.py`, read-only; without it the Orders page checks every 5 s). Each filled order is kept in
`data/fills.jsonl`, since FYERS' order book only covers today: that is your trade history for the Coach.

SEBI's retail algo framework (in force for all brokers from 1 Apr 2026) applies to API orders: register this PC's
**static IP** in the FYERS API dashboard and log in every trading day. Below 10 orders a second your own orders need no
strategy registration; the app stays at 1 a second. Your own account only: the app never trades for anyone else.

### Replay (`g y`): practise on real past sessions
Pick a stock and a past day, or **Random, blind** (the name and date stay hidden until the end, so memory can't help),
then reveal one bar at a time (Space play / pause, → next bar, `b` buy, `s` sell). 5- and 15-minute replays cover the
~150 most liquid F&O stocks over the months in the intraday store, after two sessions of context; Daily replays the
next 60 sessions from any date since 2018 (long only: delivery can't be sold short). Market orders fill at the last
close plus slippage, stops and targets on the bars after (at the open when the price gaps past them, the stop first
when one bar touches both), intraday positions are squared off at the close, and FYERS' real charges apply. A finished
session with trades is saved to `data/replay_log.jsonl` with the P&L recomputed on the server from the bars, never
taken from the browser; the page shows your practice record (win rate, per trade, R, profit factor, exits).

### Charts: types, drawings, multi-chart (`g c`, `g l`)
- **Chart types** on the daily / weekly chart: candles, Heikin Ashi (smoothed; indicators and drawings still line up),
  Renko (1-5% bricks) and three-line break (time left out, so they get their own simple chart).
- **Drawings**: level, trendline, Fibonacci, zone, text note and anchored VWAP (from any bar). A level or a trendline
  becomes an alert in one click; a trendline alert follows the line as it rises or falls.
- **Multi-chart** (`/charts`): 1, 2 or 4 charts, each its own stock and timeframe (1W / 1D / 15m / 5m / 1m), or one
  stock on four timeframes at once.

### Alerts beyond price
Besides price, day-change and trendline alerts (checked on every live tick), alerts on **RSI(14)**, a **moving-average
cross** (10 to 200 days), a **saved scan getting a new stock**, and a **candle pattern with a tested edge** on a stock
(only patterns whose 8-year study verdict is "edge"). The RSI / average / scan ones use the live price on the daily
history (`scanner/rule_alerts.py`) and are checked by the 5-minute intraday job, the open dashboard and each scan;
patterns after each scan. Telegram and, after **Turn on notifications** (Watchlist > Alerts), a desktop notification.

### Installable app
The dashboard can be installed as an app (the install icon in Edge / Chrome's address bar): its own window and a
Start-menu / taskbar icon. Notifications then show with the window in the background, and a click opens the right page.
Only the build files are cached; prices, signals and orders always come from the server. A phone gets alerts through
Telegram (the dashboard runs on this PC).

### Live scans
Scans > **Live prices** runs the scan on today's live prices (re-run every minute): today's candle is the last bar,
indicators included; only stocks with a live quote can match. The bell on a saved scan sets a new-hit alert.

### Practice account (`g u`) and trading from the chart
A practice account on today's live prices: the same order ticket as the real one (switch **Practice / Real · FYERS**),
market and limit orders, stop-loss and target, intraday shorts squared off at 15:20, FYERS charges, nothing sent to
FYERS (`web/api/services/sim_svc.py`, `data/sim_account.json`). On a chart, **Trade on chart** opens a ticket at the
price you click; the **Market depth** card shows FYERS' five best bids and offers (needs today's login, refreshed every
2 s while open) and a click on a price opens a ticket there. Personal use only: NSE's data policy does not allow
offering simulated trading on live prices to others.

### Strategy builder (`g j`)
Describe a strategy in plain English (Claude turns it into rules; it never says whether they work) or build it from
the rule editor: entry rules from the scan fields, exits by stop, target, trailing stop, holding days or exit rules,
up to 50 positions, ranked by any field. **Test 8 years** runs it exactly like the built-in strategies: the
survivorship-free top 500, costs, slippage, tax, the "working" test, plus the first 70% of the years against the last
30%. **Optimise exits** tries 27 exit settings with a walk-forward: each year uses the settings that did best on the
years before it only, shown next to the hindsight best and a deflated Sharpe ratio, so the optimism of tuning is
visible. A spec is data, never code (`scanner/custom.py`); saved in `data/custom_strategies.json`.

### Your strategies in every scan, basket orders
- Strategy builder > **Re-test in every scan**: a saved strategy joins the daily scan like the built-in ones (re-tested
  on the survivorship-free universe, a "working" status); its BUY / SELL appear on Today only while it is working.
- Today > **Review all**: the day's BUYs / SELLs in one basket, practice or real. Real orders are reviewed with every
  check (nothing sent), then sent one at a time at least a second apart, each once; one that fails doesn't stop the rest.

### Seasonality, market heatmap
- **Seasonality** (chart side panel): each calendar month's average return over the years in the store (8-9 here),
  up years, and a t-statistic; only months with |t| >= 2 over 8+ years count as a pattern, the rest is noise.
- **Market heatmap** (`g v`): today's universe by industry, sized by 20-day traded value (NSE's day files carry no
  market cap), coloured by today's live move or the 1W / 1M / 3M / 12M return; click a stock for its chart.

### Order flow (intraday chart > Order flow)
Without FYERS Prime: the live service splits each tick's new volume into bought (at or above the ask) and sold (at or
below the bid; in between by the price move) per minute and price level (`scanner/intraday/orderflow.py`,
`data/intraday/live/orderflow_YYYYMMDD.parquet`, 10 days kept). The chart shows delta per bar and cumulative delta under
the candles, and the side panel today's volume profile (point of control, 70% value area). An estimate (a tick can
bundle several trades); exact tick-by-tick order flow needs Prime.

### More timeframes and indicators, smart watchlists
- Charts: 1m, 5m, 15m, **30m, 1H** (starting 09:15 like NSE's), 1D, 1W and **monthly**; indicators now include
  **Ichimoku** (9, 26, 52), **Parabolic SAR** and **Aroon 25** (26 indicators in all).
- **Smart watchlists**: Watchlist > "Smart list from a scan" fills a list with a saved scan's stocks, refreshed after
  each scan (and right away when created); its stocks stream live and can carry alerts like any list.

### Dated charges and 1-minute history
- Backtests charge the SEBI fee, stamp duty and NSE transaction charge **as they were on each trade date** (documented
  changes of Jun 2020, Jul 2020, Oct 2024 and Mar 2026; everything else at today's rates).
- **1-minute bars from FYERS** history after the daily archive (last 60 days; `intraday.one_minute_days`, ~150 calls a
  day, 0 turns it off), alongside the ones the live feed builds.

### Browser tests
`npm run build` then `npm run e2e` in web/ui: Playwright drives the built dashboard in the Edge installed on this PC
(no browser download), served by the real API on port 8620. Read-only: pages, a replay, chart types, the practice
ticket (cancelled) and a strategy-builder test.

### 1-minute charts, login reminder
- **1-minute candles** (Chart › 1m, up to 5 sessions): the live service builds them from the same FYERS ticks as the
  5-minute bars (`data/intraday/live/1m_YYYYMMDD.parquet`) and keeps them in the intraday store at each close, so they
  exist for the symbols it streams, from the first session it runs with this version.
- **08:45 login reminder** (task "NSE Scanner login reminder", added by the one-click setup on the Data & Settings
  page): on a trading day without today's FYERS login it sends a Telegram message, and always logs a line to
  `data/logs/reminders.log`. Nothing on holidays or once you are logged in.
- **Paper** open positions are marked to the live price while the market is open.

### Coach (`g h`): where your own trading leaks money
Reads only your own record: replays, real fills (`data/fills.jsonl`, matched buy to sell first-in, first-out) and your
holdings against their stops. It checks your process: trades without a stop, holding losers longer than winners, one
loss wiping out several wins, busy sessions, the trade right after a loss, charges, and whether recent trades are
better. With an `ANTHROPIC_API_KEY` in `.env`, **Write my review** sends those numbers (nothing else) to Claude for a
written review with concrete if-then rules (one call, about Rs 5-15), kept until your numbers change. Fewer than ~30
practice trades or ~15 real round trips: it says the patterns are first hints, not findings.

### Fyers login, step by step
No command to run: everything happens in Quant Desk.
1. Click the **Fyers** chip in the top bar (or **Log in** in Settings › Fyers, or the yellow banner), then **Log in with Fyers**. The Fyers login page opens in a new tab.
2. Log in there with your Fyers ID, PIN and TOTP.
3. Fyers sends that tab back to your app's Redirect URL:
   - If that is Quant Desk's own `http://127.0.0.1:8600/fyers/callback`, Quant Desk finishes the login by itself, the Fyers tab says "✓ Logged in" and closes, and the dialog closes. **One click.**
   - If it is another address on a free port, Quant Desk listens there for the login (also one click).
   - If it is `127.0.0.1:8000`, which your Docker setup also uses, the browser may show an error or another app's page. **That's fine.** Copy the **full address** from the address bar (it contains `auth_code=`), paste it into the dialog, and click **Complete login**.

*To make it one click (one-time setup):* in the [Fyers API dashboard](https://myapi.fyers.in/dashboard), set your app's Redirect URL to `http://127.0.0.1:8600/fyers/callback`, then click **I've changed it in Fyers** in the login dialog (it writes `FYERS_REDIRECT_URI` in `.env` for you). If your Docker app uses the same Fyers app, create a second Fyers app for Quant Desk instead and put its App ID and Secret in `.env`.

`1_login.bat` still works as a fallback when Quant Desk isn't running.

---

## 2. The strategies (and the evidence)

| Strategy | What it does | Evidence |
|---|---|---|
| **Momentum leaders** | Holds the 15 strongest stocks by risk-adjusted 6- and 12-month return (NSE's momentum-index formula), reviewed monthly. A holding is kept while it stays in the top 30. Only stocks above their 200-day average. No new buys when Nifty is below its 200-day average. | The best-documented stock-selection effect, in India and globally. NSE's whitepaper backtest of Nifty200 Momentum 30 (Apr 2005 on): 18.6% CAGR vs 12.7% for the Nifty 200 (`docs/strategy_catalogue.md`, L1). Falls harder in crashes. |
| **Trend-template breakout** | Buys a stock in a strong uptrend (above rising 50/150/200-day averages, near its high, top relative strength) when it breaks its 20-day high on heavy volume. 8% stop, no trailing stop (`trail_pct: 0`), exit below the 50-day average. | A practitioner method (Minervini). Works in bull phases. In our tests it roughly matched the average stock. |
| Near 52-week high (off: tested and rejected) | Holds uptrending stocks closest to their 52-week high, reviewed monthly. | Academic (George & Hwang; Indian study by Raju 2023). Works best as a filter, not on its own. Never beat the average stock here. |
| **Low volatility** | Holds the 20 steadiest large, liquid stocks, reviewed quarterly (Nifty100 Low Vol 30 method). | Lost less in crashes (2008: −43% vs −54%). Defensive; lags in strong rallies. |
| RSI-2 pullback (off: tested and rejected) | Buys sharp dips in uptrending stocks. | Short-term reversal mostly works in illiquid stocks. After realistic costs it fails here. |

Also re-tested after every scan (rules in `scanner/strategies.py`; numbers on the dashboard):

| Strategy | What it does | Evidence grade |
|---|---|---|
| Sector rotation | Each month, the strongest stocks inside the 3 strongest industries (average 6-month return of their stocks), above their 200-day average; regime filter. | MODERATE (Moskowitz & Grinblatt 1999). Its point-in-time result is **flattered**: NSE lists industries only for today's index members, so companies that later dropped out can never be picked (83% of the test's stock-days have an industry). |
| Golden cross trend | Buys a strong stock (RS 60+) when its 50-day average crosses above the 200-day; sells on the cross back down; 15% stop. | WEAK (`docs/strategy_catalogue.md` S11 graded it "skip: no evidence" for single stocks). |
| Nifty trend timing (ETF) | Holds NIFTYBEES while Nifty is above its 200-day average, cash otherwise; checked monthly. | MODERATE (Faber): smaller crashes, not a higher return. |
| Dual momentum (ETF rotation) | Each month the 2 ETFs (NIFTYBEES, JUNIORBEES, BANKBEES, GOLDBEES, MON100) with the best positive 12-month return, otherwise cash. | MODERATE (Antonacci). |
| VCP breakout | A leader near its 52-week high in a tight 15-day box breaks out on 1.5× volume; 7% stop, exit below the 50-day average. | WEAK |
| Turtle / Donchian 55-day | Buys a new 55-day high above the 200-day average; exit on a new 20-day low; 2-ATR stop. | MODERATE in futures, weaker on single stocks |
| Pullback in leaders (21-EMA) (off: tested and rejected 25 Oct 2026) | An RS-80+ stock in a stage-2 uptrend touches its 21-day EMA and closes above it; exit below the 50-day average or after 20 days; 7% stop. | WEAK. +8.5%/year in the 24 Oct 2026 point-in-time scan, below the Nifty 500 (+13.1%); profit factor 1.08 over 1,188 trades. |
| Earnings gap-up (PEAD) | After results, a 4%+ gap up on 3× volume that holds; 8% stop, 40-day limit; no regime filter. | MODERATE (mixed in India) |
| Bollinger squeeze breakout (off: tested and rejected 25 Oct 2026) | Narrowest bands in 6 months, then a close above the upper band in an uptrend; exit below the 20-day average; 8% stop. | WEAK. +6.9%/year in the 24 Oct 2026 point-in-time scan, below Nifty 50 (+10.6%); max drawdown −49%. |
| NR7 breakout (off: tested and rejected 25 Oct 2026) | After the quietest day in 7, a close above that day's high in an uptrending leader; exit below the 10-day average or after 7 days; 5% stop. | WEAK. **Lost money** after costs in the 24 Oct 2026 point-in-time scan (−9.7%/year, 2,632 trades). |

New on 25 Oct 2026, tested from the next scan on (no results yet; judge each by its own backtest, never by the
papers behind it):

| Strategy | What it does | Evidence grade |
|---|---|---|
| NSE momentum replica (`momentum_n200`) | NSE's Nifty200 Momentum 30 rules: the 30 best by the momentum score among the 200 most-traded stocks with a year of history, reviewed in June and December, kept while in the top 60; no trend or market filter; equal weight. | STRONG (the NSE index method). Mainly a **check**: compare it with the real Nifty200 Momentum 30 over the same years. If it lands far above, the backtest flatters. With ₹5 lakh, a 30-stock slot is close to the ₹15,000 minimum position. |
| Residual momentum (`residual_momentum`) | Ranks stocks by their 12-1 month return not explained by Nifty 50 (CAPM alpha / residual volatility); otherwise the same rules as Momentum leaders. | MODERATE (Blitz, Huij & Martens 2011; no Indian test found). Expect it to lag rallies led by high-beta stocks. |
| Alpha + low volatility (`alpha_low_vol`) | NSE Alpha Low-Volatility 30 method on the 150 most-traded stocks: half 1-year alpha vs Nifty 50, half low 1-year volatility; 30 stocks, reviewed in June and December. | MODERATE (NSE index method; Joshipura 2020 for India). Mainly smaller drawdowns, not a higher return. |
| ETF trend basket (`etf_trend`) | A quarter each in NIFTYBEES, JUNIORBEES, GOLDBEES and MON100, each held only while above its 200-day average (checked monthly); otherwise that quarter waits in cash. | MODERATE (Faber 2007). Smaller drawdowns, not reliably a higher return; gold and Nasdaq gains are asset-class bets. |

### Honest expectations
Since October 2026 the backtests are **survivorship-free**. On each past day a strategy may only pick
from that day's 500 most-traded NSE stocks, built from NSE's own archive. That list includes the
companies that later crashed, merged or were delisted: 1,173 different companies were in it at some
point, and 74 of them no longer trade (24 Oct 2026 scan; DHFL, Jet Airways, Future Retail, Lakshmi Vilas Bank, the state banks
merged in 2019–20, HDFC Ltd ...). The old way, testing on *today's* Nifty 500 list, left all of those out.

Same rules, same costs and tax, 2019-08-19 to 2026-10-22:

| Strategy | Tested on | Yearly return | Timing range | Worst drop | Sharpe | After tax |
|---|---|---|---|---|---|---|
| Momentum leaders | today's Nifty 500 list | +41.1% | 41–46% | −33% | 1.58 | +37.5% |
|  | **point-in-time top 500** | **+28.3%** | 28–30% | −33% | 1.16 | +25.6% |
| Trend breakout (experimental) | today's Nifty 500 list | +39.8% | 40–41% | −30% | 1.64 | +33.4% |
|  | **point-in-time top 500** | **+19.6%** | 18–20% | −32% | 0.93 | +16.3% |
| Low volatility | today's Nifty 500 list | +9.0% | 9–11% | −28% | 0.67 | +8.8% |
|  | **point-in-time top 500** | **+10.7%** | 9–11% | −28% | 0.78 | +10.5% |
| Average stock (equal weight) | today's Nifty 500 list | +27.0% | – | −40% | 1.36 | +25.0% |
|  | **point-in-time top 500** | **+19.5%** | – | −41% | 0.99 | +17.9% |
| Nifty 500 index (the real one) | – | +13.3% | – | −38% | 0.80 | +12.0% |

*Timing range* = the same rules rebalanced a few days earlier, or started a few weeks later.
*After tax* = short-term gains taxed every April at the rate of the day they were realised (15.6% before 23 Jul 2024, 20.8% after; buy & hold pays LTCG once, at the end).
*Updated 23 Oct 2026* after fixing price-data errors in both data sets (missing NSE sessions, wrong "data
corrections", three incomplete NSE files). Momentum point-in-time went 27.1% → 28.3% (inside its timing range),
trend breakout 44.1% → 39.8% on today's list and 21.0% → 19.6% point-in-time.

*The dashboard's numbers differ a little from this table.* The daily scan adds each new day, and money it has not
invested earns the Nifty 1D Rate (the overnight rate, as if parked in a liquid ETF), while `compare` leaves it at zero.
Scan of 24 Oct 2026 (data to 23 Oct, point-in-time): momentum +28.7%/yr (timing range 28.7–30.9%), trend breakout
+21.3%, low volatility +10.8%, average stock +19.1%, Nifty 500 +13.1%, Nifty 50 +10.6%. Over the same days the real
NSE Nifty200 Momentum 30 index made +14.3%/yr (price index, no costs): a real-world yardstick, about half the
backtest's yearly return.

What this shows:
- **Survivorship bias was large.** It added 7.5% a year to the average stock, and 13% (momentum) to
  20% (trend breakout) a year to the active strategies.
  They buy exactly the stocks that were flying, and some of those later collapsed.
- **Momentum still has an edge, but a much smaller one:** +8.8% a year over the average stock and
  +15.0% over the Nifty 500 index, with a smaller worst drop (−33% vs −41%). NSE's own momentum indices beat their parent
  index by about 3–6% a year over 20 years. Expect live results nearer that, not 28%.
- **Trend breakout is about the average stock** (+0.1% a year, lower Sharpe): no real edge.
- **Low volatility barely moves** (+9.0% → +10.7%): it holds big, steady companies, which rarely
  vanish, so survivorship never flattered it. It lagged because small and mid caps boomed in 2019–2026.
  It is insurance, not a return engine.
- The average stock beat the Nifty 500 index by 6.2% a year. That is the small/mid-cap boom of these
  years (equal weight vs company size), not skill. Don't count on it repeating.
- **Check of the data:** today's list tested on the NSE-rebuilt prices gives the same picture as the main
  store (momentum +39.4% vs +41.1%, average stock +27.1% vs +27.0%). So the gap comes from the missing
  companies, not from different prices.

What is still not perfect:
- **Timing luck:** the same strategy rebalanced a few days apart ends up several % a year apart (see the range).
- **Total return.** Dividends are counted: a stock held before its ex-date pays its dividend in cash that day (NSE's
  corporate-actions list, ~12,000 dividends since 2018, `scanner/dividends.py`), taxed at your slab from FY 2020-21
  (before that the company paid dividend distribution tax). The indices they are compared with include dividends
  too: the average stock gets the same dividends, and the Nifty 50 / 500 and factor indices accrue NSE's own daily
  dividend yield (an approximation of NSE's TRI). Buy-and-hold benchmarks are taxed at LTCG at the end, slightly
  generous to them. Effect on this data: average stock 14.0% -> 15.3% a year, Nifty 500 11.3% -> 12.7%, momentum
  +0.6%, low volatility +1.7%. Pattern studies, scans and the late-entry test compare a stock with the average
  member over the same days, so they stay on price returns.
- **Rights issues are adjusted** in the point-in-time prices from their terms (NSE does not re-base the price for
  them): the history before the ex-date is rescaled to the theoretical ex-rights price, (held x price + new x issue
  price) / (held + new). 81 since 2018; Vodafone Idea's 2019 issue no longer shows as a 40% crash.
- The universe ranks by traded value, re-ranked every day. NSE's Nifty 500 ranks by free-float company size and
  is reviewed twice a year.
- A holding that stops trading (merger, delisting) is sold at its last price after 20 days without trades.
- The past is not the future. Momentum crashes happen: expect 30–40% drops (−68% in 2008) and 1–2 years of
  lagging. NSE's Nifty200 Momentum 30 returned −0.5% in the 12 months to Sep 2026.
- **Tax:** momentum sells within a year, so gains are taxed at 20.8% every April. Frequent trading can also be
  treated as business income; ask a CA.

Regenerate this table with `4_build_universe.bat compare` (saved to `data/history/pit/comparison.csv`).

### Paper trading: live proof
Backtests can be flattered; live results can't. Every scan of a **completed** trading day (after ~6 PM, or before
9:15 AM) writes each strategy's orders and model portfolio to `data/journal.sqlite`. Scanning the same day twice
replaces that day's entry. Intraday scans are provisional, so they are never written.

A paper portfolio per strategy then follows the journal:
- it starts with your `account.capital` on its first journal day, and on that day buys the model's current holdings;
- orders fill at the **next day's official NSE open**, plus slippage and all charges (`costs:`), sized like the backtest;
- stop-losses and targets trigger from the day's low/high, as in the backtest;
- if you miss a scan, it catches up with the model portfolio at the open after your next scan.

The **📒 Paper trading** tab shows each paper portfolio against Nifty 50 and the real Nifty 500 over the same days,
every paper trade, and how the result compares with what the backtest promised (survivorship-free backtests need
no correction; for old current-list backtests ~8%/yr of survivorship bias is removed). It also shows how far luck alone could move the result. Telegram gets one paper line per strategy.
Everything is recomputed from the journal and stored prices on every view, so the same data always gives the same
numbers. To start over, delete `data/journal.sqlite`. Expect to need **about a year** before the comparison means much.

---

## 3. One-time setup (already done on this PC)

- Python, all libraries (pinned versions), and 8 years of cleaned price data are installed in this folder.
- Your Fyers App ID, Secret and Redirect URL are saved in **`.env`**. That file is private: never share it or upload it anywhere.
- **Your capital:** edit `account: capital:` in `config.yaml`. Order quantities are sized from it.

On a new PC: install Python 3.12 and Node.js (LTS; `3_dashboard.bat` needs it once to build Quant Desk, because
`web/ui/dist` is not in git), then double-click `setup.bat`, fill in `.env`, then run `3_dashboard.bat`. The first scan downloads and repairs 8 years of data, which takes about 4 minutes. Then double-click **`4_build_universe.bat`** once: it downloads NSE's full archive (about 2,000 day files plus corporate-action notices, roughly 30 minutes) for the survivorship-free backtests. Until then backtests use today's list, and the dashboard says so.

---

## 4. Where the data comes from (and how it's kept clean)

| Data | Source |
|---|---|
| 8 years of daily history | Yahoo Finance, bulk download |
| Every completed trading day | **NSE official end-of-day files** (official OHLC, volume, delivery %) |
| Splits, bonuses, demergers | **NSE corporate-action notices**. History is rescaled by the exact factor (e.g. BONUS 1:1 → ×0.5; demerger → special-session price). |
| Symbol renames | NSE symbol-change list (e.g. TATAMOTORS → TMPV) |
| Today's live prices | Fyers quotes (real-time) when logged in; otherwise Yahoo (~15 minutes delayed) |
| Holidays | Detected from NSE's own files, including Diwali Muhurat and Budget-day sessions |

The first build repairs Yahoo's history automatically with NSE's files:
- removes fake "flat" bars (1,290; e.g. on 18 Mar 2025 Yahoo repeated the day before's price for 469 stocks) and
  dates with no prices at all (15 Jan 2026, an NSE holiday);
- adds the NSE sessions Yahoo lacks entirely: 13 Feb and 29 Mar 2019, Budget days 1 Feb 2020 and 2026, Muhurat
  2023, and the Saturday sessions of 20 Jan, 2 Mar and 18 May 2024 (every calendar day is checked with NSE once);
- fills missing prices from NSE (about 4,000), converted to the same split-adjusted units as Yahoo's history;
- fixes splits, bonuses, demergers and wrong Yahoo prices (18: VEDL, TMPV, HEGAM, TRENT, CGCL and others);
- keeps real moves untouched (YES Bank 2020, POLICYBZR 2026), also across a gap: a price jump is compared with NSE's move over exactly the same
  days. Before Oct 2026 it compared across missing sessions and gaps, and "corrected" real moves by 5–32%
  (IFCI, IRCON, HINDZINC, PNB Housing, Force Motors, CONCOR, Karur Vysya). Updating from that version downloads
  the history again once (about 4 minutes).

Corporate-action notices are looked up in NSE's files around each ex-date (the day itself, the days before and
the day after; a moved ex-date counts on its new date), and the last stored day is checked again once the next
day's notices are out.

If NSE is unreachable for more than a day, Yahoo fills in temporarily. Those days are replaced with official data as soon as it is available.

### FYERS first, inside its rate limits

FYERS is the first choice for everything real-time and intraday. Every FYERS call from every program goes through **one shared rate limiter** (`scanner/fyers_limits.py`). The table shows FYERS' published limits and what the platform actually uses.

| FYERS Standard (free) plan | FYERS limit | What the platform uses |
|---|---|---|
| Data calls (history, quotes) | 5/second, 50/minute, 5,000/day | **4/second, 45/minute, 4,500/day** |
| User calls (profile, holdings) | 10/second, 200/minute, 100,000/day | 8/second, 180/minute, 90,000/day |
| Rate-limit breaches | 3 in a day = account blocked for the day | **Stops using FYERS for the day after 2** |
| WebSocket (live ticks) | up to 100 symbols, no REST cost | the `live_fno` index futures / options (default 20), then the most liquid intraday stocks (80) |

Usage is counted in `data/fyers_usage.json`, which every process shares. If the day's budget runs out, everything falls back to NSE and Yahoo automatically, with no errors.

| Data | Source order | FYERS calls |
|---|---|---|
| Live prices in a scan | FYERS quotes → Yahoo | about 11 per scan (50 symbols per call) |
| Today's intraday bars | FYERS WebSocket live feed → Yahoo (delayed) | 0 (WebSocket) |
| Intraday history (1 year) | FYERS → Yahoo (60 days only) | about 600 once (automatic at 15:45 after a Fyers login, or **Download 1 year of FYERS history** on the Intraday page; ~14 min), then about 150 a day |
| Completed daily candles | NSE official file → Yahoo | 0 (NSE is the exchange's own data) |

### The survivorship-free backtest universe (`scanner/pit.py`)
Built only from NSE's own archive, for **every** NSE equity since August 2018, including companies that no longer exist:
- **Prices:** NSE's official day files. The newer format exists from 30 Sep 2019, and the older bhavcopy covers the
  days before. Every calendar day is checked, so special sessions are included (Budget days, Saturday sessions,
  Muhurat trading): 2,033 sessions in all.
- **Universe:** on each day, the 500 stocks with the highest average daily traded value (close × volume) over the
  previous 6 months, using only data up to that day. A stock needs 1 month of trading history and a trade in the
  last 5 days. REITs, InvITs and ETFs are left out: they are funds, not companies (about 40 gold, silver, liquid
  and index ETFs trade enough to have ranked in the top 500).
- **Renames** are stitched into one history (old symbol before the change date → today's symbol).
- **Splits, bonuses and demergers:** 385 adjustments from NSE's corporate-action notices, using the same factor
  rule as the main store (bonus a:b → b/(a+b), split by the face-value ratio, demerger by the special-session
  price). NSE's notice files are incomplete, so 8 jumps with no notice were fixed by checks: Yahoo's
  adjusted history, a clean split ratio, or a special dividend (360 ONE, Shriram Finance, Majesco's ₹974 payout ...).
- NSE's newer day file lacks about 10% of the stocks on 13 Apr 2020, 28 Sep 2020 and 7 Mar 2022; the older
  bhavcopy of the same day fills them in.
- A stock that didn't trade for a while (suspension) keeps its real move when it resumes. NSE's "previous close"
  is then often a placeholder (BCG 2025: ₹2, opened at ₹21.80), so it is only trusted for a clean split ratio
  the market agrees with (CCAVENUE Oct 2026: 10:1 consolidation).
- Checked against the main store (Oct 2026): 469 of 500 shared stocks agree within 2% on every day. The other 31:
  12 rights issues (Yahoo adjusts them; the point-in-time prices now do too, from the issue terms), 6 demergers where Yahoo used a different
  factor (SIEMENS 2025, NMDC 2022 ...), 2 small demergers without a price gap that only Yahoo adjusts (Aarti
  Industries and TTML, July 2019), and Yahoo prices 2–4% off NSE on 18 Mar 2019 and 2 May 2025 (7 stocks, one day)
  and for about a week each between Apr 2024 and Nov 2025 (IIFL, Sobha, UPL, Thangamayil, M&M Finance, Adani
  Enterprises). Those Yahoo errors remain in the main store: they are too small for its >20% gap check.
- Cached under `data/history/pit/`. Scans add each new NSE day (about 30 s, once a day).
- ETFs are not companies, so they are never universe members; the ETF strategies (Nifty trend timing, dual
  momentum) still trade them from the main store's prices on the point-in-time test.

---

## 5. Intraday (honest)

- **Nine intraday strategies** are tested on 5-minute bars of the ~150 most liquid F&O stocks, using textbook parameters with no tuning:
  - opening-range breakout (15-min and 5-min "in play")
  - VWAP trend and VWAP pullback
  - gap-and-go and gap fade
  - morning-predicts-close momentum
  - closing-hour trend
  - narrow CPR breakout
  - Supertrend
- Every test uses FYERS intraday charges and slippage, squares off at 15:00 for F&O stocks (5 minutes before FYERS' 15:05 MIS cut-off) and 15:15 for others, and taxes profit as speculative business income.
- **Result so far (60 Yahoo sessions, 29 Jul – 23 Oct 2026):** all nine strategies **lose money after costs**, eight of them by a statistically significant margin. This matches SEBI's July 2024 study, which found that 71% of individual intraday traders lost money.
- **Three pre-registered research tests** were added on 25 Oct 2026 (large-cap gap fade, stocks-in-play ORB-15, NIFTYBEES last-half-hour momentum; `docs/intraday_data.md` §5). They have no results yet and none is expected to beat Indian MIS costs; they are there to measure that honestly, never to produce orders.
- **One year of FYERS history** gives a much stronger test. Nothing to run: the 15:45 task downloads it on the first afternoon you are logged in to Fyers (or click **Download 1 year of FYERS history** on the Intraday page), then keeps it growing; FYERS itself only keeps a rolling year.
- **Why none of them works:** before costs the average trade makes about nothing (between -0.2% and +0.3%), and brokerage, STT, exchange fees, GST and slippage take 0.15-0.30% a trade. The Intraday page shows both columns. No 200-day or 200-EMA filter is involved.
- **Live bars:** `4_intraday_live.bat` builds live 5-minute bars from the FYERS WebSocket. The scheduled task starts it at 09:14.
- **Live signals, only from proven strategies:** every 5 minutes from 09:20 to 15:05 (`intraday_sync.py --signals`), the strategies whose backtest shows a real edge after costs (a profit beyond luck over 40+ sessions) are run on today's bars. Their trades appear on the Signals page, Intraday tab. A strategy that loses money or can't be told from luck never gives a signal; while none qualifies, the tab says so.

---

## 5b. Options, F&O positioning and price action (positioning, not signals)

Three Quant Desk pages describe what the derivatives market is doing. None of them gives buy or sell orders: no
backtest in this app shows that PCR, max pain, open-interest levels or candle patterns predict prices.

- **Options** (`scanner/options.py`): NSE's public option chain for the indices and F&O stocks in
  `options.underlyings` (default NIFTY, BANKNIFTY; add a stock with the box on the page). The 09:12 task
  (`intraday_sync.py --options`) stores a chain every `options.interval_seconds` in market hours; an unchanged
  chain (same NSE time stamp) is not stored twice. The page shows:
  - spot and forward, the put-call ratio and max pain;
  - at-the-money implied volatility and the 25-delta skew;
  - the straddle's expected move and the 1-SD range;
  - open interest by strike, now, since yesterday or over the last 5-60 minutes;
  - OI levels and build-ups per strike;
  - **unusual activity**: strikes that traded more contracts than are open, or whose open interest jumped 10%+
    within the window, ranked by premium traded.

  Implied volatility and greeks are computed on the put-call-parity forward (Black-76). NSE's own IV column uses the
  spot and gives calls and puts of one strike different values, so it is shown for reference only.
  FYERS is not used for chains yet: its response has not been checked against a real one.
- **Does it work?** (`scanner/options_research.py`, Options page): three popular claims checked on the stored
  end-of-day chains:
  - whether the price is pulled towards max pain by expiry (vs a 50% coin flip);
  - whether expiry closes land inside spot ± straddle (about 57% if options are fairly priced);
  - whether the put-call ratio says anything about the next day.

  Each needs 60 days before it gets a verdict. Option signals would come only from a claim that holds.
- **F&O positions** (`scanner/fno.py`): NSE's participant-wise open interest, the contracts FII, DII, Pro (brokers'
  own money) and Client hold long and short in index and stock futures and options. NSE publishes totals per group
  after the close and names no one. Also the day's futures build-ups (price vs open interest), basis, put-call
  ratio and call / put walls for every F&O underlying, from the F&O bhavcopy. The 19:30 task
  (`intraday_sync.py --fno`) adds each day; the first **Fetch** loads the last 30 trading days (about 30 MB).
- **Price action** (`scanner/levels.py`, under each chart): pivots and the CPR for the next session, swing support
  and resistance of the last year (with how often each level formed), trend versus the 20/50/200-day averages,
  higher highs / lower lows, Supertrend, daily candle patterns and **chart patterns** (double top / bottom, head
  and shoulders, triangles, wedges, rectangles, flags: forming or confirmed, with the breakout level, where the
  pattern is void and the textbook target; about half of all stocks show one at any time). When the stock has
  5-minute bars it adds
  today's VWAP with 1-SD bands, the 15-minute opening range, the volume profile (point of control, value area) and
  intraday patterns.

- **Pattern evidence** (`scanner/pattern_study.py`, shown on every pattern): each candle and chart pattern tested
  on the survivorship-free top 500, Aug 2018 - Oct 2026 (808,294 events): buy at the next open after the pattern
  first appeared (using only data up to that day), compare with the average top-500 stock over the same 5 / 10 /
  20 days, t-statistic on monthly averages. **No pattern beat the average stock after costs (~0.45% round trip).**
  Gap-ups did worse than it (-0.20% over 10 days, t -5.0), ascending-triangle breakouts too (-0.36% over 20 days,
  t -2.2). The closest to an edge, symmetrical-triangle breakouts, made +0.69% in 5 days (t 4.6) - +0.24% after
  costs, gone by 20 days. It re-runs by itself every Saturday at 11:00 (an automatic job, ~17 minutes).
- **Big trades live** (`scanner/fno_live.py`, Options page): the 09:14 live service (FYERS WebSocket, needs
  today's FYERS login) also streams the nearest NIFTY and BANKNIFTY futures and NIFTY's nearest-expiry calls and
  puts within 4 strikes of the money (`live_fno` in `config.yaml`; picked from FYERS' public symbol list). Every
  single trade of Rs 5 crore notional (futures) or Rs 25 lakh premium (options) or more is kept with the side that
  most likely started it: at the ask a buyer, at the bid a seller (tick rule). Totals per instrument show which side
  was more aggressive today. These 20 symbols come off the 100 the live feed allows, so 80 stocks stay. Not yet
  seen on a live session: the first one after a FYERS login confirms the tick fields.
- **Claude's forecast** (`scanner/ai_forecast.py`, `web/api/services/forecast_svc.py`, Options page, needs
  `ANTHROPIC_API_KEY` in `.env`). Claude (Opus 5.5) reads the stored chain near the money, NSE's participant
  positions, the futures build-up, recent official closes and levels, and the app's tested readings. For the next
  official close and the expiry close it gives:
  - the chance the close ends above the spot it saw;
  - a range for about 2 closes in 3;
  - the level that would prove it wrong.

  Its answer has a fixed JSON shape. Every forecast is journalled (`data/results/ai_forecasts.json`, with the exact
  snapshot it read) and scored from NSE's official closes against a coin flip, "always up" and the options-implied
  1-SD range. The 19:30 task (`intraday_sync.py --fno --ai-forecast`) stores the day's last chains and sends one
  forecast per `ai_forecast.underlyings` (Batch API, half price); the 09:12 task collects the answers. "Ask Claude
  now" on the page costs roughly Rs 8-13. A chain older than the last official close is never forecast.
  **Unproven** until 60+ settled forecasts beat a coin flip beyond luck; it never changes the options verdict.

What no one can show: who is behind a trade while it happens, or when a big trader will exit. NSE names buyers
and sellers only later (block / bulk deals the same evening, insider disclosures within two days, shareholding
each quarter: see Smart money).

---

## 6. Telegram alerts and automatic scans (optional)

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token. Then send any message to your new bot, and message **@userinfobot** to get your chat ID.
2. Put both in `.env` (`TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`).
3. In Quant Desk, open **Settings › Automatic jobs** and click **Set up automatic jobs** (a banner offers the same when a job is missing; no window or command). This sets up weekday scans at 8:30 AM, 3:40 PM and 7:15 PM that send a summary to your phone, a live scan every 30 minutes from 9:45 AM to 3:15 PM (provisional signals on today's live candle, no Telegram), plus the three intraday jobs (section 5). While the market is open, the top bar and the Signals page also show live prices every 30 seconds (FYERS real time when logged in, else Yahoo ~15 min delayed). Click **Repair / update** there after updating the app, so the tasks get the current settings. The option chains (09:12), F&O positioning and Claude forecasts (19:30) and the weekly pattern study (Saturday 11:00) are set up the same way.

If a scan fails, you get a Telegram alert; a scheduled scan skipped because another scan was running sends a short
note too. Details go to `data\logs\scanner.log` (a scheduled scan that cannot even start, e.g. a missing
library: `data\logs\scan_console.log`), and Quant Desk's Settings › Scan shows the scheduled scans' progress and failures.
No message arrives when you are signed out of Windows (the tasks run only while you are signed in) or when a scan
is stopped at the tasks' 45-minute limit.

---

## 7. Your holdings

In Quant Desk, open **Portfolio** (old Streamlit dashboard: **💼 My holdings**):
- add stocks by hand (symbol, quantity, buy price, **buy date**), or click **Import from Fyers** (Streamlit: **⬇️ Import my holdings from Fyers**);
- the **buy date** lets the app adjust your buy price if the stock had a split or bonus since you bought, so no false "stop-loss hit" alerts;
- alerts include: stop-loss hit, target reached, below the 50/200-day average, momentum rank, and renamed symbols.

`holdings.csv` stays on your PC. It is excluded from git.

---

## 8. Settings (`config.yaml`)

- `account`: capital, minimum position size
- `universe`: nifty50 / nifty100 / nifty200 / nifty500
- `filters`: minimum price, minimum daily traded value
- `costs`: brokerage, STT, stamp duty, GST, DP charge, slippage (FYERS Standard plan rates, Oct 2026)
- `tax`: STCG 20.8%, LTCG 13% above ₹1.25 lakh
- `strategies`: switch any strategy on or off, or change its settings. The next scan re-tests automatically.
- `backtest_universe`: `point_in_time` (survivorship-free, as set in `config.yaml`) or `current` (today's list, flattered; also what a scan uses when the key is missing). Today's orders always come from `universe`.

---

## 9. For developers

```
scanner/
  store.py       price store (atomic generations, NSE completion, history repair, live overlay)
  nse.py         NSE end-of-day files (stocks + indices), validated and cached
  corporate.py   NSE corporate-action notices, purpose parsing, symbol renames
  providers.py   Yahoo (history) and Fyers (live quotes; plan-aware throttle, timeouts, auth errors)
  panel.py       whole-market vectorized factors (bottleneck): momentum, RS, 52w, ATR, regime
  engine.py      portfolio simulator: next-open fills, stops, ranking/rebalance, costs, tax, metrics
  strategies.py  strategy definitions (parameters from config.yaml)
  daily.py       one scan = refresh + re-test + today's orders + holdings check -> latest.json
  pit.py         survivorship-free universe: NSE archive -> renames, corporate actions, daily top 500
  paper.py       paper-trading journal (data/journal.sqlite) + deterministic replay at next-day opens
  holdings.py    holdings file, corporate-action-adjusted buy price
  lock.py        one scan at a time across processes
  intraday/      5-minute bars (Yahoo, FYERS history and live WebSocket), MIS backtests -> intraday.json
  intraday/quote_hub.py  live quotes from the FYERS WebSocket (quotes.json) and the screen's subscriptions
  watch.py       watchlists and one-shot price alerts (checked by the live service and the dashboard)
  scans.py       your own scans: rules over whole-market factors, today's matches, 8-year point-in-time backtest
  late_entry.py  does a strategy's edge survive joining its trades 5 / 10 / 21 days late (late-entry BUYs)
  index_study.py an index's own history of today's setup (options direction for NIFTY / BANKNIFTY)
  options.py     NSE option chains: parsing, Black-76 IV / greeks, PCR, max pain, OI levels, unusual activity
  options_research.py  do PCR / max pain / the straddle's expected move hold up on the stored days?
  fno.py         NSE participant-wise OI and F&O bhavcopy: FII/DII/Pro/Client positions, futures build-ups
  fno_live.py    big trades live: index futures / near-the-money options on the FYERS feed, large trades by side
  levels.py      price action: pivots, swing S/R, trend, candle / chart patterns, VWAP / opening range / profile
  pattern_study.py  every candle / chart pattern tested on the point-in-time top 500 (event study, after costs)
web/             Quant Desk: FastAPI backend (web/api) and React app (web/ui), started by 3_dashboard.bat
  api/routers/stream.py        live prices as Server-Sent Events (one stream per tab)
  api/services/action_svc.py   one answer per stock: BUY / SELL (exit) / HOLD / NO EDGE (Today, Chart)
  api/services/intraday_chart.py  5 / 15-minute candles with VWAP for the Chart page
  api/services/robustness.py   Monte Carlo, deflated Sharpe and consistency per strategy
  api/services/orders_svc.py   your own FYERS orders: preview, checks, place once, kill switch, protection, audit
  api/services/replay_svc.py   market replay: past sessions bar by bar, results recomputed with real charges
  api/services/coach_svc.py    trade coach: your own record's process checks, and Claude's review of them
  api/services/sim_svc.py      practice account on live prices; depth_svc.py: FYERS market depth
  api/services/builder_svc.py  strategy builder: plain English -> spec, tests, walk-forward optimiser
app.py           old Streamlit dashboard (3b_dashboard_streamlit.bat; scans run in a background process)
run_scan.py      CLI / scheduler entry point (status file, rotating log, Telegram)
intraday_sync.py intraday jobs: backfill, 15:45 archive, live feed, re-test
login.py         daily Fyers OAuth login
tests/           pytest suite: costs, tax, corporate actions, factors (no look-ahead), engine, paper trading,
                 point-in-time universe (no look-ahead, renames, adjustments, delistings)
```

Run the tests with `.venv\Scripts\python.exe -m pytest -q` (in a git worktree under `.worktrees\` use the main checkout's `..\..\.venv\Scripts\python.exe`; the `.bat` files and `setup_schedule.ps1` find it automatically). Rebuild the point-in-time universe from scratch with
`.venv\Scripts\python.exe -m scanner.pit build`; print the comparison table with `... -m scanner.pit compare`.
For the web API, `scanner.pit.comparison_report()` returns the same comparison (plus facts about the universe) as plain JSON.

### Roadmap
| Next | Why |
|---|---|
| Sector strength from NSE sector indices | Avoid weak sectors |
| Momentum + low-volatility combined portfolio | Smoother returns |

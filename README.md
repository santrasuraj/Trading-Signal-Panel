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
| After 9:15 AM, once a day | **🔑 Log in to Fyers.** Click the button in the dashboard, or double-click `1_login.bat`. SEBI rules require a daily login since April 2026. |
| Any time | Double-click **`3_dashboard.bat`**, then click **🔄 Run scan now**. A scan takes 1–2 minutes (it re-tests every strategy; longer when it downloads new prices). |
| 3:40 PM / 7:15 PM | Automatic Telegram summaries, if you set them up (section 5). |
| **After about 7 PM** | **Best time to decide.** NSE's official end-of-day data is published, so signals are final. |

Orders marked *provisional* are based on a candle that is still forming during market hours. They can change before 3:30 PM.

### Fyers login, step by step
1. Click **🔑 Log in to Fyers**. A small window opens, and so does the Fyers login page.
2. Log in with your Fyers ID, PIN and TOTP.
3. Your app's redirect address is `127.0.0.1:8000`, which your Docker setup is also using. So after login the browser may show an error page. **That's fine.** Copy the **full address** from the browser's address bar (it contains `auth_code=`), paste it into the small window, and press Enter.
4. You'll see "✅ Logged in". Refresh the dashboard.

*To make login fully automatic:* in the [Fyers API dashboard](https://myapi.fyers.in/dashboard), change your app's Redirect URL to `http://127.0.0.1:8765/fyers/callback`. Then put the same address in `.env` as `FYERS_REDIRECT_URI`.

---

## 2. The strategies (and the evidence)

| Strategy | What it does | Evidence |
|---|---|---|
| **Momentum leaders** | Holds the 15 strongest stocks by risk-adjusted 6- and 12-month return (NSE's momentum-index formula), reviewed monthly. A holding is kept while it stays in the top 30. Only stocks above their 200-day average. No new buys when Nifty is below its 200-day average. | The best-documented stock-selection effect, in India and globally. NSE Nifty200 Momentum 30: about 19% CAGR vs 15% for Nifty 200 since 2005. Beat it in 15 of 20 years, but fell harder in crashes. |
| **Trend-template breakout** | Buys a stock in a strong uptrend (above rising 50/150/200-day averages, near its high, top relative strength) when it breaks its 20-day high on heavy volume. 8% stop, 15% trailing stop, exit below the 50-day average. | A practitioner method (Minervini). Works in bull phases. In our tests it roughly matched the average stock. |
| **Near 52-week high** | Holds uptrending stocks closest to their 52-week high, reviewed monthly. | Academic (George & Hwang; Indian study by Raju 2023). Works best as a filter, not on its own. |
| **Low volatility** | Holds the 20 steadiest large, liquid stocks, reviewed quarterly (Nifty100 Low Vol 30 method). | Lost less in crashes (2008: −43% vs −54%). Defensive; lags in strong rallies. |
| RSI-2 pullback | Buys sharp dips in uptrending stocks. | Short-term reversal mostly works in illiquid stocks. After realistic costs it fails here. |
| Old textbook rules | The v1 rules (50-DMA / 52-week breakouts, 5% stop / 10% target). | **Lost money** in testing (−12%/year). Kept only for comparison. |

### Honest expectations
Since October 2026 the backtests are **survivorship-free**. On each past day a strategy may only pick
from that day's 500 most-traded NSE stocks, built from NSE's own archive. That list includes the
companies that later crashed, merged or were delisted: 1,170 different companies were in it at some
point, and 73 of them no longer trade (DHFL, Jet Airways, Future Retail, Lakshmi Vilas Bank, the state banks
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
*After tax* = short-term gains taxed at 20.8% every April (buy & hold pays 13% once, at the end).
*Updated 23 Oct 2026* after fixing price-data errors in both data sets (missing NSE sessions, wrong "data
corrections", three incomplete NSE files). Momentum point-in-time went 27.1% → 28.3% (inside its timing range),
trend breakout 44.1% → 39.8% on today's list and 21.0% → 19.6% point-in-time.

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
- **Rights issues are not adjusted** in the point-in-time prices, so an ex-rights day shows as a small loss
  (slightly pessimistic). **Dividends are left out** of every line, the Nifty 500 index included (price returns).
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

On a new PC: install Python 3.12, then double-click `setup.bat`, fill in `.env`, then run `3_dashboard.bat`. The first scan downloads and repairs 8 years of data, which takes about 4 minutes. Then double-click **`4_build_universe.bat`** once: it downloads NSE's full archive (about 2,000 day files plus corporate-action notices, roughly 30 minutes) for the survivorship-free backtests. Until then backtests use today's list, and the dashboard says so.

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
| WebSocket (live ticks) | up to 100 symbols, no REST cost | 100 most liquid intraday symbols |

Usage is counted in `data/fyers_usage.json`, which every process shares. If the day's budget runs out, everything falls back to NSE and Yahoo automatically, with no errors.

| Data | Source order | FYERS calls |
|---|---|---|
| Live prices in a scan | FYERS quotes → Yahoo | about 11 per scan (50 symbols per call) |
| Today's intraday bars | FYERS WebSocket live feed → Yahoo (delayed) | 0 (WebSocket) |
| Intraday history (1 year) | FYERS → Yahoo (60 days only) | about 600 once (`5_intraday_backfill.bat`, ~14 min), then about 150 a day |
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
  12 rights issues (Yahoo adjusts them, NSE's prices here don't), 6 demergers where Yahoo used a different
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
- Every test uses FYERS intraday charges and slippage, squares off at 15:00 (FYERS' MIS cut-off for F&O stocks), and taxes profit as speculative business income.
- **Result so far (60 sessions):** every strategy is about break-even *before* costs and **loses money after costs**. This matches SEBI's July 2024 study, which found that 71% of individual intraday traders lost money.
- **One year of FYERS history** gives a much stronger test. Run `5_intraday_backfill.bat` once after logging in. A daily 15:45 task keeps it growing; FYERS itself only keeps a rolling year.
- **Real-time setups:** `4_intraday_live.bat` builds live 5-minute bars from the FYERS WebSocket. The scheduled task starts it at 09:14.

---

## 6. Telegram alerts and automatic scans (optional)

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token. Then send any message to your new bot, and message **@userinfobot** to get your chat ID.
2. Put both in `.env` (`TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`).
3. Right-click **`setup_schedule.ps1`** and choose **Run with PowerShell**. This sets up weekday scans at 3:40 PM and 7:15 PM that send a summary to your phone.

If a scan fails, you get a Telegram alert. Details go to `data\logs\scanner.log`.

---

## 7. Your holdings

In the dashboard, open **💼 My holdings**:
- add stocks by hand (symbol, quantity, buy price, **buy date**), or click **⬇️ Import my holdings from Fyers**;
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
- `backtest_universe`: `point_in_time` (survivorship-free, the default) or `current` (today's list, flattered). Today's orders always come from `universe`.

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
app.py           Streamlit dashboard (scans run in a background process)
run_scan.py      CLI / scheduler entry point (status file, rotating log, Telegram)
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
| Results calendar: flag stocks with results in the next 7 days | Avoid buying just before a results surprise |
| Adjust rights issues in the point-in-time prices (needs the RIGHTS rows of NSE's notices) | A little more accuracy |
| Sector strength from NSE sector indices | Avoid weak sectors |
| Momentum + low-volatility combined portfolio | Smoother returns |

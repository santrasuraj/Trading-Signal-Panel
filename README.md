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
| Any time | Double-click **`3_dashboard.bat`**, then click **🔄 Run scan now**. A scan takes about 15–20 seconds. |
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

Same rules, same costs and tax, 2019-08-21 to 2026-10-22:

| Strategy | Tested on | Yearly return | Timing range | Worst drop | Sharpe | After tax |
|---|---|---|---|---|---|---|
| Momentum leaders | today's Nifty 500 list | +41.3% | 40–50% | −33% | 1.59 | +37.7% |
|  | **point-in-time top 500** | **+27.1%** | 27–31% | −34% | 1.11 | +24.5% |
| Trend breakout (experimental) | today's Nifty 500 list | +44.1% | 44–45% | −30% | 1.75 | +36.7% |
|  | **point-in-time top 500** | **+21.0%** | 19–21% | −36% | 0.97 | +17.4% |
| Low volatility | today's Nifty 500 list | +9.5% | 9–11% | −28% | 0.70 | +9.2% |
|  | **point-in-time top 500** | **+10.8%** | 9–11% | −28% | 0.79 | +10.6% |
| Average stock (equal weight) | today's Nifty 500 list | +27.5% | – | −40% | 1.38 | +25.4% |
|  | **point-in-time top 500** | **+19.9%** | – | −41% | 1.01 | +18.3% |
| Nifty 500 index (the real one) | – | +13.5% | – | −38% | 0.81 | +12.2% |

*Timing range* = the same rules rebalanced a few days earlier, or started a few weeks later.
*After tax* = short-term gains taxed at 20.8% every April (buy & hold pays 13% once, at the end).

What this shows:
- **Survivorship bias was large.** It added 7.5% a year to the average stock, and 14% (momentum) to
  23% (trend breakout) a year to the active strategies.
  They buy exactly the stocks that were flying, and some of those later collapsed.
- **Momentum still has an edge, but a much smaller one:** +7.1% a year over the average stock and
  +13.5% over the Nifty 500 index, with a smaller worst drop (−34% vs −41%). NSE's own momentum indices beat their parent
  index by about 3–6% a year over 20 years. Expect live results nearer that, not 27%.
- **Trend breakout is about the average stock** (+1.1% a year, lower Sharpe): no real edge.
- **Low volatility barely moves** (+9.5% → +10.8%): it holds big, steady companies, which rarely
  vanish, so survivorship never flattered it. It lagged because small and mid caps boomed in 2019–2026.
  It is insurance, not a return engine.
- The average stock beat the Nifty 500 index by 6.4% a year. That is the small/mid-cap boom of these
  years (equal weight vs company size), not skill. Don't count on it repeating.
- **Check of the data:** today's list tested on the NSE-rebuilt prices gives the same picture as the main
  store (momentum +39.6% vs +41.3%, average stock +27.5% vs +27.5%). So the gap comes from the missing
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

The first build repaired Yahoo's history automatically:
- removed 1,290 fake "flat" bars;
- filled missing days from NSE;
- fixed 125 split, bonus and demerger errors (VEDL, TMPV, HEGAM, TRENT and others);
- kept genuine crashes untouched (YES Bank 2020, POLICYBZR 2026).

If NSE is unreachable for more than a day, Yahoo fills in temporarily. Those days are replaced with official data as soon as it is available.

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
- **Splits, bonuses and demergers:** 474 adjustments from NSE's corporate-action notices, using the same factor
  rule as the main store (bonus a:b → b/(a+b), split by the face-value ratio, demerger by the special-session
  price). NSE's notice files are incomplete, so 8 jumps with no notice were fixed by checks: Yahoo's
  adjusted history, a clean split ratio, or a special dividend (360 ONE, Shriram Finance, Majesco's ₹974 payout ...).
- Checked against the main store: for 9 in 10 shared stocks the two price histories agree within 2% on every day.
  Where they differ, the cause was mostly the store (gaps in Yahoo's history, sessions it lacks) or rights issues.
- Cached under `data/history/pit/`. Scans add each new NSE day (about 30 s, once a day).

---

## 5. Telegram alerts and automatic scans (optional)

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token. Then send any message to your new bot, and message **@userinfobot** to get your chat ID.
2. Put both in `.env` (`TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`).
3. Right-click **`setup_schedule.ps1`** and choose **Run with PowerShell**. This sets up weekday scans at 3:40 PM and 7:15 PM that send a summary to your phone.

If a scan fails, you get a Telegram alert. Details go to `data\logs\scanner.log`.

---

## 6. Your holdings

In the dashboard, open **💼 My holdings**:
- add stocks by hand (symbol, quantity, buy price, **buy date**), or click **⬇️ Import my holdings from Fyers**;
- the **buy date** lets the app adjust your buy price if the stock had a split or bonus since you bought, so no false "stop-loss hit" alerts;
- alerts include: stop-loss hit, target reached, below the 50/200-day average, momentum rank, and renamed symbols.

`holdings.csv` stays on your PC. It is excluded from git.

---

## 7. Settings (`config.yaml`)

- `account`: capital, minimum position size
- `universe`: nifty50 / nifty100 / nifty200 / nifty500
- `filters`: minimum price, minimum daily traded value
- `costs`: brokerage, STT, stamp duty, GST, DP charge, slippage (FYERS Standard plan rates, Oct 2026)
- `tax`: STCG 20.8%, LTCG 13% above ₹1.25 lakh
- `strategies`: switch any strategy on or off, or change its settings. The next scan re-tests automatically.
- `backtest_universe`: `point_in_time` (survivorship-free, the default) or `current` (today's list, flattered). Today's orders always come from `universe`.

---

## 8. For developers

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

Run the tests with `.venv\Scripts\python.exe -m pytest -q`. Rebuild the point-in-time universe from scratch with
`.venv\Scripts\python.exe -m scanner.pit build`; print the comparison table with `... -m scanner.pit compare`.

### Roadmap
| Next | Why |
|---|---|
| Results calendar: flag stocks with results in the next 7 days | Avoid buying just before a results surprise |
| Adjust rights issues in the point-in-time prices (needs the RIGHTS rows of NSE's notices) | A little more accuracy |
| Sector strength from NSE sector indices | Avoid weak sectors |
| Momentum + low-volatility combined portfolio | Smoother returns |

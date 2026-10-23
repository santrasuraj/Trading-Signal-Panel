# NSE Scanner v2: user guide and plan

A personal, evidence-based tool for the Indian stock market. Every day it:

1. **Updates prices** for about 500 Nifty 500 stocks, using 8 years of history, NSE's official end-of-day files, and Fyers real-time prices.
2. **Re-tests every strategy** on that 8-year history. Each test buys at the next day's open and pays full Indian charges and tax.
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
- The tests use **today's** Nifty 500 list. Companies that collapsed or were dropped are missing, so **every result is flattered.** Even the "average stock" line shows 27%/year.
- **Judge a strategy by how much it beats the average stock**, not Nifty.
- NSE's own momentum indices, which don't have this bias, beat their parent index by **about 3–6% a year** over 20 years. That is a realistic edge. 40% a year is not.
- **Momentum crashes happen.** Expect 30–40% drops (−68% in 2008) and 1–2 years of lagging. NSE's Nifty200 Momentum 30 returned −0.5% in the 12 months to Sep 2026.
- **Tax:** momentum sells within a year, so gains are taxed at 20.8% every April. The dashboard shows after-tax returns. Frequent trading can also be treated as business income; ask a CA.

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
every paper trade, and how the result compares with what the backtest promised (also after removing the ~8%/yr
survivorship bias). It also shows how far luck alone could move the result. Telegram gets one paper line per strategy.
Everything is recomputed from the journal and stored prices on every view, so the same data always gives the same
numbers. To start over, delete `data/journal.sqlite`. Expect to need **about a year** before the comparison means much.

---

## 3. One-time setup (already done on this PC)

- Python, all libraries (pinned versions), and 8 years of cleaned price data are installed in this folder.
- Your Fyers App ID, Secret and Redirect URL are saved in **`.env`**. That file is private: never share it or upload it anywhere.
- **Your capital:** edit `account: capital:` in `config.yaml`. Order quantities are sized from it.

On a new PC: install Python 3.12, then double-click `setup.bat`, fill in `.env`, then run `3_dashboard.bat`. The first scan downloads and repairs 8 years of data, which takes about 4 minutes.

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
  paper.py       paper-trading journal (data/journal.sqlite) + deterministic replay at next-day opens
  holdings.py    holdings file, corporate-action-adjusted buy price
  lock.py        one scan at a time across processes
app.py           Streamlit dashboard (scans run in a background process)
run_scan.py      CLI / scheduler entry point (status file, rotating log, Telegram)
login.py         daily Fyers OAuth login
tests/           pytest suite: costs, tax, corporate actions, factors (no look-ahead), engine, paper trading
```

Run the tests with `.venv\Scripts\python.exe -m pytest -q`.

### Roadmap
| Next | Why |
|---|---|
| Results calendar: flag stocks with results in the next 7 days | Avoid buying just before a results surprise |
| Survivorship-free universe: point-in-time top 500 by turnover from NSE's full archive | Honest backtests |
| Sector strength from NSE sector indices | Avoid weak sectors |
| Momentum + low-volatility combined portfolio | Smoother returns |

# NSE Stock Scanner: plan and user guide

A personal tool that scans NSE stocks every day and shows:

- **Buy signals**: stocks matching your buy rules, with the reason for each
- **Sell signals**: stocks showing weakness
- **My holdings**: alerts when your stop-loss or target is hit, or a sell signal fires on a stock you own
- **Today's movers**: top gainers, top losers, volume spikes
- **Market mood**: Nifty trend, India VIX, how many stocks are rising
- **Backtest**: how often each rule actually worked over the last 2 years
- **Charts**: candlesticks with moving averages, RSI and past signal markers

> ⚠️ **These are rule-based signals, not investment advice.** No system knows tomorrow's prices.
> The goal is to replace tips and guesswork with clear rules that have been tested on past data.
> You make the final decision. Sharing these signals as recommendations with other people
> requires SEBI Research Analyst registration.

---

## 1. Daily routine (after setup)

| Time (IST) | What to do |
|---|---|
| Before 9:15 AM | Double-click **`1_login.bat`** and log in to Fyers. Fyers tokens expire every morning. |
| Any time | Double-click **`3_dashboard.bat`**, then click **🔄 Run scan now** |
| 9:45 AM / 3:05 PM | Automatic Telegram summaries arrive (if you set up step 5) |
| After 3:30 PM | Best time to scan. Daily candles are complete, so signals are final. |

**Signals during market hours can change before 3:30 PM.** A breakout at 11 AM may fail by the
close. Swing traders usually act on the scan from around 3:00 PM or after the close.

---

## 2. One-time setup

Python, the libraries and the project folders are **already installed** on this PC.

### Step 1: Create a Fyers API app (5 minutes)
1. Go to **https://myapi.fyers.in/dashboard** and log in with your Fyers account.
2. Click **Create App**:
   - App name: anything, e.g. `My Scanner`
   - **Redirect URL:** `http://127.0.0.1:8765/fyers/callback` (copy it exactly)
   - Permissions: tick everything related to **data / quotes / history / profile**. Order placement is not needed.
3. After creating it, note the **App ID** (looks like `ABCD1234EF-100`) and the **Secret ID**.

### Step 2: Put your keys in `.env`
Open the file **`.env`** in this folder with Notepad and fill in:
```
FYERS_CLIENT_ID=ABCD1234EF-100
FYERS_SECRET_KEY=your-secret-id
FYERS_REDIRECT_URI=http://127.0.0.1:8765/fyers/callback
```
Never share this file with anyone.

### Step 3: Log in
Double-click **`1_login.bat`**. A browser opens the Fyers login page. Log in with your client ID,
PIN and TOTP, and the window shows "✅ Logged in".

### Step 4: First scan
Double-click **`3_dashboard.bat`**, then click **🔄 Run scan now**. The first scan downloads about 3 years of
prices for about 500 stocks, which takes **about 10 minutes with Fyers** because of its API limit of 200 requests a minute.
After that, scans take seconds. Then click **🧪 Run backtest** once.

### Step 5 (optional): Telegram alerts on your phone
1. In Telegram, message **@BotFather**, send `/newbot`, and copy the **bot token**.
2. Send any message to your new bot, then message **@userinfobot** to get your **chat ID**.
3. Put both in `.env` (`TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`).
4. Test it: run `2_scan.bat --telegram` from a terminal, or `python run_scan.py --telegram`.
5. For automatic messages every weekday at 9:45 and 15:05: right-click **`setup_schedule.ps1`**, then **Run with PowerShell**.

**If you forget to log in:** everything still works with **Yahoo Finance data, delayed about 15 minutes**.
The dashboard and the Telegram message tell you when this happens.

---

## 3. The rules (what each signal means)

| Signal | Side | Meaning |
|---|---|---|
| 50-DMA breakout | BUY | Price crossed above its 50-day average on 2× or more normal volume, while in a long-term uptrend (above the 200-DMA) |
| 52-week high breakout | BUY | Closed at a new 1-year high on 1.5× or more volume |
| RSI oversold bounce | BUY | RSI climbed back above 30, so heavy selling may be ending |
| MACD bullish crossover | BUY | MACD crossed above its signal line, in a long-term uptrend |
| EMA 9/21 bullish crossover | BUY | Short-term trend turned up, price above the 50-DMA, volume above normal |
| 50-DMA breakdown | SELL | Fell below the 50-day average on 1.5× or more volume |
| 52-week low breakdown | SELL | New 1-year low on 1.5× or more volume |
| RSI overbought reversal | SELL | RSI fell back below 70, so the rally may be fading |
| MACD bearish crossover | SELL | MACD crossed below its signal line, price below the 50-DMA |
| EMA 9/21 bearish crossover | SELL | Short-term trend turned down on above-normal volume |

**Tuning:** open `config.yaml` to change any number, switch a rule off (`enabled: false`), change the
stock universe (`nifty50` / `nifty100` / `nifty200` / `nifty500`), the price and volume filters, or the stop-loss and target %.

### How to read a signal
- **Signals** (count): more rules agreeing means a stronger setup. The list is sorted by this.
- **Volume ×**: today's volume compared with the 20-day average. Moves on high volume are more meaningful.
- **Past win %**: from the backtest, how often this rule's trades made money over the last 2 years.
- **Stop-loss / Target**: from your % settings. **Always decide your stop-loss before buying.**

---

## 4. The backtest (the most important part)

Before trusting a rule, check the **🧪 Backtest** tab:

- **BUY rules:** the test buys at the next day's open and exits at −5% stop, +10% target, or after 15 days.
  It subtracts 0.25% for brokerage, STT and slippage.
- **SELL rules:** the test measures how often the stock fell over the next 15 days.
- **Baseline:** the result of buying *every* stock on *every* day. A rule is only useful if it **beats the baseline**.
- **Verdict:** *Worked better than random* / *No real edge* / *Worse than random* / *Not enough data*

**The first test on Nifty 50 stocks (Oct 2026) found that most textbook rules had no real edge over
the last 2 years.** That's normal: popular rules are popular because they're simple, not because they work.
Use the backtest to switch off rules that don't work, adjust parameters, and re-test.
Never trust a rule with fewer than about 30 past signals.

---

## 5. Honest limits

- **Nobody can predict tomorrow.** Even a good rule loses on many trades. It makes money only over
  many trades, **with stop-losses**, and with position sizes that never risk more than 1–2% of your capital on one trade.
- **Market mood matters.** When the dashboard says *Bearish*, most buy signals fail. Consider waiting.
- **Built for swing trading** (holding days to weeks) using daily candles. It is **not** built for intraday scalping.
- **Splits and bonus issues:** after a stock does a split or bonus, delete its file in
  `data/history/<source>/` so the next scan re-downloads clean history.
- **Not covered:** news, quarterly results dates, and company fundamentals. Check these yourself before buying.
  A stock can break out on day 1 and crash on its results on day 3.

---

## 6. Roadmap (next phases)

| Phase | Feature | Status |
|---|---|---|
| 1 | Daily scan, signals, movers, holdings alerts, dashboard | ✅ Done |
| 2 | Backtesting of every rule | ✅ Done |
| 3 | Telegram alerts and Windows scheduling | ✅ Done |
| 4 | Results/earnings calendar and corporate actions (avoid buying just before results) | Next |
| 5 | Sector strength: which sectors are leading or lagging | Next |
| 6 | Intraday mode (15-minute candles, live Fyers WebSocket) if you trade intraday | Later |
| 7 | Paper-trading log: record what you'd have done and track real performance | Later |
| 8 | Auto-sync holdings from your Fyers account | Later |

---

## 7. Files

| File | Purpose |
|---|---|
| `1_login.bat` | Daily Fyers login |
| `2_scan.bat` | Run a scan in a terminal window (`--telegram`, `--backtest`, `--source yahoo`) |
| `3_dashboard.bat` | Open the web dashboard |
| `config.yaml` | All settings and rule parameters |
| `holdings.csv` | Your holdings (also editable in the dashboard) |
| `.env` | Your Fyers and Telegram keys (private) |
| `setup_schedule.ps1` | Create the 9:45 / 15:05 weekday auto-scans |
| `scanner/` | The code: data download, indicators, rules, scan, backtest, alerts |
| `data/` | Downloaded prices, scan results, login token (safe to delete; it will re-download) |

# Intraday bars for the NSE platform: what Yahoo and FYERS actually give, plus a tested loader

> **Status, 24 Oct 2026.** This note was written on 23 Oct 2026, before the loader joined the project. It is now
> `scanner/intraday/`, run by `intraday_sync.py` and the scheduled tasks: a 15:45 FYERS archive (not a Yahoo job),
> the 09:14 FYERS WebSocket feed, and `5_intraday_backfill.bat` for the one-year backfill. The backtests square off
> at 15:00 for F&O stocks and 15:15 for others, before FYERS' MIS cut-offs of 15:05 and 15:20
> (`docs/strategy_catalogue.md` §3a), not at the 15:10/15:15 bar suggested in §3 below.

**Short answer.** Yahoo is free and fast, but it only goes back about 3 months for 5-minute bars. That is too short for an honest intraday backtest, and its first and last 15 minutes of each day can't be trusted. FYERS Standard gives at least a year of 1-minute to 5-minute bars, and a full Nifty 100 backfill takes about 15 minutes of API calls. The plan:
- **Now:** run a daily job that saves Yahoo 5-minute bars. Every day saved stays saved, so the store keeps growing past Yahoo's 3-month window.
- **On the first FYERS login:** do a one-time backfill.
- **Live, during the session:** stream up to 100 symbols over the FYERS WebSocket, building bars from the ticks locally.

The loader module is written and all 10 of its tests pass. Nothing under `D:\New folder\stock_scanner` was modified.

## 1. Yahoo (yfinance 1.7, `.NS`) — measured 2026-10-23

### How far back each interval goes (RELIANCE)
`period="Nd"` counts **trading sessions**. A `start=`/`end=` window must lie within the last N **calendar** days.

| interval | most you can get with `period` | `start=` limit | per-request cap |
|---|---|---|---|
| 1m | `8d` = 8 sessions (2,883 bars) | within last 30 calendar days (29 works, 30 fails) | 8 days per request |
| 2m / 5m / 15m / 90m | `60d` = 60 sessions (5m: 2026-07-28→10-22, 4,388 bars); `59d` works, `61d` fails | 59 days works, 60 fails | — |
| 30m | `60d` | — | bars are clock-aligned at **09:00** (not 09:15), so don't use the native 30m |
| 60m / 1h | `730d` = **727 sessions** (2023-11-07→2026-10-22, 5,069 bars); `731d` fails | 729 days works, 730 fails | — |
| 1d | `max`, from 1996 | — | — |

- **Recent listings:** a stock with less history than the period fails the `period` form (HYUNDAI on 1h/730d). Retrying it with `start=` works: 492 sessions from 2024-10-24. The loader does this retry automatically.
- **1-minute depth by chunking:** stepping through the last 30 calendar days in 7-day windows gave 18 sessions.

### Bulk download speed, Nifty 100 (official NSE list, 100 symbols, threads on)
| request | time | bars | symbols returned |
|---|---|---|---|
| 5m / 60d, 1 batch of 100 | 32.4 s | 438,396 | 100 |
| 5m / 60d, 2 batches of 50 | 35.5 s | 438,396 | 100 |
| 15m / 60d | 34.9 s | 148,833 | 100 |
| 1h / 730d | 48.1 s | 477,252 | 99 (HYUNDAI needed the retry) |
| 1m / 8d | 25.6 s | 288,192 | 100 |

### Data quality (all 100 symbols, compared with the project's official NSE daily store)
- **Clean basics:**
  - Timestamps are tz-aware `Asia/Kolkata` on every interval.
  - No pre-open bars (09:00–09:14), no bars outside the session, no duplicates, no NaNs, and no bars where open/close fall outside high/low.
- **Missing bars:** 5m has a median of 73 of 75 bars per stock per day (only 10.0% of stock-days are complete; 2.58% of expected bars are missing). 15m is 80.6% complete, 1h 97.9%, 1m 2.6%.
- **The last 15 minutes are unreliable.** Yahoo drops most real bars after 15:15 and puts one flat bar (open = high = low = close = the official close) at 15:28/15:29 (1m), 15:25 or 15:15 (5m), and 15:15 (15m/1h).
  - 1m: 97% of stock-days have no bars at all between 15:16 and 15:27.
  - 5m: the last real bar is 15:15 on 62.5% of stock-days, 15:10 on 27.4%, and 15:25 on only 10.1%.
- **Opening volume is missing in stored history.**
  - The 09:15 bar has zero volume on 5,864 of 6,000 stock-days (5m), every stock-day (1m), and 58,767 of 68,510 (1h).
  - Summed volume as a share of NSE daily volume (median): 0.957 for 5m (5th percentile 0.884), 0.983 for 1m, and only 0.78 for 1h.
  - Live today, the 5m 09:15 bar did carry volume (306,530 for RELIANCE). So Yahoo seems to zero it after the session. I saw this on one day only; it needs rechecking tomorrow.
- **Open, high, low and close against NSE:**

| field | exact match | within 0.5% | median difference |
|---|---|---|---|
| open | 13.7% | 92.2% | 13 bp |
| high | 41.8% | 98.3% | 1.8 bp |
| low | 40.6% | 98.8% | 1.8 bp |
| close | 92.6% | 99.57% | 0 |

  - The open differs because NSE's official open comes from the 09:08 pre-open auction, while Yahoo's first bar starts with continuous trading.
  - Yahoo's high is below NSE's high on 31.2% of days, and its low is above NSE's low on 27.2% (by more than 5 bp). In 19% and 11% of those cases the missing extreme is the auction price. Yahoo is never above NSE's high.
  - Yahoo's close matches only because of the flat closing bar. Without it, exact matches fall to 78.7%.
  - On 2026-08-31, the official close differed from the last trade by up to 3.5% (ITC 255.5 vs 264.4, also IOC and JINDALSTEL). Yahoo's daily data agrees with NSE, so intraday bars simply can't reproduce that close.
- **Splits and bonuses are not adjusted consistently.** In the 1h data, 1,829 stock-days across 29 symbols differ from the adjusted store by more than 1.5%; BAJFINANCE before mid-2025 is about 5× off. After `adjust_to_store`, 97.6% of days are within 1.5% and BAJFINANCE's worst gap is 0.99%.
- **Resampling works.** 5m bars resampled to 15m match Yahoo's native 15m exactly on every field (148,833 bars). So storing 5m (or 1m) is enough; build 15m/30m/60m from it.

### Live behaviour (polled every ~55 s from 08:58 IST)
- 09:00–09:14: still returns the previous day's data. No pre-open bars.
- The first bar for today appeared at 09:15:11.
- The current 1m bar is present about 20–30 s into each minute. It is a single price (open = high = low = close, volume 0); its real values arrive when the next minute starts.
- The current 5m bar updates in place (high, low, close and volume grow).
- `fast_info.lastPrice` equals the latest 1m close.
- One 5-ticker call took 0.9–8.6 s, slowest around the open.
- I could not measure how stale Yahoo's prices really are, because I had no live reference feed to compare against.

## 2. FYERS Standard plan (from SDK 3.2.0 source and fyers.in/api-docs/v3; no live calls, since you aren't logged in)
- **Call format:** `FyersModel.history(data={...})`, a GET to `https://api-t1.fyers.in/data/history`. Fields:
  - `symbol`: `"NSE:SBIN-EQ"`
  - `resolution`: `1/2/3/5/10/15/20/30/60/120/240` minutes, or `D`/`1W`/`1M`. Seconds resolutions (`5S`–`45S`) are Prime only.
  - `date_format`: `"1"` for `yyyy-mm-dd`, or `"0"` for epoch seconds
  - `range_from`, `range_to`, `cont_flag: "1"`, optional `oi_flag`
  - The response is `{"s":"ok","candles":[[epoch_s,o,h,l,c,v],...]}`, with epochs in UTC at the bar start.
- **Limits per call:** up to 100 days for any minute resolution, 366 for daily.
- **How far back on Standard:** intraday covers the "last 1 year (from 2025)", rolling; daily goes back 5 years (from 2021). As of today I read that as data from 2025-01-01. This needs checking on the first login (ask for 2024-12-01→2025-01-31).
- **Unfinished candles:** set `range_to` before the current bar starts. The module does this clamp for you.
- **Rate limits:** 5/s, 50/min, 5,000/day. Exceeding the per-minute limit more than 3 times in a day blocks you for the rest of the day. Error code is -429.
- **Splits and bonuses:** whether intraday history is adjusted isn't documented. A FYERS staff reply on the forum says daily data is adjusted. So the module stores raw prices and adjusts against the store.
- **Backfill cost** (the call count doesn't depend on resolution, so fetching 1m and resampling costs the same as 5m):

| job | calls | time at 48/min | share of daily quota |
|---|---|---|---|
| Nifty 100, 1 year | 400 | 8.3 min | 8% |
| Nifty 100, since 2025-01-01 | 700 | 14.6 min | 14% |
| Nifty 500, 1 year | 2,000 | 41.7 min | 40% |
| Daily top-up | 1 per symbol | — | — |

- **Live data options:**
  - **Quotes:** 50 symbols per call. Refreshing the Nifty 500 every minute would use 3,750 calls a day (75% of the quota); every 5 minutes uses 750.
  - **Polling 5m history** for 100 symbols would need 7,500 calls a day, which is more than the 5,000 quota, so it isn't viable.
  - **Data WebSocket:** 100 symbols on Standard, counted per user across all connections. The SDK itself allows 5,000 (`symbol_limit=5000` in `data_ws.py`); the server enforces the plan limit and reports it with code 51001. Lite mode sends only the last price, so building bars needs full `SymbolUpdate` messages, which include the day's cumulative volume.
  - **Recommendation:** WebSocket for up to 100 watchlist symbols, quotes every 2–5 minutes for the rest of the Nifty 500, and a history backfill after the close to fill any gaps.

## 3. Storage design (built in the module)
- **Layout:** `data/intraday/<interval>/<YYYY-MM>.parquet` (zstd compression) plus a `manifest.json` per interval.
- **Format:** one row per bar, with columns `ts, symbol, open, high, low, close, volume, flags, source`.
  - `ts` is the bar's start time in IST with no timezone attached.
  - The session runs 09:15–15:30 and bars are aligned to 09:15: 75 slots for 5m, 25 for 15m, 375 for 1m, 7 for 60m.
- **Prices:** stored as traded. `adjust_to_store` rescales them to the store's split/bonus-adjusted prices when you need multi-day continuity.
- **Saving:**
  - New bars merge into each month's file.
  - A crash can't leave a half-written file, because each write goes to a temp file that then replaces the old one, as `store.py` already does.
  - When two sources disagree, FYERS beats the FYERS WebSocket, which beats Yahoo.
  - An unfinished live bar is never saved.
- **Flags on each bar:** zero volume on the opening bar, Yahoo's flat closing bar, high/low corrected, a jump of more than 10%, and unfinished.
- **Size and speed (measured):** 16.2 bytes per bar. The 60-day Nifty 100 5m set is 7.08 MB, saves in 5.2 s and loads in 0.85 s.
  - A year of 5m is about 30 MB for the Nifty 100 and about 150 MB for the Nifty 500.
- **`load_grid`:** returns a (days × slots × symbols) array of 60×75×100 in 3.4 s, with 2.58% NaN, for vectorised strategies in the style of `panel.py`.
  - For the Nifty 500 over a full year, use float32 or load a quarter at a time.

**Rules for honest backtests on Yahoo bars:**
- Exit by the 15:10/15:15 bar. Brokers square off intraday positions around 15:15–15:20 anyway.
- Exclude the flat closing bar when testing the price path within a bar.
- Take gap and open prices from the NSE daily store, not Yahoo.
- Don't use 5m or 1h opening-bar volume; use 15m bars or FYERS for that.

## 4. Module and tests
- **Data module:** `scanner/intraday/data.py`
  - `fetch_yahoo_intraday(symbols, interval, days)`
  - `fetch_fyers_intraday(provider, symbols, start, end, resolution)`. It works with the project's `FyersProvider` or a raw `FyersModel` (wrapped by `FyersProvider.from_model`), so every call goes through the shared rate limiter `scanner/fyers_limits.py`.
  - `clean_bars`, `daily_from_bars`, `merge_by_priority`, `IntradayStore.save / load`, `TickBarBuilder`, `FileLock`
  - Research helpers the pipeline doesn't use: `fyers_backfill_budget`, `validate_against_daily`, `adjust_to_store`, `resample_bars`, `load_grid`, `completed_only`
- **FYERS sync:** `scanner/intraday/fyers_sync.py` handles the resumable 1-year backfill and the daily archive. It saves its progress in `data/intraday/fyers_sync.json` and holds `data/intraday/.sync.lock` while it runs. `IntradayStore.save` holds `<interval>/.save.lock`.
- **Live feed:** `scanner/intraday/live.py` builds bars from the FYERS WebSocket. It writes `data/intraday/live/YYYYMMDD.parquet` and `forming.json`, whose `last_tick` field `feed_fresh()` uses to detect a dead feed. One instance runs at a time, held by `live/.live.lock`.
- **Entry point:** `intraday_sync.py` (`--backfill`, `--archive`, `--live`, `--run`, `--usage`). Its `--run` and the web app's re-run share `data/results/.intraday.lock`.
- **Tests:** `tests/test_intraday.py` and `tests/test_fyers_limits.py`. They use fake providers and `tmp_path`, so they make no network calls and don't touch the real data folder.
- The first measurement scripts and raw outputs were kept in this session's scratchpad. They're not part of the project.

## 5. Three pre-registered intraday research tests (added 25 Oct 2026)

**Read this first.** These are tests, not strategies to fund. At Indian MIS costs a round trip is about 0.05% for
NIFTYBEES and 0.12–0.32% for stocks, which is as large as or larger than every documented intraday edge. None of the
three is expected to be clearly profitable. They are in the platform so that the honest answer can be measured. They
have **not been run yet** (no results exist for them as of 25 Oct 2026). The code is in `scanner/intraday/strategies.py`
and the tests are in `tests/test_intraday_new.py`. Their settings are fixed in advance (`PRE_REGISTERED`). Any other
value is refused with an error, because choosing a setting after seeing the results would make the test worthless.

| key | what it does (all decisions use only prices known at the decision time) | primary spec | the only other pre-registered settings |
|---|---|---|---|
| `gap_fade_largecap` | At 09:15, take the 100 most-traded F&O stocks (20-day value to the previous day, price ≥ Rs 100). Drop results days and the day after, ADR stocks (INFY, WIPRO, HDFCBANK, ICICIBANK, DRREDDY) and raw gaps above 10%. Idiosyncratic gap = stock gap − NIFTYBEES gap. Short the 3 largest ≥ +threshold and buy the 3 most negative ≤ −threshold. Enter at the **09:20 bar open** (an auction fill is not assumed). Stop 1 × daily ATR; exit at the 15:00 bar open. Equal notional legs of 2 × equity / 6 (about market-neutral). | `threshold_pct: 1.5` | `1.0`, `2.0` |
| `inplay_orb15` | At 09:30, rank F&O stocks by 09:20–09:30 volume against their previous 14 sessions (≥ 1.0×; build_days' `relvol`, bars 1–2 for both Yahoo and FYERS). Keep the top 2 and never revise. Direction = price at 09:30 vs the 09:15 open. A buy-stop at the 09:15–09:30 high (sell-stop at the low) works 09:30–14:55. A pick that never triggers stays an empty slot; no lower-ranked stock replaces it. Exit at the stop or the 15:00 bar open. Risk 0.5% of equity, at most 1× equity per trade. | `stop: atr10` (10% of daily ATR), `filter: rvol`, `entry_bar: stop_first` | `stop: range` (other side of the range); `filter: rvol_news` (results day or \|gap\| ≥ 2%); `entry_bar: entry_first` |
| `niftybees_eod_momentum` | NIFTYBEES only. If it is up from yesterday's close at 09:45, buy at the 14:45 bar open (short if down) and exit at the 15:15 bar open. Emergency stop 1%. One trade a day, 1× equity, slippage 0.02% a side. | `rule: sign` | `rule: agree` (14:15→14:45 must agree), `rule: rod` (yesterday's close → 14:45) |

**Running the variants.** Each variant is one line in `config.yaml`, for example
`intraday_strategies: {gap_fade_largecap: {threshold_pct: 1.0}}`. Report **every** variant you run, not just the best
one. For NIFTYBEES, also run `{niftybees_eod_momentum: {slippage_pct: 0.07}}` as a robustness check. For the ORB, run
both `entry_bar` settings: 5-minute bars cannot show whether a 0.2–0.3% stop was hit before or after the entry, so the
truth lies between them. The intraday page applies a Bonferroni correction over all enabled strategies (now 12), so
a variant has to clear about |t| ≥ 3 to count as significant.

**Gap fade on daily data first.** `gap_fade_daily(frames, universe=..., results=...)` in the same module runs the
same picks open → official close on the daily store: about 1,800 sessions from 2019, instead of 60 intraday ones.
Entry is at the open × (1 ± 0.05%) and exit at the close ∓ 0.03%, with the intraday charges. Membership on day t
comes from the point-in-time universe row t−1, and there is no stop. It returns overall metrics plus the periods
before 3 Aug 2026 (closing auction), from 3 Aug to 6 Sep, and from 7 Sep 2026 (new pre-open). It is **not wired into
the scan yet**. To run it by hand: `pit.load()` gives `.frames` and `.universe`; add the store's NIFTYBEES columns
(`pit.backtest_frames(data, load_store(), ["NIFTYBEES"])`); pass `events.results_history(...)` as `results`. The
daily test exits at the close, not at 15:00, and the last half hour can flatter it, so any positive result still
needs the 5-minute check.

**Engine hooks they use** (`scanner/intraday/engine.py`, all optional, so the older nine strategies behave exactly as
before):
- `prepare(days, params)` makes the day's cross-sectional picks once, from decision-time data.
- `notional_x` sizes trades at a multiple of equity instead of by risk.
- `slippage_pct` replaces the Nifty 50 / other slippage tiers, e.g. for NIFTYBEES.
- Every trade now records `gross_pct` (fill to fill, before slippage and charges), and the metrics include
  `avg_trade_gross_pct`. This shows whether a strategy has no edge or whether costs eat it.

**Still not modelled for these tests:**
- The 5-minute run does not split at 3 Aug / 7 Sep 2026; only the daily gap-fade test does.
- F&O membership is today's list.
- There is no news filter beyond the results calendar.
- There is no volume-participation cap.
- Yahoo's 09:15 open is the first continuous trade, not the official auction open.
- Whether FYERS accepts MIS orders in the pre-open, and MIS shorting of NIFTYBEES, needs confirming with FYERS.
- Profits are taxed as speculative income at the slab rate.

Sources: [FYERS historical data](https://fyers.in/api-docs/v3/api/market-data/historical-data/), [FYERS plans and limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/), [FYERS data socket](https://fyers.in/api-docs/v3/api/websockets/data-socket/data-socket-symbol-update/), [FYERS History API delay](https://support.fyers.in/portal/en/kb/articles/is-there-any-delay-in-the-data-provided-by-the-history-api), [FYERS community: adjusted history](https://fyers.in/community/t/how-can-we-retrieve-historical-stock-data-from-fyers-api-with-all-corporate-actions-adjusted-splits-bonus-merger-demerger-etc/22650)
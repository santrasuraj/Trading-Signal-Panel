# Quant Desk v3: platform spec (UI, API and backend wiring)

**Replaces:** `app.py` (Streamlit). **Branch:** `platform-v3` (worktree `D:\New folder\stock_scanner\.worktrees\platform`, already has the scaffold in `web/`).
**Audience:** the engineers building `web/api` (FastAPI) and `web/ui` (React). This document is the contract.
**Basis:** I read `scanner/daily.py`, `engine.py`, `strategies.py`, `panel.py`, `store.py`, `paper.py`, `pit.py`, `holdings.py`, `events.py`, `lock.py`, `providers.py`, `costs.py`, `indicators.py`, `app.py`, `run_scan.py`, `login.py`, `README.md`, `config.yaml`, `docs/strategy_catalogue.md` and the scaffold. I also checked the real `data/results/latest.json` (scan of 23 Oct 2026 09:18, 13 strategies) and `curves.parquet`. Every widget below is fed by data that exists now, or by one of the small backend additions B1 to B8 in section 1.4. Nothing is mocked.

---

## 0. Decisions at a glance

| Topic | Decision |
|---|---|
| Product shape | A dark-first research terminal: left icon rail, a top bar with live market context, a bottom status bar, and dense tables. Keyboard-first (Ctrl+K palette). Quality bar: Kite, TradingView, Tickertape. |
| Pages | Overview · Signals · Strategies (+ detail) · Screener · Chart · Portfolio · Paper · Market · Intraday (honest placeholder until the intraday engine lands) · Data & Settings |
| Honesty | Shown on every page: backtest vs live, the survivorship-bias flag, the timing-luck range, edge vs the *average stock*, after-tax numbers, and a "Tested & rejected" list. Not-working strategies stay visible but are greyed. |
| Frontend | Vite 6.4.5 + React 18.3.1 + TypeScript 5.8.3 + Tailwind 3.4.17 + TanStack Query 5.62.0 + TanStack Table 8.21.3 + lightweight-charts **5.2.1** + lucide-react 0.468.0 + react-router-dom 6.28.0 + cmdk 1.1.1. No other chart library. |
| Backend | FastAPI 0.120.4 + uvicorn 0.38.0 + pydantic 2.14.1 (already in `.venv`). Serves `/api/*` JSON and the built SPA from `web/ui/dist`. Port **8600**, bound to **127.0.0.1** only. |
| Wire format | snake_case JSON. Percent values are in percent units. Money is in rupees. Dates are IST trading dates (`YYYY-MM-DD`). Nullable fields are always present. |
| Change propagation | `GET /api/status` returns `latest.scan_id`. When it changes, the UI invalidates every query. No websockets in v3.0. |
| Scanner code | The API only **imports and calls** existing functions. A short list of additions to `scanner/daily.py` (B1 to B8) is spelled out. Everything else is derived in `web/api/services`. |

---

## 1. Ground truth: what data exists

### 1.1 Files and their producers

| Artifact | Producer | Refresh | Used by |
|---|---|---|---|
| `data/results/latest.json` (~180 KB, `version: 2`) | `daily.run_daily` → `_save` | every scan | almost every page |
| `data/results/scan_YYYYMMDD_HHMM.json` (last 60 kept) | `_save` | every scan | "Since last scan" diff, scan history |
| `data/results/curves.parquet` | `_save` | every scan | equity / drawdown / heatmaps. Index = dates (2019-08-21 →); columns = strategy keys + `NIFTY 50`, `Average stock`, `NIFTY 500`; every column is normalised to 1.0 at the start. |
| `data/results/status.json` | `run_scan.py --status` | during a scan | scan progress `{state, message, progress, started}` |
| `data/.scan.lock` + `.scan.lock.json` | `lock.scan_lock` | during a scan | `lock.running_scan()` → `{started, by, pid}` or None |
| `data/history/store/CURRENT` → `gen_*/{open,high,low,close,volume,deliv_pct}.npy, dates.npy, symbols.json` | `store.refresh_store` | completed days only | chart, sparklines, breadth history, screener fallback (`store.load_store()`, `PanelStore().version()`) |
| `data/history/store/meta.json` | store | every refresh | data health: `failed`, `holidays`, `corporate_actions` (125), `provisional` |
| `data/nse/index_history.parquet` | `nse.index_history` (platform branch) | every scan | sector and factor index tables (already summarised into `latest.indices`) |
| `data/nse/events_YYYYMMDD.json` | `events.upcoming_results` | 6 h cache | results calendar (raw NSE rows with `purpose`) |
| `data/nse/results_YYYYMM.json` | `events.results_history` | monthly | PEAD strategy; past results markers |
| `data/nse/holidays_YYYY.json` | `events.trading_holidays` | 7 d | market clock |
| `data/universe_nifty500.csv` | `universe.get_universe` | 7 d | `symbol, company, industry` (20 industries) |
| `holdings.csv` | `holdings.save_holdings` | user edits | Portfolio |
| `data/journal.sqlite` | `paper.record_scan` (main branch) | completed-day scans | Paper |
| `data/fyers_token.json` | `login.py` | daily login | Fyers status. **Never exposed.** |
| `data/history/pit/` | `scanner.pit` (survivorship session) | when built | survivorship flag, PIT comparison |
| `data/logs/scanner.log` | `run_scan.py` | every scan | Settings → logs |
| `config.yaml`, `.env` | user | manual | Settings. **`.env` is never exposed.** |
| Intraday store (future) `data/history/intraday/<interval>/<YYYY-MM>.parquet` | prototype `IntradayStore` (scratchpad `intraday/intraday.py`) | daily archive job | Intraday, 5-min chart |

### 1.2 `latest.json` today (platform branch, 23 Oct 2026 09:18)

Top level: `version, generated_at, elapsed_s, data_date, live, live_source, complete_upto, fyers_note, nse_status, universe, stocks, stale_symbols[], errors{}, corporate_actions[], capital, costs_round_trip_pct, market{}, strategies[], gainers[], losers[], volume_spikes[], holdings[], symbols[], results_note, indices{factors[], sectors[]}`.
The main branch also has `min_position` and `paper{}`. The platform branch is behind `2c1e55d` and lacks them (see B6).

- `market`: `label, level, advice, regime_up, nifty, nifty_change_pct, vix, vix_change_pct, breadth_50, advances, declines`.
  - Example: Bearish, Nifty 22,687.65 (−0.54%), VIX 15.76, 13.2% of stocks above their 50-DMA, A/D 133:344.
- `strategies[i]`: `key, name, description, kind ('rank'|'event'), horizon, evidence, universe ('stocks'|'etfs'), benchmark, status, status_reason, metrics{full,12m,6m,3m}, yearly{year: pct}, positions[], actions[], ranking[] (top 40, rank strategies), max_positions, per_position, next_rebalance, recent_trades[] (last 25)`.
  - The main branch also has `rules{stop_pct,target_pct,trail_pct,sizing,risk_pct}`.
- `metrics.full`: `return_pct, cagr_pct, max_dd_pct, sharpe, vol_pct, trades, win_rate, avg_win_pct, avg_loss_pct, expectancy_pct, profit_factor, avg_days, exposure_pct, start, end, benchmark{}, ew_benchmark{}, n500_benchmark{}, factor_benchmark{}, after_tax_cagr_pct, after_tax_return_pct, factor_benchmark_name, cagr_range[lo,hi]`. The windows have the same fields without exposure, after-tax or range.
- `indices.factors[]` / `indices.sectors[]`: `name, last, chg_1d, ret_1m, ret_3m, ret_6m, ret_1y, cagr, max_dd, since, above_50dma` (+ `rank` for sectors). These are 13 factor indices and 21 NSE sector indices.
- `actions[]`: `action, symbol, reason, company, industry, price, qty, amount, stop, results_on, results_in_days, results_warning, provisional`.
- `positions[]`: `symbol, entry_date, entry_price, qty, last_price, ret_pct, stop, days, company, industry, results_on`.
- `holdings[]`: `symbol, company, qty, buy_price, price, change_pct, pnl_pct, pnl_amount, stop_price, target_price, momentum_rank, rs, results_on, level, alerts[]`.

Today's leaderboard, for scale (full period 2019-08-21 → 2026-10-22):
- Average stock: 27.5%/yr. Nifty 500: 13.6%/yr. That 14-point gap is mostly survivorship bias.

| key | horizon | evidence | status | CAGR | Edge vs avg stock |
|---|---|---|---|---|---|
| momentum | longterm | STRONG | working | 42.3% | +14.9 |
| earnings_gap | swing | MODERATE | working | 17.9% | −9.5 |
| index_trend | longterm | MODERATE | working | 12.1% | (ETF; vs Nifty 50 +1.1) |
| golden_cross | longterm | WEAK | working | 24.9% | −2.5 |
| vcp_breakout | swing | WEAK | working | 8.3% | −19.2 |
| trend_breakout | swing | EXPERIMENTAL | working | 46.0% | +18.6 |
| dual_momentum | longterm | MODERATE | mixed | 4.8% | (ETF; vs Nifty 50 −6.2) |
| sector_rotation | longterm | MODERATE | mixed | 30.9% | +3.5 |
| donchian | swing | MODERATE | mixed | 24.2% | −3.2 |
| bb_squeeze | swing | WEAK | mixed | 12.0% | −15.5 |
| pullback_leaders | swing | WEAK | mixed | 26.2% | −1.2 |
| nr7_breakout | swing | WEAK | mixed | 2.3% | −25.2 |
| low_vol | longterm | STRONG | not-working | 9.5% | −18.0 |

### 1.3 Data issues found while designing (backend must know)

1. **The timing range is inconsistent with the base CAGR** for several strategies. Examples:
   - earnings_gap: 17.9% vs range [13.5, 14.1]
   - index_trend: 12.1 vs [4.4, 10.5]
   - vcp: 8.3 vs [4.4, 5.1]
   - trend_breakout: 46.0 vs [43.8, 45.1]

   The `timing_cache.json` signature misses inputs that changed results: the results-history calendar, the ETF list, the cash-rate index and code version. **Fix:** add those to `sig`, and always `min/max` the base value into the range. **API guard:** set `timing.consistent=false` and show "range out of date" when `!(lo <= base <= hi)`.
2. **SELL orders are sized like buys** (`sized()` runs for every order). For SELL, the API must use the model position's qty (`model_qty`) and the user's own qty if they hold it.
3. The **platform branch is behind main**: `paper.py`, `pit.py`, `min_position`, `paper{}`, `rules{}` and `te_n500_pct` are missing → B6.
4. **Disabled strategies are not tested at all.** The honesty rule needs them listed with their result → B4.
5. **Holdings health is computed only at scan time.** After an edit it is stale → the API flags `health_stale` and the UI offers "Re-check (no download, ~15 s)" = `POST /api/scan {update:false}`.
6. `market` has no Nifty 500 level and no distance to the 200-DMA. The API derives both: Nifty 500 from `indices.factors`, and Nifty vs its 200-DMA from the store.

### 1.4 Backend additions (small, in `scanner/daily.py` on `platform-v3`)

| ID | Addition | Why | Phase |
|---|---|---|---|
| B1 | `_save` writes `data/results/trades.parquet`: `strategy, symbol, entry_date, entry_price, exit_date, exit_price, qty, pnl, ret_pct, days, reason` (all closed trades of the base simulation) | full trades table, chart markers | P1 |
| B2 | `_save` writes `data/results/screener.parquet`, one row per tradable stock at scan time: `symbol, price, change_pct, ret_1w, ret_1m, ret_3m, ret_6m, ret_12m, rs, momentum_score, momentum_rank, vol_ann_pct, pct_from_52w_high, above_sma50, above_sma200, sma50_above_sma200, rsi14, vol_ratio, turnover_cr, atr_pct, deliv_pct` | the screener matches the orders (same live overlay) | P1 (the API falls back to computing from the store) |
| B3 | add `nifty_sma200` and `min_position` to the result (`market.nifty_sma200`) | regime distance | P1 |
| B4 | test disabled strategies too (cached by signature like the timing cache, recomputed once per completed day). Emit `lifecycle: 'active'\|'disabled'\|'rejected'` and produce **no orders** unless active. `rejected` = `enabled:false` plus `rejected_reason` in config. | "Tested & rejected" list with real numbers | P1 |
| B5 | per strategy, emit `rules` again (dropped on this branch) plus `params` (the effective config values) | rules card, sizing, regime explanation | P1 (the API can also read them from `build_strategies(cfg)`) |
| B6 | merge `main` (2c1e55d): paper journal, `pit.py`, `min_position`, `paper` summaries | Paper page | P1 |
| B7 | `backtest_universe: 'current_list'\|'point_in_time'` (from the survivorship session) | bias banner | P1 (default `current_list`) |
| B8 | optional `validation{}` per strategy: walk-forward in-sample vs holdout, `variants_tried`, expectancy 95% CI (catalogue §8) | evidence card | P2 |

The API must run **without** B1, B2, B4 and B8: those features show an "available after next scan / not built yet" state, never fake data.

---

## 2. Information architecture

### 2.1 Navigation and routes

| Rail item (lucide icon) | Route | Purpose |
|---|---|---|
| Overview (`LayoutDashboard`) | `/` | Regime, indices, breadth, next-open orders across strategies, alerts, what changed |
| Signals (`Crosshair`) | `/signals?horizon=` | Orders for the next open by horizon, sized to capital/allocation, stops, warnings |
| Strategies (`Trophy`) | `/strategies?horizon=&status=&evidence=` | Leaderboard by horizon, plus Tested & rejected |
| Strategy detail | `/strategies/:key/:tab?` (tabs: `performance`, `trades`, `holdings`, `rules`, `paper`) | Everything about one strategy |
| Screener (`ListFilter`) | `/screener?preset=&industry=` | Momentum / RS / 52w / low-vol / volume rankings |
| Chart (`CandlestickChart`) | `/chart/:symbol?tf=1d&range=1y&s=momentum` | Candles + indicators + strategy markers |
| Portfolio (`Briefcase`) | `/portfolio` | Your holdings health, P&L, alerts, editor, Fyers import |
| Paper (`NotebookPen`) | `/paper`, `/paper/:key` | Live paper-trading journal vs backtest |
| Market (`Globe2`) | `/market/:tab?` (tabs: `movers`, `sectors`, `factors`, `results`, `breadth`) | Market context |
| Intraday (`Timer`, badge "soon") | `/intraday` | Status, data coverage, SEBI facts, planned strategies |
| Settings (`Settings2`) | `/settings/:section?` (sections: `data`, `fyers`, `scan`, `capital`, `strategies`, `costs`, `filters`, `appearance`, `about`) | Data health, login, scan, config, costs, disclaimer |

All filters live in the URL (`useSearchParams`), so back/forward and reloads keep state. The FastAPI SPA fallback already serves deep links.

### 2.2 Global chrome (every page)

- **Top bar (48 px):**
  - command palette trigger: `Search stocks, strategies, pages… Ctrl K`
  - index ticker: NIFTY 50 · NIFTY 500 · INDIA VIX · A/D, plus a regime pill (`BULLISH` / `MIXED` / `BEARISH`)
  - data freshness pill: `EOD 22 Oct · NSE official`, `LIVE · Fyers · provisional` (amber) or `STALE · 21 Oct` (amber)
  - Fyers status dot
  - Scan button: shows a progress ring and percentage while running, and a split menu: *Full scan* / *Re-check without download*
  - theme toggle
- **Left rail:** 60 px collapsed, 224 px expanded. Collapsed by default below 1440 px; the choice is remembered.
- **Status bar (28 px, desktop only):** `Last scan 09:18 IST (11.6 s) · Prices 22 Oct (official close) · NIFTY500 (cached list) · 478 liquid · Capital ₹5,00,000 · Backtests: today's list (survivorship bias) · Not investment advice`
- **Global banners** (stacked, dismissible per scan_id): Provisional (market open), No scan yet, Server unreachable, Scan failed (with message), Fyers not logged in during market hours.

### 2.3 App shell wireframe (1280 × 800)

```
┌────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
│ QD │ [ Search stocks, strategies, pages…  Ctrl K ]  NIFTY 22,687.65 −0.54%  N500 21,696.55 −0.60%  │
│    │  VIX 15.76 +0.51%  A/D 133:344  [BEARISH]   [EOD 22 Oct · NSE]  [o Fyers]  [Scan v]  [theme] │
├────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Ov │                                                                                             │
│ Sg │                                                                                             │
│ St │                              page content (gutter 20 px, grid gap 12 px)                    │
│ Sc │                                                                                             │
│ Ch │                                                                                             │
│ Pf │                                                                                             │
│ Pp │                                                                                             │
│ Mk │                                                                                             │
│ In │                                                                                             │
│ ── │                                                                                             │
│ Se │                                                                                             │
├────┴─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Last scan 09:18 IST (11.6 s) · Prices 22 Oct (official close) · 478 liquid · ₹5,00,000 · Not advice │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl/Cmd K` | Command palette: symbols (from `/api/symbols`), strategies, pages, actions (Run scan, Log in to Fyers, Toggle theme) |
| `g o` `g s` `g t` `g c` `g p` `g m` `g ,` | Go to Overview / Signals / sTrategies / Chart / Portfolio / Market / Settings |
| `/` | Focus the current table's filter box |
| `j` / `k`, `Enter` | Move the table row selection; open the chart for the selected symbol |
| `[` / `]` | Previous/next strategy on the detail page; previous/next symbol on the chart (within the source list) |
| `1`…`6` on Chart | Range 3M 6M 1Y 2Y 5Y Max |
| `d` / `w` / `5` on Chart | Timeframe daily / weekly / 5-min (5-min disabled until intraday exists) |
| `Shift T` | Toggle dark/light |
| `?` | Shortcut help sheet |

---

## 3. Page specs

Notation: **[src]** = API endpoint feeding the widget. All numbers in the wireframes are real values from the 23 Oct 2026 scan.

### 3.1 Overview `/`

**[src] `GET /api/overview`**, plus `GET /api/market/breadth?range=1y` for the chart.

Widgets:
1. **Regime card:**
   - `market.label` with an icon (TrendingUp / Minus / TrendingDown) and the `advice` text
   - "Nifty vs 200-DMA: −x.x%" (`nifty_vs_sma200_pct`)
   - breadth % and A/D bar (advances green, declines red, proportional)
   - VIX ≥ 20 adds a warn chip "High volatility"
2. **Index tiles** (Nifty 50, Nifty 500, India VIX, Nifty200 Momentum 30): last, 1-day change, 3-month mini-sparkline (from the store / index history). Click → Market › factors.
3. **Breadth chart** (1 year): % of stocks above their 50-DMA, with a 50% reference line, and Nifty with its 200-DMA on a second scale. Data: the store via `Factors.breadth_50`.
4. **Next-open orders:**
   - grouped by horizon, with tabs showing counts
   - row: status dot, strategy, horizon/evidence chips, side, symbol, qty × price = amount, stop (distance %), warnings (results-date chip, provisional chip)
   - orders from `not-working` strategies collapse into "1 order from strategies that are not working (comparison only)"
   - empty group text uses real reasons (`empty_reason`): "Regime filter on: no new buys while Nifty is below its 200-DMA" / "No entry signals today" / "Next rebalance 30 Oct".
5. **Alerts** (sorted danger → warn → info), each linking to its page. Generation rules are in §6.13.
6. **Strategy pulse:** the top 6 active strategies in leaderboard order: status, name, horizon letter, evidence, CAGR, edge vs avg stock, 12m return vs Nifty 500. Link: "All 13 strategies".
7. **Since last scan:** diff vs the previous scan with a *different* `data_date` (so intraday re-scans don't spam): status changes, regime flip, new orders, positions opened or closed.
8. **Top gainers / losers / volume spikes** (5 each) and **Results in the next 7 days** that matter: stocks you hold, model holdings, ranked stocks, or symbols with orders.
9. **Paper strip** (if the journal exists): one line per strategy, e.g. `Momentum paper +x.x% vs N500 +y.y% · 12 days · Too early to judge`.

```
┌ Overview ────────────────────────────────────────────────────── Prices 22 Oct 2026 · official close ─┐
│┌ MARKET REGIME ──────────────────────────────┐┌ NIFTY 50 ─────┐┌ NIFTY 500 ────┐┌ INDIA VIX ──────┐│
││ [v] BEARISH       Nifty −x.x% below 200-DMA ││ 22,687.65     ││ 21,696.55     ││ 15.76           ││
││ Strategies make no new buys in this regime  ││ −0.54%  ~~~   ││ −0.60%  ~~~   ││ +0.51%  ~~~     ││
││ and only manage existing positions.         │└───────────────┘└───────────────┘└─────────────────┘│
││ Breadth 13.2% above 50-DMA                  │┌ BREADTH · % ABOVE 50-DMA · 1Y ────────── Nifty/200D ┐│
││ A/D [■■■■■■■□□□□□□□□□□□□□□□□] 133 : 344     ││   ▁▂▅▇▆▄▃▂▁▁▂▃▅▆▇▆▅▃▂▁▁  ····· 50%                ││
│└─────────────────────────────────────────────┘└─────────────────────────────────────────────────────┘│
│┌ NEXT-OPEN ORDERS   [All 1] [Long-term 0] [Swing 1] [Intraday —]          sized for ₹5,00,000 ──────┐│
││ ● Earnings gap-up (PEAD)  SWING MODERATE  BUY  IGIL   141 × 353.20 = ₹49,801   stop 324.94 (−8.0%)  ││
││ Long-term: no orders. Regime filter on: no new buys while Nifty is below its 200-DMA.               ││
││                                                                               View all signals ->  ││
│└─────────────────────────────────────────────────────────────────────────────────────────────────────┘│
│┌ ALERTS (4) ──────────────────────────────────┐┌ STRATEGY PULSE ─────── CAGR · edge vs avg · 12m ──┐│
││ [warn] Fyers not logged in: Yahoo prices     ││ ● Momentum leaders   L STRONG  42.3%  +14.9  +14.5 ││
││ [warn] STLTECH (#1 momentum) reports today   ││ ● Earnings gap-up    S MOD     17.9%   −9.5  +18.1 ││
││ [info] 2 symbols no fresh price (BIRET …)    ││ ◐ Sector rotation    L MOD     30.9%   +3.5   +2.1 ││
││ [info] Backtests use today's list (bias)     ││ ○ Low volatility     L STRONG   9.5%  −18.0   −9.9 ││
│└──────────────────────────────────────────────┘└───────────────────────────── All 13 strategies -> ┘│
│┌ SINCE LAST SCAN ──────────┐┌ GAINERS ────────────┐┌ LOSERS ─────────────┐┌ RESULTS · 7 DAYS ─────┐│
││ low_vol mixed -> not work ││ IGIL  353.20 +10.0% ││ KEI 3,873.00 −8.45% ││ Today  STLTECH  M#1   ││
││ New: BUY IGIL (PEAD)      ││ …                   ││ …                   ││ …                     ││
│└───────────────────────────┘└─────────────────────┘└─────────────────────┘└───────────────────────┘│
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Strategies leaderboard `/strategies`

**[src] `GET /api/strategies?horizon=`**

- **Horizon tabs** with counts: `Long-term 6 · Swing 7 · Intraday 0 (soon)`. The default tab is `All`.
- **Filters:** status (Working / Mixed / Not working / Too new), evidence (STRONG…FOLKLORE), universe (Stocks / ETFs). View toggle: **Table** (default) / **Cards**.
- **Benchmark strip:** "Same period 21 Aug 2019 → 22 Oct 2026: Nifty 50 10.9%/yr · **Nifty 500 13.6%/yr** · Average stock in this list 27.5%/yr." Then the survivorship callout: "Gap 13.9 pts/yr ≈ survivorship bias. Judge strategies by **edge vs average stock**."
- **Table columns:**
  - Status
  - Strategy (name, plus horizon/evidence/ETF chips)
  - **CAGR** with an inline timing-range bar
  - After tax
  - **Edge vs avg stock** (stocks) or vs Nifty 50 (ETFs)
  - vs ETF alternative (factor index CAGR difference, when `factor_benchmark_name` is set)
  - Max DD
  - Sharpe
  - 12m (and Nifty 500 12m in the tooltip)
  - 6m
  - Win %
  - Trades
  - Exposure %
  - Equity spark (120 pts)
  - Orders (B/S counts)
- **Default sort** = the server order (working first, then evidence tier, then 12m return), identical to `daily.py`. Clicking a column header sorts by it. "Reset to evidence order" is always visible.
- **Not-working rows:** 60% opacity, but shown in full.
- **"Tested & rejected" section** (collapsed by default, under the table):
  - lifecycle `rejected` / `disabled` rows from B4, with CAGR, edge and a one-line reason ("Lost money after realistic costs").
  - Until B4 ships, show the catalogue entries with `source: 'catalogue'`, the text result from README, and the label "Not re-tested by this version".
- **Cards view:** 3 columns at 1280. Each card: status badge, name, chips, big CAGR + timing range, edge, spark, max DD, 12m, "n orders".

```
┌ Strategies ───────────────────── [All 13] [Long-term 6] [Swing 7] [Intraday · soon]   [Table|Cards] ┐
│ Status ▾  Evidence ▾  Universe ▾                               Sort: evidence order (reset)        │
│ Same period 21 Aug 2019 -> 22 Oct 2026: Nifty 50 10.9%/yr · Nifty 500 13.6%/yr · Avg stock 27.5%/yr │
│ [!] Avg stock beats Nifty 500 by 13.9 pts/yr = survivorship bias. Judge by EDGE VS AVG STOCK.       │
├──────────┬──────────────────────────────┬────────────────┬──────┬───────┬──────┬──────┬──────┬──────┤
│ STATUS   │ STRATEGY                     │ CAGR · TIMING  │ AFTER│ EDGE  │ MAX  │SHARPE│ 12M  │EQUITY│
│          │                              │                │ TAX  │vs AVG │ DD   │      │      │      │
├──────────┼──────────────────────────────┼────────────────┼──────┼───────┼──────┼──────┼──────┼──────┤
│ Working  │ Momentum leaders  L STRONG   │ 42.3% [─|──]   │ 38.7%│ +14.9 │ −32.4│ 1.62 │+14.5 │ ~~/  │
│ Working  │ Earnings gap-up   S MODERATE │ 17.9% [!range] │ 15.2%│  −9.5 │ −10.7│ 1.59 │+18.1 │ ~/   │
│ Working  │ Nifty trend (ETF) L MOD ETF  │ 12.1% [!range] │ 11.4%│ +1.1* │ −14.4│ 1.11 │ +4.0 │ _/   │
│ …        │                              │                │      │       │      │      │      │      │
│ Not work │ Low volatility    L STRONG   │  9.5% [|──]    │  9.2%│ −18.0 │ −27.9│ 0.70 │ −9.9 │ _/~  │
├──────────┴──────────────────────────────┴────────────────┴──────┴───────┴──────┴──────┴──────┴──────┤
│ v Tested & rejected (3)  RSI-2 pullback · Old textbook rules · Near 52-week high   (* vs Nifty 50)  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Strategy detail `/strategies/:key/:tab`

**[src] `GET /api/strategies/{key}`, `GET /api/strategies/{key}/curve?range=`, `GET /api/strategies/{key}/trades`**

**Header:**
- name, status badge + `status_reason`, chips (horizon, evidence, kind "Ranked portfolio · monthly" / "Signal-based", universe)
- "Next review 30 Oct" (rank strategies)
- paper link
- prev/next arrows

**KPI strip (10 tiles):**
- CAGR, with a timing-range sub-bar
- After-tax CAGR
- Edge vs avg stock
- vs ETF alternative (e.g. "Nifty200 Momentum 30 14.8%/yr → +27.5")
- Max drawdown
- Sharpe
- Volatility
- Win rate (with avg win / avg loss)
- Profit factor
- Exposure %, plus trades and average hold in the tooltip

**Tab Performance:**
- **Equity chart** (lightweight-charts, line series):
  - strategy (accent, 2 px) vs NIFTY 500 (muted dashed) vs Average stock (amber dotted) vs NIFTY 50 (faint dotted)
  - range 1Y / 3Y / All; Log / % / ₹ toggle (₹ = the `capital` growth path)
  - crosshair legend with values for all series
- **Drawdown chart** below with a synced time scale: area under 0 in loss tint, with the Nifty 500 drawdown as a thin muted line.
- **Windows table:** 3M / 6M / 12M / Full × Strategy / Nifty 50 / Nifty 500 / Avg stock / Factor index (return %, and in a second row max DD).
- **Yearly heatmap:** rows = Strategy, Nifty 500, Avg stock, Nifty 50; columns = years 2019 (partial, marked) → 2026 YTD. Cells show a diverging tint and the value.
- **Monthly heatmap** (strategy only): 12 columns × years, plus a year total column.
- **Timing-luck card:**
  - horizontal bar from low to high with a marker at base
  - text: "Same rules rebalanced 5/10/15 days earlier (or started a few weeks later): 40.6% to 50.3%/yr. Expect anything in this range."
  - if `consistent=false`, an amber note: "Range computed on older data; re-scan".
- **Validation card** (B8, P2): in-sample vs holdout CAGR, variants tried, expectancy 95% CI. Until B8: "Walk-forward check not run yet".

**Tab Trades:**
- filters: winners / losers / exit reason; search by symbol
- histogram of trade returns (inline SVG, 2% bins, green/red)
- exit-reason table (count, avg return)
- trades table: symbol, bought, buy ₹, sold, sell ₹, qty, P&L ₹, return %, days, reason; paginated at 50
- `source='recent_only'` shows "Showing the last 25 trades. Full history after the next scan."

**Tab Holdings & orders:**
- orders for the next open (same component as Signals)
- model holdings: symbol, bought, buy ₹, now ₹, return %, stop, days, weight %, results date
- current ranking (rank strategies): #, symbol, sector, score, 6m, 12m, RS, results, held badge

**Tab Rules & evidence:**
- plain-language rules (from `rules.plain_rules`)
- parameter table (effective config values, with a link to Settings › Strategies)
- costs used (round trip ≈ 0.61%)
- evidence card: grade, catalogue ID (L1, S6…), summary, sources (links open in a new tab), failure modes, "What to expect" (e.g. "30–40% drops; 1–2 years of lagging")

**Tab Paper:** the paper detail for this key (§3.8).

```
┌ < Strategies / Momentum leaders                                         [<] [>]  Open paper -> ┐
│ [Working now] Beat both Nifty and the average stock over the last 12 and 6 months.            │
│ LONG-TERM · STRONG · Ranked portfolio, monthly · Stocks · Next review 30 Oct 2026            │
├────────┬─────────┬─────────┬─────────┬────────┬───────┬───────┬────────┬────────┬───────────┤
│ CAGR   │AFTER TAX│EDGE AVG │ vs ETF  │ MAX DD │SHARPE │ VOL   │ WIN %  │ PF     │ EXPOSURE  │
│ 42.3%  │ 38.7%   │ +14.9   │ +27.5   │ −32.4% │ 1.62  │ 23.6% │ 47.4%  │ 2.26   │ 86.6%     │
│[40.6─|─50.3]│    │         │N200M30  │        │       │       │+61/−13 │        │215 trades │
├────────┴─────────┴─────────┴─────────┴────────┴───────┴───────┴────────┴────────┴───────────┤
│ [Performance] [Trades] [Holdings & orders] [Rules & evidence] [Paper]                         │
│┌ GROWTH OF ₹1 ───────────────────── [1Y][3Y][All]  [Log|%|₹]  ── Strategy ·· N500 ·· Avg ·· N50┐│
││                                                       ____/‾‾\__/                            ││
││                                       ______/‾‾‾‾‾‾‾‾/                                       ││
││  ________/‾‾‾‾‾‾\_______/‾‾‾‾‾‾‾‾‾‾‾                    ·········· Avg stock                  ││
│├ DRAWDOWN ────────────────────────────────────────────────────────────────────────────────────┤│
││ ▔▔▔\▁▁/▔▔▔▔▔▔\▁▁▁▁▁/▔▔▔▔▔▔▔▔▔▔\▁▁▁▁▁/▔▔▔                         −32.4% (worst)            ││
│└──────────────────────────────────────────────────────────────────────────────────────────────┘│
│┌ YEARLY ─────────────────────────────────────────────┐┌ TIMING LUCK ───────────────────────────┐│
││          2019* 2020  2021  2022  2023  2024 2025 26 ││ 40.6% ├──────●─────────────┤ 50.3%      ││
││ Strategy +10.9 +92.5 +99.8 −3.4 +102.6 +38.2 −16.8 ││ base 42.3%. Same rules rebalanced 5-15 ││
││ Nifty500  …                                         ││ days earlier. Expect anything here.    ││
││ Avg stk   …                                         │└────────────────────────────────────────┘│
│└─────────────────────────────────────────────────────┘┌ WINDOWS: 3M  6M  12M  FULL ────────────┐│
│                                                       │ Strategy  …   …  +14.5  +42.3/yr       ││
│                                                       │ Nifty 500 …   …   −6.4  +13.6/yr       ││
│                                                       └────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.4 Signals `/signals`

**[src] `GET /api/signals?horizon=&allocations=`**

- **Header line:** "Orders for the next market open · sized for ₹5,00,000 · based on prices of 22 Oct (official close)". When live: an amber "PROVISIONAL: based on today's still-forming candle; re-check after 3:30 PM, final after ~7 PM."
- **Allocation bar:**
  - stacked horizontal bar of `allocations` (config); each segment shows the strategy name and %
  - "Edit" opens Settings › Capital
  - with no allocations: a warning "Each strategy is sized on your full capital. Following more than one? Set allocations so they share ₹5,00,000."
  - what-if: a draggable % per strategy (session only, passed as `?allocations=`)
- **Horizon tabs:** Long-term / Swing / Intraday (disabled).
- **Group per strategy:**
  - header: status, name, chips, `max_positions` × `per_position`, next review
  - table columns: Side (BUY green pill / SELL red pill), Symbol + company, Sector, Last ₹, Qty, Amount ₹, Stop ₹, Stop distance %, Risk ₹ (= qty × (price − stop)), Results (chip "in 0 d" red / "in 5 d" amber), Why, Flags (`provisional`, `below min position`, `you hold 120`)
  - row actions: Chart, Copy order (`BUY IGIL 141 @ MKT, SL 324.94` to clipboard), Open in Fyers web (plain link to `https://trade.fyers.in`, no deep-link order placement)
- **Footer totals:** buy amount ₹, cash freed by sells, total risk ₹ at stops, and number of results warnings.
- **Comparison-only group:** orders from not-working strategies, collapsed and greyed.
- **Empty states** use `empty_reason`.

```
┌ Signals ──── Orders for the next market open · sized for ₹5,00,000 · prices 22 Oct (official) ──┐
│ ALLOCATION [ momentum 100% ·································································· ] Edit │
│ [warn] Each strategy is sized on your full capital. Following more than one? Set allocations.    │
│ [Long-term 0] [Swing 1] [Intraday · soon]                                                        │
│┌ ● Earnings gap-up (PEAD) · SWING · MODERATE · up to 10 × ₹50,000 ─────────────────────────────┐│
││ SIDE SYMBOL               SECTOR    LAST ₹  QTY  AMOUNT ₹  STOP ₹  DIST  RISK ₹  RESULTS  WHY   ││
││ BUY  IGIL                 Services  353.20  141   49,801  324.94 −8.0%  3,985   —     entry   ││
││      Intl Gemological Inst.                                                 [Chart][Copy]     ││
│└───────────────────────────────────────────────────────────────────────────────────────────────┘│
│┌ ● Momentum leaders · LONG-TERM · next review 30 Oct ──────────────────────────────────────────┐│
││ No orders. Regime filter on: no new buys while Nifty is below its 200-DMA (holding 1 of 15).  ││
│└───────────────────────────────────────────────────────────────────────────────────────────────┘│
│ Totals: buy ₹49,801 · sells 0 · risk at stops ₹3,985 · results warnings 0                        │
│ > 0 orders from strategies that are not working (comparison only)                                │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.5 Screener / Rankings `/screener`

**[src] `GET /api/screener?preset=`, `GET /api/sparklines?symbols=`**

- **Presets (segmented):**
  - Momentum (NSE score)
  - Relative strength (RS 1–99)
  - Near 52-week high
  - Low volatility
  - Volume spike (≥ 3×)
  - Above 200-DMA
  - All
- **Filters:** industry multi-select, min turnover ₹cr (default from config), "only stocks in a model portfolio", "only stocks with results within 7 days". Column chooser; CSV export.
- **Columns (default, Momentum preset):** #, Symbol / company, Sector, Price, 1D %, 1M %, 3M %, 6M %, 12M %, RS, Score, Vol %, From 52w high %, 60-day spark, Results, In models (chips).
- Row click → Chart. Top-40 rows from strategy rankings carry an "in portfolio" dot.
- `source='store'` (B2 missing) shows a muted note: "Computed from stored closes of 22 Oct; today's live candle not included."

```
┌ Screener ─ [Momentum][Rel. strength][Near 52w high][Low vol][Vol spike][>200-DMA][All]  CSV  Cols ┐
│ Industry ▾   Turnover ≥ ₹5 cr   [ ] in a model   [ ] results ≤ 7 d        478 stocks · 22 Oct     │
├───┬──────────────────────┬──────────┬────────┬──────┬──────┬───────┬──────┬────┬──────┬──────────┤
│ # │ SYMBOL               │ SECTOR   │ PRICE  │  1D  │  6M  │  12M  │  RS  │SCORE│ 52wH │ 60D      │
├───┼──────────────────────┼──────────┼────────┼──────┼──────┼───────┼──────┼────┼──────┼──────────┤
│ 1 │ STLTECH  [res today] │ Telecom  │ 800.85 │  …   │+187.6│ +611.0│  99  │7.71│  …   │ ▁▂▃▅▇    │
│ 2 │ …                    │          │        │      │      │       │      │    │      │          │
└───┴──────────────────────┴──────────┴────────┴──────┴──────┴───────┴──────┴────┴──────┴──────────┘
```

### 3.6 Chart `/chart/:symbol`

**[src] `GET /api/chart/{symbol}?tf=&range=&indicators=&strategies=`, `GET /api/stock/{symbol}`**

**Toolbar:**
- symbol picker (palette), timeframe `1D | 1W | 5m (soon)`, range `3M 6M 1Y 2Y 5Y Max`
- Indicators menu (checkboxes): SMA 20/50/200 (on), EMA 21, Bollinger 20,2, Volume (on), RSI 14 (on), MACD
- Strategy markers menu: all strategies that ever traded this symbol (from B1) plus "None"
- Log scale toggle; screenshot (`chart.takeScreenshot()` → PNG download)

**Chart (lightweight-charts v5, one chart, panes):**
- pane 0: candles + MAs + BB; volume as an overlay histogram (`priceScaleId: ''`, `scaleMargins {top: 0.8, bottom: 0}`), up/down tinted at 45% alpha
- pane 1: RSI 14 (height 120) with 30/70 dashed lines
- pane 2: MACD (optional)
- markers (`createSeriesMarkers`):
  - entry ▲ below the bar (profit color, text `B · MOM`)
  - exit ▼ above the bar (text `S +28.5%`, loss color if negative)
  - open model entry (circle)
  - corporate action (square, `Bonus ×0.5`)
  - past results days (small circle, muted)
- price lines: model entry and stop, order stop (dashed loss), your buy price / stop / target (from holdings), 52w high/low (faint)
- **legend top-left:** `IGIL · NSE · 1D   O 340.10 H 360.00 L 338.50 C 353.20 +10.00%   Vol 14.6× avg`, updated on crosshair move. Then a line of indicator values.
- Corporate actions note: "Prices adjusted for splits/bonuses/demergers using NSE data".

**Right panel (320 px, collapsible):**
- price + change
- 52-week range bar with marker
- RS, momentum rank, 1M/3M/6M/12M returns, turnover, delivery %
- results date chip
- "In strategies" list: role holding / order / ranked #n, linking to the strategy
- "Your holding": qty, avg, P&L, alerts
- corporate actions list

```
┌ Chart ─ [IGIL v] Intl Gemological Inst. · Services   [1D|1W|5m·soon] [3M 6M 1Y 2Y 5Y Max] Ind▾ Str▾ Log ┐
│┌───────────────────────────────────────────────────────────────────────┐┌ IGIL ────────────────────┐│
││ IGIL 1D  O 340.10 H 360.00 L 338.50 C 353.20 +10.00%  Vol 14.6× avg   ││ 353.20   +10.00%         ││
││ SMA20 … SMA50 … SMA200 …                                              ││ 52w [──────●───]         ││
││                                    ┃┃                    ▲B·PEAD      ││ RS 9x · Mom rank …       ││
││                    ┃┃ ┃┃┃  ┃┃┃┃ ┃┃┃┃┃┃┃┃  ~~~~ SMA50                  ││ 1M … 3M … 6M … 12M …     ││
││  ┃┃┃┃┃ ┃┃┃┃┃┃┃┃┃┃┃┃                         ── stop 324.94 (order)    ││ Results: —               ││
││ ▂▃▂▅▂▃▂▂▃▂▂▃▅▂▃▂▂▃▅▇ volume                                           ││ IN STRATEGIES            ││
│├ RSI 14 ───────────────────────────────────────────────────────────────┤│ ● Earnings gap: order BUY││
││ ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾ 70 ··· /\/\__/\/‾‾ ··· 30                  ││ YOUR HOLDING: none       ││
│└───────────────────────────────────────────────────────────────────────┘└──────────────────────────┘│
│ Daily candles from the local store, split/bonus/demerger adjusted with NSE data.   (TradingView logo) │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.7 Portfolio `/portfolio`

**[src] `GET /api/holdings`, `PUT /api/holdings`, `POST /api/holdings/import/fyers`, `POST /api/scan {update:false}`**

- **KPI strip:** Invested ₹, Value ₹, P&L ₹ / %, Today ₹, Holdings n, Danger n, Watch n.
- **Stale banner** (if `health_stale`): "Holdings changed after the last scan, so alerts are out of date." Button: [Re-check now (no download, ~15 s)].
- **Alerts list:** per holding, colored by `level`. danger = stop-loss hit / below 200-DMA with the stop hit; good = target reached; watch = below 50/200-DMA, no fresh price, results soon. The full alert text comes from the scan.
- **Holdings table:** Symbol / company, Qty, Avg ₹, LTP ₹, Today %, P&L ₹, P&L %, Stop ₹ (distance %), Target ₹ (distance %), Momentum rank, RS, Results, In models, Level pill. Row → Chart with the your-buy/stop/target lines.
- **Allocation donut** is NOT included (sector data is too coarse and adds little). Instead: "Weight by sector" horizontal bars from `industry`.
- **Editor (drawer, right, 560 px):**
  - editable grid with columns Symbol (autocomplete from `/api/symbols`), Qty, Buy price ₹, Buy date (date picker; helper "needed to adjust for splits/bonuses after you bought"), Stop %, Target % (placeholders show the defaults 8 / 20)
  - inline validation: unknown symbol, negative qty, future date
  - buttons: Save · Cancel · Import from Fyers
- **Import from Fyers:**
  - calls the import endpoint → preview dialog listing rows with a **Replace / Merge** choice and a note "Fyers cost prices are already split/bonus adjusted; buy date unknown"
  - Save → PUT
  - not logged in → the button is disabled with the hint "Log in to Fyers first".

```
┌ Portfolio ───────────────────────────────────────────────────────── [Edit holdings] [Import Fyers] ┐
│ INVESTED ₹x · VALUE ₹x · P&L +₹x (+x.x%) · TODAY −₹x · 6 holdings · 1 danger · 2 watch          │
│ [!] Holdings changed after the last scan. [Re-check now · no download · ~15 s]                     │
│┌ ALERTS ─────────────────────────────────────────────────────────────────────────────────────────┐│
││ DANGER  XYZ  STOP-LOSS HIT: down more than 8% from your buy price | Below its 200-day average   ││
││ WATCH   ABC  Quarterly results on 28 Oct, expect a big move either way                         ││
│└─────────────────────────────────────────────────────────────────────────────────────────────────┘│
│ SYMBOL   QTY   AVG ₹     LTP ₹    TODAY   P&L ₹     P&L %   STOP ₹ (dist)   TARGET ₹  MOM# RS LVL │
│ …                                                                                                  │
│ Empty: "Add your holdings to get stop-loss, target, trend and results alerts."                     │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.8 Paper trading `/paper`

**[src] `GET /api/paper`, `GET /api/paper/{key}`**

- **Intro** (one line, collapsible): "Live proof: every completed-day scan journals orders; fills at the next official open with full charges. Nothing here can be fitted to the past."
- **List table:**
  - Strategy, Since, Days
  - Paper %, P&L ₹
  - Nifty 50 %, Nifty 500 %
  - Backtest expected % (with range)
  - Gap vs N500
  - Noise band ±%
  - Verdict pill (`level`): neutral "Too early" / bad "Behind backtest" / good "Ahead (probably luck)"
  - Holding n, Closed n
- **Detail:**
  - KPI tiles: Paper value ₹ (+%), N500 same days, Backtest expected, Worst drop, Charges + slippage ₹
  - verdict sentence (server text)
  - an "evidence meter": a horizontal bar of the gap vs N500 with the expected value marker and a ±noise band. This visualises `excess_pct`, `expected_excess_pct`, `haircut_excess_pct` and `noise_pct`.
  - equity chart (₹): Paper vs NIFTY 50 vs NIFTY 500
  - pending orders, open positions (fill ₹, qty, now ₹, value, P&L, return, stop, days, via), closed trades
  - footer: "Journal: n scan days, first → last; prices to …; recomputed from journal + stored prices on every view."
- **Empty state** (no journal): "The journal starts automatically with the next scan of a completed trading day (after ~6 PM or before 9:15 AM). Intraday scans are never journaled."

### 3.9 Market `/market/:tab`

- **Movers:** gainers / losers / volume spikes. Each row has symbol, company, sector, price, change %, volume × and a spark. [src] `GET /api/market/movers`.
- **Sectors:**
  - (a) NSE sector indices table (`indices.sectors`, 21 rows): rank, name, last, 1D, 1M, 3M, 6M, 1Y, CAGR, max DD, above 50-DMA dot. A bar visual of 3M returns sorted, e.g. "Nifty IT +12.4% … Nifty MNC −13.4%".
  - (b) Universe industries (20, equal-weight, from the store): members, breadth % above 50-DMA, A/D today, 1D/1W/1M/3M/6M, top 3 leaders by 3M.
  - [src] `GET /api/market/sectors`.
- **Factor indices:** the `indices.factors` gallery (13: Nifty 50, Nifty 500, Momentum 30/50, Alpha 50, Low Vol 30, Quality 30, Value 30, EW, Midcap 150, Smallcap 250, 1D Rate).
  - Title: "Investable alternatives (index funds / ETFs exist for most): real NSE indices, no survivorship bias."
  - Columns: CAGR, max DD, 1Y, since. [src] `GET /api/market/factors`.
- **Results calendar:**
  - next 14 days grouped by day; each event: symbol, company, sector, purpose
  - relevance chips: You hold · In model (strategy) · Order · Ranked #n
  - toggle "Only relevant to me"
  - source note `results_note`. [src] `GET /api/market/results`.
- **Breadth:** 1Y/3Y chart of % above 50-DMA, A/D line (cumulative), Nifty vs 200-DMA, VIX. [src] `GET /api/market/breadth`.

### 3.10 Intraday `/intraday` (honest placeholder, then real)

**[src] `GET /api/intraday/status`** (always 200).

- **Before the intraday engine exists:**
  - status card "Intraday research is not live yet": phase, data coverage (interval, symbols, first → last, days), next step
  - **"Read this first" card** (SEBI, July 2024, FY23):
    - 71% of individual intraday traders lost money; 80% of those with more than 500 trades a year lost money
    - trading costs made loss-makers' losses 57% larger and took 19% of profit-makers' profits
  - market structure card: MIS auto square-off 15:05 (F&O stocks) / 15:20 (others); closing auction session since 3 Aug 2026
  - planned strategies list from the catalogue (I1–I8), each with an evidence grade and "not tested yet"
  - the intraday cost preview (₹1,00,000 round trip ≈ ₹82.7 + slippage)
- **After the engine exists:**
  - the same leaderboard / detail components with `horizon='intraday'`, plus intraday extras: trades/day, avg minutes held, % auto-squared, cost share of gross P&L, results by day type
  - a live session board: signals with time, entry, stop, target, status, square-off-by

### 3.11 Data & Settings `/settings/:section`

- **Data health:**
  - store generation, date span, symbols, trading days, size
  - NSE status, complete-upto
  - failed / stale symbols, errors
  - last 20 corporate-action adjustments (symbol, ex-date, factor, reason)
  - index history last date, results calendar note, universe note, PIT status, journal status
  - log tail (monospace, last 200 lines, filter ERROR)
- **Fyers:**
  - status (configured, masked client id, plan, token created, logged in today, verified name)
  - **Log in** button (paste flow, §6.9)
  - "Open login window (legacy)" button
  - help text on redirect URL / callback mode
- **Scan:** Run full scan / Re-check without download; progress with message stream; last 60 scans list (time, elapsed, data date, live); "Scheduled scans: 08:30, 15:40 and 19:15 weekdays (setup_schedule.ps1)".
- **Capital & allocations:** capital, min position, allocation % per active strategy (sum ≤ 100, "cash" remainder shown).
- **Strategies:** enable/disable toggles and parameter forms (numbers with min/max) for each key; "needs re-scan" badge after save.
- **Costs & tax:** the cost fields with a live breakdown table for an order value (`/api/costs/preview`); tax fields; the intraday profile shown read-only (P3).
- **Filters:** min price, min turnover, universe, lookback days, results warn days, movers count.
- **Appearance:**
  - theme (System / Dark / Light), density (Comfortable / Compact)
  - colour-blind safe mode (blue/orange gains/losses)
  - number style (₹ compact L/Cr on KPIs on/off)
  - stored in localStorage
- **About & disclaimer:**
  - the full disclaimer
  - "Sharing these signals as recommendations with others requires SEBI Research Analyst registration."
  - data sources, versions, licenses (lightweight-charts Apache-2.0 attribution)

### 3.12 Mobile (< 768 px)

- Bottom tab bar: Overview · Signals · Strategies · Portfolio · More (Chart, Screener, Paper, Market, Intraday, Settings).
- Top bar shrinks to: logo, regime pill, freshness pill, scan icon.
- Tables become list rows: line 1 `SYMBOL · value · colored change`, line 2 muted secondary fields. Tap opens a bottom sheet with full row detail.
- Charts take the full width at 300 px tall; the RSI pane is off by default; the right panel moves below the chart.
- KPI strips scroll horizontally with snap.
- Usable at 375 px with a 16 px gutter and no horizontal page scroll; only table regions scroll inside their card.

```
┌ 375 px ─────────────────────────┐
│ QD  [BEARISH] [EOD 22 Oct] [Sc] │
│┌ REGIME ────────────────────────┐│
││ BEARISH · below 200-DMA        ││
││ Breadth 13.2% · A/D 133:344    ││
│└────────────────────────────────┘│
│ [N50 22,687 −0.54%][N500 …][VIX] │  <- swipe
│┌ NEXT-OPEN ORDERS (1) ──────────┐│
││ BUY IGIL  141 × 353.20         ││
││ PEAD · stop 324.94 (−8.0%)     ││
│└────────────────────────────────┘│
│┌ ALERTS (4) ────────────────────┐│
│└────────────────────────────────┘│
├──────────────────────────────────┤
│ Overview Signals Strat Port More │
└──────────────────────────────────┘
```

---

## 4. Visual system

### 4.1 Colour tokens

These are CSS variables holding RGB triplets, consumed in Tailwind as `rgb(var(--x) / <alpha-value>)`. This extends the scaffold's `src/index.css`. Dark is the default. Light is set with `<html class="light">`. Colour-blind mode is set with `<html data-cvd="on">`.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0B0E14` | `#F6F7F9` | page |
| `--panel` | `#11151D` | `#FFFFFF` | cards, rail, top bar |
| `--raised` | `#181D27` | `#F1F3F6` | table header, hover, inputs |
| `--line` | `#262C38` | `#E2E6EC` | borders, grid |
| `--line-strong` | `#343C4B` | `#CBD1DA` | focused borders, separators |
| `--fg` | `#E6E9EF` | `#0F172A` | primary text |
| `--muted` | `#9AA3B2` | `#4B5563` | secondary text |
| `--faint` | `#6B7385` | `#7A8392` | axis labels, placeholders only (≥ 3:1) |
| `--accent` | `#4C8DF6` | `#1F5FD6` | links, focus, primary series |
| `--accent-strong` | `#2F6FE0` | `#1F5FD6` | filled buttons (white text) |
| `--profit` | `#26C281` | `#0F7B4A` | gains, BUY, working |
| `--loss` | `#F0616D` | `#C5283D` | losses, SELL, not working, danger |
| `--warn` | `#F5A524` | `#A15C00` | provisional, mixed, results-soon |
| `--info` | `#38BDF8` | `#0369A1` | info alerts |
| `--violet` | `#A78BFA` | `#6D28D9` | SMA200, factor-index series |
| `--candle-up` / `--candle-down` | `#26C281` / `#F0616D` | `#149E62` / `#D93A4F` | candles (non-text, ≥ 3:1) |
| CVD `--profit` / `--loss` | `#3B9EFF` / `#FF9F40` | `#1A63BE` / `#A84E00` | colour-blind-safe mode |

**Measured WCAG contrast** (text on `--panel`):

| Token | Dark | Light |
|---|---|---|
| fg | 15.0 | 17.9 |
| muted | 7.2 | 7.6 |
| profit | 7.9 | 5.3 |
| loss | 5.8 | 5.6 |
| warn | 9.0 | 5.2 |
| accent | 5.6 | 5.7 |
| faint | 3.8 | 3.8 (non-body only) |

White on `--accent-strong` is 4.7 (dark) and 5.7 (light).

Rules:
- **Colour never carries meaning alone.** Signed numbers always show `+` or `−` (U+2212), status badges have icons, and BUY/SELL are text pills.
- Green/red are used **only** for signed returns/P&L, BUY/SELL, and status. Risk metrics (max DD, volatility) are neutral `--fg`. Red appears only in the drawdown chart itself.
- **Tints for badges:** background is the token at 12% alpha (dark) or 10% (light); text is the token at 100%.
- **Heatmap:** a diverging scale of 7 buckets: loss 40/25/12%, neutral raised, profit 12/25/40% alpha. Clamp ±40% (yearly) / ±10% (monthly). The value is always printed in the cell.

### 4.2 Status, evidence and horizon vocabulary

| Value | Label | Style |
|---|---|---|
| status `working` | Working now | profit tint, `CheckCircle2` |
| `mixed` | Mixed | warn tint, `CircleDashed` |
| `not-working` | Not working | loss tint, `XCircle`; the row is at 60% opacity |
| `unknown` | Too new | faint, `Clock` |
| lifecycle `rejected` | Tested & rejected | muted, `Ban` |
| `disabled` | Off | muted, `PowerOff` |
| evidence `STRONG` | Strong evidence | filled accent chip |
| `MODERATE` | Moderate | accent outline |
| `WEAK` | Weak | muted outline |
| `FOLKLORE` | Folklore | dashed muted outline |
| `EXPERIMENTAL` | Experimental | warn outline, `FlaskConical` |
| horizon `longterm` | Long-term (L) | `CalendarRange` |
| `swing` | Swing (S) | `Activity` |
| `intraday` | Intraday (I) | `Timer` |

The verdict wording on the paper page follows the catalogue: Works / Mixed / Fails / Not enough data.

### 4.3 Typography

- **Inter Variable**, self-hosted via `@fontsource-variable/inter@5.3.0`. The app must work offline; drop the Google Fonts `<link>` in `index.html`.
- **JetBrains Mono** via `@fontsource/jetbrains-mono@5.3.0`, for logs/code only.
- **Numbers:** class `.num` = `font-variant-numeric: tabular-nums; font-feature-settings: 'tnum' 1, 'zero' 1;`. Use it on every price, qty, % and ₹ cell, KPI and axis.

| Role | Size / line height | Weight | Notes |
|---|---|---|---|
| Page title | 20/28 | 600 | |
| Card title | 13/20 | 600 | uppercase off; muted subtitle 12 |
| Table header | 11/16 | 600 | uppercase, letter-spacing 0.04em, muted |
| Table body | 13/20 | 400 (symbol 600) | compact density 12/18 |
| Body / prose | 14/22 | 400 | max width 72ch |
| KPI value | 24/30 | 600 | `.num` (28/34 hero on Overview) |
| KPI label | 11/16 | 500 | muted |
| Micro (chips, status bar) | 11/16 | 500 | |

### 4.4 Spacing, density, layout

- 4 px base. Card padding 16 (compact 12). Grid gap 12 (≥ 1536 px: 16). Page gutter 20 desktop, 16 mobile. Radii: 6 controls, 8 cards, 999 pills. Borders (1 px `--line`) instead of shadows; popovers/menus get `0 8px 24px rgb(0 0 0 / .35)`.
- Rows are 32 px (compact 28). KPI tiles are 72 px tall.
- Breakpoints (Tailwind defaults): `md 768`, `lg 1024`, `xl 1280` (**design target**), `2xl 1536`.
  - 12-column grid at xl and above; the rail is collapsed below 1440.
  - lg: two-column cards become one; tables scroll horizontally inside cards with a sticky first column.
  - md and below: the mobile spec in §3.12.
- Motion: 120 ms ease-out for hover/press, 200 ms for drawers. No number "count-up" animations. Respect `prefers-reduced-motion`.

### 4.5 Tables (one `DataTable` component on TanStack Table 8)

- Sticky header (`--raised`); numeric columns right-aligned; text left; the first column is sticky with symbol (600) and the company below it (muted 12 px, comfortable density only).
- Sort on header click: three states (asc / desc / none) with an indicator; multi-sort with Shift.
- Hover → `--raised`. Selected row: accent 8% background plus a 2 px left accent bar.
- Null/NaN shows `—` in `--faint`. Signed columns are coloured and always show their sign.
- Column visibility menu (persisted per table id in localStorage). CSV export (client side; raw numbers, not formatted).
- Pagination at > 100 rows (trades). No virtualization needed: the largest table is about 500 rows (screener) and renders fine.
- Inline sparkline cell 80×24 SVG: stroke `--muted`, last point coloured by sign of the period change.
- Keyboard: `j/k`, `Enter`, `/`.

### 4.6 Charts (lightweight-charts v5; inline SVG for small things)

**Theme object** built from CSS variables at runtime (`getComputedStyle`), re-applied with `chart.applyOptions` on theme change:
- `layout.background = panel`, `textColor = muted`, `fontFamily = Inter`
- `grid.vertLines/horzLines = line @ 50%`
- crosshair `--line-strong`; price/time scale borders `--line`

**Series palette:**

| Series | Style |
|---|---|
| Strategy | `--accent`, 2 px |
| Nifty 500 | `--muted`, 1.5 px, dashed |
| Average stock | `--warn`, dotted |
| Nifty 50 | `--faint`, dotted |
| Factor index | `--violet`, 1.5 px |
| SMA20 | `--warn` |
| SMA50 | `--accent` |
| SMA200 | `--violet` |
| EMA21 | `--info` |
| Bollinger | `--muted`, dashed |
| RSI | `--accent` |

At most 5 series per chart.

**Time handling:**
- Daily: `time` = `'YYYY-MM-DD'` strings (BusinessDay), so there is no timezone shift.
- Intraday: `UTCTimestamp` of the **IST wall-clock treated as UTC** (epoch of IST + 19800 s). The axis then reads 09:15–15:30 without timezone code. Document this in `chartTheme.ts`.

**Other rules:**
- Heatmaps, timing bar, histogram and sparklines are hand-rolled SVG/CSS grid (no library).
- Keep the TradingView attribution logo on (`layout.attributionLogo: true`) to satisfy the Apache-2.0 NOTICE.

### 4.7 Number and date formatting (`src/lib/format.ts`)

```ts
export const MINUS = '\u2212', DASH = '\u2014';
const nf = (min: number, max: number) => new Intl.NumberFormat('en-IN', { minimumFractionDigits: min, maximumFractionDigits: max });
const F2 = nf(2, 2), F1 = nf(1, 1), F0 = nf(0, 0);
const ok = (x: number | null | undefined): x is number => x != null && Number.isFinite(x);
const sgn = (s: string) => s.replace('-', MINUS);

export const price  = (x?: number | null) => ok(x) ? sgn(F2.format(x)) : DASH;                // 1,23,456.78
export const qty    = (x?: number | null) => ok(x) ? F0.format(x) : DASH;                      // 4,866
export function money(x?: number | null, o: { dp?: 0 | 2; signed?: boolean } = {}) {          // ₹1,23,457 / +₹12,340 / −₹5,000
  if (!ok(x)) return DASH;
  const s = (o.dp === 2 ? F2 : F0).format(Math.abs(x));
  return `${x < 0 ? MINUS : o.signed && x > 0 ? '+' : ''}₹${s}`;
}
export function moneyCompact(x?: number | null) {                                              // ₹5.00 L, ₹1.25 Cr (KPIs only)
  if (!ok(x)) return DASH;
  const a = Math.abs(x), neg = x < 0 ? MINUS : '';
  if (a >= 1e7) return `${neg}₹${F2.format(a / 1e7)} Cr`;
  if (a >= 1e5) return `${neg}₹${F2.format(a / 1e5)} L`;
  return money(x);
}
export function pct(x?: number | null, o: { dp?: number; signed?: boolean } = {}) {            // +12.4% / −3.20%
  if (!ok(x)) return DASH;
  const dp = o.dp ?? 1, signed = o.signed ?? true;
  const s = nf(dp, dp).format(Math.abs(x));
  return `${x < 0 ? MINUS : signed && x > 0 ? '+' : ''}${s}%`;
}
export const pts   = (x?: number | null) => ok(x) ? `${x < 0 ? MINUS : x > 0 ? '+' : ''}${F1.format(Math.abs(x))}` : DASH; // edge in % points
export const ratio = (x?: number | null) => ok(x) ? F2.format(x) : DASH;                      // Sharpe 1.62, PF 2.26
export const tone  = (x?: number | null): 'profit' | 'loss' | 'flat' => !ok(x) || x === 0 ? 'flat' : x > 0 ? 'profit' : 'loss';
// Dates: parse 'YYYY-MM-DD' manually (never new Date('YYYY-MM-DD'), which is UTC); display '22 Oct 2026' / '22 Oct';
// times: '09:18 IST' via Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
// relative: '9 h ago' with the absolute time in a tooltip.
```

Conventions:
- Prices always show 2 decimals. Amounts are whole rupees. Percent: 1 decimal by default, 2 for daily changes and index moves.
- Dense tables put the ₹ in the column header (`Price ₹`); KPI tiles put it in the value.

### 4.8 States

| State | Treatment |
|---|---|
| First run (no `latest.json`) | Full-page onboarding card: "No scan yet". [Run first scan] (first run ≈ 4 min: downloads 8 years and repairs with NSE data). Optional "Log in to Fyers for real-time prices". |
| Loading (first load) | Skeletons that match the final layout (KPI blocks, 8 table rows, chart frame with axes). No full-page spinners. |
| Refetching | Keep the previous data (`placeholderData: keepPreviousData`); show a 2 px accent progress bar under the top bar. |
| Scan running | Scan button shows a ring and %; status message in a popover; pages stay usable; on finish everything refetches and a toast says "Scan done in 11.6 s · 1 new order". |
| Error (endpoint) | Inline card: icon, `message`, `hint`, [Retry], plus a collapsible `code`/details. Never a blank card. |
| Server unreachable | Global red banner: "Can't reach the local server (127.0.0.1:8600). Is 3_dashboard.bat still running?" Auto-retries with backoff. |
| Stale data | Amber pill `STALE · data 21 Oct` when `as_of.stale`. Overview banner: "Prices are from 21 Oct. Run a scan." |
| Provisional | Amber striped `PROVISIONAL` chip on every order row; banner text from §3.4. |
| Feature unavailable (501) | Muted card explaining what is missing and how it gets built (e.g. "Full trade history appears after the next scan (needs trades.parquet)"). |
| Empty lists | Real reason text from the API (`empty_reason`), never a bare "No data". |
| Disclaimer | Status bar text, a one-time first-run notice (stored in localStorage), and the full text in Settings › About. |

### 4.9 Copy rules

- Say "backtest", "model portfolio" and "orders for the next open". Never "tips", "calls", "recommendation" or "guaranteed".
- Every backtest number has the survivorship context nearby while `backtest_universe='current_list'`.
- Use plain English with the abbreviation in a tooltip: "Worst drop (max drawdown)", "Yearly return (CAGR)".

---

## 5. Tech stack, layout, workflow

### 5.1 Versions (exact pins; `npm ci` from the lockfile)

| Package | Version | Why |
|---|---|---|
| vite | 6.4.5 | already installed; mature 6.x line (Vite 7 brings nothing we need) |
| @vitejs/plugin-react | 4.7.0 | installed |
| react, react-dom | **18.3.1** | per the brief. **The scaffold currently has 19.3.1: re-pin to 18.3.1** (all libraries below support 18). |
| @types/react / @types/react-dom | 18.3.31 / 18.3.7 | match React 18 |
| typescript | 5.8.3 | installed |
| tailwindcss / postcss / autoprefixer | 3.4.17 / 8.4.49 / 10.4.20 | installed; the CSS-variable token setup is already written for v3 |
| @tanstack/react-query | 5.62.0 | installed; stable v5 API |
| @tanstack/react-table | **8.21.3** | final v8 (Apr 2025). Do not use v9 (Aug 2026, new API). |
| lightweight-charts | **5.2.1** | see 5.2 |
| lucide-react | 0.468.0 | installed |
| react-router-dom | 6.28.0 | installed; data router, no v7 migration |
| cmdk | 1.1.1 | command palette (Mar 2025, stable) |
| clsx | 2.1.1 | installed |
| @fontsource-variable/inter, @fontsource/jetbrains-mono | 5.3.0, 5.3.0 | self-hosted fonts (offline) |
| openapi-typescript (dev) | 7.10.1 | generate `src/api/schema.gen.ts` from `/api/openapi.json` |
| vitest (dev) | 3.2.4 | unit tests for `format.ts`, sizing, chart mappers |
| Python: fastapi / uvicorn / pydantic / starlette | 0.120.4 / 0.38.0 / 2.14.1 / 0.49.3 | already in `.venv` |
| Python: ruamel.yaml | 0.18.17 | P2 config editing that keeps the comments in `config.yaml` |
| Python: httpx (dev) | 0.28.1 | FastAPI `TestClient` |

### 5.2 lightweight-charts: v5, not v4

- **Native panes** (v5): candles + volume + RSI + MACD live in *one* chart with one time scale and a synced crosshair. v4 needs several charts plus manual sync code.
- **Markers as a plugin** (`createSeriesMarkers`), plus primitives/plugins for the timing bands and price-line labels we need.
- A smaller, tree-shakable bundle. v5.2.1 (12 Aug 2026) has been out for more than two months; the v5 line has been stable since early 2025.
- Migration notes for the team:
  - `chart.addSeries(CandlestickSeries, opts, paneIndex)` replaces `addCandlestickSeries`
  - `createSeriesMarkers(series, markers)` replaces `series.setMarkers`
  - `chart.panes()[i].setHeight(px)` sets pane heights
  - use `autoSize: true`
- Lazy-load the Chart, Strategy detail and Paper routes (`React.lazy`) so lightweight-charts is not in the initial bundle.

### 5.3 Project layout

```
web/
  serve.py                    # uvicorn on 127.0.0.1:8600, opens browser (exists)
  api/
    main.py                   # app factory: middleware, routers, error handlers, SPA mount (exists -> extend)
    security.py               # TrustedHost + mutation header guard
    errors.py                 # ApiError, codes, handlers
    caches.py                 # FileCache (mtime), VersionCache (store version), keyed caches, warm-up
    models/                   # pydantic: common, status, overview, strategies, signals, screener, chart,
                              #           holdings, paper, market, scan, fyers, config, data, intraday
    routers/                  # one module per section; all paths under /api
    services/
      catalog.py              # static strategy metadata (evidence text, sources, failure modes, catalogue id)
      sizing.py               # allocation-aware order sizing (mirrors daily.sized, fixes SELL qty)
      alerts.py               # alert + "since last scan" generation
      market_derived.py       # breadth history, industry strength, Nifty 200-DMA (from store via scanner.panel)
      chart_data.py           # bars, indicators (scanner.indicators.add_indicators), markers, price lines
      screener.py             # reads screener.parquet or computes from store
      scan_runner.py          # Popen run_scan.py, status merge
      fyers_login.py          # paste/callback OAuth flow, writes TOKEN_FILE like login.py
      clock.py                # IST market session + holidays
  ui/
    src/
      main.tsx, app/{router.tsx, providers.tsx, AppShell.tsx}
      api/{client.ts, schema.gen.ts, types.ts, keys.ts, hooks.ts}
      components/{layout/*, data/*, charts/*, feedback/*}
      pages/{Overview, Signals, Strategies, StrategyDetail, Screener, Chart, Portfolio, Paper, Market, Intraday, Settings}.tsx
      lib/{format.ts, time.ts, theme.ts, chartTheme.ts, useLocalStorage.ts, shortcuts.ts}
      index.css               # tokens (§4.1)
tests/test_api_contract.py    # TestClient against a fixture copy of latest.json + curves.parquet
```

### 5.4 Dev and production

- **Dev:** two terminals.
  - `.venv\Scripts\python.exe -m web.serve --reload --no-browser` (API on :8600)
  - `cd web\ui && npm run dev` (Vite on 127.0.0.1:5173, proxies `/api` → 8600; already in `vite.config.ts`)
  - `npm run gen:api` = `openapi-typescript http://127.0.0.1:8600/api/openapi.json -o src/api/schema.gen.ts`. `types.ts` re-exports friendly names. The pydantic models are the source of truth, and CI fails if the generated file is out of date.
- **Production** (`3_dashboard.bat`, replacing the Streamlit one):

```bat
@echo off
REM Open Quant Desk at http://127.0.0.1:8600. Keep this window open while using it.
cd /d "%~dp0"
if not exist "web\ui\dist\index.html" (
  echo Building the app once - about a minute...
  pushd web\ui && call npm ci && call npm run build && popd
)
".venv\Scripts\python.exe" -m web.serve
pause
```

- Keep `app.py` and a `3b_dashboard_streamlit.bat` until the Phase-1 acceptance list passes, then delete them.
- `setup.bat` gains the `npm ci && npm run build` step.

### 5.5 Security (local-only, but browsers are hostile)

- Bind `127.0.0.1` only (never `0.0.0.0`).
- `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost"])` blocks DNS rebinding.
- **Every non-GET request must send `X-Quant-Desk: 1`.** The API returns 403 `CSRF` otherwise. There is no CORS middleware at all, so a custom header from another origin triggers a preflight that fails. The UI `client.ts` adds the header.
- Never return `.env` values, `access_token` or the secret. The client id is masked (`ABCD****-100`). Logs shown in the UI are scrubbed of `access_token=`/`auth_code=`.
- The Fyers `auth_code` travels only in a POST body. It is never put in a URL that the app creates.
- `Cache-Control: no-store` on `/api/*`.

---

## 6. REST API contract

### 6.1 Conventions

- **Base `/api`**, JSON UTF-8, **snake_case**. Numbers are JSON numbers (never formatted strings).
- Percent values are in percent units (`12.3` = 12.3%). Money is in rupees. Dates are `YYYY-MM-DD` (IST trading date). Datetimes are ISO-8601 with `+05:30`.
- **All declared fields are always present**; unknown = `null`. In TS, `?` is used only in request bodies.
- NaN/inf serialise as `null` (`ConfigDict(ser_json_inf_nan='null')`).
- Errors are always `{"error": {"code", "message", "hint", "details"}}`:

| Code | HTTP | When |
|---|---|---|
| `NO_SCAN` | 404 | `latest.json` missing or not version 2 |
| `NOT_FOUND` | 404 | unknown strategy key / symbol |
| `VALIDATION` | 422 | bad params/body (FastAPI errors re-wrapped) |
| `SCAN_BUSY` | 409 | a scan already holds the lock (`details` = lock info) |
| `FYERS_NOT_CONFIGURED` | 409 | `.env` lacks client id/secret |
| `FYERS_LOGIN_REQUIRED` | 409 | an action needs today's token (import holdings, quotes) |
| `FYERS_AUTH` | 502 | Fyers rejected the token/code |
| `FYERS_RATE_LIMIT` | 429 | local guard or Fyers limit |
| `NSE_UNAVAILABLE` | 503 | NSE API down and no cache |
| `FEATURE_UNAVAILABLE` | 501 | paper / intraday / trades artifact not available (`details.feature`) |
| `CSRF` / `FORBIDDEN_HOST` | 403 | security guards |
| `INTERNAL` | 500 | anything else (message only; traceback in `data/logs/api.log`) |

- **Scan-derived responses carry `as_of: AsOf`.** The UI watches `GET /api/status` → `latest.scan_id`; when it changes it calls `queryClient.invalidateQueries()`.
- **Polling:** `/api/status` every 10 s; every 1 s while `scan.running` or `state==='starting'`; every 30 s when the tab is hidden. Other queries use `staleTime: Infinity` (only scan_id invalidation refreshes them). The chart uses a 10-minute staleTime.
- Response size targets: lists < 60 KB; chart 5Y daily ≈ 70 KB; curves All ≈ 120 KB.

### 6.2 Endpoint index

| # | Method | Path | Source (python) | Cache key | Phase |
|---|---|---|---|---|---|
| 1 | GET | `/api/health` | — | — | P1 |
| 2 | GET | `/api/status` | `load_latest`, `lock.running_scan`, `status.json`, `providers.load_token`, `events.trading_holidays` | latest mtime | P1 |
| 3 | GET | `/api/overview` | `latest.json` + previous `scan_*.json`, store (`Factors.index_sma200`), events cache | scan_id | P1 |
| 4 | GET | `/api/strategies` | `latest.strategies`, `curves.parquet`, `build_strategies(cfg)`, `services.catalog` | scan_id + config mtime | P1 |
| 5 | GET | `/api/strategies/{key}` | same + `latest.paper` | scan_id | P1 |
| 6 | GET | `/api/strategies/{key}/curve` | `curves.parquet` | scan_id | P1 |
| 7 | GET | `/api/strategies/{key}/trades` | `trades.parquet` (B1) else `recent_trades` | scan_id | P1 |
| 8 | GET | `/api/curves` | `curves.parquet` | scan_id | P1 |
| 9 | GET | `/api/signals` | `latest.strategies[].actions/positions`, `config.allocations`, `services.sizing` | scan_id + query | P1 |
| 10 | GET | `/api/screener` | `screener.parquet` (B2) else store + `Factors` | scan_id / store ver | P1 |
| 11 | GET | `/api/rankings/{key}` | `latest.strategies[key].ranking` | scan_id | P1 |
| 12 | GET | `/api/sparklines` | store close | store ver | P1 |
| 13 | GET | `/api/symbols` | `latest.symbols` + universe csv + `config.etfs` + index symbols | scan_id | P1 |
| 14 | GET | `/api/chart/{symbol}` | store + `indicators.add_indicators` + trades + latest positions/actions + holdings + `meta.corporate_actions` | store ver + params | P1 |
| 15 | GET | `/api/stock/{symbol}` | latest + store + holdings | scan_id | P1 |
| 16 | GET | `/api/holdings` | `holdings.load_holdings` + `latest.holdings` | csv mtime + scan_id | P1 |
| 17 | PUT | `/api/holdings` | `holdings.save_holdings` | — | P1 |
| 18 | POST | `/api/holdings/import/fyers` | `providers.get_fyers(cfg).holdings()` | — | P1 |
| 19 | GET | `/api/paper` | `latest.paper` / `paper.build_report` | store ver + journal mtime + costs | P1 (needs B6) |
| 20 | GET | `/api/paper/{key}` | `paper.build_report` | same | P1 |
| 21 | GET | `/api/market/movers` | `latest.gainers/losers/volume_spikes` | scan_id | P1 |
| 22 | GET | `/api/market/sectors` | `latest.indices.sectors` + store industries | scan_id + store ver | P1 |
| 23 | GET | `/api/market/factors` | `latest.indices.factors` | scan_id | P1 |
| 24 | GET | `/api/market/results` | `events.upcoming_results` cache file + latest | day | P1 |
| 25 | GET | `/api/market/breadth` | store → `panel_from_wide` → `Factors.breadth_50`, `index_sma200` | store ver | P1 |
| 26 | GET | `/api/market/clock` | `services.clock` | 30 s | P1 |
| 27 | POST | `/api/scan` | `subprocess.Popen(run_scan.py --status … --by platform [--no-update])` | — | P1 |
| 28 | GET | `/api/scan/status` | `lock.running_scan`, `status.json`, Popen handle | — | P1 |
| 29 | GET | `/api/scan/history` | `RESULTS_DIR.glob('scan_*.json')` (names + first 600 bytes) | dir mtime | P1 |
| 30 | GET | `/api/scan/log` | tail `data/logs/scanner.log` | — | P1 |
| 31 | GET | `/api/fyers/status` | `load_token`, `.env` presence, `get_fyers` (verify) | 5 min (verify) | P1 |
| 32 | POST | `/api/fyers/login` | `fyersModel.SessionModel.generate_authcode` / spawn `1_login.bat` | — | P1 |
| 33 | POST | `/api/fyers/login/complete` | `SessionModel.set_token/generate_token` → `TOKEN_FILE` | — | P1 |
| 34 | GET | `/api/fyers/callback` | same, callback mode | — | P1 |
| 35 | GET | `/api/config` | `settings.load_config` | config mtime | P1 |
| 36 | PATCH | `/api/config` | ruamel round-trip write | — | P2 |
| 37 | GET | `/api/costs/preview` | `CostModel.from_config` | config mtime | P1 |
| 38 | GET | `/api/data/health` | `PanelStore`, `meta.json`, latest, files | store ver | P1 |
| 39 | GET | `/api/quotes` | `FyersProvider.live_rows` (≤ 50 symbols) | 15 s | P2 |
| 40 | GET | `/api/intraday/status` | intraday store manifest, clock | 60 s | P1 (placeholder) |
| 41 | GET | `/api/intraday/strategies` | intraday results file | scan | P3 |
| 42 | GET | `/api/intraday/strategies/{key}` | same | scan | P3 |
| 43 | GET | `/api/intraday/signals` | intraday live engine | 5 s | P3 |
| 44 | GET | `/api/intraday/bars/{symbol}` | `IntradayStore.load` | manifest mtime | P3 |
| 45 | GET | `/api/intraday/watchlist` | in-play selector | 60 s | P3 |

Until P3, endpoints 41 to 45 return 501 `FEATURE_UNAVAILABLE` with `details.feature='intraday'`.

### 6.3 Shared types (TypeScript)

```ts
// ---------------------------------------------------------------- primitives
export type ISODate = string;          // 'YYYY-MM-DD' (IST trading date)
export type ISODateTime = string;      // '2026-10-23T09:18:47+05:30'
export type Horizon = 'intraday' | 'swing' | 'longterm';
export type StrategyKind = 'rank' | 'event' | 'intraday';
export type StrategyStatus = 'working' | 'mixed' | 'not-working' | 'unknown';
export type Lifecycle = 'active' | 'disabled' | 'rejected';
export type Evidence = 'STRONG' | 'MODERATE' | 'WEAK' | 'FOLKLORE' | 'EXPERIMENTAL';
export type Tone = 'good' | 'neutral' | 'bad';
export type Side = 'BUY' | 'SELL';
export type AssetUniverse = 'stocks' | 'etfs';
export type ErrorCode = 'NO_SCAN' | 'NOT_FOUND' | 'VALIDATION' | 'SCAN_BUSY' | 'FYERS_NOT_CONFIGURED'
  | 'FYERS_LOGIN_REQUIRED' | 'FYERS_AUTH' | 'FYERS_RATE_LIMIT' | 'NSE_UNAVAILABLE' | 'FEATURE_UNAVAILABLE'
  | 'CSRF' | 'FORBIDDEN_HOST' | 'INTERNAL';

export interface ApiError { error: { code: ErrorCode; message: string; hint: string | null; details: unknown | null } }

export interface AsOf {
  scan_id: string;                 // == generated_at
  generated_at: ISODateTime;
  elapsed_s: number;
  data_date: ISODate;
  live: boolean;                   // today's candle still forming
  provisional: boolean;            // == live (orders can change before 15:30)
  live_source: string | null;
  complete_upto: ISODate | null;
  stale: boolean;                  // data_date < last completed trading day (clock + holidays)
  backtest_universe: 'current_list' | 'point_in_time';   // B7; default 'current_list'
  universe_note: string;           // latest.universe, e.g. 'NIFTY500 (cached list)'
  stocks: number;                  // liquid tradable stocks
  capital: number;
  min_position: number | null;
}

export interface SeriesPoint { t: ISODate; v: number | null }

// ---------------------------------------------------------------- metrics (mirror engine.evaluate)
export interface PerfStats {
  return_pct: number | null; cagr_pct: number | null; max_dd_pct: number | null;
  sharpe: number | null; vol_pct: number | null; after_tax_cagr_pct: number | null;
}
export interface TradeStats {
  trades: number; win_rate: number | null; avg_win_pct: number | null; avg_loss_pct: number | null;
  expectancy_pct: number | null; profit_factor: number | null; avg_days: number | null;
}
export interface WindowMetrics extends PerfStats, TradeStats {
  benchmark: PerfStats | null;          // Nifty 50
  ew_benchmark: PerfStats | null;       // average stock (same biased list)
  n500_benchmark: PerfStats | null;     // real Nifty 500 index
  factor_benchmark: PerfStats | null;   // matching NSE factor index, if any
}
export interface FullMetrics extends WindowMetrics {
  exposure_pct: number | null; start: ISODate; end: ISODate; after_tax_return_pct: number | null;
  cagr_range: [number, number] | null; te_n500_pct: number | null; factor_benchmark_name: string | null;
}
export interface StrategyMetrics { full: FullMetrics; m12: WindowMetrics | null; m6: WindowMetrics | null; m3: WindowMetrics | null }
// NOTE: latest.json uses keys '12m','6m','3m'; the API renames them to m12/m6/m3 (valid identifiers).
```

### 6.4 System

**`GET /api/health`** → `{ ok: true; version: string; uptime_s: number }`

**`GET /api/status`** → `AppStatus`

```ts
export type MarketSession = 'pre_open' | 'open' | 'post_close' | 'closed' | 'holiday' | 'weekend';
export interface MarketClock {
  now: ISODateTime; session: MarketSession; is_trading_day: boolean; holiday_name: string | null;
  next_open: ISODateTime | null;           // next 09:15 IST trading session
  eod_expected_after: ISODateTime | null;  // today 18:00 IST on trading days (store.NSE_PUBLISH_HOUR)
  signals_final: boolean;                  // latest.data_date == today && !live && now >= 18:00, or market closed day
}
export interface Features { paper: boolean; pit: boolean; intraday: boolean; trades_artifact: boolean; screener_artifact: boolean; config_edit: boolean; quotes: boolean }
export interface AppStatus {
  server_version: string;
  latest: AsOf | null;                     // null => onboarding
  scan: ScanStatus;
  fyers: FyersStatus;                      // verify=false variant (no network)
  clock: MarketClock;
  features: Features;
  ticker: { nifty: number | null; nifty_change_pct: number | null; nifty500: number | null; nifty500_change_pct: number | null;
            vix: number | null; vix_change_pct: number | null; advances: number | null; declines: number | null;
            regime_up: boolean | null; label: 'Bullish' | 'Mixed' | 'Bearish' | null } | null;
}
```

Clock rules:
- weekend or `trading_holidays(year)` → `weekend` / `holiday`
- 09:00–09:15 → `pre_open`; 09:15–15:30 → `open`; 15:30–18:00 → `post_close`; otherwise `closed`

### 6.5 Overview

**`GET /api/overview`** → `OverviewResponse`

```ts
export interface MarketSnapshot {
  label: 'Bullish' | 'Mixed' | 'Bearish'; level: Tone; advice: string; regime_up: boolean;
  nifty: number | null; nifty_change_pct: number | null;
  nifty_sma200: number | null; nifty_vs_sma200_pct: number | null;          // B3 or store
  nifty500: number | null; nifty500_change_pct: number | null;              // indices.factors['Nifty 500']
  vix: number | null; vix_change_pct: number | null; high_vix: boolean;     // vix >= 20
  breadth_50: number | null; advances: number; declines: number;
}
export interface Mover { symbol: string; company: string | null; industry: string | null; price: number | null; change_pct: number | null; vol_ratio: number | null }
export type AlertSeverity = 'danger' | 'warn' | 'info' | 'good';
export interface Alert {
  id: string;                                 // stable: `${category}:${symbol ?? ''}:${hash(title)}`
  severity: AlertSeverity;
  category: 'holding' | 'order' | 'data' | 'login' | 'scan' | 'market' | 'paper' | 'bias';
  title: string; detail: string | null; symbol: string | null; strategy_key: string | null;
  href: string | null;                        // UI route, e.g. '/portfolio', '/chart/STLTECH'
}
export interface Change {
  kind: 'status' | 'regime' | 'new_order' | 'position_opened' | 'position_closed';
  text: string;                               // 'Low volatility: mixed -> not working'
  strategy_key: string | null; symbol: string | null;
}
export interface OverviewResponse {
  as_of: AsOf;
  market: MarketSnapshot;
  orders_by_horizon: Record<Horizon, Order[]>;          // active strategies only; not-working flagged via strategy_status
  order_counts: Record<Horizon, { buy: number; sell: number }>;
  empty_reasons: Record<Horizon, string | null>;        // e.g. regime filter text
  alerts: Alert[];                                      // sorted danger > warn > info > good
  changes: { since: ISODateTime | null; items: Change[] };
  strategy_pulse: StrategySummary[];                    // first 6 active, server order
  movers: { gainers: Mover[]; losers: Mover[]; volume_spikes: Mover[] };   // 5 each
  sectors_top: IndexRow[]; sectors_bottom: IndexRow[];  // 3 each by 3M
  results_soon: ResultsEvent[];                         // <= 7 days and relevant
  paper: PaperSummary[];                                // [] if no journal
}
```

### 6.6 Strategies

**`GET /api/strategies?horizon=longterm|swing|intraday&lifecycle=active|all`** → `StrategyListResponse`

```ts
export interface Edges {
  vs_ew_cagr_pct: number | null;      // full.cagr - ew.cagr        (stock strategies' primary edge)
  vs_n500_cagr_pct: number | null;    // full.cagr - n500.cagr
  vs_nifty_cagr_pct: number | null;   // full.cagr - benchmark.cagr (primary edge for universe='etfs')
  vs_factor_cagr_pct: number | null;  // full.cagr - factor.cagr ('ETF alternative')
  primary: 'ew' | 'nifty';            // which edge the table shows
  r12m_vs_n500_pct: number | null;    // m12.return - m12.n500.return
  r6m_vs_n500_pct: number | null;
}
export interface TimingRange {
  base_cagr_pct: number | null; low: number | null; high: number | null;
  consistent: boolean;                // low <= base <= high
  method: 'rebalance_offsets' | 'start_offsets';   // rank vs event (daily.py)
  note: string;
}
export interface StrategySummary {
  key: string; name: string; description: string;
  kind: StrategyKind; horizon: Horizon; evidence: Evidence; universe: AssetUniverse; lifecycle: Lifecycle;
  status: StrategyStatus; status_reason: string; rejected_reason: string | null;
  headline: {
    cagr_pct: number | null; after_tax_cagr_pct: number | null; max_dd_pct: number | null; sharpe: number | null;
    vol_pct: number | null; win_rate: number | null; trades: number; exposure_pct: number | null; avg_days: number | null;
    ret_12m_pct: number | null; ret_6m_pct: number | null; ret_3m_pct: number | null;
    n500_12m_pct: number | null;
  };
  edges: Edges;
  timing: TimingRange | null;
  benchmark_name: string | null;          // factor index name
  counts: { orders_buy: number; orders_sell: number; positions: number; max_positions: number };
  per_position: number | null;
  rebalance: string | null;               // 'monthly' | 'quarterly' | ... (rank only)
  next_rebalance: ISODate | null;
  uses_regime_filter: boolean;
  blocked_by_regime: boolean;             // uses_regime_filter && !market.regime_up
  spark: number[];                        // <=120 points of normalised equity (curves.parquet, even sampling)
  paper: { return_pct: number | null; days: number; level: Tone } | null;
  source: 'scan' | 'catalogue';           // 'catalogue' = rejected entry without B4 metrics
}
export interface RejectedEntry {          // until B4 ships
  key: string; name: string; horizon: Horizon; evidence: Evidence; result_text: string; source: 'catalogue' | 'scan';
}
export interface StrategyListResponse {
  as_of: AsOf;
  period: { start: ISODate; end: ISODate };
  benchmarks: { nifty50: PerfStats | null; nifty500: PerfStats | null; average_stock: PerfStats | null;
                survivorship_gap_pct: number | null };   // ew.cagr - n500.cagr
  counts: Record<Horizon, number>;
  strategies: StrategySummary[];           // active, server order (status, evidence tier, 12m)
  rejected: StrategySummary[];             // lifecycle rejected/disabled with metrics (B4)
  rejected_catalogue: RejectedEntry[];     // fallback rows when B4 metrics are absent
}
```

**`GET /api/strategies/{key}`** → `StrategyDetail`

```ts
export interface WindowRow {
  window: '3m' | '6m' | '12m' | 'full';
  strategy: PerfStats; nifty50: PerfStats | null; nifty500: PerfStats | null; average_stock: PerfStats | null; factor: PerfStats | null;
}
export interface YearlyRow { year: number; partial: boolean; strategy: number | null; nifty500: number | null; average_stock: number | null; nifty50: number | null }
export interface MonthlyCell { year: number; month: number; ret_pct: number | null }  // month 1..12; plus year totals via YearlyRow
export interface StrategyRules {
  kind: StrategyKind; rebalance: string | null; top_n: number | null; keep_rank: number | null; max_positions: number;
  stop_pct: number | null; stop_atr: number | null; target_pct: number | null; trail_pct: number | null; max_hold: number | null;
  sizing: 'equal' | 'risk'; risk_pct: number | null; use_regime: boolean; regime_action: 'hold' | 'cash' | null;
  params: Record<string, number | string | boolean | string[] | null>;   // effective config.yaml values for this key
  plain_rules: string[];             // catalog text, e.g. 'Buy: top 15 by NSE momentum score, above 200-DMA'
  costs_round_trip_pct: number | null;
}
export interface EvidenceCard {
  grade: Evidence; catalogue_id: string | null;   // 'L1', 'S6', ...
  summary: string; what_to_expect: string;
  sources: { title: string; url: string | null }[];
  failure_modes: string[];
  validation: {                                   // B8, else null
    in_sample: { start: ISODate; end: ISODate; cagr_pct: number | null; sharpe: number | null } | null;
    holdout: { start: ISODate; end: ISODate; cagr_pct: number | null; sharpe: number | null } | null;
    variants_tried: number | null; expectancy_ci95: [number, number] | null;
  } | null;
}
export interface ModelPosition {
  symbol: string; company: string | null; industry: string | null;
  entry_date: ISODate; entry_price: number; qty: number; last_price: number | null; ret_pct: number | null;
  stop: number | null; days: number; value: number | null; weight_pct: number | null;
  results_on: ISODate | null; results_in_days: number | null;
}
export interface RankingRow {
  rank: number; symbol: string; company: string | null; industry: string | null; score: number | null; price: number | null;
  ret_6m: number | null; ret_12m: number | null; rs: number | null; in_portfolio: boolean;
  results_on: ISODate | null; results_in_days: number | null;
}
export interface TradeRow {
  symbol: string; entry_date: ISODate; exit_date: ISODate; entry_price: number | null; exit_price: number | null;
  qty: number | null; pnl: number | null; ret_pct: number | null; days: number; reason: string;
}
export interface StrategyDetail {
  as_of: AsOf;
  strategy: StrategySummary;
  metrics: StrategyMetrics;
  windows: WindowRow[];
  yearly: YearlyRow[];             // strategy from latest.yearly; benchmarks from curves.parquet, same first/last formula
  monthly: MonthlyCell[];          // from curves.parquet (month-end last / previous month-end last - 1)
  timing: TimingRange | null;
  rules: StrategyRules;
  evidence: EvidenceCard;
  positions: ModelPosition[];
  orders: Order[];                 // sized with current allocations (same as /api/signals)
  ranking: RankingRow[];           // [] for event strategies
  recent_trades: TradeRow[];       // last 25 from latest.json
  trades_available: boolean;       // B1 present
  regime_note: string | null;      // 'No new buys: Nifty below its 200-DMA (regime filter on). Holding 1 of 15.'
  paper: PaperSummary | null;
}
```

**`GET /api/strategies/{key}/curve?range=1y|3y|all&rebase=true&benchmarks=NIFTY%20500,Average%20stock,NIFTY%2050,factor`** → `CurveResponse`

```ts
export interface CurveSeries { id: string; label: string; role: 'strategy' | 'benchmark'; points: SeriesPoint[] }
export interface CurveResponse {
  as_of: AsOf; key: string; range: '1y' | '3y' | 'all'; rebased: boolean;   // rebased: 1.0 at range start
  series: CurveSeries[];                 // strategy first
  drawdown: SeriesPoint[];               // strategy eq/cummax - 1, in %
  benchmark_drawdown: SeriesPoint[];     // NIFTY 500
  capital: number;                       // UI multiplies for the ₹ view
}
```

The factor series comes from `data/nse/index_history.parquet[factor_benchmark_name]`, aligned and normalised. If it is unavailable it is omitted.

**`GET /api/strategies/{key}/trades?page=1&page_size=50&outcome=all|win|loss&reason=&symbol=&sort=-exit_date`** → `TradesPage`

```ts
export interface TradesPage {
  as_of: AsOf; key: string; source: 'artifact' | 'recent_only';
  total: number; page: number; page_size: number; rows: TradeRow[];
  stats: TradeStats;                                   // over the filtered set
  histogram: { bin_lo: number; bin_hi: number; count: number }[];   // 2% bins, clamp [-30, +100]
  reasons: { reason: string; count: number; avg_ret_pct: number | null }[];
}
```

**`GET /api/curves?keys=momentum,low_vol&range=all&rebase=true`** → `{ as_of: AsOf; series: CurveSeries[] }` (comparison chart on the leaderboard; benchmarks always included).

### 6.7 Signals and sizing

**`GET /api/signals?horizon=&allocations=momentum:60,low_vol:40&include_comparison=true`** → `SignalsResponse`

```ts
export interface Order {
  strategy_key: string; strategy_name: string; strategy_status: StrategyStatus; horizon: Horizon;
  action: Side; symbol: string; company: string | null; industry: string | null; reason: string;
  price: number | null;                // last close/live price used for sizing
  qty: number;                         // BUY: sized to allocation; SELL: model position qty (fixes daily.py)
  amount: number | null;               // qty * price
  stop: number | null; stop_distance_pct: number | null;   // (stop/price - 1)*100
  risk_amount: number | null;          // qty * (price - stop), BUY only
  results_on: ISODate | null; results_in_days: number | null; results_warning: boolean;
  provisional: boolean;
  below_min_position: boolean;         // amount < account.min_position (the backtest would skip it)
  model_qty: number | null;            // for SELL: qty in the model portfolio
  you_hold_qty: number | null;         // from holdings.csv
}
export interface Allocation { strategy_key: string; pct: number; capital: number }
export interface SignalGroup {
  horizon: Horizon;
  strategy: StrategySummary;
  sizing: { capital: number; per_position: number; max_positions: number; sizing: 'equal' | 'risk'; risk_pct: number | null };
  orders: Order[];
  empty_reason: string | null;   // regime filter / 'No entry signals today' / 'Next review 30 Oct' / 'Strategy is off'
  comparison_only: boolean;      // strategy_status == 'not-working'
}
export interface SignalsResponse {
  as_of: AsOf;
  capital: number; min_position: number | null;
  allocations: Allocation[];               // from config.allocations or the query override
  allocation_source: 'config' | 'query' | 'none';
  allocation_warning: string | null;       // 'none' => each strategy uses the full capital
  regime: { regime_up: boolean; note: string | null };
  groups: SignalGroup[];                   // non-comparison first
  totals: { buy_count: number; sell_count: number; buy_amount: number; risk_amount: number; results_warnings: number };
}
```

Sizing (`services/sizing.py`) mirrors `daily.sized`, with `alloc` = `capital × pct / 100`, or the full capital when there are no allocations:
- `per_pos = alloc / max_positions`
- `qty = floor(per_pos / price)`
- if `sizing=='risk'` and `stop` and `price > stop`: `qty = min(floor(alloc × risk_pct / 100 / (price − stop)), floor(2 × per_pos / price))`
- SELL: `qty = model position qty`

### 6.8 Screener, rankings, symbols, sparklines

```ts
// GET /api/screener?preset=momentum|rs|near_high|low_vol|volume|uptrend|all&industry=IT,Banks&min_turnover_cr=5&in_models=false&results_within=7&sort=-momentum_score&limit=500
export interface ScreenerRow {
  symbol: string; company: string | null; industry: string | null; price: number | null; change_pct: number | null;
  ret_1w: number | null; ret_1m: number | null; ret_3m: number | null; ret_6m: number | null; ret_12m: number | null;
  rs: number | null; momentum_score: number | null; momentum_rank: number | null; vol_ann_pct: number | null;
  pct_from_52w_high: number | null; above_sma50: boolean | null; above_sma200: boolean | null; sma50_above_sma200: boolean | null;
  rsi14: number | null; vol_ratio: number | null; turnover_cr: number | null; atr_pct: number | null; deliv_pct: number | null;
  results_on: ISODate | null; in_models: string[]; you_hold: boolean;
}
export interface ScreenerResponse {
  as_of: AsOf; source: 'scan' | 'store'; source_date: ISODate; preset: string; total: number; rows: ScreenerRow[];
  default_columns: (keyof ScreenerRow)[];
}
// Presets: momentum = sort momentum_score desc, above_sma200; rs = rs desc; near_high = pct_from_52w_high desc & uptrend;
//          low_vol = vol_ann asc among top-150 turnover; volume = vol_ratio >= 3; uptrend = above_sma200 & sma50_above_sma200.

// GET /api/rankings/{key}            -> { as_of: AsOf; key: string; rows: RankingRow[] }
// GET /api/symbols                   -> { as_of: AsOf | null; symbols: SymbolInfo[] }
export interface SymbolInfo { symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index'; in_universe: boolean }
// GET /api/sparklines?symbols=A,B,C&days=60   (max 100 symbols)
export interface SparklinesResponse { source_date: ISODate; days: number; series: Record<string, (number | null)[]> }
```

### 6.9 Chart and stock

```ts
// GET /api/chart/{symbol}?tf=1d|1w|5m&range=3m|6m|1y|2y|5y|max&indicators=sma20,sma50,sma200,rsi14,vol_avg20&strategies=momentum,earnings_gap&holding=true
export type ChartTf = '1d' | '1w' | '5m' | '15m';
export type IndicatorId = 'sma20' | 'sma50' | 'sma200' | 'ema9' | 'ema21' | 'bb_upper' | 'bb_mid' | 'bb_lower'
  | 'rsi14' | 'macd' | 'macd_signal' | 'macd_hist' | 'vol_avg20' | 'atr14' | 'vwap';
export interface ChartBars {
  t: (ISODate | number)[];   // daily/weekly: 'YYYY-MM-DD'; intraday: IST-wall-clock-as-UTC epoch seconds
  o: number[]; h: number[]; l: number[]; c: number[]; v: number[];
}
export interface ChartMarker {
  t: ISODate | number; position: 'aboveBar' | 'belowBar' | 'inBar'; shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  kind: 'entry' | 'exit' | 'open_entry' | 'pending_order' | 'corporate_action' | 'results';
  tone: 'profit' | 'loss' | 'neutral' | 'warn'; text: string; detail: string | null; strategy_key: string | null;
}
export interface PriceLine {
  price: number; label: string; strategy_key: string | null;
  kind: 'model_entry' | 'model_stop' | 'order_stop' | 'your_buy' | 'your_stop' | 'your_target' | 'high_52w' | 'low_52w';
}
export interface ChartResponse {
  symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index';
  tf: ChartTf; range: string; tz: 'Asia/Kolkata'; adjusted: boolean; source: 'store' | 'intraday_store';
  source_date: ISODate;                       // last stored bar
  bars: ChartBars;
  indicators: Partial<Record<IndicatorId, (number | null)[]>>;   // aligned to bars.t
  markers: ChartMarker[];
  price_lines: PriceLine[];
  strategies_available: { key: string; name: string; trades: number }[];   // strategies that ever traded it (B1)
  results_on: ISODate | null;
  live_overlay: { price: number; change_pct: number | null; at: ISODateTime; source: string } | null;   // P2 quotes
}
```

Chart construction rules:
- Indicators are computed on the **full** history and then sliced to the range, so the SMA200 is valid at the left edge.
- `1w` = resample W-FRI: O first, H max, L min, C last, V sum.
- Rows where close is NaN are dropped (never forward-filled on charts).

```ts
// GET /api/stock/{symbol}
export interface StockSnapshot {
  as_of: AsOf | null; symbol: string; company: string | null; industry: string | null; kind: 'stock' | 'etf' | 'index';
  price: number | null; change_pct: number | null; data_date: ISODate | null;
  high_52w: number | null; low_52w: number | null; pct_from_52w_high: number | null;
  ret_1m: number | null; ret_3m: number | null; ret_6m: number | null; ret_12m: number | null;
  rs: number | null; momentum_rank: number | null; sma50: number | null; sma200: number | null;
  vol_ratio: number | null; turnover_cr: number | null; deliv_pct: number | null; results_on: ISODate | null;
  strategies: { key: string; name: string; status: StrategyStatus; role: 'holding' | 'order' | 'ranked'; detail: string }[];
  your_holding: HoldingRow | null;
  corporate_actions: { date: ISODate; factor: number; reason: string }[];
}
```

### 6.10 Holdings

```ts
export interface HoldingInput {          // one row of holdings.csv (holdings.HOLDING_COLS)
  symbol: string; qty: number | null; buy_price: number | null; buy_date: ISODate | null;
  stop_loss_pct: number | null; target_pct: number | null;
}
export type HoldingLevel = 'ok' | 'good' | 'watch' | 'danger' | 'unknown';
export interface HoldingRow {            // latest.holdings[] + derived
  symbol: string; company: string | null; qty: number | null; buy_price: number | null; price: number | null;
  change_pct: number | null; pnl_pct: number | null; pnl_amount: number | null;
  stop_price: number | null; target_price: number | null; momentum_rank: number | null; rs: number | null;
  results_on: ISODate | null; level: HoldingLevel; alerts: string[];
  value: number | null; day_pnl: number | null; weight_pct: number | null; industry: string | null; in_models: string[];
}
// GET /api/holdings
export interface HoldingsResponse {
  as_of: AsOf | null;
  rows: HoldingRow[];                    // health as of the last scan
  inputs: HoldingInput[];                // current holdings.csv
  health_stale: boolean;                 // holdings.csv mtime > generated_at, or symbols differ
  totals: { count: number; invested: number | null; value: number | null; pnl: number | null; pnl_pct: number | null;
            day_pnl: number | null; danger: number; watch: number };
  by_industry: { industry: string; weight_pct: number }[];
  defaults: { stop_loss_pct: number; target_pct: number };
}
// PUT /api/holdings   body HoldingsPutRequest   (header X-Quant-Desk: 1)
export interface HoldingsPutRequest { rows: HoldingInput[]; mode?: 'replace' }   // full replacement; the UI merges client-side
export interface HoldingsPutResponse {
  saved: number; health_stale: true;
  rejected: { index: number; symbol: string; reason: string }[];   // qty<0, price<=0, future date, empty symbol
  unknown_symbols: string[];                                        // saved, but not in latest.symbols (warning)
}
// POST /api/holdings/import/fyers   (no body) -> preview only, nothing saved
export interface FyersImportResponse { rows: HoldingInput[]; count: number; note: string }
// mapping as in app.py: symbol = 'NSE:SBIN-EQ'.split(':')[-1].rsplit('-',1)[0]; qty = quantity; buy_price = costPrice; buy_date = null
```

### 6.11 Paper trading

```ts
export interface PaperSummary {          // == paper.summarize() output, rounded
  key: string; name: string; start: ISODate; days: number; last_date: ISODate;
  equity: number; return_pct: number | null; pnl: number;
  nifty_pct: number | null; n500_pct: number | null; excess_pct: number | null;
  expected_pct: number | null; expected_range_pct: [number | null, number | null] | null; haircut_pct: number | null;
  expected_excess_pct: number | null; haircut_excess_pct: number | null; noise_pct: number | null;
  backtest_cagr_pct: number | null; backtest_n500_cagr_pct: number | null; max_dd_pct: number | null;
  trades: number; win_rate: number | null; open: number; pending: number; fees: number; slippage: number;
  verdict: string; level: Tone;
}
// GET /api/paper
export interface PaperListResponse {
  available: boolean;                    // false => module/journal missing (UI shows the empty state, no error)
  journal: { days: number; first: ISODate; last: ISODate } | null;
  survivorship_haircut_pct: number;      // paper.SURVIVORSHIP_HAIRCUT_PCT (8)
  min_days_to_judge: number;             // paper.MIN_DAYS_TO_JUDGE (21)
  strategies: PaperSummary[];
}
// GET /api/paper/{key}
export interface PaperPosition { symbol: string; entry_date: ISODate; entry_price: number; qty: number; last_price: number; value: number; pnl: number; ret_pct: number; stop: number | null; days: number; via: string }
export interface PaperTrade { symbol: string; entry_date: ISODate; entry_price: number; exit_date: ISODate; exit_price: number; qty: number; pnl: number; ret_pct: number; days: number; reason: string; via: string }
export interface PaperDetail {
  summary: PaperSummary; capital: number; cash: number;
  equity: CurveSeries[];                 // rupees: 'Paper', 'NIFTY 50', 'NIFTY 500'
  open: PaperPosition[]; trades: PaperTrade[]; pending: { action: Side; symbol: string; reason: string }[];
  trade_stats: TradeStats; journal_days: number; last_journal: ISODate;
}
```

The paper-trading session (branch `paper-json`) may change `paper.py`. Keep the router thin: it calls `paper.build_report()` and maps fields defensively, missing → null.

### 6.12 Market

```ts
// GET /api/market/movers -> { as_of: AsOf; gainers: Mover[]; losers: Mover[]; volume_spikes: Mover[] }
export interface IndexRow {
  name: string; last: number | null; chg_1d: number | null; ret_1m: number | null; ret_3m: number | null; ret_6m: number | null;
  ret_1y: number | null; cagr: number | null; max_dd: number | null; since: ISODate | null; above_50dma: boolean | null; rank: number | null;
}
export interface IndustryRow {
  industry: string; members: number; advances: number; declines: number; breadth_50: number | null;
  ret_1d: number | null; ret_1w: number | null; ret_1m: number | null; ret_3m: number | null; ret_6m: number | null;
  leaders: { symbol: string; ret_3m: number | null }[];      // top 3
}
// GET /api/market/sectors -> { as_of: AsOf; nse_sectors: IndexRow[]; industries: IndustryRow[]; industries_source_date: ISODate }
// GET /api/market/factors -> { as_of: AsOf; factors: IndexRow[]; note: string }
export interface ResultsEvent {
  symbol: string; company: string | null; industry: string | null; date: ISODate; days_until: number; purpose: string | null;
  you_hold: boolean; in_models: string[]; in_orders: string[]; rank_momentum: number | null;
}
// GET /api/market/results?days=14&relevant=false -> { as_of: AsOf | null; note: string; events: ResultsEvent[] }
export interface BreadthPoint { t: ISODate; breadth_50: number | null; nifty: number | null; nifty_sma200: number | null; vix: number | null; nifty500: number | null; ad_line: number | null }
// GET /api/market/breadth?range=1y|3y|all -> { source_date: ISODate; points: BreadthPoint[] }
// GET /api/market/clock -> MarketClock
```

### 6.13 Alert rules (`services/alerts.py`)

1. **holding:** every `latest.holdings[].alerts` entry. Severity from `level`: danger→danger, watch→warn, good→good, unknown→warn. `href=/portfolio`.
2. **order:** `results_warning` on any active order (warn: "STLTECH reports in 0 days; consider waiting").
3. **login:** session `open`/`pre_open` and not `logged_in_today` (warn: "Yahoo prices ~15 min delayed").
4. **scan:** `as_of.stale` (warn); the last scan state `failed` (danger, with message).
5. **data:** `stale_symbols` (info, first 3 names); `errors` (warn, count); `nse_status` not ok/cached (warn).
6. **market:** regime changed vs previous scan (info); VIX ≥ 20 (warn).
7. **paper:** any summary with `level=='bad'` (warn).
8. **bias:** `backtest_universe=='current_list'` (info, dismissible per session).

"Since last scan" (`changes`): compare with the newest `scan_*.json` whose `data_date` is older than the current one. Diff, in this order: status per key, `market.regime_up`, the set of `(key, action, symbol)` orders, and the position symbol sets.

### 6.14 Scan

```ts
export type ScanState = 'idle' | 'starting' | 'running' | 'done' | 'failed' | 'busy';
export interface ScanStatus {
  state: ScanState; running: boolean; progress: number | null; message: string | null;
  started_at: ISODateTime | null; elapsed_s: number | null; by: string | null; pid: number | null;
  update: boolean | null; last_scan_id: string | null; exit_code: number | null;
}
// POST /api/scan  body { update?: boolean }  (default true; false = '--no-update' re-check, ~15 s)
//   202 { accepted: true; status: ScanStatus }
//   409 SCAN_BUSY  details: { started: string; by: string; pid: number | null }
// GET  /api/scan/status -> ScanStatus
// GET  /api/scan/history?limit=60 -> { scans: { scan_id: ISODateTime; file: string; data_date: ISODate | null; live: boolean | null; elapsed_s: number | null }[] }
// GET  /api/scan/log?lines=200&level=all|error -> { path: string; lines: string[] }
```

`scan_runner.py` behaviour:
- **Start:**
  - if `running_scan()` → 409
  - else delete `RESULTS_DIR/status.json`
  - `Popen([sys.executable, ROOT/'run_scan.py', '--status', str(STATUS_FILE), '--by', 'platform', *([] if update else ['--no-update'])], cwd=ROOT, creationflags=CREATE_NO_WINDOW, stdout=DEVNULL, stderr=DEVNULL)`
  - keep the handle and launch time in memory
- **State merge** (same logic as `app.py`'s `scan_monitor`):
  - `running_scan()` or (< 30 s since launch and status not final) → `running` or `starting`
  - otherwise the status.json `state` (`done` / `failed` / `busy`), or `idle` if there is no file
  - if the Popen handle exited non-zero before writing status → `failed` with "Scan process exited (code n), see data/logs/scanner.log"
- Scheduled and manual scans hold the same lock, so the UI follows them too (`by` shows who started it).

### 6.15 Fyers

```ts
export interface FyersStatus {
  configured: boolean;                     // FYERS_CLIENT_ID and FYERS_SECRET_KEY present in .env
  client_id_masked: string | null;         // 'ABCD****-100'
  plan: 'standard' | 'prime';              // config.fyers_plan
  data_source: 'auto' | 'yahoo';
  token_present: boolean; token_created: ISODateTime | null;
  logged_in_today: boolean;                // token.created date == IST today (same rule as app.py)
  verified: boolean | null; verified_at: ISODateTime | null; user_name: string | null;   // only with ?verify=true
  live_prices: 'fyers' | 'yahoo_delayed';
  redirect_uri: string;                    // FYERS_REDIRECT_URI or login.DEFAULT_REDIRECT
  login_modes: ('paste' | 'callback' | 'window')[];   // 'callback' only if redirect == http://127.0.0.1:8600/api/fyers/callback
  note: string;                            // latest.fyers_note or computed
}
// GET  /api/fyers/status?verify=false|true   (verify: one get_profile call, cached 5 min)
// POST /api/fyers/login   body { mode: 'paste' | 'callback' | 'window' }
export interface FyersLoginResponse {
  mode: 'paste' | 'callback' | 'window';
  login_url: string | null;                // paste/callback: UI opens it in a new tab
  expires_at: ISODateTime | null;          // pending session TTL 10 min
  instructions: string[];                  // shown verbatim in the login dialog
}
// POST /api/fyers/login/complete   body { redirect_url: string }   (full address from the browser bar)
export interface FyersLoginCompleteResponse { ok: boolean; user_name: string | null; status: FyersStatus }
// GET  /api/fyers/callback?auth_code=...&state=...   (callback mode) -> small HTML page "Logged in, you can close this tab"
```

Login flows:

| Mode | How it works |
|---|---|
| `paste` (default) | The server builds a `fyersModel.SessionModel(client_id, secret_key, redirect_uri, response_type='code', grant_type='authorization_code', state=token_urlsafe(16))` and keeps it in memory for 10 min. It returns `generate_authcode()`. The user logs in, copies the address bar, and pastes it into the dialog. `complete` runs `login._extract_code(text)`, checks `state` when present, then `set_token(code)` → `generate_token()`. It writes `TOKEN_FILE` atomically with exactly `{client_id, access_token, created}` (the `login.py` format), runs `FyersProvider(...).check_login()` and clears `providers._fyers_cache`. This works with the user's current redirect (127.0.0.1:8000 is used by Docker). |
| `callback` | Only when the redirect is set to `http://127.0.0.1:8600/api/fyers/callback`. Same as paste, but the browser lands on our endpoint and the UI polls `/api/fyers/status` every 2 s. |
| `window` (legacy) | `subprocess.Popen(['cmd', '/c', str(ROOT/'1_login.bat')], cwd=ROOT, creationflags=CREATE_NEW_CONSOLE)`. Returns immediately; the UI polls status. |

### 6.16 Config and costs

```ts
export interface CostConfig { brokerage_pct: number; brokerage_max: number; stt_pct: number; exchange_pct: number; sebi_pct: number;
  stamp_buy_pct: number; gst_pct: number; dp_per_sell: number; slippage_pct: number; slippage_illiquid_pct: number; illiquid_below_cr: number }
export interface TaxConfig { stcg_pct: number; ltcg_pct: number; ltcg_exempt: number }
export interface ConfigView {
  account: { capital: number; min_position: number };
  data_source: 'auto' | 'yahoo'; fyers_plan: 'standard' | 'prime';
  universe: 'nifty50' | 'nifty100' | 'nifty200' | 'nifty500'; lookback_days: number;
  filters: { min_price: number; min_turnover_cr: number };
  holdings_defaults: { stop_loss_pct: number; target_pct: number };
  results: { warn_days: number }; movers_count: number; etfs: string[];
  costs: CostConfig; tax: TaxConfig;
  allocations: Record<string, number>;     // new optional section: strategy_key -> % of capital
  strategies: Record<string, { enabled: boolean; params: Record<string, number | string | boolean | string[] | null> }>;
  telegram: { top_n: number; configured: boolean };   // configured = env vars present (values never returned)
}
// GET   /api/config -> { values: ConfigView; editable_paths: string[]; file_mtime: ISODateTime; needs_rescan: boolean }
// PATCH /api/config  body: JSON merge patch over ConfigView restricted to editable_paths (P2)
//   -> { saved: true; changed: string[]; needs_rescan: boolean }   errors: VALIDATION with details.path
export interface CostBreakdown { value: number; side: 'buy' | 'sell'; brokerage: number; stt: number; exchange: number; sebi: number;
  stamp: number; gst: number; dp: number; slippage: number; total: number; total_pct: number }
// GET /api/costs/preview?value=33333&profile=delivery|intraday
export interface CostPreviewResponse { profile: 'delivery' | 'intraday'; value: number; buy: CostBreakdown; sell: CostBreakdown; round_trip_pct: number }
```

- `editable_paths` (P2): `account.*`, `allocations.*`, `filters.*`, `holdings_defaults.*`, `results.warn_days`, `movers_count`, `costs.*`, `tax.*`, `strategies.<key>.enabled`, `strategies.<key>.<param>` (only keys already present), `universe`, `data_source`, `fyers_plan`.
- Writes use `ruamel.yaml` round-trip to keep the comments, `tmp + replace` for atomicity, and are refused while a scan runs (409 `SCAN_BUSY`).
- `CostBreakdown` components mirror `CostModel._fees/buy_cost/sell_cost` exactly (slippage = value × slippage_pct, liquid case). The intraday profile is read-only until P3; constants are from catalogue §3a.

### 6.17 Data health

```ts
// GET /api/data/health
export interface DataHealth {
  store: { version: string; first_date: ISODate; last_date: ISODate; symbols: number; trading_days: number; fields: string[]; size_mb: number };
  nse: { status: string | null; complete_upto: ISODate | null };
  failed_symbols: Record<string, string>;            // meta.failed
  stale_symbols: string[]; errors: Record<string, string>;
  corporate_actions_recent: { symbol: string; date: ISODate; factor: number; reason: string }[];   // last 20 by date
  corporate_actions_total: number;
  index_history: { last_date: ISODate | null; columns: number } | null;
  results_calendar: { note: string | null; cached_on: ISODate | null };
  universe: { name: string; note: string; size: number };
  pit: { built: boolean; last_date: ISODate | null; members: number | null } | null;
  journal: { exists: boolean; days: number | null; size_kb: number | null } | null;
  logs: { path: string; size_kb: number; last_error: string | null };
  scans: { count: number; newest: ISODateTime | null; oldest: ISODateTime | null };
}
```

### 6.18 Quotes (P2, optional)

- `GET /api/quotes?symbols=A,B` (max 50) → `{ source: 'fyers' | 'yahoo' | 'cache'; at: ISODateTime; quotes: Record<string, { ltp: number; change_pct: number | null; open: number | null; high: number | null; low: number | null; volume: number | null; prev_close: number | null }> }`
- **Rate-limit guard** (the Fyers Standard plan blocks the user for the day after 3 per-minute breaches):
  - the API makes at most 1 quotes call per 15 s (≤ 4/min), shared across all clients
  - it serves the cache otherwise
  - it makes **no** Fyers calls while `running_scan()`, because the scan subprocess has its own 1.25 s throttle and budgets don't add safely
  - used only for the top-bar ticker and visible watch rows during `session=='open'`

### 6.19 Intraday (contract fixed now, implemented in P3)

```ts
export interface IntradayStatus {
  available: boolean;
  phase: 'not_started' | 'collecting_data' | 'backtesting' | 'live';
  reason: string;                                   // 'No 1-minute bars archived yet'
  coverage: { interval: '1m' | '5m'; symbols: number; first: ISODate | null; last: ISODate | null; days: number }[];
  clock: MarketClock;
  rules: { fo_square_off: string; non_fo_square_off: string; cas_since: ISODate; tax_basis: 'speculative_business_income' };
            // '15:05', '15:20', '2026-08-03'
  websocket: { connected: boolean; symbols: number; max_symbols: 100 };
  costs: CostPreviewResponse | null;                // intraday profile, ₹1,00,000
  sebi: { year: 'FY23'; loss_makers_pct: 71; heavy_traders_loss_pct: 80; cost_adds_to_losses_pct: 57; cost_share_of_profits_pct: 19; source_url: string };
  planned: { id: string; name: string; evidence: Evidence }[];   // catalogue I1..I8
}
export interface IntradayExtras {
  trades_per_day: number | null; avg_minutes_held: number | null; pct_auto_squared: number | null;
  cost_share_of_gross_pct: number | null;
  by_day_type: { day_type: 'normal' | 'expiry' | 'results' | 'event'; trades: number; expectancy_pct: number | null }[];
  sample_days: number; pooled_symbols: number; sharpe_ci95: [number, number] | null;
}
// GET /api/intraday/strategies        -> { as_of: AsOf; strategies: (StrategySummary & { intraday: IntradayExtras })[] }   (horizon='intraday', kind='intraday')
// GET /api/intraday/strategies/{key}  -> StrategyDetail & { intraday: IntradayExtras }
export interface IntradaySignal {
  strategy_key: string; symbol: string; side: 'LONG' | 'SHORT'; triggered_at: ISODateTime;
  entry: number; stop: number; target: number | null; qty: number;
  status: 'pending' | 'open' | 'stopped' | 'target' | 'squared_off' | 'cancelled';
  exit_at: ISODateTime | null; exit_price: number | null; pnl: number | null; square_off_by: string; reason: string;
}
// GET /api/intraday/signals?date=YYYY-MM-DD -> { date: ISODate; session: MarketSession; signals: IntradaySignal[] }
// GET /api/intraday/bars/{symbol}?interval=1m|5m|15m&date=|days=5 -> ChartResponse (tf='5m', source='intraday_store', t = IST-as-UTC seconds)
// GET /api/intraday/watchlist -> { at: ISODateTime; symbols: { symbol: string; reason: string }[]; max: 100 }
```

### 6.20 Pydantic mirror (`web/api/models/*.py`)

Rules:
- Every TS interface above has a same-named `BaseModel`.
- Field names are identical. `T | null` ↔ `T | None = None`. Unions of string literals ↔ `Literal[...]`. `Record<string, X>` ↔ `dict[str, X]`. Tuples `[a, b]` ↔ `tuple[float, float]`.
- All models share `model_config = ConfigDict(extra='ignore', ser_json_inf_nan='null')`.
- Routers declare `response_model=`, so OpenAPI drives `schema.gen.ts`.
- Exception: `ChartResponse` and `CurveResponse` are built as plain dicts with `response_model=None` plus `responses={200: {'model': ChartResponse}}`, which avoids validating ~10k floats per request.

Core models:

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict

Horizon = Literal["intraday", "swing", "longterm"]
StrategyKind = Literal["rank", "event", "intraday"]
StrategyStatus = Literal["working", "mixed", "not-working", "unknown"]
Lifecycle = Literal["active", "disabled", "rejected"]
Evidence = Literal["STRONG", "MODERATE", "WEAK", "FOLKLORE", "EXPERIMENTAL"]
Tone = Literal["good", "neutral", "bad"]
Side = Literal["BUY", "SELL"]

class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", ser_json_inf_nan="null")

class ApiErrorBody(Model):
    code: str; message: str; hint: str | None = None; details: object | None = None
class ApiError(Model):
    error: ApiErrorBody

class AsOf(Model):
    scan_id: str; generated_at: str; elapsed_s: float; data_date: str; live: bool; provisional: bool
    live_source: str | None = None; complete_upto: str | None = None; stale: bool
    backtest_universe: Literal["current_list", "point_in_time"] = "current_list"
    universe_note: str; stocks: int; capital: float; min_position: float | None = None

class PerfStats(Model):
    return_pct: float | None = None; cagr_pct: float | None = None; max_dd_pct: float | None = None
    sharpe: float | None = None; vol_pct: float | None = None; after_tax_cagr_pct: float | None = None

class TradeStats(Model):
    trades: int = 0; win_rate: float | None = None; avg_win_pct: float | None = None; avg_loss_pct: float | None = None
    expectancy_pct: float | None = None; profit_factor: float | None = None; avg_days: float | None = None

class WindowMetrics(PerfStats, TradeStats):
    benchmark: PerfStats | None = None; ew_benchmark: PerfStats | None = None
    n500_benchmark: PerfStats | None = None; factor_benchmark: PerfStats | None = None

class FullMetrics(WindowMetrics):
    exposure_pct: float | None = None; start: str; end: str; after_tax_return_pct: float | None = None
    cagr_range: tuple[float, float] | None = None; te_n500_pct: float | None = None; factor_benchmark_name: str | None = None

class StrategyMetrics(Model):
    full: FullMetrics; m12: WindowMetrics | None = None; m6: WindowMetrics | None = None; m3: WindowMetrics | None = None

class Edges(Model):
    vs_ew_cagr_pct: float | None = None; vs_n500_cagr_pct: float | None = None; vs_nifty_cagr_pct: float | None = None
    vs_factor_cagr_pct: float | None = None; primary: Literal["ew", "nifty"]
    r12m_vs_n500_pct: float | None = None; r6m_vs_n500_pct: float | None = None

class TimingRange(Model):
    base_cagr_pct: float | None = None; low: float | None = None; high: float | None = None
    consistent: bool; method: Literal["rebalance_offsets", "start_offsets"]; note: str

class Headline(Model):
    cagr_pct: float | None = None; after_tax_cagr_pct: float | None = None; max_dd_pct: float | None = None
    sharpe: float | None = None; vol_pct: float | None = None; win_rate: float | None = None; trades: int = 0
    exposure_pct: float | None = None; avg_days: float | None = None; ret_12m_pct: float | None = None
    ret_6m_pct: float | None = None; ret_3m_pct: float | None = None; n500_12m_pct: float | None = None

class Counts(Model):
    orders_buy: int; orders_sell: int; positions: int; max_positions: int

class PaperPulse(Model):
    return_pct: float | None = None; days: int; level: Tone

class StrategySummary(Model):
    key: str; name: str; description: str; kind: StrategyKind; horizon: Horizon; evidence: Evidence
    universe: Literal["stocks", "etfs"] = "stocks"; lifecycle: Lifecycle = "active"
    status: StrategyStatus; status_reason: str; rejected_reason: str | None = None
    headline: Headline; edges: Edges; timing: TimingRange | None = None; benchmark_name: str | None = None
    counts: Counts; per_position: float | None = None; rebalance: str | None = None; next_rebalance: str | None = None
    uses_regime_filter: bool; blocked_by_regime: bool; spark: list[float]; paper: PaperPulse | None = None
    source: Literal["scan", "catalogue"] = "scan"

class Order(Model):
    strategy_key: str; strategy_name: str; strategy_status: StrategyStatus; horizon: Horizon
    action: Side; symbol: str; company: str | None = None; industry: str | None = None; reason: str
    price: float | None = None; qty: int; amount: float | None = None; stop: float | None = None
    stop_distance_pct: float | None = None; risk_amount: float | None = None
    results_on: str | None = None; results_in_days: int | None = None; results_warning: bool = False
    provisional: bool = False; below_min_position: bool = False
    model_qty: int | None = None; you_hold_qty: float | None = None

class HoldingInput(Model):
    symbol: str; qty: float | None = None; buy_price: float | None = None; buy_date: str | None = None
    stop_loss_pct: float | None = None; target_pct: float | None = None

class ScanStatus(Model):
    state: Literal["idle", "starting", "running", "done", "failed", "busy"]; running: bool
    progress: float | None = None; message: str | None = None; started_at: str | None = None
    elapsed_s: float | None = None; by: str | None = None; pid: int | None = None; update: bool | None = None
    last_scan_id: str | None = None; exit_code: int | None = None

class FyersStatus(Model):
    configured: bool; client_id_masked: str | None = None; plan: Literal["standard", "prime"]
    data_source: Literal["auto", "yahoo"]; token_present: bool; token_created: str | None = None
    logged_in_today: bool; verified: bool | None = None; verified_at: str | None = None; user_name: str | None = None
    live_prices: Literal["fyers", "yahoo_delayed"]; redirect_uri: str
    login_modes: list[Literal["paste", "callback", "window"]]; note: str
# ... the remaining models (Overview*, Signals*, Screener*, Chart*, Holdings*, Paper*, Market*, Config*, DataHealth,
#     Intraday*) are mechanical 1:1 transcriptions of the TS blocks above and live in the matching modules.
```

### 6.21 Caching and process model (`web/api/caches.py`)

| Cache | Key | Loader |
|---|---|---|
| `latest` | mtime of `latest.json` | `daily.load_latest()` → normalise (rename windows `12m`→`m12`, fill defaults: horizon `rank→longterm, event→swing`, `evidence ''→'EXPERIMENTAL'`, lifecycle `active`) |
| `curves` | mtime of `curves.parquet` | `daily.load_curves()` |
| `trades` / `screener` | file mtimes | `pd.read_parquet` (absent → feature flag false) |
| `store` | `PanelStore().version()` (re-checked at most every 2 s) | `store.load_store()` (~50 MB RAM) |
| `panel` / `factors` | store version | `panel_from_wide(frames, universe symbols)` + `Factors(p)`: breadth, industries, screener fallback, stock snapshot |
| `paper` | (store version, journal mtime, `json.dumps(cfg['costs'], sort_keys=True)`) | `paper.build_report(store, CostModel.from_config(...))` (identical to `app.py`) |
| `config` | mtime of `config.yaml` | `settings.load_config()`; `build_strategies(cfg)` for rules |
| `universe` | 7-day file | `universe.get_universe(cfg['universe'])` |

- Each cache has a `threading.Lock` so concurrent requests don't recompute.
- Routes are plain `def` (FastAPI runs them in its threadpool), because pandas work is blocking.
- **Warm-up:** on startup, a background thread loads latest → curves → store → factors, so the first chart opens in under 400 ms after a ~2 s warm-up.
- Logs go to `data/logs/api.log` (rotating 1 MB × 3).
- **Performance budgets:** latest-derived endpoints p95 < 150 ms; chart (warm) < 300 ms; breadth (warm) < 200 ms; initial JS < 300 KB gzip; route chunks lazy.

---

## 7. Frontend architecture notes

- **`api/client.ts`:**
  - `fetchJson<T>(path, init)`: adds `X-Quant-Desk: 1` on non-GET, parses the `ApiError` envelope into `class ApiFailure { code, message, hint, status }`
  - network failure → `code: 'OFFLINE'`, which drives the global banner
- **`api/keys.ts`:** query keys include `scan_id` where relevant; `hooks.ts` exports `useStatus`, `useOverview`, `useStrategies(h)`, `useStrategy(key)`, `useCurve(key, range)`, `useTrades(key, params)`, `useSignals(params)`, `useScreener(params)`, `useChart(symbol, params)`, `useStock(symbol)`, `useHoldings`, `useSaveHoldings`, `usePaper`, `usePaperDetail`, `useMarket*`, `useScan`, `useStartScan`, `useFyers*`, `useConfig`, `useCostPreview`, `useDataHealth`, `useIntradayStatus`.
- **ScanWatcher** (in the AppShell): when `status.latest.scan_id` changes → `invalidateQueries()`, plus a toast with the diff count from overview `changes`.
- **Theme:**
  - `<html class="dark|light" data-cvd="on|off" data-density="comfortable|compact">`
  - the initial value is set by an inline script in `index.html` (localStorage → `prefers-color-scheme`) before React mounts, to avoid a flash
  - charts subscribe to a `themeVersion` context and re-apply their options
- **Component inventory:**
  - layout: `AppShell, Rail, TopBar, StatusBar, CommandPalette`
  - data: `DataTable, Num, Price, Money, Pct, Pts, Delta, Sparkline, KpiTile, Card, Tabs, Segmented, Chip, StatusBadge, EvidenceChip, HorizonChip, SidePill, LevelPill, ResultsChip, ProvisionalChip`
  - charts: `PriceChart, EquityChart, DrawdownChart, BreadthChart, YearlyHeatmap, MonthlyHeatmap, TimingRangeBar, ReturnHistogram, EvidenceMeter, AdBar, RangeBar52w`
  - feedback: `Skeleton*, EmptyState, ErrorState, FeatureUnavailable, Banner, Toast`
- **Tests (vitest):** `format.ts` (Indian grouping, minus sign, null), `sizing` parity fixtures, `toLwcTime` (IST-as-UTC), heatmap bucketing.
- **Backend tests (pytest):** a fixture copy of the real `latest.json` + `curves.parquet` in `tests/fixtures/`. Every router returns a model-valid response. Also test the `SCAN_BUSY` path (mock `running_scan`), the CSRF header guard, Host guard, the holdings PUT round-trip into a temp `HOLDINGS_FILE`, and Fyers paste-flow code extraction.

---

## 8. Build order and acceptance

**Phase 1: replace `app.py` (parity plus the new layout)**
1. API: system, overview, strategies (+curve/trades fallback), signals, holdings, paper, market (movers/sectors/factors/results/breadth), chart (daily), scan, fyers (paste + window), config GET, costs preview, data health, intraday status placeholder.
2. Backend additions B1, B3, B5, B6 (merge main), the timing-cache fix (§1.3.1) and the SELL-qty fix in the API.
3. UI: shell, Overview, Strategies + detail, Signals, Chart, Portfolio, Paper, Market, Settings (read-only config), Intraday placeholder.
4. Acceptance:
   - everything in the Streamlit app is reachable
   - the provisional, stale, first-run, server-down, scan-busy and scan-failed states each render correctly
   - 1280×800 and 1440×900 have no overflow; 375 px is usable
   - dark and light pass the contrast table
   - keyboard: Ctrl+K, `g` shortcuts, table `j/k/Enter`
   - no fabricated numbers: every value traces to an endpoint/source in §6.2

**Phase 2:**
- B2 screener artifact, B4 rejected strategies, B8 validation card
- config PATCH (ruamel) with allocations editor
- quotes ticker (guarded)
- Fyers callback mode
- weekly chart polish, CSV exports

**Phase 3 (intraday):**
- 1-min archive job (prototype `IntradayStore`)
- intraday engine with MIS cutoffs, the CAS split and the intraday cost/tax profile (catalogue §3a, §7)
- `/api/intraday/*` live; 5-min chart; session board; WebSocket for ≤ 100 in-play symbols

**Explicitly out of scope** (no data or not appropriate; never faked): order placement, market depth, option chains, fundamentals/valuation, news, social sentiment. Orders are copied into the Fyers app by the user.

---

## 9. Open questions and risks

1. **React 18 vs 19:** the scaffold installed 19.3.1. This spec pins 18.3.1 per the brief. If the team prefers to keep 19, every other pin above is compatible. Decide once, before the first page.
2. **Allocations:** the new `config.yaml` `allocations:` section must also be read by `daily.py` before order sizing in `latest.json` matches the platform. Until then, only the API re-sizes, and `latest.json` and Telegram stay at full capital per strategy.
3. **Paper module churn:** the `paper-json` session may change field names. The router maps fields defensively, and the contract in 6.11 is what the UI relies on.
4. **Survivorship flag:** `backtest_universe` must flip to `point_in_time` only when the PIT session's universe actually drives the daily scan. At that point the bias banner disappears and "edge vs average stock" stays the primary column.
5. **Fyers rate limits:** the API makes no Fyers data calls during scans. Quotes polling (P2) must stay ≤ 4/min, or the user risks a day-long block.
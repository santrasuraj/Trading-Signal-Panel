# Smart money - build contract (v1)

Feature: show which stocks big investors (FIIs/FPIs, mutual funds, insurers, banks, pension/sovereign funds,
promoters, well-known individual investors) are **buying or selling**, and which stocks they **exited**, from NSE's
official disclosures. Three builders implement it in parallel from this document alone. Every name, column, field,
type and unit below is binding. When this document and your instinct disagree, follow this document.

Honesty rule (applies to every layer): this is **disclosed** data. It is not live, not a prediction and not a tip.
Never invent a number: unknown stays `NaN` in pandas and `null` in JSON. Never default an unknown side to BUY. Never
call something an "exit" unless the source can show it (section 4.8.4 says what each source can prove).

---------------------------------------------------------------------------------------------------------------------

## 0. Who builds what

| Builder | Creates (NEW files only) |
|---|---|
| **A - data** | `scanner/smart_money.py`, `tests/test_smart_money.py` |
| **B - API** | `web/api/models/smart_money.py`, `web/api/services/smart_money_svc.py`, `web/api/routers/smart_money.py` |
| **C - UI** | `web/ui/src/api/smartMoney.ts`, `web/ui/src/pages/SmartMoney.tsx`, `web/ui/src/components/SmartMoneyPanel.tsx` |

Hard rules for every builder:

- Do **not** run any command (no python, pytest, npm, git, servers, browser). Write the code by reading, re-read
  every file you write for syntax, imports, types and unused names, and say in your summary that it is unverified.
- Do **not** edit any existing file. Wiring (router registration, nav, route, Chart side panel, daily scan,
  Telegram, openapi.json) is listed in section 9 and happens later.
- Never touch `data/`, `.env`, `.venv`, `node_modules`, `web/ui/dist`, `.worktrees/`.
- Match the existing style: module docstring that says what the file does and where its data comes from,
  `from __future__ import annotations`, short comments only where the reason is not obvious, plain `def` routes,
  2-space TS with single quotes and no semicolons, `@/` imports.
- Python 3.12, pandas 3.1 (copy-on-write: never chained assignment; string columns come back from parquet as
  Arrow-backed `str` dtype and **missing strings are NaN, not None** - always test with `pd.isna`), requests,
  pydantic v2, FastAPI. No new dependencies (XML via `xml.etree.ElementTree`, gzip via `gzip`).
- TypeScript is `strict`, `noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax` (type-only imports must
  use `import type`), `erasableSyntaxOnly` (no `enum`, no parameter properties). React 18.3, react-router-dom 6.28,
  TanStack Query 5.62, TanStack Table 8.21, lucide-react 0.468, Tailwind 3.4. No new packages.

---------------------------------------------------------------------------------------------------------------------

## 1. Conventions (all layers)

- **Dates** are ISO strings `'YYYY-MM-DD'` (IST trading/disclosure dates) everywhere: in pandas columns (dtype
  `str`, missing = NaN), in JSON and in TS (`ISODate`). Comparing ISO strings lexically is correct and is how
  windows are applied. Date-times are ISO-8601 with `+05:30` (`'2026-10-23T19:05:12+05:30'`).
- **Money** is in **rupees** (float) - deal values, insider values, prices. The only exception: FII/DII daily
  flows are in **crore**, as NSE publishes them, and every such field ends in `_cr`.
- **Percent** fields are percent units (`6.0` = 6%), never fractions. `*_pct` = percent of the company's shares.
  `*_pts` / `change_pts` = change in percentage points.
- **Quantities** are shares. Stored as float64 in pandas, sent as JSON integers.
- **Window** of `days` ending at an anchor date `A` (inclusive): `since = A - (days - 1) calendar days`. `days=1`
  means "the anchor day only". Function `window(as_of, days)` in section 4.8.
- **Categories** (slugs used in data, API and UI):

| slug | label (`CATEGORY_LABELS`) | group |
|---|---|---|
| `fii` | FII/FPI | institution |
| `mf` | Mutual fund | institution |
| `insurance` | Insurance | institution |
| `bank` | Bank/NBFC | institution |
| `pension` | Pension/sovereign | institution |
| `promoter` | Promoter | big money |
| `famous` | Well-known investor | big money |
| `broker` | Broker/prop | (not big money) |
| `other` | Other | (not big money) |

  `INSTITUTIONS = {fii, mf, insurance, bank, pension}`; `BIG_MONEY = INSTITUTIONS | {promoter, famous}`.
  Category filter values (API `category` param): `all`, `big` (= BIG_MONEY), `institutions` (= INSTITUTIONS), or one
  slug.

---------------------------------------------------------------------------------------------------------------------

## 2. Scope

**In v1:** bulk deals and block deals (daily archive files + historical backfill), insider trades (SEBI PIT
Reg 7(2): promoters, directors, KMP), FII/DII daily cash-market net (market-wide), quarterly shareholding pattern
(category % and named holders with 1% or more) for the scan universe + your holdings.

**Not in v1** (do not build): SAST Reg 29 filings, pledge/encumbrance API, short selling, NSDL FPI history,
F&O participant OI, live block-deal window API, BSE data.

---------------------------------------------------------------------------------------------------------------------

## 3. Data sources (what builder A calls)

All requests go through one function, `_fetch` (section 4.2). Two kinds of host:

**Archive host (no cookies)** - `api=False`, plain GET via `scanner.nse._get_bytes(url)` (thread-local session,
`nse.HEADERS`: browser User-Agent, Referer `https://www.nseindia.com/`):

| name | URL | notes |
|---|---|---|
| bulk | `https://nsearchives.nseindia.com/content/equities/bulk.csv` | latest trading day only; overwritten daily |
| block | `https://nsearchives.nseindia.com/content/equities/block.csv` | same; header-only file is normal |
| SHP XBRL | the `xbrl` URL of a shareholding filing (`https://nsearchives.nseindia.com/corporate/xbrl/SHP_..._WEB.xml`) | immutable: cache forever |

bulk.csv header: `Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks`
(block.csv: same without Remarks). May start with a UTF-8 BOM; quantities may contain commas (`"1,08,709"`);
dates are `DD-MON-YYYY` with mixed case (`23-OCT-2026`, `23-Oct-2026`); Remarks `-` means empty. On holidays the
file still holds the last trading day: always store the date **inside** the file.

**NSE API (cookies needed)** - `api=True`, base `API = "https://www.nseindia.com/api/"`:

| name | path + params | Referer page | response |
|---|---|---|---|
| deals history | `historicalOR/bulk-block-short-deals` `{"optionType": "bulk_deals" or "block_deals", "from": "DD-MM-YYYY", "to": "DD-MM-YYYY", "csv": "true"}` (max 365 days per call; we use one calendar month) | `https://www.nseindia.com/report-detail/display-bulk-and-block-deals` | CSV `"Date","Symbol","Security Name","Client Name","Buy / Sell","Quantity Traded","Trade Price / Wght. Avg. Price","Remarks"`; or JSON `{"data": [{"BD_DT_DATE", "BD_SYMBOL", "BD_SCRIP_NAME", "BD_CLIENT_NAME", "BD_BUY_SELL", "BD_QTY_TRD", "BD_TP_WATP", "BD_REMARKS"}]}`. Empty = header-only CSV or `{"data": []}` (normal). |
| large deals snapshot (fallback only) | `snapshot-capital-market-largedeal` (no params) | `https://www.nseindia.com/market-data/large-deals` | `{"as_on_date", "BULK_DEALS_DATA": [...], "BLOCK_DEALS_DATA": [...], ...}`, row keys `date, symbol, name, clientName, buySell ('BUY'/'SELL'/'B'/'S'), qty, watp, remarks` (numbers may be strings) |
| insider (PIT) | `corporates-pit` `{"index": "equities", "from_date": "DD-MM-YYYY", "to_date": "DD-MM-YYYY"}` | `https://www.nseindia.com/companies-listing/corporate-filings-insider-trading` | `{"acqNameList": [...], "data": [row...]}` (or a bare list) - keys in 4.4.3 |
| FII/DII | `fiidiiTradeReact` (no params) | `https://www.nseindia.com/reports/fii-dii` | list of 2 rows `{"category": "DII **" or "FII/FPI *", "date": "23-Oct-2026", "buyValue", "sellValue", "netValue"}` (strings, Rs crore) |
| SHP filings list | `corporate-share-holdings-master` `{"index": "equities", "from_date", "to_date"}` (date-range mode) or `{"index": "equities", "symbol": "XYZ"}` (per-symbol mode) | `https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern` | list (or `{"data": [...]}`) of `{"symbol", "name", "date": "30-SEP-2026", "xbrl", "revisedData": "N", "recordId": 2001, "pr_and_prgrp": 50.0, "public_val": 50.0, "submissionDate": "15-OCT-2026", "broadcastDate": "15-OCT-2026 10:10:10", ...}` |

Publication timing (for UI text and scheduling): bulk/block after the close (~6:30-7 PM IST); FII/DII provisional,
same evening; insider filings any time, up to ~4 trading days after the trade; shareholding within 21 days of each
quarter end.

---------------------------------------------------------------------------------------------------------------------

## 4. Data layer: `scanner/smart_money.py` (builder A)

Module docstring: one paragraph naming the sources (section 3), the cache folder, and "network failures never
raise: refresh() records them and the loaders return whatever is cached".

### 4.1 Imports, constants, paths

```python
from __future__ import annotations

import functools, gzip, io, json, math, re, threading, time          # (one import per line in the real file)
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, NamedTuple

import numpy as np
import pandas as pd
import requests

from . import nse
from .events import HEADERS as API_HEADERS
from .lock import _try_lock, _unlock
from .settings import DATA_DIR, IST, ist_now, ist_today, load_config
```
(Keep only the imports you use; `scanner.holdings` is imported inside `_default_symbols` to keep imports light.)

Constants (exact names and values):

```python
SM_DIR = DATA_DIR / "smart_money"           # NOT created at import; refresh() creates it
API = "https://www.nseindia.com/api/"
HOME = "https://www.nseindia.com/"
BULK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
PAGES = {
    "deals": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
    "large": "https://www.nseindia.com/market-data/large-deals",
    "pit": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    "fiidii": "https://www.nseindia.com/reports/fii-dii",
    "shp": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
API_GAP_S = 0.4              # at least this long between two NSE API requests
SESSION_MAX_AGE_S = 420      # re-warm the NSE cookies after 7 minutes
ROUND_TRIP_RATIO = 0.8       # min(buy, sell) / max(buy, sell) at or above this = intraday round trip
HOLDER_MIN_CHANGE_PTS = 0.25 # named-holder stake change that counts as added / cut
CATEGORY_MIN_CHANGE_PTS = 1.0  # category (FII, MF, ...) change that counts as up / down
SHP_LISTING_DAYS = 200       # how far back the shareholding filings list is read
SHP_EVENT_DAYS = 120         # shareholding changes stay "news" this long after the filing
SHP_MAX_GAP_DAYS = 200       # two periods further apart than this are not compared
MAX_SYMBOL_LOOKUPS = 80      # per-symbol shareholding lookups per refresh
RECHECK_DAYS = 7             # failed XBRL / per-symbol lookups are retried after this many days
PAST_MONTH_GRACE_DAYS = 7    # a month whose last day is older than this is final (never re-fetched)
XBRL_WORKERS = 4
XBRL_MAX_FAILURES = 10       # consecutive download failures that stop the XBRL step for this refresh
LOCK_GRACE_S = 2.0           # refresh_running() probes hold the lock for an instant: don't mistake one for a refresh
QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}

CATEGORIES = ("fii", "mf", "insurance", "bank", "pension", "promoter", "famous", "broker", "other")
CATEGORY_LABELS = {"fii": "FII/FPI", "mf": "Mutual fund", "insurance": "Insurance", "bank": "Bank/NBFC",
                   "pension": "Pension/sovereign", "promoter": "Promoter", "famous": "Well-known investor",
                   "broker": "Broker/prop", "other": "Other"}
INSTITUTIONS = frozenset({"fii", "mf", "insurance", "bank", "pension"})
BIG_MONEY = INSTITUTIONS | {"promoter", "famous"}
ODI_LABEL = "ODI/arbitrage desk - often hedging clients, weak signal"
LIKELY_PROMOTER = "Likely promoter (name match)"
INSIDER_LABEL = "Company insider (director/KMP)"
```

`files(folder: Path | None = None) -> dict[str, Path]` - the only place paths are built, **at call time** from
`folder or SM_DIR` (tests pass `tmp_path`; never capture paths at import):

```python
{"deals": f / "deals.parquet", "insider": f / "insider.parquet", "flows": f / "flows.parquet",
 "holdings": f / "holdings.parquet", "holders": f / "holders.parquet", "filings": f / "shp_filings.parquet",
 "state": f / "state.json", "unmatched": f / "unmatched_names.json"}
```
plus the folder `f / "xbrl"` (raw XBRL cache, `SHP_<record_id>.xml.gz`) and the lock file `f / ".refresh.lock"`.
Every public function below takes `folder: Path | None = None` where it touches files.

Atomic writes (helpers, private): `_save_parquet(df, path)` writes `path.name + ".tmp"` with
`df.reset_index(drop=True).to_parquet(tmp, index=False)` then `tmp.replace(path)`; `_save_json(obj, path)` the same
with `json.dumps(obj, ensure_ascii=False, indent=1)`, UTF-8. On `PermissionError` from `replace` (Windows: a
reader has the file open) retry up to 5 times, 0.2 s apart, then re-raise.

### 4.2 Network seam

```python
def _fetch(url: str, params: dict | None = None, *, api: bool = False, referer: str | None = None) -> tuple[int, bytes]:
```

- **Every** network call in the module goes through the module-level name `_fetch`, looked up at call time (tests
  do `monkeypatch.setattr(smart_money, "_fetch", fake)`). Nothing else may call requests or `nse._get_bytes`.
- `api=False`: `return nse._get_bytes(url)` (params are never used for archive URLs).
- `api=True`: `_api_get(url, params, referer)`:
  - Module state: `_api_session: requests.Session | None`, `_api_warm_at: float`, `_api_last: float`,
    `_api_blocked: bool`, `_api_fail_streak: int`, `_api_lock = threading.Lock()`. `_reset_api()` sets
    `_api_blocked = False`, `_api_fail_streak = 0` (called at the start of each `refresh`).
  - Whole call under `_api_lock` (one API request at a time). If `_api_blocked`: return `(-2, b"")` immediately.
  - Session: created with `API_HEADERS`; warm-up = `GET HOME` (timeout 15, exceptions ignored), also when the
    session is older than `SESSION_MAX_AGE_S` (clear cookies first). Request headers: `{"Referer": referer}` when
    given.
  - Up to 3 attempts. Before each, sleep so that `API_GAP_S` has passed since `_api_last`. `GET` with
    `timeout=25`. `requests.RequestException` -> sleep `1.5 * (attempt + 1)`, next attempt.
  - 401/403 on the first attempt: clear cookies, warm up again (`HOME`, then `referer` if given), retry.
  - 200: reset `_api_fail_streak`, return `(200, r.content)`.
  - 401/403 after the retry, or 429: set `_api_blocked = True` (stop all NSE API calls for this refresh - never
    hammer), return `(status, b"")`.
  - 404: return `(404, b"")`. Other codes: sleep `1.5 * (attempt + 1)` and retry.
  - After 3 failed attempts: `_api_fail_streak += 1`; when it reaches 3 set `_api_blocked = True`; return
    `(last_status or -1, b"")`.
- Callers treat `-2` as "blocked: skip the rest of this source" and any non-200 as a failure of that one request.

### 4.3 Stored tables (exact columns and dtypes)

`str` = pandas string/object column (missing = NaN). `float` = float64. All dates ISO strings (section 1).
Loaders always return exactly these columns, in this order, also when the file is missing or unreadable (empty
frame built with `pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLS.items()})`). Define each as a module
dict `NAME_COLS: dict[str, str]` (column -> dtype string: `"object"`, `"float64"`, `"int64"`, `"bool"`).

**`DEAL_COLS`** - `deals.parquet`, one row per raw NSE deal line (after dedupe):

| column | dtype | meaning |
|---|---|---|
| date | object | ISO trade date |
| kind | object | `"bulk"` or `"block"` |
| symbol | object | upper-case NSE symbol |
| security | object | Security Name as filed (NaN if empty) |
| client | object | client name as filed, internal whitespace collapsed |
| client_key | object | `parent_key(client)` |
| side | object | `"BUY"` / `"SELL"` |
| qty | float64 | shares (> 0) |
| price | float64 | Rs, weighted average (NaN if missing) |
| value | float64 | `qty * price` (NaN if price NaN) |
| remarks | object | NaN when `-` or empty |
| source | object | `"archive"` (bulk.csv/block.csv), `"history"` (historicalOR), `"snapshot"` |

Dedupe key: `(date, symbol, client_key, side, qty, round(price, 2))` across kinds; when a line exists as both
block and bulk keep the **block** row (sort by `kind` rank block=0, bulk=1, then `drop_duplicates(keep="first")`).
Stored sorted by date desc, symbol, client.

**`INSIDER_COLS`** - `insider.parquet` (stored):

| column | dtype | from PIT key | notes |
|---|---|---|---|
| symbol | object | `symbol` | upper |
| company | object | `company` | |
| person | object | `acqName` | whitespace collapsed |
| person_key | object | | `normalise_name(person)` |
| person_category | object | `personCategory` | as filed |
| sec_type | object | `secType` | |
| txn | object | `tdpTransactionType` | as filed |
| side | object | | `"BUY"`/`"SELL"`/NaN (4.4.3) |
| mode | object | `acqMode` | as filed |
| mode_kind | object | | 4.4.3 |
| qty | float64 | `secAcq` | > 0 |
| value | float64 | `secVal` | Rs, NaN if not given |
| before_shares | float64 | `befAcqSharesNo` | |
| before_pct | float64 | `befAcqSharesPer` | |
| after_shares | float64 | `afterAcqSharesNo` or `aftAcqSharesNo` | |
| after_pct | float64 | `afterAcqSharesPer` or `aftAcqSharesPer` | |
| trade_from | object | `acqfromDt` | ISO |
| trade_to | object | `acqtoDt` | ISO |
| intimated | object | `intimDt` | ISO (company told) |
| disclosed | object | `date` (date part) | ISO; falls back to `intimated` |
| disclosed_at | object | `date` | ISO datetime +05:30 or NaN |
| exchange | object | `exchange` | |
| xbrl | object | `xbrl` | URL or NaN |

Dedupe key `(symbol, person_key, trade_from, qty, txn.lower())`, keep the row with the latest `disclosed_at`
(revised filings repeat earlier ones). Sorted by disclosed desc.

`load_insider()` adds (enrichment, not stored) **`INSIDER_EXTRA_COLS`**:
`id` (object), `role` (object: `"promoter"|"insider"|"other"`), `category` (object), `sub_label` (object),
`investor` (object), `avg_price` (float64: value/qty when both > 0), `change_pts` (float64: after_pct -
before_pct), `is_market` (bool), `fully_exited` (bool), `delay_days` (float64: calendar days disclosed - trade_to).

**`FLOW_COLS`** - `flows.parquet`, one row per date, sorted by date asc:
`date` (object), `fii_buy_cr`, `fii_sell_cr`, `fii_net_cr`, `dii_buy_cr`, `dii_sell_cr`, `dii_net_cr` (float64).

**`FILING_COLS`** - `shp_filings.parquet` (the filings list), dedupe on record_id (keep last):
`symbol`, `company`, `period` (ISO quarter end), `record_id` (int64), `xbrl`, `broadcast` (ISO datetime),
`submission` (ISO), `revised` (bool), `promoter_pct`, `public_pct` (float64).

**`HOLDING_COLS`** - `holdings.parquet`, one row per parsed filing (dedupe on record_id; prefer
`source == "xbrl"` over `"master"`):
`symbol`, `company`, `period`, `record_id` (int64), `broadcast`, `source` (`"xbrl"` = parsed XBRL, `"master"` =
only the list's promoter/public %), `total_shares` (float64), `promoter_pct`, `public_pct`, `fii_pct`, `dii_pct`,
`mf_pct`, `insurance_pct`, `banks_pct`, `pension_pct`, `aif_pct` (float64).

**`HOLDER_COLS`** - `holders.parquet` (named holders of xbrl filings), stored:
`symbol`, `period`, `record_id` (int64), `holder` (as filed), `holder_key` (`normalise_name(holder)`), `group`
(`"promoter"|"public"`), `xbrl_member` (local name of the category member or typed axis), `shares` (float64),
`pct` (float64). `load_holders()` adds `category`, `sub_label`, `investor` (4.5.4).

**`state.json`** (written by refresh; `load_state()` returns `{}`-safe defaults):

```json
{
  "version": 1,
  "last_run": {"started_at": "2026-10-23T19:02:01+05:30", "finished_at": "2026-10-23T19:05:12+05:30",
               "elapsed_s": 191.2, "ok": true, "days": 365},
  "sources": {"deals": SOURCE, "insider": SOURCE, "flows": SOURCE, "holdings": SOURCE},
  "errors": ["holdings: 12 shareholding files could not be downloaded (will retry)"],
  "deals_months_done": {"bulk": ["2026-09", "2026-08"], "block": ["2026-09"]},
  "insider_months_done": ["2026-09"],
  "shp_months_done": ["2026-09"],
  "shp_failed": {"2001": "2026-10-23"},
  "shp_symbol_checked": {"XYZ": "2026-10-23"}
}
```
`SOURCE = {"status": "ok"|"partial"|"failed"|"skipped", "message": str, "rows_added": int,
"last_ok_at": ISO datetime|null, "latest_date": ISO|null}`.

**`unmatched_names.json`**: `{"updated": ISO datetime, "names": [{"name": str, "count": int}, ...]}` - top 300
deal client names (as filed) whose classification is `other/Unclassified`, by number of raw rows.

### 4.4 Parsers (public, pure, used by refresh and by the tests)

Shared private helpers (exact behaviour):

- `_to_num(x) -> float`: None/NaN -> NaN; `str(x).replace(",", "").strip()`; `''`, `'-'`, `'nil'`, `'na'`,
  `'n.a.'`, `'none'`, `'null'` (case-insensitive) -> NaN; else `float()`, ValueError -> NaN.
- `_iso(x) -> str | None`: date only. Strip, take the part before a space or `T` only if the full string fails;
  try formats `%d-%b-%Y`, `%d-%B-%Y`, `%d-%m-%Y`, `%Y-%m-%d`, `%d/%m/%Y`, then the datetime formats of `_iso_dt`;
  return `date.isoformat()` or None. (`strptime` `%b` is case-insensitive: `23-OCT-2026` works.)
- `_iso_dt(x) -> str | None`: formats `%d-%b-%Y %H:%M:%S`, `%d-%b-%Y %H:%M`, `%d-%m-%Y %H:%M:%S`, `%d-%m-%Y %H:%M`,
  `%Y-%m-%dT%H:%M:%S`, `%Y-%m-%d %H:%M:%S`; result `datetime.replace(tzinfo=IST).isoformat(timespec="seconds")`;
  a date-only string -> that date at `00:00:00+05:30`; else None.
- `_text(x) -> str | None`: None/NaN -> None; `" ".join(str(x).split())`; `''` or `'-'` -> None.
- `_records(payload) -> list[dict]`: bytes -> decode `"utf-8-sig"` (strips the BOM), strip; text starting with `{`
  or `[` -> `json.loads`; a dict -> its `"data"` value if a list, else `[]`; a list -> itself (dict items only);
  other text -> CSV via `pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False).to_dict("records")`;
  empty text or a `pd.errors.EmptyDataError` -> `[]`.
- `_key(name) -> str`: header key normaliser `re.sub(r"[^a-z0-9]", "", str(name).lower())`.

#### 4.4.1 `parse_deals(payload, kind: str, source: str) -> pd.DataFrame` (DEAL_COLS)

`payload`: bytes/str (CSV or JSON) or a list/dict. Rows from `_records(payload)`. Map each row's keys with
`_key()` through:

```python
DEAL_KEYS = {"date": "date", "bddtdate": "date", "symbol": "symbol", "bdsymbol": "symbol",
             "securityname": "security", "bdscripname": "security", "name": "security",
             "clientname": "client", "bdclientname": "client", "buysell": "side", "bdbuysell": "side",
             "quantitytraded": "qty", "bdqtytrd": "qty", "qty": "qty",
             "tradepricewghtavgprice": "price", "bdtpwatp": "price", "watp": "price",
             "remarks": "remarks", "bdremarks": "remarks"}
```
(Header spaces, `/`, `.` and case all vanish under `_key`, so `Buy / Sell`, `Buy/Sell` and `buySell` all become
`buysell`.) Side: upper-stripped value `BUY`/`B`/`PURCHASE` -> `"BUY"`, `SELL`/`S`/`SALE` -> `"SELL"`, anything
else -> **drop the row** (never default to BUY). Drop rows with no date, no symbol, no client, or qty NaN/<= 0.
`value = qty * price`. `client_key = parent_key(client)`. Returns the empty DEAL_COLS frame when nothing is left.

`parse_large_deals(payload) -> pd.DataFrame`: the snapshot JSON; `parse_deals(obj["BULK_DEALS_DATA"], "bulk",
"snapshot")` + `parse_deals(obj["BLOCK_DEALS_DATA"], "block", "snapshot")` (missing keys -> empty).

#### 4.4.2 `parse_fiidii(payload) -> pd.DataFrame` (FLOW_COLS)

For each record: `cat = str(category).strip().upper()`; `"FII" in cat or "FPI" in cat` -> prefix `fii`, elif
`"DII" in cat` -> `dii`, else skip. `date = _iso(r["date"])` (skip if None). Values via `_to_num` of `buyValue`,
`sellValue`, `netValue` into `<prefix>_buy_cr`, `_sell_cr`, `_net_cr`. One output row per date (missing side's
columns NaN).

#### 4.4.3 `parse_pit(payload) -> pd.DataFrame` (INSIDER_COLS)

Read keys exactly as in the INSIDER_COLS table; `_first(r, *keys)` returns the first key present with a
non-empty value (for the `afterAcq*`/`aftAcq*` spellings). Numbers via `_to_num` (strings, commas, `-`, `Nil`).

- `side`: `t = (txn or "").lower()`; `"buy" in t or "acqui" in t or "purchase" in t` -> BUY; `"sell" in t or
  "sale" in t or "dispos" in t` -> SELL; else from `m = (mode or "").lower()`: `"purchase" in m` -> BUY,
  `"sale" in m` -> SELL; else NaN.
- `mode_kind` from `m = (mode or "").lower()`, first match wins:
  1. `"invocation" in m or "invoke" in m` -> `pledge_invoked`
  2. `"pledge" in m or "revok" in m or "encumb" in m` -> `pledge`
  3. `"off market" in m or "off-market" in m` -> `off_market`
  4. `"market" in m` -> `market`
  5. `"esop" in m or "esos" in m or "employee stock" in m` -> `esop`
  6. `"gift" in m` -> `gift`
  7. `"inter" in m and "se" in m` -> `inter_se`
  8. any of `preferential`, `allot`, `rights`, `bonus`, `conversion` in m -> `preferential`
  9. else `other`
- Drop rows with no symbol, no person, or qty NaN/<= 0 (this drops derivative rows, whose `secAcq` is empty).
- `disclosed_at = _iso_dt(r["date"])`; `disclosed = disclosed_at[:10]` if set else `_iso(intimDt)`.
- Dedupe as in 4.3.

Enrichment in `load_insider()` (pure helper `_enrich_insider(df) -> df`, also used by tests):

- `role` from `pc = (person_category or "").lower()`: `"promoter" in pc` -> `promoter`; any of `director`,
  `key managerial`, `kmp`, `designated`, `employee`, `immediate relative`, `insider` in pc -> `insider`; else
  `other`.
- `category/sub_label/investor`: promoter -> `("promoter", None, None)`; insider -> `("other", INSIDER_LABEL,
  None)`; other -> `classify(person)`.
- `is_market = mode_kind == "market" and side notna`.
- `fully_exited = side == "SELL" and (after_shares == 0 or (after_shares isna and after_pct == 0)) and
  (before_shares > 0 or before_pct > 0)`.
- `avg_price = value / qty` when both > 0, else NaN. `change_pts = after_pct - before_pct`.
- `delay_days = (date(disclosed) - date(trade_to)).days` when both set, else NaN.
- `id = f"{symbol}|{person_key}|{trade_from or ''}|{qty:.0f}|{side or mode_kind}"`; duplicates get `#2`, `#3`...
  (via `groupby("id").cumcount()`).

#### 4.4.4 `parse_shp_master(payload) -> pd.DataFrame` (FILING_COLS)

Per record: `symbol` (upper), `company = _text(name)`, `period = _iso(date)`, `record_id = int(_to_num(recordId))`,
`xbrl = _text(xbrl)`, `broadcast = _iso_dt(broadcastDate)`, `submission = _iso(submissionDate)`,
`revised = str(revisedData).strip().upper() in ("Y", "YES", "TRUE")`, `promoter_pct = _to_num(pr_and_prgrp)`,
`public_pct = _to_num(public_val)`. Drop rows without symbol, period or record_id, and rows whose period is not a
quarter end (`(month, day) in QUARTER_ENDS`) - allotment-date patterns are not quarterly data.

#### 4.4.5 `parse_shp_xbrl(data: bytes) -> tuple[dict, list[dict]]`

Returns `(cats, holders)`; raises `ValueError` when the file has neither a grand total nor any category.

```python
cats = {"total_shares": float, "promoter_pct": float, "public_pct": float, "fii_pct": float, "dii_pct": float,
        "mf_pct": float, "insurance_pct": float, "banks_pct": float, "pension_pct": float, "aif_pct": float}
holders = [{"holder": str, "group": "promoter"|"public", "xbrl_member": str, "shares": float, "pct": float}, ...]
```

Algorithm (namespaces vary by taxonomy year: match **local names only**):

1. `root = ET.fromstring(data)`. `local(tag)` = text after `}` (or after `:`); `qlocal(text)` = text after the
   last `:` (`"in-bse-shp:MutualFundsMember"` -> `"MutualFundsMember"`).
2. Contexts: for every element with local name `context`: `explicit = [(qlocal(dimension), qlocal(text))]` for
   descendants named `explicitMember`; `typed = [(qlocal(dimension), "".join(itertext()).strip())]` for
   descendants named `typedMember`. Key by the context `id`.
3. Facts: every element with a `contextRef` attribute -> `facts[contextRef][local(tag)] = text.strip()` (first one
   wins).
4. Fact getters on one context's dict: `pct` = `PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"` exact,
   else the first key starting with PCT; `shares` = `"NumberOfShares"` exact, else first key starting with
   `"NumberOfShares"` that does not start with `"NumberOfShareholders"`; `name` = `"NameOfTheShareholder"` exact,
   else first key containing `"NameOfTheShareholder"` or `"NameOfShareholder"`. Values via `_to_num`.
5. Category contexts: `typed` empty and exactly one explicit item whose axis contains `"CategoryOfShareholders"`.
   Build `cat_pct[member] = pct`, `cat_shares[member] = shares` (only members with a pct value for `cat_pct`).
6. Grand total: category members containing `"ShareholdingPattern"`, the shortest one. Scale: grand pct present ->
   `100 if grand_pct <= 1.5 else 1`; absent -> `100 if cat_pct and max(cat_pct.values()) <= 1.0 else 1`. No grand
   pct and empty `cat_pct` -> `raise ValueError("no shareholding categories")`.
7. Targets (case-insensitive substring on the member name; among matches pick the shortest name, ties -> larger
   pct); value = `round(pct * scale, 4)`:

```python
SHP_TARGETS = {"promoter_pct": ("PromoterAndPromoterGroup",), "public_pct": ("PublicShareholding", "PublicShareholder"),
               "dii_pct": ("InstitutionsDomestic",), "fii_pct": ("InstitutionsForeign",), "mf_pct": ("MutualFund",),
               "insurance_pct": ("InsuranceCompan",), "banks_pct": ("Banks",),
               "pension_pct": ("ProvidentFund", "PensionFund"),
               "aif_pct": ("AlternateInvestmentFund", "AlternativeInvestmentFund")}
```
   Missing values: promoter missing and public present -> `100 - public` (and the reverse). If `dii_pct` or
   `fii_pct` was found (the file uses the institutions layout), any missing one of `dii, fii, mf, insurance, banks,
   pension, aif` -> `0.0` (a missing subtotal means none). Otherwise missing -> NaN. `total_shares` = shares of the
   grand-total member (NaN if absent).
8. Holders: contexts with `typed` non-empty and a non-empty `name` fact. Skip the context when any axis or member
   name (lower-case) contains `personsactinginconcert`, `personsinconcert`, `significantbeneficial` or
   `unclaimed`. `group = "promoter"` if any axis or member name (lower-case) contains `"promoter"` but not
   `"nonpromoter"` (the "Non Promoter - Non Public" category: employee trusts, DR custodians), else `"public"`. `xbrl_member` = first explicit member name if any, else the first typed axis name.
   `pct = round(pct * scale, 4)` (NaN allowed), `shares`. Drop rows whose `normalise_name(holder)` is in `SHP_LABEL_NAMES`
   (category totals that look like names); drop `public` rows with pct NaN or `< 1.0`. Dedupe on
   `(normalise_name(holder), group)` keeping the larger pct.

```python
SHP_LABEL_NAMES = {"CLEARING MEMBERS", "CLEARING MEMBER", "BODIES CORPORATE", "BODY CORPORATE", "HUF",
                   "HINDU UNDIVIDED FAMILY", "TRUSTS", "TRUST", "NON RESIDENT INDIANS", "NRI", "IEPF",
                   "INVESTOR EDUCATION AND PROTECTION FUND", "OTHERS", "ANY OTHER", "FOREIGN NATIONALS", "LLP",
                   "FOREIGN COMPANIES", "OVERSEAS CORPORATE BODIES", "EMPLOYEES", "KEY MANAGERIAL PERSONNEL",
                   "DIRECTORS AND THEIR RELATIVES", "ESOP TRUST", "FIRMS", "PARTNERSHIP FIRMS",
                   "QUALIFIED INSTITUTIONAL BUYER", "SUSPENSE ACCOUNT", "EMPLOYEE TRUSTS"}
```

### 4.5 Classification

```python
class Label(NamedTuple):
    category: str            # one of CATEGORIES
    sub_label: str | None    # e.g. ODI_LABEL, LIKELY_PROMOTER, INSIDER_LABEL, 'Individual'
    investor: str | None     # display name of the well-known investor (category 'famous'), else None

def normalise_name(name: object) -> str: ...
def parent_key(name: object) -> str: ...
def classify(name: object, *, promoters: set[str] | None = None, company: str | None = None,
             round_trip: bool = False) -> Label: ...
```

#### 4.5.1 `normalise_name`

1. None/NaN -> `""`. `s = str(name).upper()`.
2. `&` -> `" AND "`. Each of `. , ( ) ' " ; :` -> space. `-` -> `" - "` (a hyphen becomes its own token, so
   `FUND-1` -> `FUND - 1` and `LTD-A/C` -> `LTD - A/C`).
3. Collapse whitespace, strip. Remove leading and trailing `-` tokens (`re.sub(r"^(- )+|( -)+$", "", s)`).
4. Remove a leading `M/S ` or `MS ` token.
5. Whole-token replacements: `PVT` -> `PRIVATE`, `LTD` -> `LIMITED`, `CO` -> `COMPANY`.

`_has(s, phrase)` = `f" {phrase} " in f" {s} "` (whole-token match on a normalised string; `LIC` does not match
`PUBLIC` or `CLICK`). `_any(s, phrases)` = any `_has`.

`parent_key(name)`: `s = normalise_name(name)`; `p = f" {s} "`; positions of the first `" A/C "`, `" ACCOUNT "`,
`" SCHEME "`, `" - "` in `p` that are `> 0`; if any -> `p[:min].strip()`, else `s`.
Examples: `SBI MUTUAL FUND A/C SBI SMALL CAP FUND` -> `SBI MUTUAL FUND`;
`NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND` -> `NIPPON LIFE INDIA TRUSTEE LIMITED`;
`SOCIETE GENERALE - ODI` -> `SOCIETE GENERALE`.

#### 4.5.2 Word lists (exact)

```python
FAMOUS_INVESTORS: dict[str, list[str]] = {   # display name -> aliases (all alias tokens must be in the name)
    "Rekha Jhunjhunwala (RJ estate)": ["REKHA RAKESH JHUNJHUNWALA", "REKHA JHUNJHUNWALA",
                                       "RAKESH RADHEYSHYAM JHUNJHUNWALA", "RAKESH JHUNJHUNWALA", "RARE ENTERPRISES"],
    "Radhakishan Damani": ["RADHAKISHAN SHIVKISHAN DAMANI", "RADHAKISHAN DAMANI", "GOPIKISHAN SHIVKISHAN DAMANI",
                           "DERIVE TRADING AND RESORTS", "BRIGHT STAR INVESTMENTS"],
    "Ashish Kacholia": ["ASHISH RAMESHCHANDRA KACHOLIA", "ASHISH KACHOLIA", "BENGAL FINANCE AND INVESTMENT"],
    "Vijay Kedia": ["VIJAY KISHANLAL KEDIA", "VIJAY KEDIA", "KEDIA SECURITIES"],
    "Dolly Khanna": ["DOLLY KHANNA", "DOLLY RAJIV KHANNA", "RAJIV KHANNA"],
    "Mukul Agrawal": ["MUKUL MAHAVIR AGRAWAL", "MUKUL AGRAWAL", "PARAM CAPITAL"],
    "Sunil Singhania (Abakkus)": ["SUNIL SINGHANIA", "ABAKKUS"],
    "Ashish Dhawan": ["ASHISH DHAWAN"],
    "Porinju Veliyath": ["PORINJU VELIYATH", "EQUITY INTELLIGENCE INDIA"],
    "Anil Kumar Goel": ["ANIL KUMAR GOEL"],
    "Madhusudan Kela": ["MADHUSUDAN KELA", "MADHURI MADHUSUDAN KELA", "SINGULARITY"],
    "Nemish Shah": ["NEMISH S SHAH", "NEMISH SHAH"],
    "Akash Bhanshali": ["AKASH PRAKASH BHANSHALI", "AKASH BHANSHALI"],
    "Vallabh Bhanshali": ["VALLABH BHANSHALI"],
    "Ramesh Damani": ["RAMESH DAMANI"],
    "Raamdeo Agrawal": ["RAAMDEO AGRAWAL", "RAAMDEO RAMGOPAL AGRAWAL"],
    "Seetha Kumari": ["SEETHA KUMARI"],
    "Satpal Khattar": ["SATPAL KHATTAR", "KHATTAR HOLDINGS"],
    "Ajay Upadhyaya": ["AJAY UPADHYAYA"],
    "Hemendra Kothari": ["HEMENDRA KOTHARI"],
    "Mohnish Pabrai": ["MOHNISH PABRAI", "PABRAI INVESTMENT FUND", "DALAL STREET LLC"],
    "Shankar Sharma": ["SHANKAR SHARMA"],
    "Vikas Khemani (Carnelian)": ["CARNELIAN"],
}
BRAND_TOKENS = frozenset({"ABAKKUS", "CARNELIAN", "SINGULARITY"})   # the only single-token aliases allowed
# (alias token set, display), most tokens first; aliases go through normalise_name
_ALIASES = sorted(((frozenset(normalise_name(a).split()), d) for d, al in FAMOUS_INVESTORS.items() for a in al),
                  key=lambda x: -len(x[0]))

AMC_BRANDS = ("SBI", "HDFC", "ICICI PRUDENTIAL", "NIPPON INDIA", "NIPPON LIFE INDIA", "KOTAK MAHINDRA", "AXIS",
              "ADITYA BIRLA SUN LIFE", "UTI", "DSP", "MIRAE ASSET", "TATA", "MOTILAL OSWAL", "QUANT", "BANDHAN",
              "INVESCO INDIA", "FRANKLIN TEMPLETON", "PPFAS", "PARAG PARIKH", "WHITEOAK CAPITAL", "EDELWEISS",
              "BARODA BNP PARIBAS", "HSBC", "CANARA ROBECO", "SUNDARAM", "UNION", "LIC", "MAHINDRA MANULIFE",
              "PGIM INDIA", "360 ONE", "JM FINANCIAL", "ITI", "NAVI", "GROWW", "ZERODHA", "SAMCO", "HELIOS",
              "OLD BRIDGE", "BAJAJ FINSERV", "JIO BLACKROCK", "QUANTUM", "SHRIRAM", "TAURUS", "NJ",
              "BANK OF INDIA", "UNIFI", "ANGEL ONE")
FOREIGN_MARKERS = ("PLC", "LLC", "LP", "L P", "PTE", "SICAV", "UCITS", "OEIC", "FCP", "S A", "SA", "AG", "GMBH",
                   "NV", "BV", "INC", "MASTER FUND", "OFFSHORE", "MAURITIUS", "SINGAPORE", "CAYMAN", "LUXEMBOURG",
                   "IRELAND", "HONG KONG", "DIFC", "DUBAI", "EMERGING MARKETS", "FOREIGN PORTFOLIO")
INSURANCE_WORDS = ("INSURANCE", "ASSURANCE", "REINSURANCE")
INSURANCE_BRANDS = ("HDFC LIFE", "SBI LIFE", "ICICI PRUDENTIAL LIFE", "ICICI LOMBARD", "TATA AIA", "MAX LIFE",
                    "AXIS MAX LIFE", "BAJAJ ALLIANZ", "BAJAJ LIFE", "KOTAK MAHINDRA LIFE",
                    "ADITYA BIRLA SUN LIFE INSURANCE", "NEW INDIA ASSURANCE", "STAR HEALTH", "CANARA HSBC LIFE",
                    "PNB METLIFE")
PENSION_WORDS = ("PENSION", "PROVIDENT FUND", "EMPLOYEES PROVIDENT", "NPS TRUST", "SUPERANNUATION",
                 "RETIREMENT SYSTEM", "PUBLIC EMPLOYEES", "TEACHERS", "INVESTMENT AUTHORITY", "MONETARY AUTHORITY",
                 "SOVEREIGN", "GOVERNMENT OF", "PRESIDENT OF INDIA", "GIC PRIVATE", "TEMASEK",
                 "PUBLIC INVESTMENT FUND", "NORGES BANK", "CANADA PENSION PLAN", "CPP INVESTMENT",
                 "CAISSE DE DEPOT", "ONTARIO TEACHERS")
PROP_FIRMS = ("GRAVITON RESEARCH CAPITAL", "HRTI", "QE SECURITIES", "JUNOMONETA FINSOL", "NK SECURITIES RESEARCH",
              "IRAGE BROKING", "ALPHAGREP", "TOWER RESEARCH", "SILVERLEAF CAPITAL", "MICROCURVES TRADING",
              "MATHISYS ADVISORS", "QUADEYE", "ESTEE ADVISORS", "SHARE INDIA SECURITIES", "PACE STOCK BROKING",
              "DOLAT CAPITAL", "RAJASTHAN GLOBAL SECURITIES", "JUMP TRADING", "CITADEL SECURITIES",
              "BNP PARIBAS ARBITRAGE")
BROKER_WORDS = ("ARBITRAGE", "STOCK BROKING", "BROKING", "SHARE BROKERS", "STOCK BROKERS", "COMMODITIES", "FINSOL",
                "RESEARCH LLP", "TRADING LLP", "CAPITAL MARKETS LLP")
ODI_PHRASES = ("ODI", "SOCIETE GENERALE", "BOFA SECURITIES EUROPE", "CITIGROUP GLOBAL MARKETS MAURITIUS",
               "MORGAN STANLEY ASIA SINGAPORE", "GOLDMAN SACHS SINGAPORE PTE", "MERRILL LYNCH MARKETS SINGAPORE",
               "NOMURA SINGAPORE")
BANK_WORDS = ("BANK", "HOUSING FINANCE", "FINANCE LIMITED", "FINANCIAL SERVICES LIMITED", "FINVEST", "FINCORP",
              "NBFC", "INVESTMENT AND FINANCE", "CREDIT CAPITAL")
FII_BRANDS = ("VANGUARD", "BLACKROCK", "ISHARES", "FIDELITY", "GOLDMAN SACHS", "MORGAN STANLEY", "CITIGROUP",
              "J P MORGAN", "JP MORGAN", "JPMORGAN", "NOMURA", "MERRILL LYNCH", "BOFA SECURITIES", "UBS", "CLSA",
              "MACQUARIE", "SOCIETE GENERALE", "BNP PARIBAS", "HSBC", "ABRDN", "ABERDEEN", "NORTHERN TRUST",
              "STATE STREET", "WISDOMTREE", "SCHRODER", "INVESCO", "T ROWE", "CAPITAL GROUP", "SMALLCAP WORLD",
              "GOVERNMENT PENSION", "NALANDA", "AMANSA", "ELARA INDIA OPPORTUNITIES", "COPTHALL MAURITIUS", "FPI",
              "INDIA FUND")
AIF_WORDS = ("AIF", "ALTERNATIVE INVESTMENT", "ALTERNATE INVESTMENT", "CATEGORY III", "OPPORTUNITIES FUND",
             "PORTFOLIO MANAGEMENT", "ABAKKUS", "CARNELIAN", "MARCELLUS", "SINGULARITY", "NEO", "3P INDIA", "ASK")
COMPANY_WORDS = ("LIMITED", "LLP", "PRIVATE", "ENTERPRISES", "INDUSTRIES", "VENTURES", "HOLDINGS")
TRUST_WORDS = ("HUF", "TRUST", "FOUNDATION")
CORPORATE_TOKENS = frozenset(COMPANY_WORDS + TRUST_WORDS + (
    "COMPANY", "CORPORATION", "FUND", "FUNDS", "CAPITAL", "INVESTMENT", "INVESTMENTS", "SECURITIES", "ADVISORS",
    "ADVISERS", "MANAGEMENT", "PARTNERS", "GROUP", "ASSOCIATES", "FINANCE", "FINANCIAL", "TRADING", "EXPORTS"))
PROMOTER_HINTS = ("HOLDINGS", "INVESTMENTS", "FAMILY TRUST", "ENTERPRISES", "VENTURES")
COMPANY_STOPWORDS = frozenset({"THE", "SHREE", "SHRI", "SRI", "NEW", "INDIA", "INDIAN", "NATIONAL", "GLOBAL",
                               "INTERNATIONAL", "UNITED", "GENERAL", "ASIAN", "BHARAT", "HINDUSTAN"})
```

#### 4.5.3 Rules (first match wins; implement exactly this)

```python
def classify(name, *, promoters=None, company=None, round_trip=False) -> Label:
    s = normalise_name(name)
    if not s:
        return Label("other", "Unclassified", None)
    # 1) promoter of this stock (per-symbol set built by promoter_sets)
    if promoters and (s in promoters or parent_key(name) in promoters):
        return Label("promoter", None, None)
    word = _company_word(company)      # first token of normalise_name(company) not in COMPANY_STOPWORDS,
    if word and _has(s, word) and _any(s, PROMOTER_HINTS):   # alphabetic, len >= 4; else None
        return Label("promoter", LIKELY_PROMOTER, None)
    return _classify_name(s, bool(round_trip))


@functools.lru_cache(maxsize=65536)
def _classify_name(s: str, round_trip: bool) -> Label:
    toks = set(s.split())
    for alias, display in _ALIASES:                                   # 2) well-known investor
        if alias <= toks:
            return Label("famous", None, display)
    insurance_like = _any(s, INSURANCE_WORDS)
    if not insurance_like:                                            # 3) mutual fund
        brand = _any(s, AMC_BRANDS)
        if (_has(s, "MUTUAL FUND") or ((_has(s, "MF") or _has(s, "ETF")) and brand)
                or (_has(s, "TRUSTEE") and _has(s, "A/C"))
                or (brand and _has(s, "FUND") and not _any(s, FOREIGN_MARKERS))):
            return Label("mf", None, None)
    if (insurance_like or (_has(s, "LIC") and not _has(s, "LIC HOUSING"))   # 4) insurance
            or _any(s, INSURANCE_BRANDS)):
        return Label("insurance", None, None)
    if _any(s, PENSION_WORDS):                                        # 5) pension / sovereign
        return Label("pension", None, None)
    if _any(s, PROP_FIRMS) or _any(s, BROKER_WORDS):                  # 6) broker / prop / arbitrage
        return Label("broker", None, None)
    if _any(s, ODI_PHRASES):                                          #    P-note issuers are FPIs
        return Label("fii", ODI_LABEL, None)
    if round_trip:                                                    #    intraday round trip, no rule matched
        return Label("broker", None, None)
    if _any(s, BANK_WORDS):                                           # 7) bank / NBFC
        return Label("bank", None, None)
    if _any(s, FOREIGN_MARKERS) or _any(s, FII_BRANDS):               # 8) foreign investor
        return Label("fii", None, None)
    if _any(s, AIF_WORDS):                                            # 9) other, with a sub-label
        return Label("other", "AIF/PMS fund", None)
    if _any(s, COMPANY_WORDS):
        return Label("other", "Company", None)
    if _any(s, TRUST_WORDS):
        return Label("other", "HUF/Trust", None)
    if 2 <= len(toks) <= 5 and not (toks & CORPORATE_TOKENS) and all(t.isalpha() for t in toks):
        return Label("other", "Individual", None)
    return Label("other", "Unclassified", None)
```

A name that only *looks like* a famous investor can be another person: the UI always shows the filed name next to
the label.

#### 4.5.4 Category of shareholding holders (`load_holders` enrichment)

`group == "promoter"` -> `("promoter", None, None)`. Else on `m = xbrl_member.lower()`: `"mutualfund"` ->
`mf`; `"insurance"` -> `insurance`; `"foreignportfolio"`, `"institutionsforeign"` or `"foreigninstitution"` ->
`fii`; `"sovereign"`, `"providentfund"` or `"pensionfund"` -> `pension`; `"bank"` -> `bank`; else
`classify(holder)` (finds well-known investors listed under "Individuals" or "Bodies corporate").

#### 4.5.5 `promoter_sets(holders, insider) -> dict[str, set[str]]`

symbol -> set of both `normalise_name(x)` and `parent_key(x)` for every holder with `group == "promoter"` (all
periods) and every insider `person` with `role == "promoter"`.

### 4.6 `refresh()`

```python
def refresh(days: int = 365, log: Callable[[str], None] = print, symbols: list[str] | None = None, *,
            holdings_quarters: int = 2, max_xbrl: int = 300, folder: Path | None = None,
            today: date | None = None) -> dict:
```

Never raises for network/data problems. Returns the **report**:

```python
{"ok": bool, "started_at": iso_dt, "finished_at": iso_dt, "elapsed_s": float,
 "sources": {"deals": SOURCE, "insider": SOURCE, "flows": SOURCE, "holdings": SOURCE}, "errors": [str]}
```
`ok = all(s["status"] in ("ok", "partial") for s in sources.values())`.

Steps:

1. `folder = Path(folder or SM_DIR)`; create it and `folder / "xbrl"`. `today = today or ist_today()`;
   `days = max(1, min(int(days), 730))`.
2. Lock: open `folder / ".refresh.lock"` (`"a+"`), `_try_lock`, retried every 0.1 s for up to `LOCK_GRACE_S` (a
   `refresh_running()` probe from the dashboard holds it for an instant). Not acquired -> return a report with
   `ok False`, every source `{"status": "skipped", "message": "Another refresh is running", "rows_added": 0,
   "last_ok_at": None, "latest_date": None}`, `errors ["Another smart-money refresh is already running."]`, and
   write nothing. Release with `_unlock` + close in `finally`.
3. `_reset_api()`. `state = load_state(folder)`.
4. Run the steps in this order, each in its own `try/except Exception as e` (an exception -> `{"status":
   "failed", "message": f"{type(e).__name__}: {e}"[:300], "rows_added": 0, "latest_date": <previous>}`):
   `deals` -> `_refresh_deals`, `insider` -> `_refresh_insider`, `flows` -> `_refresh_flows`, `holdings` ->
   `_refresh_holdings`. After each step: `last_ok_at = now` when status is ok/partial, else keep the previous
   value; store it in `state["sources"][name]` and `_save_json(state)` (progress survives a crash).
5. `errors = [f"{name}: {src['message']}" for sources with status partial/failed/skipped]`, max 20.
   `state["last_run"]`, `state["errors"] = errors`, save. Return the report.

Month helper `_months(start: date, end: date) -> list[tuple[date, date, str, bool]]`: calendar months touching
`[start, end]`, **newest first**, each `(first, last, "YYYY-MM", full)` with `first/last` clipped to the range and
`full = first is the 1st of the month`. A month key may be added to a `*_months_done` list only when `full` is
true and `last_of_month < today - PAST_MONTH_GRACE_DAYS` (past months never change).

#### `_refresh_deals(folder, state, today, days, log) -> SOURCE`

1. `log("Smart money: bulk and block deals...")`. `new = []`, `fails = []`.
2. For `(kind, url)` in `(("bulk", BULK_CSV_URL), ("block", BLOCK_CSV_URL))`: `code, body = _fetch(url)`;
   200 -> `new.append(parse_deals(body, kind, "archive"))`; else `fails.append(f"{kind}.csv HTTP {code}")`.
3. If both archive files failed: `_fetch(API + "snapshot-capital-market-largedeal", api=True,
   referer=PAGES["large"])`; 200 -> `new.append(parse_large_deals(body))`.
4. History backfill: for `kind, option` in `(("bulk", "bulk_deals"), ("block", "block_deals"))`, for each month of
   `_months(today - timedelta(days=days - 1), today)` not in `state["deals_months_done"][kind]`:
   `_fetch(API + "historicalOR/bulk-block-short-deals", {"optionType": option, "from": first.strftime("%d-%m-%Y"),
   "to": last.strftime("%d-%m-%Y"), "csv": "true"}, api=True, referer=PAGES["deals"])`. 200 ->
   `new.append(parse_deals(body, kind, "history"))` and mark done when allowed; `-2` -> note "NSE blocked
   requests" and stop the backfill (both kinds); other -> `fails.append(...)`.
5. Merge with `load_deals(folder)`, dedupe (4.3), save only when the row count or content changed.
   `rows_added = len(merged) - len(old)`.
6. Write `unmatched_names.json` (4.3) from the merged raw rows (`classify(client).sub_label == "Unclassified"`).
7. Status: no request succeeded -> `failed`; some failed -> `partial`; else `ok`. `message` in plain English,
   e.g. `"1,204 deal rows up to 23 Oct 2026; 2 history months failed"`. `latest_date` = max date.

#### `_refresh_insider(...)`

For each month of `_months(today - timedelta(days=days - 1), today)` not in `state["insider_months_done"]`:
`_fetch(API + "corporates-pit", {"index": "equities", "from_date": first.strftime("%d-%m-%Y"),
"to_date": last.strftime("%d-%m-%Y")}, api=True, referer=PAGES["pit"])`; 200 -> `parse_pit(body)`; `-2` -> stop.
Merge with the stored table (`load_insider` **without** enrichment: read the parquet, INSIDER_COLS only), dedupe
(4.3), save. `latest_date` = max `disclosed`. Log once per month: `"Smart money: insider trades Oct 2026..."`.

#### `_refresh_flows(...)`

`_fetch(API + "fiidiiTradeReact", api=True, referer=PAGES["fiidii"])`; 200 -> `parse_fiidii(body)`. Upsert by
date: `new.set_index("date").combine_first(old.set_index("date"))` (a NaN in the new row keeps the old value),
reset index, sort asc, save. Status `ok` when a row was parsed, `failed` otherwise. History builds up only from the
first refresh (NSE gives one day per call).

#### `_refresh_holdings(folder, state, today, symbols, holdings_quarters, max_xbrl, log)`

1. `syms = [s.upper() for s in symbols]` if given, else `_default_symbols()`: the cached universe CSV
   `DATA_DIR / f"universe_{name}.csv"` (`name = str(load_config().get("universe") or "nifty500").lower()`, column
   `symbol`; config errors -> nifty500; missing file -> none) + `scanner.holdings.load_holdings()["symbol"]`
   (import inside the function), minus `load_config().get("etfs")`, de-duplicated in order. Never downloads the
   universe.
2. Listing (date-range mode): months of `_months(today - timedelta(days=SHP_LISTING_DAYS), today)` not in
   `state["shp_months_done"]` -> `_fetch(API + "corporate-share-holdings-master", {"index": "equities",
   "from_date": ..., "to_date": ...}, api=True, referer=PAGES["shp"])` -> `parse_shp_master`. `-2` -> stop.
3. Per-symbol fallback: symbols in `syms` with **no** filing in the merged list whose `period >= today -
   SHP_LISTING_DAYS`, and not in `state["shp_symbol_checked"]` within `RECHECK_DAYS`, at most
   `MAX_SYMBOL_LOOKUPS` (never-checked first): `_fetch(..., {"index": "equities", "symbol": s}, ...)`; record
   `state["shp_symbol_checked"][s] = today.isoformat()` whatever the result.
4. Save the merged filings list (dedupe record_id).
5. Needed filings: for each `s in syms`, its filings with the latest revision per period (sort by broadcast desc,
   record_id desc), the newest `holdings_quarters` periods. Skip record_ids already in `holdings.parquet` with
   `source == "xbrl"` and those in `state["shp_failed"]` within `RECHECK_DAYS`. Order: period desc, then the
   order of `syms`. Take at most `max_xbrl`.
6. Download + parse in batches of `2 * XBRL_WORKERS` with `ThreadPoolExecutor(XBRL_WORKERS)`: cached
   `xbrl/SHP_<record_id>.xml.gz` -> read it; else `_fetch(xbrl_url)` and on 200 with a body write the gz file
   (atomic). Parse with `parse_shp_xbrl`. Success -> one HOLDING row (`source "xbrl"`, `company`, `broadcast` from
   the filing) + HOLDER rows; failure (download or parse) -> `state["shp_failed"][str(rid)] = today` and, if that
   record has no holdings row yet, a `source "master"` row from the filing's `promoter_pct`/`public_pct` (other
   columns NaN). Stop after `XBRL_MAX_FAILURES` consecutive download failures. Log every 50 files:
   `"Smart money: shareholding 150/300 files"`.
7. Merge: holdings dedupe record_id preferring xbrl; holders: drop stored rows whose record_id was just parsed,
   append the new ones. Save both.
8. Status: `ok` when nothing failed; `partial` when some failed or files are left for the next refresh
   (message e.g. `"Shareholding for 412 of 500 stocks, newest quarter Sep 2026; 88 files left for the next
   refresh"`); `failed` when the listing and every download failed. `latest_date` = newest period.

`refresh_running(folder: Path | None = None) -> bool`: True when another handle holds `.refresh.lock` (probe:
open `"a+"`, `_try_lock` -> unlock and False; not acquired -> True; missing file -> False).

### 4.7 Loaders (never raise; missing/corrupt file -> empty frame with the exact columns)

```python
def load_deals(folder=None) -> pd.DataFrame        # DEAL_COLS, as stored
def load_insider(folder=None) -> pd.DataFrame      # INSIDER_COLS + INSIDER_EXTRA_COLS (enriched, 4.4.3)
def load_flows(folder=None) -> pd.DataFrame        # FLOW_COLS, date asc
def load_holdings(folder=None) -> pd.DataFrame     # HOLDING_COLS: one row per (symbol, period): prefer source
                                                   # xbrl, then latest broadcast, then highest record_id;
                                                   # sorted by symbol, period desc
def load_holders(folder=None) -> pd.DataFrame      # HOLDER_COLS + category, sub_label, investor; only rows of
                                                   # the records chosen by load_holdings with source xbrl
def load_state(folder=None) -> dict                # state.json or {} (keys of 4.3 default to empty)
```
Any missing column in an older file is added as NaN (so new columns never break old caches).

### 4.8 Derived tables (pure functions; the API calls these)

#### 4.8.1 Small helpers

```python
def latest(df: pd.DataFrame, col: str) -> str | None       # max non-null value of an ISO column, or None
def window(as_of: str | None, days: int) -> str | None     # (date(as_of) - (days-1) days).isoformat(), None if no as_of
def share_counts(holdings: pd.DataFrame) -> dict[str, float]   # symbol -> total_shares of its newest xbrl row (>0)
def company_names(net: pd.DataFrame, insider: pd.DataFrame, holdings: pd.DataFrame) -> dict[str, str]
    # symbol -> name: holdings.company first, then insider.company, then net.security (first non-empty)
def category_mask(categories: pd.Series, flt: str) -> pd.Series
    # 'all' -> all True; 'big' -> isin(BIG_MONEY); 'institutions' -> isin(INSTITUTIONS); slug -> == slug
```

#### 4.8.2 `net_deals(deals, promoters=None, shares=None) -> pd.DataFrame` (NET_DEAL_COLS)

One row per `(date, symbol, client_key)` over both kinds:

| column | dtype | rule |
|---|---|---|
| id | object | `f"{date}\|{symbol}\|{client_key}"` |
| date, symbol, client_key | object | group keys |
| security | object | first non-NaN in the group |
| client | object | `client` of the group's row with the largest `value` (ties: first) |
| kind | object | `"block"` if all rows block, `"bulk"` if all bulk, else `"both"` |
| buy_qty, sell_qty | float64 | sum of qty by side |
| net_qty | float64 | buy_qty - sell_qty |
| buy_value, sell_value | float64 | sum of value by side (NaN treated as 0) |
| net_value | float64 | buy_value - sell_value |
| side | object | `"BUY"` if net_qty > 0, `"SELL"` if < 0, else `"FLAT"` |
| avg_price | float64 | BUY: buy_value/buy_qty; SELL: sell_value/sell_qty; FLAT: (bv+sv)/(bq+sq); NaN when the value is 0 |
| round_trip | bool | buy_qty > 0 and sell_qty > 0 and min/max >= ROUND_TRIP_RATIO |
| category, sub_label, investor | object | `classify(client, promoters=promoters.get(symbol), company=security, round_trip=round_trip)` |
| pct_equity | float64 | `shares[symbol]` known: `(max(buy_qty, sell_qty) if round_trip else abs(net_qty)) / shares * 100`, rounded 3; else NaN |
| counterparties | object (list[str]) | kind block/both: sorted unique `client` of raw **block** rows of the same (date, symbol) on the opposite side of this row's side (FLAT: both sides minus itself); bulk: `[]` |

Sorted by date desc, then `abs(net_value)` desc (round trips: `buy_value` desc). Empty input -> empty frame with
these columns.

#### 4.8.3 `holder_changes(holders, holdings) -> pd.DataFrame` (HOLDER_CHANGE_COLS)

Columns: `symbol, period, prev_period, holder, holder_key, group, category, sub_label, investor` (object),
`pct, prev_pct, change_pts, shares` (float64), `status` (object: `new|added|cut|same|dropped`).

Per symbol: `P` = newest period with a `source == "xbrl"` holdings row; `Q` = the next older xbrl period if
`(P - Q).days <= SHP_MAX_GAP_DAYS`, else none. Outer-merge the holders of P and Q on `(holder_key, group)`:
present now and before -> `change_pts = pct - prev_pct`, status `added` (>= `HOLDER_MIN_CHANGE_PTS - 1e-9`),
`cut` (<= `-HOLDER_MIN_CHANGE_PTS + 1e-9`), else `same`; only now -> `new`; only before -> `dropped` (name,
group and category from the old row; pct/shares NaN). No Q -> every row `same` with `prev_period`/`prev_pct`
NaN. Sorted by symbol, then pct desc, dropped rows last by prev_pct desc.

#### 4.8.4 `events(net, insider, holdings, holders, since, shp_since=None, companies=None) -> pd.DataFrame`

EVENT_COLS: `id, date, symbol, company, event, direction, source, who, who_key, investor, category, sub_label`
(object), `value, qty, pct_before, pct_after, change_pts, pct_equity` (float64), `period, prev_period, exit_kind,
text` (object), `weight` (int64). `shp_since` defaults to `since`. `company` from `companies` (else NaN).

What each source can prove (this is the exit logic - keep these meanings):

| event | from | rule | direction | exit_kind |
|---|---|---|---|---|
| `deal_buy` / `deal_sell` | net rows with `date >= since`, not round_trip, `category in BIG_MONEY`, side BUY/SELL | bought/sold X shares (Y% of the company). A sell is **not** necessarily a full exit | up / down | sell: `sold_part` |
| `insider_buy` / `insider_sell` | insider rows `disclosed >= since`, `is_market`, not fully_exited | open-market buy/sell by promoter or insider | up / down | sell: `sold_part` |
| `insider_exit` | insider `is_market` and `fully_exited` | holding after = 0: **certain** full exit | down | `full_exit` |
| `pledge_invoked` | insider `mode_kind == "pledge_invoked"`, `disclosed >= since` | forced sale by a lender (warning sign) | down | null |
| `new_holder` / `holder_added` | holder_changes status new/added | new 1%+ holder / stake up | up | null |
| `holder_cut` | status cut | stake down | down | `sold_part` |
| `holder_dropped` | status dropped | "no longer shown at 1% or more - sold some or all" (cannot tell a full exit from a fall below 1%) | down | `below_1pct` |
| `category_up` / `category_down` | holdings P vs Q (both xbrl, both values non-NaN) for `fii_pct->fii, mf_pct->mf, insurance_pct->insurance, banks_pct->bank, pension_pct->pension, promoter_pct->promoter`: change >= `CATEGORY_MIN_CHANGE_PTS - 1e-9` / <= `-(CATEGORY_MIN_CHANGE_PTS) + 1e-9` | category stake up / down | up / down | down: `sold_part` |
| `category_exit` | prev > 0 and now == 0 (checked before up/down) | the whole category sold out | down | `category_exit` |

Shareholding events (`source "shareholding"`) are included only when the symbol's P filing date (`broadcast[:10]`,
else P) is `>= shp_since`; their `date` is that filing date, `period = P`, `prev_period = Q`. Deal events: `source
= "block"` if kind block/both else `"bulk"`, `date` = deal date, `who = client`, `who_key = client_key`,
`value = abs(net_value)`, `qty = abs(net_qty)`, `pct_equity`. Insider events: `source "insider"`, `date =
disclosed`, `who = person`, `who_key = person_key`, `value`, `qty`, `pct_before/pct_after/change_pts` from the
row. Holder events: `who = holder`, `who_key = holder_key`, `pct_before = prev_pct`, `pct_after = pct`,
`change_pts`, `qty = shares`. Category events: `who` NaN, `who_key = category`, pct before/after/change.

`weight`: base `{"deal_buy": 2, "deal_sell": 2, "insider_buy": 1, "insider_sell": 1, "insider_exit": 2,
"pledge_invoked": 2, "new_holder": 2, "holder_added": 1, "holder_cut": 1, "holder_dropped": 2, "category_up": 1,
"category_down": 1, "category_exit": 2}`; +1 for insider_buy/insider_sell when category is promoter; +1 for
category_up/down when `abs(change_pts) >= 3`.

`id = f"{event}|{symbol}|{date}|{who_key}"`, duplicates suffixed `#2`, `#3`.

`text` (exact templates; `who` = `investor` when set, else the filed name; `money = _inr_short(value)` or
`"value not given"`; `pct` = `f", {pct_equity:.2f}% of the company"` when known else `""`; `kind_word` =
`"block"`/`"bulk"`; `role` = `"Promoter "` for category promoter, `"Insider "` for sub_label INSIDER_LABEL, else
`""`; `q = _period_text(period)` = `"quarter to Sep 2026"`; `label = CATEGORY_LABELS[category]`):

```
deal_buy        "{who} bought {qty} shares ({money}{pct}) in a {kind_word} deal"
deal_sell       "{who} sold {qty} shares ({money}{pct}) in a {kind_word} deal"
insider_buy     "{role}{who} bought {qty} shares on the market ({money})"
insider_sell    "{role}{who} sold {qty} shares on the market ({money})"
insider_exit    "{role}{who} sold all their shares ({qty} shares, {money}) - fully exited"
pledge_invoked  "Lender sold {qty} pledged shares of {role}{who} (pledge invoked - a warning sign)"
new_holder      "{who} is a new 1%+ holder with {pct_after:.2f}% ({q})"
holder_added    "{who} raised their stake from {pct_before:.2f}% to {pct_after:.2f}% ({q})"
holder_cut      "{who} cut their stake from {pct_before:.2f}% to {pct_after:.2f}% ({q})"
holder_dropped  "{who} is no longer shown as a 1%+ holder (was {pct_before:.2f}%) - sold some or all ({q})"
category_up     "{label} holding rose {pts} to {pct_after:.2f}% ({q})"
category_down   "{label} holding fell {pts} to {pct_after:.2f}% ({q})"
category_exit   "{label} sold out completely (was {pct_before:.2f}%) ({q})"
```
Formatters (private): `_qty_text(n)` Indian grouping of the whole number (`600000` -> `"6,00,000"`);
`_inr_short(v)`: `>= 1e7` -> `f"₹{v / 1e7:,.1f} cr"`, `>= 1e5` -> `f"₹{v / 1e5:.1f} lakh"`, else
`f"₹{v:,.0f}"`; `_pts_text(x)` -> `"+1.20 pts"` / `"−0.85 pts"` (U+2212 minus); `_period_text(iso)` ->
`"quarter to " + "%b %Y"`.

Sorted by date desc, weight desc, value desc (NaN last), id asc.

`REASON_ORDER` (used for `reasons` here and by the API): weight desc, date desc, `abs(change_pts)` desc (NaN
last), id asc. Expose `top_reasons(ev_of_one_symbol, direction: str | None, n: int = 4) -> list[str]`: the `text`
of the first `n` events in REASON_ORDER, only events of `direction` when it is given.

#### 4.8.5 `stock_signals(ev, net, holdings, since) -> pd.DataFrame` (SIGNAL_COLS)

One row per symbol that has at least one event in `ev`. Columns (the API's `SmStock`, section 6):

| column | dtype | rule |
|---|---|---|
| symbol, company | object | company = first non-NaN event company |
| direction | object | `up` if only up events, `down` if only down, else `mixed` |
| up_events, down_events | int64 | counts |
| up_score, down_score | int64 | sums of `weight` |
| deal_buy_value, deal_sell_value, deal_net_value | float64 | over `net` rows `date >= since`, not round_trip, category in BIG_MONEY: sum of positive net_value; sum of -negative net_value; their difference |
| inst_buyers, inst_sellers | int64 | distinct client_key with category in INSTITUTIONS and side BUY / SELL (same rows) |
| famous_buyers, famous_sellers | object (list[str]) | sorted unique `investor` of famous BUY / SELL rows |
| insider_buy_value, insider_sell_value | float64 | sum of `value` of insider_buy events / of insider_sell + insider_exit events (NaN as 0) |
| promoter_buying, promoter_selling | bool | any up / down deal or insider event with category promoter |
| pledge_invoked | bool | any pledge_invoked event |
| exits | int64 | down events with exit_kind in full_exit, below_1pct, category_exit |
| fii_chg_pts, dii_chg_pts, mf_chg_pts, promoter_chg_pts | float64 | holdings P minus Q (both xbrl, 4.8.3 rule), rounded 2; NaN if no Q |
| period | object | P (NaN if none) |
| last_date | object | max event date |
| reasons | object (list[str]) | up to 4 event `text`s: events of the preferred direction first, each group in REASON_ORDER (4.8.4), where preferred = `up` if up_score >= down_score else `down` |

Sorted by `max(up_score, down_score)` desc, then symbol.

`accumulating(signals) -> DataFrame`: rows with `up_events > 0`, sorted by up_score desc, deal_net_value desc,
symbol. `exiting(signals) -> DataFrame`: rows with `down_events > 0`, sorted by down_score desc, deal_net_value
asc, symbol.

### 4.9 `summary_lines(folder=None, limit: int = 5) -> list[str]` (for the later Telegram wiring)

`[]` when no data at all. Otherwise these lines, each omitted when empty (`d` = deal as_of as `"23 Oct 2026"`):

```
Smart money - NSE disclosures (deals of {d}):
FII/FPI net {fmt} cr, DII net {fmt} cr on {flow date} (provisional, market-wide)
Big buys: XYZ (Ashish Kacholia ₹24.7 cr), ASTEC (SBI MUTUAL FUND A/C SBI SMALL CAP FUND ₹20.5 cr)
Big sells: XYZ (GOLDMAN SACHS (SINGAPORE) PTE ₹24.7 cr)
Promoter/insider market buys: XYZ (R K SHAH ₹62.5 lakh)
Exits: XYZ (P DIRECTOR sold all shares)
Disclosed data, not a tip: big investors also lose money.
```
Big buys/sells: net rows of the latest deal date, not round_trip, category in BIG_MONEY, top `limit` by
abs(net_value); who = investor or client. Insider: is_market BUY rows with `disclosed >= window(insider as_of,
3)`, top `limit` by value. Exits: events (`since = window(anchor, 3)`) with exit_kind full_exit (`"{who} sold all
shares"`), below_1pct (`"{who} now below 1%"`), category_exit (`"{label} sold out"`), top `limit`. Flow `fmt`:
sign + `f"{abs(v):,.0f}"` (`+2,358`, `−1,888`).

### 4.10 Error handling summary

- No public function raises on network or data problems; loaders return empty frames; refresh reports.
- A failed source never deletes stored data. Saving happens only after a successful merge.
- Programming errors inside a refresh step are caught per step and reported as `failed` with the exception text.

---------------------------------------------------------------------------------------------------------------------

## 5. Tests: `tests/test_smart_money.py` (builder A)

No network: every test that runs `refresh` monkeypatches `smart_money._fetch`; every file goes to `tmp_path`
(`folder=tmp_path`). Do not import `web.api`. Use the payloads below verbatim (as module constants).

```python
BULK_CSV = ("﻿Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,HRTI PRIVATE LIMITED,BUY,"1,08,709",826.15,-\n'
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,HRTI PRIVATE LIMITED,SELL,"1,05,000",827.40,-\n'
            '23-Oct-2026,ASTEC,Astec LifeSciences Ltd,SBI MUTUAL FUND A/C SBI SMALL CAP FUND,BUY,"2,50,000",820.00,-\n'
            "23-OCT-2026,XYZ,XYZ Limited,ASHISH RAMESHCHANDRA KACHOLIA,BUY,600000,412.35,-\n"
            "23-Oct-2026,XYZ,XYZ Limited,GOLDMAN SACHS (SINGAPORE) PTE,SELL,600000,412.10,-\n"
            "23-Oct-2026,PQR,PQR Ltd,SOME CLIENT,X,1000,10,-\n").encode("utf-8")
BLOCK_CSV = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
             "23-Oct-2026,OILCOUNTUB,Oil Country Tubular Ltd,UNITED STEEL ALLIED INDUSTRIES PVT LIMITED,SELL,4940000,65.3\n"
             "23-Oct-2026,OILCOUNTUB,Oil Country Tubular Ltd,NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND,BUY,4940000,65.3\n").encode()
BLOCK_EMPTY = b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
HIST_CSV = ('"Date","Symbol","Security Name","Client Name","Buy / Sell","Quantity Traded","Trade Price / Wght. Avg. Price","Remarks"\n'
            '"01-OCT-2026","ASTEC","Astec LifeSciences Ltd","SBI MUTUAL FUND A/C SBI SMALL CAP FUND","BUY","1,00,000","800.00","-"\n').encode()
HIST_JSON = b'{"data": [{"BD_DT_DATE": "01-OCT-2026", "BD_DT_ORDER": "2026-09-30T18:30:00.000+00:00", "BD_SYMBOL": "ASTEC", "BD_SCRIP_NAME": "Astec LifeSciences Ltd", "BD_CLIENT_NAME": "SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 100000, "BD_TP_WATP": 800.0, "BD_REMARKS": "-"}]}'
FIIDII_JSON = (b'[{"category": "DII **", "date": "23-Oct-2026", "buyValue": "15234.56", "sellValue": "12876.10", "netValue": "2358.46"},'
               b' {"category": "FII/FPI *", "date": "23-Oct-2026", "buyValue": "11000.00", "sellValue": "12888.42", "netValue": "-1888.42"}]')
PIT_JSON = json.dumps({"acqNameList": [], "data": [
    {"symbol": "XYZ", "company": "XYZ Limited", "anex": "7(2)", "acqName": "R K SHAH", "personCategory": "Promoter Group",
     "secType": "Equity Shares", "befAcqSharesNo": "1200000", "befAcqSharesPer": "12.00", "secAcq": "50,000",
     "secVal": "6250000", "tdpTransactionType": "Buy", "afterAcqSharesNo": "1250000", "afterAcqSharesPer": "12.50",
     "acqfromDt": "20-Oct-2026", "acqtoDt": "20-Oct-2026", "intimDt": "22-Oct-2026", "acqMode": "Market Purchase",
     "exchange": "NSE", "date": "22-Oct-2026 18:45", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_1.xml"},
    {"symbol": "XYZ", "company": "XYZ Limited", "anex": "7(2)", "acqName": "R K SHAH", "personCategory": "Promoter Group",
     "secType": "Equity Shares", "befAcqSharesNo": "1200000", "befAcqSharesPer": "12.00", "secAcq": "50,000",
     "secVal": "6250000", "tdpTransactionType": "Buy", "afterAcqSharesNo": "1250000", "afterAcqSharesPer": "12.50",
     "acqfromDt": "20-Oct-2026", "acqtoDt": "20-Oct-2026", "intimDt": "22-Oct-2026", "acqMode": "Market Purchase",
     "exchange": "NSE", "date": "23-Oct-2026 10:00", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_2.xml"},
    {"symbol": "XYZ", "company": "XYZ Limited", "acqName": "P DIRECTOR", "personCategory": "Director",
     "secType": "Equity Shares", "befAcqSharesNo": "10000", "befAcqSharesPer": "0.10", "secAcq": "10000",
     "secVal": "4100000", "tdpTransactionType": "Sell", "aftAcqSharesNo": "0", "aftAcqSharesPer": "0",
     "acqfromDt": "15-Oct-2026", "acqtoDt": "16-Oct-2026", "intimDt": "17-Oct-2026", "acqMode": "Market Sale",
     "exchange": "NSE", "date": "21-Oct-2026 19:02"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "ABC FAMILY TRUST", "personCategory": "Promoters",
     "secType": "Equity Shares", "befAcqSharesNo": "-", "befAcqSharesPer": "Nil", "secAcq": "25000", "secVal": "-",
     "tdpTransactionType": "Invocation", "acqMode": "Invocation of pledge", "acqfromDt": "18-Oct-2026",
     "acqtoDt": "18-Oct-2026", "intimDt": "20-Oct-2026", "exchange": "NSE", "date": "21-Oct-2026 11:30"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "S EMPLOYEE", "personCategory": "Designated Person",
     "secType": "Equity Shares", "secAcq": "500", "secVal": "50000", "tdpTransactionType": "Buy", "acqMode": "ESOP",
     "acqfromDt": "19-Oct-2026", "acqtoDt": "19-Oct-2026", "intimDt": "20-Oct-2026", "exchange": "NSE",
     "date": "21-Oct-2026 12:00"},
    {"symbol": "ABC", "company": "ABC Ltd", "acqName": "D TRADER", "personCategory": "Director", "secType": "Equity Shares",
     "secAcq": "-", "derivativeType": "Futures", "buyValue": "100000", "tdpTransactionType": "Buy", "acqMode": "Market Purchase",
     "date": "21-Oct-2026 12:30"}]}).encode()
SHP_MASTER_SEP = json.dumps([
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "30-SEP-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_2001_15102026101010_WEB.xml",
     "revisedData": "N", "recordId": 2001, "pr_and_prgrp": 50.0, "public_val": 50.0, "submissionDate": "15-OCT-2026",
     "broadcastDate": "15-OCT-2026 10:10:10"},
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "12-AUG-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1500_13082026101010_WEB.xml",
     "revisedData": "N", "recordId": 1500, "pr_and_prgrp": 51.0, "public_val": 49.0, "submissionDate": "13-AUG-2026",
     "broadcastDate": "13-AUG-2026 10:10:10"}]).encode()
SHP_MASTER_JUN = json.dumps({"data": [
    {"symbol": "XYZ", "name": "XYZ Limited", "date": "30-JUN-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1001_14072026090000_WEB.xml",
     "revisedData": "N", "recordId": 1001, "pr_and_prgrp": 52.0, "public_val": 48.0, "submissionDate": "14-JUL-2026",
     "broadcastDate": "14-JUL-2026 09:00:00"}]}).encode()
```

XBRL builder for the tests (put it in the test file exactly like this):

```python
NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp/2025-06-30/in-bse-shp"')


def _ctx(cid: str, member: str | None, typed: str | None = None) -> str:
    seg = ""
    if member:
        seg += ('<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
                f"in-bse-shp:{member}</xbrldi:explicitMember>")
    if typed:
        seg += (f'<xbrldi:typedMember dimension="in-bse-shp:{typed}Axis"><in-bse-shp:{typed}Domain>{cid}'
                f"</in-bse-shp:{typed}Domain></xbrldi:typedMember>")
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">XYZ'
            f"</xbrli:identifier><xbrli:segment>{seg}</xbrli:segment></xbrli:entity><xbrli:period>"
            "<xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>")


def _facts(cid: str, shares: float, pct: float, name: str | None = None) -> str:
    out = (f'<in-bse-shp:NumberOfShares contextRef="{cid}" unitRef="shares" decimals="0">{shares:.0f}'
           "</in-bse-shp:NumberOfShares>"
           f'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="{cid}" unitRef="pure" '
           f'decimals="4">{pct}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>')
    if name:
        out += f'<in-bse-shp:NameOfTheShareholder contextRef="{cid}">{name}</in-bse-shp:NameOfTheShareholder>'
    return out


def make_xbrl(cats: dict[str, float], holders: list[tuple[str, str, str, float]], fraction: bool = True,
              total_shares: float = 10_000_000) -> bytes:
    """cats: category member -> percent; holders: (name, member, typed axis stem, percent). fraction=True writes
    0.5 for 50% (the scale NSE often uses)."""
    k = 0.01 if fraction else 1.0
    parts = []
    for i, (member, pct) in enumerate(cats.items()):
        parts.append(_ctx(f"C{i}", member) + _facts(f"C{i}", total_shares * pct / 100, round(pct * k, 6)))
    for j, (name, member, typed, pct) in enumerate(holders):
        parts.append(_ctx(f"H{j}", member, typed) + _facts(f"H{j}", total_shares * pct / 100, round(pct * k, 6), name))
    return f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl {NS}>{"".join(parts)}</xbrli:xbrl>'.encode()


CATS_SEP = {"ShareholdingPatternMember": 100.0, "ShareholdingOfPromoterAndPromoterGroupMember": 50.0,
            "PublicShareholdingMember": 50.0, "InstitutionsDomesticMember": 15.0, "InstitutionsForeignMember": 12.0,
            "MutualFundsMember": 10.0, "InsuranceCompaniesMember": 3.0, "BanksMember": 2.0}
HOLDERS_SEP = [("ABC HOLDINGS PRIVATE LIMITED", "ShareholdingOfPromoterAndPromoterGroupMember",
                "DetailsOfSharesHeldByPromoterAndPromoterGroup", 50.0),
               ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "MutualFundsMember", "DetailsOfSharesHeldByMutualFunds", 6.0),
               ("GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO", "ForeignPortfolioInvestorsCategoryIMember",
                "DetailsOfSharesHeldByForeignPortfolioInvestors", 1.2),
               ("CLEARING MEMBERS", "ClearingMembersMember", "DetailsOfSharesHeldByClearingMembers", 0.2),
               ("RANDOM INVESTOR", "IndividualsMember", "DetailsOfSharesHeldByIndividuals", 0.5),
               ("XYZ PAC", "ShareholdingOfPromoterAndPromoterGroupMember", "DetailsOfPersonsActingInConcert", 3.0)]
CATS_JUN = {"ShareholdingPatternMember": 100.0, "ShareholdingOfPromoterAndPromoterGroupMember": 52.0,
            "PublicShareholdingMember": 48.0, "InstitutionsDomesticMember": 12.0, "InstitutionsForeignMember": 13.5,
            "MutualFundsMember": 8.0, "InsuranceCompaniesMember": 3.0, "BanksMember": 1.0}
HOLDERS_JUN = [("ABC HOLDINGS PRIVATE LIMITED", "ShareholdingOfPromoterAndPromoterGroupMember",
                "DetailsOfSharesHeldByPromoterAndPromoterGroup", 52.0),
               ("SBI MUTUAL FUND A/C SBI SMALL CAP FUND", "MutualFundsMember", "DetailsOfSharesHeldByMutualFunds", 4.5),
               ("OLD VALUE FUND LTD", "BodiesCorporateMember", "DetailsOfSharesHeldByBodiesCorporate", 2.0)]
```

Required tests (names are binding; each asserts at least what is listed):

1. `test_normalise_and_parent_key` - the three parent_key examples of 4.5.1; `normalise_name("M/S ABC & Co. Pvt.
   Ltd.") == "ABC AND COMPANY PRIVATE LIMITED"`; `"FUND-1"` becomes tokens `FUND - 1`.
2. `test_classify_table` - parametrised; expected `(category, sub_label, investor)`:
   - `SBI MUTUAL FUND A/C SBI SMALL CAP FUND` mf; `NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND`
     mf; `JIO BLACKROCK MUTUAL FUND` mf; `BARODA BNP PARIBAS MUTUAL FUND A/C BARODA BNP PARIBAS LARGE CAP FUND`
     mf; `LIC MUTUAL FUND` mf; `ADITYA BIRLA SUN LIFE TRUSTEE PRIVATE LIMITED A/C ADITYA BIRLA SUN LIFE FLEXI CAP
     FUND` mf
   - `LIFE INSURANCE CORPORATION OF INDIA` insurance; `HDFC LIFE INSURANCE COMPANY LIMITED` insurance; `TATA AIA
     LIFE INSURANCE COMPANY LIMITED` insurance; `LIC HOUSING FINANCE LIMITED` bank
   - `NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL` pension; `GOVERNMENT OF SINGAPORE` pension;
     `ABU DHABI INVESTMENT AUTHORITY` pension; `GIC PRIVATE LIMITED` pension
   - `GRAVITON RESEARCH CAPITAL LLP` broker; `HRTI PRIVATE LIMITED` broker; `BNP PARIBAS ARBITRAGE` broker
   - `SOCIETE GENERALE - ODI`, `MORGAN STANLEY ASIA (SINGAPORE) PTE.`, `GOLDMAN SACHS (SINGAPORE) PTE` ->
     `("fii", ODI_LABEL, None)`
   - `HDFC BANK LIMITED` bank; `BAJAJ FINANCE LIMITED` bank; `KOTAK MAHINDRA BANK LIMITED` bank
   - `VANGUARD EMERGING MARKETS STOCK INDEX FUND`, `ISHARES CORE MSCI EMERGING MARKETS ETF`,
     `SMALLCAP WORLD FUND, INC`, `COPTHALL MAURITIUS INVESTMENT LIMITED`,
     `GOLDMAN SACHS FUNDS - GOLDMAN SACHS INDIA EQUITY PORTFOLIO` -> fii (sub_label None)
   - `ASHISH RAMESHCHANDRA KACHOLIA` -> `("famous", None, "Ashish Kacholia")`; `REKHA RAKESH JHUNJHUNWALA` ->
     famous `"Rekha Jhunjhunwala (RJ estate)"`; `ABAKKUS EMERGING OPPORTUNITIES FUND-1` -> famous
     `"Sunil Singhania (Abakkus)"`
   - `RAJESH KUMAR` -> `("other", "Individual", None)`; `ABC ENTERPRISES PRIVATE LIMITED` -> other Company;
     `RAMESH HUF` -> other HUF/Trust
   - `CLICK COMMERCE LLP` and `PUBLICIS GROUPE` are **not** insurance
   - `XYZ TRADERS PRIVATE LIMITED` with `round_trip=True` -> broker; `ABC HOLDINGS PRIVATE LIMITED` with
     `promoters={"ABC HOLDINGS PRIVATE LIMITED"}` -> promoter
3. `test_famous_aliases_need_two_tokens` - every `_ALIASES` token set has >= 2 tokens or is a subset of
   `BRAND_TOKENS`; `classify("ASHISH SHAH")` is not famous.
4. `test_parse_bulk_and_block` - `parse_deals(BULK_CSV, "bulk", "archive")` has 5 rows (the `X` side dropped),
   all dates `"2026-10-23"`, HRTI BUY qty `108709.0`, values `qty * price`; `parse_deals(BLOCK_EMPTY, "block",
   "archive")` is empty with exactly DEAL_COLS; BLOCK_CSV has 2 rows.
5. `test_parse_history_csv_and_json` - HIST_CSV and HIST_JSON give the same single row (date `2026-10-01`,
   qty 100000, price 800, side BUY).
6. `test_net_deals_round_trip_and_counterparties` - net_deals over BULK+BLOCK with
   `shares={"XYZ": 10_000_000}`: HRTI row round_trip True, side BUY, net_qty 3709, category broker; SBI MF mf,
   net_value 205,000,000, pct_equity NaN; Kacholia famous with pct_equity 6.0; Goldman PTE fii with ODI_LABEL;
   Nippon block BUY with `counterparties == ["UNITED STEEL ALLIED INDUSTRIES PVT LIMITED"]`.
7. `test_parse_pit` - 4 rows (6 records minus the derivative row and the revised duplicate); the kept R K SHAH row
   has `disclosed == "2026-10-23"`; enriched: R K SHAH role promoter, is_market True, change_pts 0.5; P DIRECTOR
   fully_exited True, delay_days 5, category other with INSIDER_LABEL; ABC FAMILY TRUST mode_kind pledge_invoked,
   side NaN, value NaN; S EMPLOYEE mode_kind esop, is_market False.
8. `test_parse_fiidii` - one row, date `2026-10-23`, fii_net_cr -1888.42, dii_net_cr 2358.46.
9. `test_parse_shp_master` - SHP_MASTER_SEP gives 1 row (the 12-Aug allotment pattern is dropped), record_id
   2001, broadcast `"2026-10-15T10:10:10+05:30"`.
10. `test_parse_shp_xbrl_both_scales` - `make_xbrl(CATS_SEP, HOLDERS_SEP)` and the same with `fraction=False`
    give identical results: promoter 50, public 50, dii 15, fii 12, mf 10, insurance 3, banks 2, pension 0.0,
    aif 0.0, total_shares 10,000,000; holders = exactly ABC HOLDINGS (promoter, 50), SBI MF (public, 6),
    GOLDMAN SACHS FUNDS (public, 1.2) - the clearing-members row, the 0.5% holder and the PAC row are gone.
11. `test_events_and_exits` - build holdings/holders frames from the two parsed XBRLs (period
    `2026-09-30`/broadcast `2026-10-15T10:10:10+05:30` and `2026-06-30`/`2026-07-14T09:00:00+05:30`, both source
    xbrl). `events(...)` with `since="2026-10-01"` must contain for XYZ exactly these shareholding events:
    category_up mf (+2.0), category_up bank (+1.0), category_down fii (-1.5), category_down promoter (-2.0),
    holder_cut ABC HOLDINGS, holder_added SBI MF (+1.5), new_holder GOLDMAN SACHS FUNDS, holder_dropped OLD VALUE
    FUND LTD with exit_kind `below_1pct` and text containing `"sold some or all"`. With the PIT rows: insider_exit
    for P DIRECTOR (exit_kind full_exit), insider_buy for R K SHAH (weight 2), pledge_invoked for ABC, no event for
    S EMPLOYEE. With BULK net rows: deal_sell for the Goldman PTE row (exit_kind sold_part), no event for HRTI.
12. `test_stock_signals_and_lists` - for XYZ: inst_sellers 1, famous_buyers `["Ashish Kacholia"]`,
    promoter_buying True, mf_chg_pts 2.0, exits >= 2; `accumulating()` contains XYZ; `exiting()` contains XYZ.
13. `test_refresh_end_to_end(tmp_path, monkeypatch)` - fake `_fetch(url, params=None, *, api=False,
    referer=None)` returning: BULK_CSV / BLOCK_CSV for the two archive URLs; header-only HIST CSV for
    `historicalOR`; PIT_JSON when `params["from_date"] == "01-10-2026"` for `corporates-pit`, else
    `b'{"data": []}'`; FIIDII_JSON for `fiidiiTradeReact`; for `corporate-share-holdings-master` SHP_MASTER_SEP
    when `from_date == "01-10-2026"`, SHP_MASTER_JUN when `"01-07-2026"`, else `b"[]"`; `make_xbrl(CATS_SEP,
    HOLDERS_SEP)` for URLs containing `SHP_2001`, `make_xbrl(CATS_JUN, HOLDERS_JUN)` for `SHP_1001`; anything
    else `(404, b"")`. Count calls per URL. `refresh(days=60, log=lambda m: None, symbols=["XYZ"],
    folder=tmp_path, today=date(2026, 10, 24))` -> `ok` True, all four sources ok; `load_deals` 7 rows,
    `load_insider` 4 rows, `load_flows` 1 row, `load_holdings` 2 rows (both xbrl), `state.json` exists, gz files
    `xbrl/SHP_2001.xml.gz` and `xbrl/SHP_1001.xml.gz` exist. A second identical refresh adds 0 deal and 0 insider
    rows and makes **no** XBRL request.
14. `test_refresh_offline_never_raises(tmp_path, monkeypatch)` - fake returns `(-1, b"")` for everything; seed
    `deals.parquet` first via one successful run (or `parse_deals` + the module's save helper); the offline
    refresh returns `ok` False with status failed for deals, insider, flows; the deals file is unchanged; loaders
    still return the old rows; `refresh` did not raise.
15. `test_refresh_busy_lock(tmp_path)` - hold the lock (open `.refresh.lock` and `_try_lock`), then `refresh`
    returns every source `skipped` and does not write `state.json`; `refresh_running(tmp_path)` is True.

---------------------------------------------------------------------------------------------------------------------

## 6. API (builder B)

Rules from `web/api/main.py` apply: GET handlers never touch the network (they read `data/smart_money/` through
the loaders); only `POST /api/smart-money/refresh` starts network work, in a background thread.

### 6.1 `web/api/models/smart_money.py` (write exactly this; docstring/comments may be extended)

```python
"""Smart money (docs/smart_money_spec.md): bulk/block deals, insider (SEBI PIT) trades, quarterly shareholding changes
and FII/DII flows, all from NSE disclosures. Money in rupees except the *_cr FII/DII fields (NSE publishes those in
crore); *_pct are percent of the company's shares (12.3 = 12.3%); *_pts / change_pts are percentage-point changes."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ISODate, ISODateTime, Model

__all__ = ["SmCategory", "SmCategoryFilter", "SmDealKind", "SmDealSide", "SmModeKind", "SmEventType", "SmExitKind",
           "SmSourceKind", "SmRunState", "SmSourceState", "SmFreshness", "SmRefreshRun", "SmSource", "SmSources",
           "SmStatus", "SmDeal", "SmDealCounts", "SmDealsResponse", "SmInsiderTrade", "SmInsiderCounts",
           "SmInsiderResponse", "SmEvent", "SmStock", "SmHoldingsResponse", "SmFlowDay", "SmFlowsResponse", "SmKpis",
           "SmOverview", "SmHoldingPeriod", "SmHolder", "SmStockResponse", "SmRefreshRequest", "SmRefreshAccepted"]

SmCategory = Literal["fii", "mf", "insurance", "bank", "pension", "promoter", "famous", "broker", "other"]
SmCategoryFilter = Literal["all", "big", "institutions", "fii", "mf", "insurance", "bank", "pension", "promoter",
                           "famous", "broker", "other"]
SmDealKind = Literal["bulk", "block", "both"]
SmDealSide = Literal["BUY", "SELL", "FLAT"]
SmModeKind = Literal["market", "pledge", "pledge_invoked", "off_market", "esop", "gift", "inter_se", "preferential",
                     "other"]
SmEventType = Literal["deal_buy", "deal_sell", "insider_buy", "insider_sell", "insider_exit", "pledge_invoked",
                      "new_holder", "holder_added", "holder_cut", "holder_dropped", "category_up", "category_down",
                      "category_exit"]
SmExitKind = Literal["full_exit", "below_1pct", "sold_part", "category_exit"]
SmSourceKind = Literal["bulk", "block", "insider", "shareholding"]
SmRunState = Literal["idle", "running", "done", "failed"]
SmSourceState = Literal["ok", "partial", "failed", "skipped", "never"]


class SmFreshness(Model):
    deals: ISODate | None = None             # newest bulk/block deal date stored
    insider: ISODate | None = None           # newest insider disclosure date stored
    flows: ISODate | None = None             # newest FII/DII day stored
    holdings_period: ISODate | None = None   # newest shareholding quarter end stored
    refreshed_at: ISODateTime | None = None  # when the last refresh finished
    stale: bool                              # never refreshed, or newest deals > 5 days before today (IST)


class SmRefreshRun(Model):
    state: SmRunState
    running: bool
    message: str | None = None
    started_at: ISODateTime | None = None
    finished_at: ISODateTime | None = None
    errors: list[str]


class SmSource(Model):
    status: SmSourceState
    message: str | None = None
    rows_added: int = 0
    last_ok_at: ISODateTime | None = None
    latest_date: ISODate | None = None


class SmSources(Model):
    deals: SmSource
    insider: SmSource
    flows: SmSource
    holdings: SmSource


class SmStatus(Model):
    run: SmRefreshRun
    freshness: SmFreshness
    sources: SmSources
    errors: list[str]                        # the last refresh's problems, plain English


class SmDeal(Model):
    """One client's net bulk/block trading in one stock on one day (NSE's rows for that client summed)."""
    id: str
    date: ISODate
    symbol: str
    company: str | None = None
    kind: SmDealKind
    side: SmDealSide                         # sign of net_qty; FLAT = bought and sold the same number
    client: str                              # name exactly as filed with NSE
    client_key: str                          # normalised parent name (one fund house's schemes together)
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None              # well-known investor's display name (category 'famous')
    round_trip: bool                         # bought and sold about the same quantity the same day (intraday)
    buy_qty: int
    sell_qty: int
    net_qty: int
    buy_value: float                         # rupees
    sell_value: float
    net_value: float
    avg_price: float | None = None           # rupees per share
    pct_equity: float | None = None          # shares traded as % of all the company's shares (null = unknown)
    counterparties: list[str]                # block deals: clients on the other side the same day


class SmDealCounts(Model):
    buys: int
    sells: int
    intraday: int
    by_category: dict[str, int]


class SmDealsResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    until: ISODate | None = None
    intraday: bool
    total: int
    page: int
    page_size: int
    rows: list[SmDeal]
    counts: SmDealCounts
    note: str


class SmInsiderTrade(Model):
    id: str
    symbol: str
    company: str | None = None
    person: str
    role: Literal["promoter", "insider", "other"]
    person_category: str | None = None       # as filed, e.g. 'Promoter Group'
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    mode: str | None = None                  # as filed, e.g. 'Market Purchase'
    mode_kind: SmModeKind
    is_market: bool                          # an open-market buy/sell: the only real buy/sell decision
    qty: int | None = None
    value: float | None = None               # rupees
    avg_price: float | None = None
    before_pct: float | None = None
    after_pct: float | None = None
    change_pts: float | None = None
    before_shares: int | None = None
    after_shares: int | None = None
    trade_from: ISODate | None = None
    trade_to: ISODate | None = None
    disclosed: ISODate | None = None
    delay_days: int | None = None            # calendar days from the trade to the NSE filing
    fully_exited: bool
    xbrl: str | None = None


class SmInsiderCounts(Model):
    buys: int
    sells: int
    buy_value: float
    sell_value: float
    pledge_invoked: int
    full_exits: int


class SmInsiderResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    until: ISODate | None = None
    total: int
    page: int
    page_size: int
    rows: list[SmInsiderTrade]
    counts: SmInsiderCounts
    note: str


class SmEvent(Model):
    """One thing a big investor did that the disclosures show (server-written plain-English `text`)."""
    id: str
    date: ISODate                            # when it became public
    symbol: str
    company: str | None = None
    event: SmEventType
    direction: Literal["up", "down"]
    source: SmSourceKind
    who: str | None = None                   # name as filed (null for a whole-category change)
    investor: str | None = None
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    value: float | None = None               # rupees
    qty: int | None = None
    pct_before: float | None = None
    pct_after: float | None = None
    change_pts: float | None = None
    pct_equity: float | None = None
    period: ISODate | None = None            # shareholding quarter end
    prev_period: ISODate | None = None
    exit_kind: SmExitKind | None = None
    text: str


class SmStock(Model):
    symbol: str
    company: str | None = None
    direction: Literal["up", "down", "mixed"]
    up_events: int
    down_events: int
    up_score: int
    down_score: int
    deal_buy_value: float                    # rupees: big-money bulk/block net buys in the window (no intraday)
    deal_sell_value: float
    deal_net_value: float
    inst_buyers: int                         # distinct institutions net buying via deals
    inst_sellers: int
    famous_buyers: list[str]
    famous_sellers: list[str]
    insider_buy_value: float                 # open-market promoter/insider buys disclosed in the window
    insider_sell_value: float
    promoter_buying: bool
    promoter_selling: bool
    pledge_invoked: bool
    exits: int
    fii_chg_pts: float | None = None         # latest quarter vs the one before
    dii_chg_pts: float | None = None
    mf_chg_pts: float | None = None
    promoter_chg_pts: float | None = None
    period: ISODate | None = None
    last_date: ISODate
    reasons: list[str]                       # up to 4 plain-English lines, most important first


class SmHoldingsResponse(Model):
    freshness: SmFreshness
    view: Literal["accumulating", "exiting", "all"]
    days: int
    since: ISODate | None = None
    latest_period: ISODate | None = None
    previous_period: ISODate | None = None
    coverage: int                            # stocks with shareholding data
    stocks: list[SmStock]
    events: list[SmEvent]
    note: str


class SmFlowDay(Model):
    date: ISODate
    fii_buy_cr: float | None = None          # rupees crore
    fii_sell_cr: float | None = None
    fii_net_cr: float | None = None
    dii_buy_cr: float | None = None
    dii_sell_cr: float | None = None
    dii_net_cr: float | None = None


class SmFlowsResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    first_date: ISODate | None = None        # history starts here (NSE gives one day at a time)
    rows: list[SmFlowDay]                    # newest first
    fii_net_cr_total: float | None = None
    dii_net_cr_total: float | None = None
    fii_streak: int                          # +3 = 3 buying days in a row up to the latest, -2 = 2 selling days
    dii_streak: int
    note: str


class SmKpis(Model):
    days: int
    since: ISODate | None = None
    big_buy_value: float
    big_sell_value: float
    inst_net_value: float
    stocks_bought: int
    stocks_sold: int
    insider_buy_value: float
    insider_sell_value: float
    exits: int
    intraday_rows: int
    fii_net_cr: float | None = None
    dii_net_cr: float | None = None
    flows_date: ISODate | None = None


class SmOverview(Model):
    freshness: SmFreshness
    run: SmRefreshRun
    days: int
    kpis: SmKpis
    top_bought: list[SmStock]
    top_sold: list[SmStock]
    latest_deals_date: ISODate | None = None
    latest_deals: list[SmDeal]
    latest_insider: list[SmInsiderTrade]
    exits: list[SmEvent]
    flows: list[SmFlowDay]
    has_data: bool
    errors: list[str]
    note: str


class SmHoldingPeriod(Model):
    period: ISODate
    broadcast: ISODate | None = None
    source: Literal["xbrl", "master"]
    total_shares: int | None = None
    promoter_pct: float | None = None
    public_pct: float | None = None
    fii_pct: float | None = None
    dii_pct: float | None = None
    mf_pct: float | None = None
    insurance_pct: float | None = None
    banks_pct: float | None = None
    pension_pct: float | None = None
    aif_pct: float | None = None


class SmHolder(Model):
    holder: str
    holder_key: str
    group: Literal["promoter", "public"]
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None
    pct: float | None = None
    prev_pct: float | None = None
    change_pts: float | None = None
    shares: int | None = None
    status: Literal["new", "added", "cut", "same", "dropped"]


class SmStockResponse(Model):
    symbol: str
    company: str | None = None
    freshness: SmFreshness
    days: int
    has_data: bool
    summary: SmStock | None = None
    deals: list[SmDeal]
    insider: list[SmInsiderTrade]
    holdings: list[SmHoldingPeriod]
    holders_period: ISODate | None = None
    holders_prev_period: ISODate | None = None
    holders: list[SmHolder]
    events: list[SmEvent]
    note: str


class SmRefreshRequest(Model):
    days: int = Field(365, ge=30, le=730)    # history depth for the first backfill


class SmRefreshAccepted(Model):
    accepted: bool
    run: SmRefreshRun
```

### 6.2 `web/api/routers/smart_money.py` (write exactly this shape)

```python
"""Smart money: which stocks big investors are buying, selling or leaving (docs/smart_money_spec.md).

GET handlers read only data/smart_money/ (never NSE). POST /refresh is the one network job; it runs
scanner.smart_money.refresh in a background thread of this process."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..models.smart_money import (SmCategoryFilter, SmDealsResponse, SmFlowsResponse, SmHoldingsResponse,
                                  SmInsiderResponse, SmOverview, SmRefreshAccepted, SmRefreshRequest, SmStatus,
                                  SmStockResponse)
from ..services import smart_money_svc as svc

router = APIRouter(prefix="/api/smart-money", tags=["smart-money"])


@router.get("/status", response_model=SmStatus)
def status():
    return svc.status()


@router.get("/overview", response_model=SmOverview)
def overview(days: int = Query(30, ge=1, le=365)):
    return svc.overview(days)


@router.get("/deals", response_model=SmDealsResponse)
def deals(days: int = Query(1, ge=1, le=365), side: Literal["all", "buy", "sell"] = "all",
          kind: Literal["all", "bulk", "block"] = "all", category: SmCategoryFilter = "all",
          symbol: str | None = None, intraday: bool = False, page: int = Query(1, ge=1),
          page_size: int = Query(100, ge=1, le=500)):
    return svc.deals(days, side, kind, category, symbol, intraday, page, page_size)


@router.get("/insider", response_model=SmInsiderResponse)
def insider(days: int = Query(30, ge=1, le=365), side: Literal["all", "buy", "sell"] = "all",
            category: Literal["all", "promoter", "insider"] = "all", mode: Literal["market", "all"] = "market",
            symbol: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    return svc.insider(days, side, category, mode, symbol, page, page_size)


@router.get("/holdings", response_model=SmHoldingsResponse)
def holdings(view: Literal["accumulating", "exiting", "all"] = "accumulating", days: int = Query(30, ge=1, le=365),
             category: SmCategoryFilter = "all", symbol: str | None = None):
    return svc.holdings(view, days, category, symbol)


@router.get("/flows", response_model=SmFlowsResponse)
def flows(days: int = Query(30, ge=1, le=3650)):
    return svc.flows(days)


@router.get("/stock/{symbol}", response_model=SmStockResponse)
def stock(symbol: str, days: int = Query(365, ge=1, le=730)):
    return svc.stock(symbol, days)


@router.post("/refresh", response_model=SmRefreshAccepted, status_code=202)
def refresh(body: SmRefreshRequest | None = None):
    return {"accepted": True, "run": svc.start_refresh(body.days if body else 365)}
```

### 6.3 `web/api/services/smart_money_svc.py`

Module docstring: "Smart-money payloads from data/smart_money/ (scanner.smart_money loaders), cached by the files'
identity; the refresh runs in a background thread with a lock. No GET path touches the network."

Imports: `from scanner import smart_money as sm`; `from . import data`; `from ..caches import KeyedCache,
file_key, register`; `from ..errors import ApiException`; `from ..paths import P`; `from ..util import inum,
now_ist, num, today_ist`; stdlib `math`, `re`, `threading`, `datetime.date`.

Folder: `def _folder() -> Path: return P.data / "smart_money"` - every `sm.*` call passes `folder=_folder()`
(so the contract tests' `paths.configure()` repointing works without touching scanner globals).

**Caches.** `_key()` = `tuple(file_key(p) for p in sm.files(_folder()).values())`.
`_base_cache = register(KeyedCache(1))`, `_derived_cache = register(KeyedCache(8))`.

```python
def _base() -> dict:      # keyed by _key()
    deals = sm.load_deals(f); insider = sm.load_insider(f); flows = sm.load_flows(f)
    holdings = sm.load_holdings(f); holders = sm.load_holders(f); state = sm.load_state(f)
    net = sm.net_deals(deals, sm.promoter_sets(holders, insider), sm.share_counts(holdings))
    companies = {**sm.company_names(net, insider, holdings),
                 **{s: m["company"] for s, m in data.symbol_meta().items() if m.get("company")}}
    return {"deals": deals, "net": net, "insider": insider, "flows": flows, "holdings": holdings,
            "holders": holders, "state": state, "companies": companies,
            "deals_asof": sm.latest(deals, "date"), "insider_asof": sm.latest(insider, "disclosed"),
            "flows_asof": sm.latest(flows, "date"), "period": sm.latest(holdings, "period")}


def _derived(days: int) -> dict:   # keyed by (_key(), days); call _base() BEFORE _derived_cache.get
    anchor = max([d for d in (b["deals_asof"], b["insider_asof"]) if d], default=today_ist().isoformat())
    since = sm.window(anchor, days)
    shp_since = sm.window(anchor, max(days, sm.SHP_EVENT_DAYS))
    ev = sm.events(b["net"], b["insider"], b["holdings"], b["holders"], since, shp_since, b["companies"])
    sig = sm.stock_signals(ev, b["net"], b["holdings"], since)
    return {"anchor": anchor, "since": since, "events": ev, "signals": sig}
```

**Windows.** `/deals` anchors at `deals_asof` (so `days=1` is always the latest deal day), `/insider` at
`insider_asof`, `/flows` at `flows_asof`; `/overview`, `/holdings`, `/stock` use `_derived(days)` (anchor = the
later of the deal and insider dates). `until` = the anchor. No data -> `since`/`until` null and empty lists.

**Conversion helpers** (private): `_s(x)` -> str or None (None/NaN/`""` -> None; only scalars); `_f(x, nd)` =
`num(x, nd)`; `_i(x)` = `inum(x)`; `_list(x)` -> `[str(v) for v in x]` if list/tuple/ndarray else `[]`.
Rounding: rupee values 0 dp, prices 2 dp, pct 2 dp (`pct_equity` 3 dp), `_cr` 2 dp, change_pts 2 dp.
`company` of a row = `b["companies"].get(symbol)` else the row's own security/company.

Row -> JSON (one function each; fields exactly as the models):

- `_deal(r)`: from a net row; `category_label = sm.CATEGORY_LABELS[category]`; qty fields `int(round(x))`;
  `counterparties = _list(r["counterparties"])`.
- `_insider(r)`: from an enriched insider row; `qty`/`before_shares`/`after_shares`/`delay_days` via `_i`.
- `_event(r)`: from an events row (drop `who_key`, `weight`); `qty` via `_i`.
- `_stock(r)`: from a signals row; lists via `_list`; bools via `bool()`.
- `_period(r)`: from a holdings row; `broadcast = _s(r["broadcast"])[:10]` when set; `total_shares` via `_i`.
- `_holder(r)`: from a holder_changes row; `shares` via `_i`.
- `_flow(r)`: from a flows row.

**Freshness.** `_freshness(b)`: `refreshed_at = state.last_run.finished_at`; `stale = refreshed_at is None or
deals_asof is None or (today_ist() - date.fromisoformat(deals_asof)).days > 5`.

**Endpoints:**

- `status()`: `{"run": run_status(), "freshness": _freshness(b), "sources": {name: state source or
  {"status": "never", "message": None, "rows_added": 0, "last_ok_at": None, "latest_date": None}},
  "errors": state.errors or []}` for the four names.
- `overview(days)`: `d = _derived(days)`; on `net` rows `date >= d.since`: `big_buy_value` = sum of positive
  net_value of non-round-trip BIG_MONEY rows, `big_sell_value` = sum of -negative, `inst_net_value` = sum of
  net_value of non-round-trip INSTITUTIONS rows, `intraday_rows` = round-trip row count; `stocks_bought` /
  `stocks_sold` = signals with deal_net_value > 0 / < 0; `insider_buy_value` / `insider_sell_value` = sum of value
  of `is_market` BUY / SELL insider rows with `disclosed >= since`; `exits` = events with exit_kind in
  (full_exit, below_1pct, category_exit); `fii_net_cr`/`dii_net_cr`/`flows_date` from the newest flows row.
  `top_bought = accumulating(signals)[:10]`, `top_sold = exiting(signals)[:10]`, each stock's `reasons` replaced
  by `sm.top_reasons(its events, "up")` / `(…, "down")`; `latest_deals` = net rows of
  `deals_asof`, not round trip, sorted (category in BIG_MONEY) desc then abs(net_value) desc, 20 max;
  `latest_insider` = `is_market` rows sorted disclosed desc, value desc, 10 max; `exits` = down events with a
  non-null exit_kind, date desc, weight desc, 10 max; `flows` = newest 10; `has_data` = any of deals, insider,
  flows, holdings non-empty; `errors` = state errors; `note = NOTE_MAIN`.
- `deals(days, side, kind, category, symbol, intraday, page, page_size)`: rows = net rows with `date >= since`;
  `kind`: bulk -> kind in (bulk, both), block -> kind in (block, both); `symbol` -> `== symbol.strip().upper()`.
  `counts` on these rows (ignoring side/category/intraday): buys / sells = non-round-trip BUY / SELL counts,
  intraday = round-trip count, by_category = non-round-trip counts per category (only categories present). Then
  `round_trip == intraday`, `category_mask(category)`, side (buy -> BUY, sell -> SELL). `total` = rows left;
  page slice `[(page-1)*page_size : page*page_size]` (past the end -> empty). Order: 4.8.2. `note = NOTE_DEALS`.
- `insider(days, side, category, mode, symbol, page, page_size)`: rows `disclosed >= since`; symbol; category
  (promoter -> role promoter, insider -> role insider). `counts` here (before side/mode): buys/sells/buy_value/
  sell_value over `is_market` rows, pledge_invoked = mode_kind count, full_exits = fully_exited count. Then mode
  `market` -> `is_market | (mode_kind == "pledge_invoked")`; side. Sorted disclosed desc, value desc. Page as
  above. `note = NOTE_INSIDER`.
- `holdings(view, days, category, symbol)`: `d = _derived(days)`; events filtered by view (accumulating -> up,
  exiting -> down, all -> both), `category_mask(category)` on event category, symbol; stocks = `accumulating()` /
  `exiting()` / all signals, restricted to symbols left in the filtered events. For the accumulating / exiting
  views each stock's `reasons` = `sm.top_reasons(<that stock's filtered events>, "up" / "down")` (so the
  exiting list explains the selling, even for a stock that is also being bought); `all` keeps the signals'
  reasons. `stocks[:200]`, `events[:500]`.
  `latest_period` = newest period; `previous_period` = the quarter end before it (calendar); `coverage` = distinct
  symbols in holdings. `note = NOTE_HOLDINGS.format(days=days)`.
- `flows(days)`: rows with `date >= window(flows_asof, days)`, newest first; totals = sums (None when no rows);
  streaks over the full flows table: count back from the newest row while the sign of `*_net_cr` equals the newest
  row's sign (positive count for buying, negative for selling, 0 if none/zero). `first_date` = oldest stored date.
  `note = NOTE_FLOWS`.
- `stock(symbol, days)`: `sym = symbol.strip().upper()`; must match `^[A-Z0-9&\-_.]{1,30}$` else
  `ApiException("VALIDATION", "Invalid symbol.", "Use an NSE symbol such as RELIANCE or M&M.", {"param":
  "symbol"})`. Same windows as `_derived(days)` (same anchor), but `sm.events` / `sm.stock_signals` /
  `sm.holder_changes` run on this stock's rows only (they work stock by stock, so the rows are identical and the
  Chart side panel never builds a year of the whole market). `deals` = net rows of sym with `date >= since`
  (round trips included), 200 max; `insider` = rows of sym `disclosed >= since` (all modes), 200 max; `holdings` = holdings rows of sym,
  newest 4; holders = `sm.holder_changes(b["holders"], b["holdings"])` rows of sym (`holders_period` /
  `holders_prev_period` from them); `events` of sym, 200 max; `summary` = its signals row or None. Not found is
  **not** an error: `has_data` false and empty lists. `note = NOTE_STOCK`.

**Background refresh:**

```python
_run_lock = threading.Lock()
_run: dict = {"thread": None, "state": "idle", "message": None, "started_at": None, "finished_at": None, "errors": []}

def run_status() -> dict:   # SmRefreshRun
    alive = _run["thread"] is not None and _run["thread"].is_alive()
    other = not alive and sm.refresh_running(_folder())      # the daily scan (another process) is refreshing
    state = "running" if alive or other else _run["state"]
    message = "Refresh started by the daily scan" if other else _run["message"]
    return {"state": state, "running": alive or other, "message": message, "started_at": _run["started_at"],
            "finished_at": _run["finished_at"], "errors": list(_run["errors"])}

def start_refresh(days: int) -> dict:
    with _run_lock:
        if (_run["thread"] is not None and _run["thread"].is_alive()) or sm.refresh_running(_folder()):
            raise ApiException("SCAN_BUSY", "A smart-money refresh is already running.",
                               "Wait for it to finish - this page updates by itself.",
                               {"started": str(_run["started_at"] or "?"), "by": "smart-money", "pid": None})
        _run.update(state="running", message="Starting...", started_at=now_ist().isoformat(timespec="seconds"),
                    finished_at=None, errors=[])
        t = threading.Thread(target=_worker, args=(days,), name="smart-money-refresh", daemon=True)
        _run["thread"] = t
        t.start()
    return run_status()
```
`_worker(days)`: `rep = sm.refresh(days=days, log=lambda m: _run.update(message=str(m)[:300]),
folder=_folder())`; `state = "failed"` if every source status is failed/skipped else `"done"`; `message` =
`"Done in {elapsed_s:.0f} s"` plus `" with problems"` when `rep["errors"]`; `errors = rep["errors"]`. Any
exception -> `state "failed"`, `message f"{type(e).__name__}: {e}"[:300]`, logged with `errors.log.exception`.
Always set `finished_at` in `finally`. (Caches invalidate by themselves: the files' identity changes.)

**Notes (server text, exact):**

```python
NOTE_MAIN = ("What you see here are deals and holdings that big investors must report by law. It is not live, and "
             "it is not a tip. Bulk and block deals show up after the market closes. Insider trades can be reported "
             "up to about 4 trading days late, and shareholding only once a quarter, up to 3 weeks late. Many "
             "\"bulk deals\" are trading firms that buy and sell the same day: we mark those as \"intraday\" and "
             "leave them out of the buyer and seller lists. Studies on Indian stocks find most of the price move "
             "around bulk deals happens before or on the deal day. Promoter buying in small companies has been "
             "followed by gains on average, but averages hide many losers, and those stocks can be hard to trade. "
             "A famous name buying does not mean the price will rise. Big investors also lose money, and they can "
             "sell without anyone knowing until the next filing. A stock dropping off the shareholding list only "
             "means they now hold less than 1%, not always a full exit. Use this as one clue next to your own "
             "analysis, never as a buy or sell signal. This is not investment advice.")
NOTE_DEALS = ("Bulk deal = one client traded more than 0.5% of a company's shares in a day. Block deal = a single "
              "trade of at least ₹25 crore in NSE's special morning or afternoon window. Both are published after "
              "the close. Trading firms that bought and sold about the same quantity the same day are listed "
              "separately under 'Intraday / arbitrage'.")
NOTE_INSIDER = ("Promoters, directors and key staff must report trades over ₹10 lakh a quarter: they tell the "
                "company within 2 trading days and the company tells NSE within 2 more, so a filing can be about 4 "
                "or more trading days old. Only 'Market Purchase' and 'Market Sale' are real buy/sell decisions; "
                "ESOPs, gifts, transfers and pledges are not. A pledge 'invocation' means a lender sold the shares.")
NOTE_HOLDINGS = ("Shareholding is filed once a quarter, up to 21 days after the quarter ends, and only holders with "
                 "1% or more are named - so 'no longer shown' means they now hold less than 1%, not always a full "
                 "exit. Bulk/block deals and insider trades here are from the last {days} days.")
NOTE_FLOWS = ("Market-wide buying and selling in the cash market by foreign (FII/FPI) and domestic (DII) "
              "institutions, in ₹ crore, as NSE publishes it the same evening (provisional). It is not per stock, "
              "and studies find these flows mostly follow the market rather than predict it. History builds up from "
              "the day of your first refresh.")
NOTE_STOCK = ("Disclosed data only: bulk/block deals, insider filings and the quarterly shareholding pattern. It is "
              "not live and not a buy or sell signal.")
```

### 6.4 Example responses

`GET /api/smart-money/deals?days=1&category=big` (the samples of section 5; 2 of the 4 rows shown)

```json
{
  "freshness": {"deals": "2026-10-23", "insider": "2026-10-23", "flows": "2026-10-23", "holdings_period": "2026-09-30",
                "refreshed_at": "2026-10-23T19:05:12+05:30", "stale": false},
  "days": 1, "since": "2026-10-23", "until": "2026-10-23", "intraday": false, "total": 4, "page": 1, "page_size": 100,
  "rows": [
    {"id": "2026-10-23|OILCOUNTUB|NIPPON LIFE INDIA TRUSTEE LIMITED", "date": "2026-10-23", "symbol": "OILCOUNTUB",
     "company": "Oil Country Tubular Ltd", "kind": "block", "side": "BUY",
     "client": "NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA SMALL CAP FUND",
     "client_key": "NIPPON LIFE INDIA TRUSTEE LIMITED", "category": "mf", "category_label": "Mutual fund",
     "sub_label": null, "investor": null, "round_trip": false, "buy_qty": 4940000, "sell_qty": 0, "net_qty": 4940000,
     "buy_value": 322582000.0, "sell_value": 0.0, "net_value": 322582000.0, "avg_price": 65.3, "pct_equity": null,
     "counterparties": ["UNITED STEEL ALLIED INDUSTRIES PVT LIMITED"]},
    {"id": "2026-10-23|XYZ|ASHISH RAMESHCHANDRA KACHOLIA", "date": "2026-10-23", "symbol": "XYZ", "company": "XYZ Limited",
     "kind": "bulk", "side": "BUY", "client": "ASHISH RAMESHCHANDRA KACHOLIA", "client_key": "ASHISH RAMESHCHANDRA KACHOLIA",
     "category": "famous", "category_label": "Well-known investor", "sub_label": null, "investor": "Ashish Kacholia",
     "round_trip": false, "buy_qty": 600000, "sell_qty": 0, "net_qty": 600000, "buy_value": 247410000.0,
     "sell_value": 0.0, "net_value": 247410000.0, "avg_price": 412.35, "pct_equity": 6.0, "counterparties": []}
  ],
  "counts": {"buys": 3, "sells": 2, "intraday": 1, "by_category": {"mf": 2, "famous": 1, "fii": 1, "other": 1}},
  "note": "Bulk deal = one client traded more than 0.5% of a company's shares in a day. ..."
}
```

`GET /api/smart-money/insider?days=30`

```json
{
  "freshness": {"...": "as above"}, "days": 30, "since": "2026-09-24", "until": "2026-10-23", "total": 3, "page": 1,
  "page_size": 100,
  "rows": [
    {"id": "XYZ|R K SHAH|2026-10-20|50000|BUY", "symbol": "XYZ", "company": "XYZ Limited", "person": "R K SHAH",
     "role": "promoter", "person_category": "Promoter Group", "category": "promoter", "category_label": "Promoter",
     "sub_label": null, "investor": null, "side": "BUY", "mode": "Market Purchase", "mode_kind": "market",
     "is_market": true, "qty": 50000, "value": 6250000.0, "avg_price": 125.0, "before_pct": 12.0, "after_pct": 12.5,
     "change_pts": 0.5, "before_shares": 1200000, "after_shares": 1250000, "trade_from": "2026-10-20",
     "trade_to": "2026-10-20", "disclosed": "2026-10-23", "delay_days": 3, "fully_exited": false,
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_2.xml"}
  ],
  "counts": {"buys": 1, "sells": 1, "buy_value": 6250000.0, "sell_value": 4100000.0, "pledge_invoked": 1, "full_exits": 1},
  "note": "Promoters, directors and key staff must report trades over ₹10 lakh a quarter: ..."
}
```

`GET /api/smart-money/holdings?view=exiting&days=30`

```json
{
  "freshness": {"...": "as above"}, "view": "exiting", "days": 30, "since": "2026-09-24",
  "latest_period": "2026-09-30", "previous_period": "2026-06-30", "coverage": 412,
  "stocks": [
    {"symbol": "XYZ", "company": "XYZ Limited", "direction": "mixed", "up_events": 6, "down_events": 6,
     "up_score": 9, "down_score": 9, "deal_buy_value": 247410000.0, "deal_sell_value": 247260000.0,
     "deal_net_value": 150000.0, "inst_buyers": 0, "inst_sellers": 1, "famous_buyers": ["Ashish Kacholia"],
     "famous_sellers": [], "insider_buy_value": 6250000.0, "insider_sell_value": 4100000.0,
     "promoter_buying": true, "promoter_selling": false, "pledge_invoked": false, "exits": 2,
     "fii_chg_pts": -1.5, "dii_chg_pts": 3.0, "mf_chg_pts": 2.0, "promoter_chg_pts": -2.0, "period": "2026-09-30",
     "last_date": "2026-10-23",
     "reasons": ["GOLDMAN SACHS (SINGAPORE) PTE sold 6,00,000 shares (₹24.7 cr, 6.00% of the company) in a bulk deal",
                 "Insider P DIRECTOR sold all their shares (10,000 shares, ₹41.0 lakh) - fully exited",
                 "OLD VALUE FUND LTD is no longer shown as a 1%+ holder (was 2.00%) - sold some or all (quarter to Sep 2026)",
                 "Promoter holding fell −2.00 pts to 50.00% (quarter to Sep 2026)"]}
  ],
  "events": [
    {"id": "insider_exit|XYZ|2026-10-21|P DIRECTOR", "date": "2026-10-21", "symbol": "XYZ", "company": "XYZ Limited",
     "event": "insider_exit", "direction": "down", "source": "insider", "who": "P DIRECTOR", "investor": null,
     "category": "other", "category_label": "Other", "sub_label": "Company insider (director/KMP)",
     "value": 4100000.0, "qty": 10000, "pct_before": 0.1, "pct_after": 0.0, "change_pts": -0.1, "pct_equity": null,
     "period": null, "prev_period": null, "exit_kind": "full_exit",
     "text": "Insider P DIRECTOR sold all their shares (10,000 shares, ₹41.0 lakh) - fully exited"}
  ],
  "note": "Shareholding is filed once a quarter, ... from the last 30 days."
}
```

`GET /api/smart-money/flows?days=30`

```json
{"freshness": {"...": "as above"}, "days": 30, "since": "2026-09-24", "first_date": "2026-10-01",
 "rows": [{"date": "2026-10-23", "fii_buy_cr": 11000.0, "fii_sell_cr": 12888.42, "fii_net_cr": -1888.42,
           "dii_buy_cr": 15234.56, "dii_sell_cr": 12876.1, "dii_net_cr": 2358.46}],
 "fii_net_cr_total": -1888.42, "dii_net_cr_total": 2358.46, "fii_streak": -1, "dii_streak": 1,
 "note": "Market-wide buying and selling in the cash market ..."}
```

`GET /api/smart-money/overview?days=30` - `{"freshness", "run": {"state": "idle", "running": false, "message":
null, "started_at": null, "finished_at": null, "errors": []}, "days": 30, "kpis": {"days": 30, "since":
"2026-09-24", "big_buy_value": 774992000.0, "big_sell_value": 247260000.0, "inst_net_value": 280322000.0,
"stocks_bought": 3, "stocks_sold": 0, "insider_buy_value": 6250000.0, "insider_sell_value": 4100000.0, "exits": 2,
"intraday_rows": 1, "fii_net_cr": -1888.42, "dii_net_cr": 2358.46, "flows_date": "2026-10-23"}, "top_bought":
[SmStock...], "top_sold": [SmStock...], "latest_deals_date": "2026-10-23", "latest_deals": [SmDeal...],
"latest_insider": [SmInsiderTrade...], "exits": [SmEvent...], "flows": [SmFlowDay...], "has_data": true,
"errors": [], "note": NOTE_MAIN}`.

`GET /api/smart-money/stock/XYZ` - `{"symbol": "XYZ", "company": "XYZ Limited", "freshness", "days": 365,
"has_data": true, "summary": SmStock, "deals": [SmDeal...], "insider": [SmInsiderTrade...], "holdings":
[{"period": "2026-09-30", "broadcast": "2026-10-15", "source": "xbrl", "total_shares": 10000000, "promoter_pct":
50.0, "public_pct": 50.0, "fii_pct": 12.0, "dii_pct": 15.0, "mf_pct": 10.0, "insurance_pct": 3.0, "banks_pct": 2.0,
"pension_pct": 0.0, "aif_pct": 0.0}, {"period": "2026-06-30", ...}], "holders_period": "2026-09-30",
"holders_prev_period": "2026-06-30", "holders": [{"holder": "ABC HOLDINGS PRIVATE LIMITED", "holder_key": "ABC
HOLDINGS PRIVATE LIMITED", "group": "promoter", "category": "promoter", "category_label": "Promoter", "sub_label":
null, "investor": null, "pct": 50.0, "prev_pct": 52.0, "change_pts": -2.0, "shares": 5000000, "status": "cut"},
{"holder": "OLD VALUE FUND LTD", ..., "pct": null, "prev_pct": 2.0, "change_pts": null, "shares": null, "status":
"dropped"}], "events": [SmEvent...], "note": NOTE_STOCK}`.

`GET /api/smart-money/status` - `{"run": SmRefreshRun, "freshness": SmFreshness, "sources": {"deals": {"status":
"ok", "message": "1,204 deal rows up to 23 Oct 2026", "rows_added": 38, "last_ok_at": "2026-10-23T19:03:40+05:30",
"latest_date": "2026-10-23"}, "insider": {...}, "flows": {...}, "holdings": {"status": "partial", ...}}, "errors":
["holdings: 88 files left for the next refresh"]}`.

`POST /api/smart-money/refresh` body `{"days": 365}` (optional) -> **202** `{"accepted": true, "run": {"state":
"running", "running": true, "message": "Starting...", "started_at": "2026-10-23T19:02:01+05:30", "finished_at":
null, "errors": []}}`; while one runs -> **409** `{"error": {"code": "SCAN_BUSY", ...}}`. The client sends the
usual `X-Quant-Desk: 1` header (client.ts does it for every non-GET).

---------------------------------------------------------------------------------------------------------------------

## 7. UI (builder C)

### 7.1 `web/ui/src/api/smartMoney.ts` (write the types and hooks exactly; extra helpers allowed)

Header comment: "Smart money API (docs/smart_money_spec.md): types mirroring web/api/models/smart_money.py, fetchers
and TanStack Query hooks. Data changes only when a refresh finishes (SmartMoney.tsx invalidates ['smart-money']
then); /status polls every 3 s only while a refresh runs."

```ts
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'
import { DASH, MINUS, num, ok } from '@/lib/format'

// ------------------------------------------------------------------ types (mirror web/api/models/smart_money.py)
export type SmCategory = 'fii' | 'mf' | 'insurance' | 'bank' | 'pension' | 'promoter' | 'famous' | 'broker' | 'other'
export type SmCategoryFilter = 'all' | 'big' | 'institutions' | SmCategory
export type SmDealKind = 'bulk' | 'block' | 'both'
export type SmDealSide = 'BUY' | 'SELL' | 'FLAT'
export type SmModeKind = 'market' | 'pledge' | 'pledge_invoked' | 'off_market' | 'esop' | 'gift' | 'inter_se' | 'preferential' | 'other'
export type SmEventType = 'deal_buy' | 'deal_sell' | 'insider_buy' | 'insider_sell' | 'insider_exit' | 'pledge_invoked'
  | 'new_holder' | 'holder_added' | 'holder_cut' | 'holder_dropped' | 'category_up' | 'category_down' | 'category_exit'
export type SmExitKind = 'full_exit' | 'below_1pct' | 'sold_part' | 'category_exit'
export type SmSourceKind = 'bulk' | 'block' | 'insider' | 'shareholding'
export type SmRunState = 'idle' | 'running' | 'done' | 'failed'
export type SmSourceState = 'ok' | 'partial' | 'failed' | 'skipped' | 'never'

export interface SmFreshness {
  deals: ISODate | null; insider: ISODate | null; flows: ISODate | null; holdings_period: ISODate | null
  refreshed_at: ISODateTime | null; stale: boolean
}
export interface SmRefreshRun {
  state: SmRunState; running: boolean; message: string | null; started_at: ISODateTime | null
  finished_at: ISODateTime | null; errors: string[]
}
export interface SmSource {
  status: SmSourceState; message: string | null; rows_added: number; last_ok_at: ISODateTime | null; latest_date: ISODate | null
}
export interface SmSources { deals: SmSource; insider: SmSource; flows: SmSource; holdings: SmSource }
export interface SmStatus { run: SmRefreshRun; freshness: SmFreshness; sources: SmSources; errors: string[] }

export interface SmDeal {
  id: string; date: ISODate; symbol: string; company: string | null; kind: SmDealKind; side: SmDealSide
  client: string; client_key: string; category: SmCategory; category_label: string; sub_label: string | null
  investor: string | null; round_trip: boolean; buy_qty: number; sell_qty: number; net_qty: number
  buy_value: number; sell_value: number; net_value: number; avg_price: number | null; pct_equity: number | null
  counterparties: string[]
}
export interface SmDealCounts { buys: number; sells: number; intraday: number; by_category: Record<string, number> }
export interface SmDealsResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; until: ISODate | null; intraday: boolean
  total: number; page: number; page_size: number; rows: SmDeal[]; counts: SmDealCounts; note: string
}

export interface SmInsiderTrade {
  id: string; symbol: string; company: string | null; person: string; role: 'promoter' | 'insider' | 'other'
  person_category: string | null; category: SmCategory; category_label: string; sub_label: string | null
  investor: string | null; side: 'BUY' | 'SELL' | null; mode: string | null; mode_kind: SmModeKind; is_market: boolean
  qty: number | null; value: number | null; avg_price: number | null; before_pct: number | null; after_pct: number | null
  change_pts: number | null; before_shares: number | null; after_shares: number | null; trade_from: ISODate | null
  trade_to: ISODate | null; disclosed: ISODate | null; delay_days: number | null; fully_exited: boolean; xbrl: string | null
}
export interface SmInsiderCounts { buys: number; sells: number; buy_value: number; sell_value: number; pledge_invoked: number; full_exits: number }
export interface SmInsiderResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; until: ISODate | null; total: number; page: number
  page_size: number; rows: SmInsiderTrade[]; counts: SmInsiderCounts; note: string
}

export interface SmEvent {
  id: string; date: ISODate; symbol: string; company: string | null; event: SmEventType; direction: 'up' | 'down'
  source: SmSourceKind; who: string | null; investor: string | null; category: SmCategory; category_label: string
  sub_label: string | null; value: number | null; qty: number | null; pct_before: number | null; pct_after: number | null
  change_pts: number | null; pct_equity: number | null; period: ISODate | null; prev_period: ISODate | null
  exit_kind: SmExitKind | null; text: string
}
export interface SmStock {
  symbol: string; company: string | null; direction: 'up' | 'down' | 'mixed'; up_events: number; down_events: number
  up_score: number; down_score: number; deal_buy_value: number; deal_sell_value: number; deal_net_value: number
  inst_buyers: number; inst_sellers: number; famous_buyers: string[]; famous_sellers: string[]
  insider_buy_value: number; insider_sell_value: number; promoter_buying: boolean; promoter_selling: boolean
  pledge_invoked: boolean; exits: number; fii_chg_pts: number | null; dii_chg_pts: number | null
  mf_chg_pts: number | null; promoter_chg_pts: number | null; period: ISODate | null; last_date: ISODate; reasons: string[]
}
export interface SmHoldingsResponse {
  freshness: SmFreshness; view: 'accumulating' | 'exiting' | 'all'; days: number; since: ISODate | null
  latest_period: ISODate | null; previous_period: ISODate | null; coverage: number; stocks: SmStock[]
  events: SmEvent[]; note: string
}
export interface SmFlowDay {
  date: ISODate; fii_buy_cr: number | null; fii_sell_cr: number | null; fii_net_cr: number | null
  dii_buy_cr: number | null; dii_sell_cr: number | null; dii_net_cr: number | null
}
export interface SmFlowsResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; first_date: ISODate | null; rows: SmFlowDay[]
  fii_net_cr_total: number | null; dii_net_cr_total: number | null; fii_streak: number; dii_streak: number; note: string
}
export interface SmKpis {
  days: number; since: ISODate | null; big_buy_value: number; big_sell_value: number; inst_net_value: number
  stocks_bought: number; stocks_sold: number; insider_buy_value: number; insider_sell_value: number; exits: number
  intraday_rows: number; fii_net_cr: number | null; dii_net_cr: number | null; flows_date: ISODate | null
}
export interface SmOverview {
  freshness: SmFreshness; run: SmRefreshRun; days: number; kpis: SmKpis; top_bought: SmStock[]; top_sold: SmStock[]
  latest_deals_date: ISODate | null; latest_deals: SmDeal[]; latest_insider: SmInsiderTrade[]; exits: SmEvent[]
  flows: SmFlowDay[]; has_data: boolean; errors: string[]; note: string
}
export interface SmHoldingPeriod {
  period: ISODate; broadcast: ISODate | null; source: 'xbrl' | 'master'; total_shares: number | null
  promoter_pct: number | null; public_pct: number | null; fii_pct: number | null; dii_pct: number | null
  mf_pct: number | null; insurance_pct: number | null; banks_pct: number | null; pension_pct: number | null; aif_pct: number | null
}
export interface SmHolder {
  holder: string; holder_key: string; group: 'promoter' | 'public'; category: SmCategory; category_label: string
  sub_label: string | null; investor: string | null; pct: number | null; prev_pct: number | null
  change_pts: number | null; shares: number | null; status: 'new' | 'added' | 'cut' | 'same' | 'dropped'
}
export interface SmStockResponse {
  symbol: string; company: string | null; freshness: SmFreshness; days: number; has_data: boolean
  summary: SmStock | null; deals: SmDeal[]; insider: SmInsiderTrade[]; holdings: SmHoldingPeriod[]
  holders_period: ISODate | null; holders_prev_period: ISODate | null; holders: SmHolder[]; events: SmEvent[]; note: string
}
export interface SmRefreshAccepted { accepted: boolean; run: SmRefreshRun }

// ------------------------------------------------------------------ params
export interface SmDealsParams {
  days: number; side?: 'all' | 'buy' | 'sell'; kind?: 'all' | 'bulk' | 'block'; category?: SmCategoryFilter
  symbol?: string; intraday?: boolean; page?: number; page_size?: number
}
export interface SmInsiderParams {
  days: number; side?: 'all' | 'buy' | 'sell'; category?: 'all' | 'promoter' | 'insider'; mode?: 'market' | 'all'
  symbol?: string; page?: number; page_size?: number
}
export interface SmHoldingsParams { view: 'accumulating' | 'exiting' | 'all'; days?: number; category?: SmCategoryFilter; symbol?: string }

// ------------------------------------------------------------------ fetchers (client.ts's qs() is private: own copy)
function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const BASE = '/api/smart-money'
export const smApi = {
  status: () => fetchJson<SmStatus>(`${BASE}/status`),
  overview: (days = 30) => fetchJson<SmOverview>(`${BASE}/overview${qs({ days })}`),
  deals: (p: SmDealsParams) => fetchJson<SmDealsResponse>(`${BASE}/deals${qs({ ...p })}`),
  insider: (p: SmInsiderParams) => fetchJson<SmInsiderResponse>(`${BASE}/insider${qs({ ...p })}`),
  holdings: (p: SmHoldingsParams) => fetchJson<SmHoldingsResponse>(`${BASE}/holdings${qs({ ...p })}`),
  flows: (days = 30) => fetchJson<SmFlowsResponse>(`${BASE}/flows${qs({ days })}`),
  stock: (symbol: string, days = 365) => fetchJson<SmStockResponse>(`${BASE}/stock/${encodeURIComponent(symbol)}${qs({ days })}`),
  refresh: (days = 365) => fetchJson<SmRefreshAccepted>(`${BASE}/refresh`, { method: 'POST', body: JSON.stringify({ days }) }),
}

// ------------------------------------------------------------------ hooks
export const smKeys = {
  all: ['smart-money'] as const,
  status: ['smart-money', 'status'] as const,
  overview: (days: number) => ['smart-money', 'overview', days] as const,
  deals: (p: SmDealsParams) => ['smart-money', 'deals', p] as const,
  insider: (p: SmInsiderParams) => ['smart-money', 'insider', p] as const,
  holdings: (p: SmHoldingsParams) => ['smart-money', 'holdings', p] as const,
  flows: (days: number) => ['smart-money', 'flows', days] as const,
  stock: (symbol: string, days: number) => ['smart-money', 'stock', symbol, days] as const,
}

const keep = { staleTime: 5 * 60_000, placeholderData: keepPreviousData } as const

export const useSmStatus = () =>
  useQuery({ queryKey: smKeys.status, queryFn: smApi.status, staleTime: 2000, refetchInterval: (q) => (q.state.data?.run.running ? 3000 : false) })
export const useSmOverview = (days: number) => useQuery({ queryKey: smKeys.overview(days), queryFn: () => smApi.overview(days), ...keep })
export const useSmDeals = (p: SmDealsParams, enabled = true) => useQuery({ queryKey: smKeys.deals(p), queryFn: () => smApi.deals(p), ...keep, enabled })
export const useSmInsider = (p: SmInsiderParams) => useQuery({ queryKey: smKeys.insider(p), queryFn: () => smApi.insider(p), ...keep })
export const useSmHoldings = (p: SmHoldingsParams) => useQuery({ queryKey: smKeys.holdings(p), queryFn: () => smApi.holdings(p), ...keep })
export const useSmFlows = (days: number) => useQuery({ queryKey: smKeys.flows(days), queryFn: () => smApi.flows(days), ...keep })
/** No keepPreviousData: switching symbols on the chart must never show the previous stock's investors. */
export const useSmStock = (symbol: string, days = 365) =>
  useQuery({ queryKey: smKeys.stock(symbol, days), queryFn: () => smApi.stock(symbol, days), staleTime: 5 * 60_000, enabled: !!symbol })

export function useSmRefresh() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (days: number) => smApi.refresh(days),
    onSuccess: (r) => {
      qc.setQueryData<SmStatus>(smKeys.status, (s) => (s ? { ...s, run: r.run } : s))
      void qc.invalidateQueries({ queryKey: smKeys.status })
    },
  })
}

// ------------------------------------------------------------------ labels and formatting
export const CATEGORY_LABEL: Record<SmCategory, string> = {
  fii: 'FII/FPI', mf: 'Mutual fund', insurance: 'Insurance', bank: 'Bank/NBFC', pension: 'Pension/sovereign',
  promoter: 'Promoter', famous: 'Well-known investor', broker: 'Broker/prop', other: 'Other',
}
export const CATEGORY_FILTERS: { id: SmCategoryFilter; label: string }[] = [
  { id: 'all', label: 'Everyone' }, { id: 'big', label: 'Big money (institutions, promoters, well-known)' },
  { id: 'institutions', label: 'Institutions only' }, { id: 'fii', label: 'FII/FPI' }, { id: 'mf', label: 'Mutual funds' },
  { id: 'insurance', label: 'Insurance' }, { id: 'bank', label: 'Banks/NBFCs' }, { id: 'pension', label: 'Pension/sovereign' },
  { id: 'promoter', label: 'Promoters' }, { id: 'famous', label: 'Well-known investors' }, { id: 'broker', label: 'Brokers/prop' },
  { id: 'other', label: 'Others' },
]
/** Deal sizes: ₹32.26 cr / ₹62.5 L / ₹9,500 (signed adds '+'). */
export function fmtInr(v: number | null | undefined, signed = false): string {
  if (!ok(v)) return DASH
  const a = Math.abs(v)
  const s = v < 0 ? MINUS : signed && v > 0 ? '+' : ''
  if (a >= 1e7) return `${s}₹${num(a / 1e7, 2)} cr`
  if (a >= 1e5) return `${s}₹${num(a / 1e5, 1)} L`
  return `${s}₹${num(a, 0)}`
}
/** FII/DII figures, already in crore: +₹2,358 cr / −₹1,888 cr. */
export function fmtCr(v: number | null | undefined, signed = true): string {
  if (!ok(v)) return DASH
  const s = v < 0 ? MINUS : signed && v > 0 ? '+' : ''
  return `${s}₹${num(Math.abs(v), 0)} cr`
}
```

### 7.2 `web/ui/src/components/SmartMoneyPanel.tsx`

Exports (named): `CategoryBadge`, `ExitChip`, `SmartMoneyPanel`.

```ts
export function CategoryBadge({ category, subLabel, className }: { category: SmCategory; subLabel?: string | null; className?: string })
export function ExitChip({ kind }: { kind: SmExitKind | null })
export function SmartMoneyPanel({ symbol, days = 365 }: { symbol: string; days?: number })
```

- `CategoryBadge`: a pill (same shape as `badges.tsx`'s `pill`: `inline-flex h-5 shrink-0 items-center gap-1
  whitespace-nowrap rounded-full px-2 text-2xs font-medium leading-none`) showing `CATEGORY_LABEL[category]`;
  when category is `other` and `subLabel` is set, show `subLabel` instead (e.g. "Company insider
  (director/KMP)", "Individual"); title = full label + sub-label. Tone classes via `TONE_TINT`/`TONE_TEXT` from
  `@/lib/vocab`: fii/mf/insurance/bank/pension -> `info`; promoter -> `warn`; famous -> `accent`; broker ->
  `faint`; other -> `muted`. When `subLabel` is the ODI label, add a small `AlertTriangle` icon (weak signal).
- `ExitChip`: `full_exit` -> "Fully exited" (loss tone, title "Holding after the sale is zero: a certain full
  exit"); `below_1pct` -> "Now below 1%" (warn, title "No longer in the list of 1%+ holders: sold some or all -
  the filing cannot tell which"); `sold_part` -> "Sold part" (muted); `category_exit` -> "Category sold out"
  (loss); `null` -> nothing.
- `SmartMoneyPanel` (for the Chart side panel; renders inside a padded section, so its root is
  `<div className="space-y-3">`):
  1. Header row: `<div className="eyebrow">Big investors</div>` + `Help` (from `@/components/domain`) with text
     `"NSE bulk/block deals, insider filings and the quarterly shareholding pattern. Disclosed data - not live and
     not a buy/sell signal."` + right-aligned `MoreLink` to `/smart-money/today?symbol=${encodeURIComponent(symbol)}`
     labelled "Details".
  2. Loading: three `Skeleton` lines. Error: `ErrorState compact`. `has_data` false: `text-xs text-muted` line
     `"No bulk/block deals, insider trades or shareholding data for {symbol} yet."` (plus "Refresh on the Smart
     money page" when `freshness.refreshed_at` is null).
  3. Shareholding (when `holdings.length`): small grid "Promoter / FII/FPI / DII / Mutual funds" with the latest
     pct (`num(x, 2)%`) and the change vs the previous period (`Pts` from `@/components/num` with suffix `" pts"`),
     caption `"Quarter to {monthYear(period)} vs {monthYear(prev)}"` (use `holdings[0]` and `holdings[1]`;
     the change = `holdings[0].x - holdings[1].x` when both present, else `—`).
  4. "Recent big deals": up to 5 `deals` with `round_trip === false`: `date(d, {year: false})`, a BUY/SELL pill
     (`SidePill` from badges for BUY/SELL), who (`investor ?? client`, truncate, title = client), `fmtInr(abs
     net_value)`. Under it, if any round trips: `text-2xs text-faint` "N intraday trades by trading firms not
     shown".
  5. "Insider trades": up to 5 rows with `is_market || mode_kind === 'pledge_invoked'`: date, side, person,
     `fmtInr(value)`, `ExitChip` when `fully_exited` ("full_exit"), a `WarnChip` "Pledge sold" for
     pledge_invoked.
  6. "Exits / selling": up to 3 events with `direction === 'down' && exit_kind !== null`: `text` + `ExitChip`.
  7. Footer `text-2xs text-faint`: `"Disclosed data, often days or weeks old. Big investors also lose money."`

### 7.3 `web/ui/src/pages/SmartMoney.tsx` (default export `SmartMoney`)

Header comment: "Smart money `/smart-money/:tab`: which stocks big investors are buying, selling or leaving, from
NSE's bulk/block deals, insider (PIT) filings, quarterly shareholding and FII/DII flows. Disclosed data, shown with
its delays; never a signal."

Routing: tab from `useParams()` (`today | insider | accumulating | exited | flows`, unknown -> `today`); symbol
filter from `useSearchParams()` key `symbol` (upper-cased). Tab links keep the symbol: `to:
`/smart-money/${id}${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}``.

Layout, top to bottom:

1. `PageHeader` title `"Smart money"`, subtitle `"Which stocks big investors are buying, selling or leaving - from
   what they must disclose to NSE"`, `right` = `<FreshnessLine />` + `<RefreshControl />`.
2. `<HonestNote />`: an info box (`rounded-lg border border-info/25 bg-info/[0.06] px-4 py-3 text-[13px]`, as in
   Market's Factors note) titled **"Read this first"** with the server's `overview.note` (falls back to the
   constant `HONEST_NOTE` below while loading) and a "How this works" list (`RULES`). Collapsible: open state in
   `useLocalStorage('qd.smartmoney.note', true)`; collapsed shows one line "Disclosed data, not live, not a tip.
   Show more".
3. `<KpiStrip>` from `useSmOverview(30)` (skeleton `SkeletonKpis`): tiles (label / value / sub):
   "Big-money buys (30 d)" `fmtInr(big_buy_value)` / `"{stocks_bought} stocks"`; "Big-money sells (30 d)"
   `fmtInr(big_sell_value)` / `"{stocks_sold} stocks"`; "Institutions net" `fmtInr(inst_net_value, true)` coloured
   with `toneClass`; "Promoter/insider buys" `fmtInr(insider_buy_value)` / `"sells " + fmtInr(insider_sell_value)`;
   "Exits seen" `exits`; "FII net (latest)" `fmtCr(fii_net_cr)` / `date(flows_date)`; "DII net (latest)"
   `fmtCr(dii_net_cr)`.
4. Tabs (`Tabs` from ui, inside `<div className="mb-3 border-b border-line">`): `today` "Today's big trades",
   `insider` "Insider & promoter trades", `accumulating` "Accumulating", `exited` "Exited / selling", `flows`
   "FII/DII flows".
5. Symbol filter row: a small text input (`input h-8 w-[160px] text-xs`, placeholder "Filter by symbol", Enter
   applies, upper-cases) and, when set, a `Chip` `"Symbol: XYZ"` with an `X` button clearing it. Applies to every
   tab except flows.
6. Tab body.

First run: when `useSmStatus().data?.freshness.refreshed_at == null` and not running, replace 3-6 with a card
`EmptyState` title "No smart-money data yet", body "Downloads about a year of NSE bulk/block deals and insider
filings, today's FII/DII figures and the latest shareholding of your stock list. The first time takes 3-6 minutes;
it runs in the background.", action = the refresh button.

Shared components inside the page (not exported):

- `RefreshControl`: like `Intraday.tsx`'s `RerunControl`. Uses `useSmStatus()` and `useSmRefresh()`. Running ->
  `Spinner` + `run.message` (truncate, max 320 px). `useRef` remembers `running`; on the transition running ->
  not running: `qc.invalidateQueries({ queryKey: smKeys.all })` and a toast: state failed -> `{ tone: 'bad',
  title: 'Smart-money refresh failed', detail: run.message }`; errors non-empty -> `{ tone: 'info', title:
  'Smart-money data refreshed with some gaps', detail: run.errors[0] }`; else `{ tone: 'good', title:
  'Smart-money data refreshed' }`. Button: `size="sm"`, icon `RefreshCw`, label "Refresh data", `loading` while
  the mutation is pending, `disabled` while running, title "Download the latest NSE deals, insider filings,
  FII/DII figures and shareholding in the background (1-6 minutes)". Mutation errors -> toast bad with
  `e.message` / `e.hint` (use `isFailure` from client).
- `FreshnessLine({ f })`: `text-xs text-muted`: `Deals {date(f.deals, {year:false})} · Insider {date(f.insider,
  {year:false})} · Shareholding {monthYear(f.holdings_period)} · refreshed {relative(f.refreshed_at)}`, plus
  `WarnChip` "Stale" (title "The newest deals are more than 5 days old - refresh") when `f.stale`.
- `CategoryPicker({ value, onChange })`: `Popover` + `SelectButton` (label "Who", value = the filter's label) +
  `MenuItem`s from `CATEGORY_FILTERS` (active item highlighted).
- `Pager({ page, pageSize, total, onPage })`: `"{from}–{to} of {total}"` + previous/next `IconButton`s
  (`ChevronLeft`/`ChevronRight`), hidden when `total <= pageSize`.
- `WhoCell({ name, investor, subLabel })`: first line `investor ?? name` (font-medium, truncate, max-w 260 px,
  title = name); when `investor` is set a second line with the filed name (`text-2xs text-muted truncate`).
- `DealSide({ side })`: `SidePill` for BUY/SELL; FLAT -> a muted pill "FLAT".

**Tab `today` (`DealsTab`)** - state: `days` (Segmented: `1` "Latest day", `7` "1 W", `30` "1 M", `90` "3 M";
default 1), `side` (Segmented All/Buys/Sells), `kind` (Segmented All/Bulk/Block), `category` (CategoryPicker,
default `'big'`), `page` (reset to 1 whenever a filter changes). Query `useSmDeals({ days, side, kind, category,
symbol: symbol || undefined, page, page_size: 100 })`. Card title `days === 1 ? "Big trades on {date(until)}" :
"Big trades {date(since)} – {date(until)}"`, subtitle = `note`, `right` = counts text
`"{buys} buys · {sells} sells"`. Table `DataTable id="sm.deals"` with `onRowClick={(r) => nav(`/chart/${r.symbol}`)}`,
`exportName="smart-money-deals"`, `filterable`, columns:

```ts
const dealCols: Col<SmDeal>[] = [
  { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })}</span>, width: 72 },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.client} ${r.investor ?? ''}` },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => <DealSide side={r.side} />, width: 64, mobile: 'secondary' },
  { id: 'who', header: 'Who', value: (r) => r.investor ?? r.client, cell: (r) => <WhoCell name={r.client} investor={r.investor} subLabel={r.sub_label} />, minWidth: 220 },
  { id: 'cat', header: 'Type', value: (r) => r.category_label, cell: (r) => <CategoryBadge category={r.category} subLabel={r.sub_label} />, mobile: 'secondary', label: 'Type' },
  { id: 'kind', header: 'Deal', value: (r) => r.kind, cell: (r) => <span className="text-muted">{r.kind === 'both' ? 'Bulk + block' : r.kind === 'block' ? 'Block' : 'Bulk'}</span>, hideBelow: 1100 },
  { id: 'qty', header: 'Shares', align: 'right', value: (r) => (r.round_trip ? r.buy_qty : Math.abs(r.net_qty)), cell: (r) => <span className="num">{qty(r.round_trip ? r.buy_qty : Math.abs(r.net_qty))}</span> },
  { id: 'price', header: 'Avg ₹', align: 'right', value: (r) => r.avg_price, cell: (r) => <Price v={r.avg_price} /> },
  { id: 'value', header: 'Value', align: 'right', value: (r) => (r.round_trip ? r.buy_value : Math.abs(r.net_value)), cell: (r) => <span className="num">{fmtInr(r.round_trip ? r.buy_value : Math.abs(r.net_value))}</span>, mobile: 'value' },
  { id: 'pct', header: '% of co.', title: "Shares traded as a % of all the company's shares", align: 'right', value: (r) => r.pct_equity, cell: (r) => <span className="num">{r.pct_equity == null ? '—' : `${num(r.pct_equity, 2)}%`}</span>, mobile: 'change' },
  { id: 'other', header: 'Other side', title: 'Block deals: who was on the other side the same day', value: (r) => r.counterparties.join(', '), cell: (r) => <span className="block max-w-[220px] truncate text-muted" title={r.counterparties.join(', ')}>{r.counterparties.join(', ') || '—'}</span>, hideBelow: 1240 },
]
```
Below the table: `Pager`. Then a collapsed section button `"Intraday / arbitrage trades ({counts.intraday})"`
with `ChevronDown` (rotates when open); when open, `useSmDeals({ ...same filters but category 'all', intraday:
true, page: 1, page_size: 200 }, open)` in a second `DataTable id="sm.deals.intraday"` with the same columns,
preceded by `text-xs text-muted` "Trading firms that bought and sold about the same number of shares the same day.
They keep no stake, so they are left out of the buyer and seller lists." Empty main table:
`EmptyState compact title="No big trades in this window"` with body "Try a longer window or 'Everyone'.".

**Tab `insider` (`InsiderTab`)** - state: `days` (Segmented `7` "1 W", `30` "1 M" default, `90` "3 M", `365`
"1 Y"), `side`, `who` (Segmented `all` "Everyone", `promoter` "Promoters", `insider` "Directors & staff"),
`marketOnly` (`Switch`, default true, label "Market trades only", title "Shows open-market buys and sells and
forced pledge sales; hides ESOPs, gifts, transfers and new pledges"), `page`. Query `useSmInsider({ days, side,
category: who, mode: marketOnly ? 'market' : 'all', symbol, page, page_size: 100 })`. Card subtitle = `note`;
`right` = `"{buys} buys ({fmtInr(buy_value)}) · {sells} sells ({fmtInr(sell_value)})"`, plus WarnChip
`"{pledge_invoked} pledge sales"` when > 0. Columns:

```ts
const insiderCols: Col<SmInsiderTrade>[] = [
  { id: 'disc', header: 'Disclosed', value: (r) => r.disclosed, cell: (r) => <span className="num text-muted">{date(r.disclosed, { year: false })}</span>, width: 84 },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.person}` },
  { id: 'person', header: 'Person', value: (r) => r.person, cell: (r) => (<div className="flex min-w-0 flex-col leading-tight"><span className="max-w-[220px] truncate font-medium" title={r.person}>{r.investor ?? r.person}</span><span className="text-2xs text-muted">{r.person_category ?? '—'}</span></div>), minWidth: 200 },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => (r.side ? <SidePill side={r.side} /> : <span className="text-faint">—</span>), width: 64, mobile: 'secondary' },
  { id: 'how', header: 'How', value: (r) => r.mode, cell: (r) => (<span className="flex items-center gap-1"><span className={r.is_market ? 'text-fg' : 'text-muted'}>{r.mode ?? '—'}</span>{r.fully_exited && <ExitChip kind="full_exit" />}{r.mode_kind === 'pledge_invoked' && <WarnChip title="A lender sold pledged shares: a forced sale">Pledge sold</WarnChip>}</span>) },
  { id: 'qty', header: 'Shares', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{qty(r.qty)}</span> },
  { id: 'value', header: 'Value', align: 'right', value: (r) => r.value, cell: (r) => <span className="num">{fmtInr(r.value)}</span>, mobile: 'value' },
  { id: 'price', header: 'Avg ₹', align: 'right', value: (r) => r.avg_price, cell: (r) => <Price v={r.avg_price} />, hideBelow: 1100 },
  { id: 'stake', header: 'Stake', title: 'Their holding before → after, % of the company', align: 'right', value: (r) => r.after_pct, cell: (r) => <span className="num">{r.before_pct == null && r.after_pct == null ? '—' : `${num(r.before_pct, 2)}% → ${num(r.after_pct, 2)}%`}</span>, mobile: 'change' },
  { id: 'trade', header: 'Traded', value: (r) => r.trade_from, cell: (r) => <span className="num text-muted">{r.trade_from === r.trade_to || !r.trade_to ? date(r.trade_from, { year: false }) : `${date(r.trade_from, { year: false })} – ${date(r.trade_to, { year: false })}`}</span>, hideBelow: 1180 },
  { id: 'delay', header: 'Delay', title: 'Days from the trade to the filing reaching NSE', align: 'right', value: (r) => r.delay_days, cell: (r) => <span className="num text-muted">{r.delay_days == null ? '—' : `${r.delay_days} d`}</span>, hideBelow: 1240 },
]
```
Empty: `EmptyState compact title="No insider trades in this window"`.

**Tabs `accumulating` / `exited` (`HoldingsTab({ view })`)** - `view = tab === 'exited' ? 'exiting' :
'accumulating'`. State: `days` (Segmented `30` "1 M" default, `90` "3 M"), `category` (CategoryPicker, default
`'big'`). Query `useSmHoldings({ view, days, category, symbol })`. Two cards:

1. Stocks card - title `view === 'accumulating' ? 'Stocks big investors are adding' : 'Stocks big investors are
   selling or leaving'`, subtitle = `note` + (latest_period ? ` Shareholding: quarter to {monthYear(latest_period)}
   vs {monthYear(previous_period)}, {coverage} stocks.` : ' Shareholding not downloaded yet.').

```ts
const stockCols: Col<SmStock>[] = [
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary' },
  { id: 'why', header: 'Why', value: (r) => r.reasons[0] ?? '', sortable: false, cell: (r) => (<Tip text={<ul className="space-y-1">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}><span className="block max-w-[420px] truncate">{r.reasons[0] ?? '—'}{r.reasons.length > 1 && <span className="text-faint"> +{r.reasons.length - 1} more</span>}</span></Tip>), minWidth: 300 },
  { id: 'deals', header: 'Big-money deals', title: 'Bulk/block buying minus selling by institutions, promoters and well-known investors (no intraday)', align: 'right', value: (r) => r.deal_net_value, cell: (r) => <span className={cn('num', toneClass(r.deal_net_value))}>{r.deal_net_value === 0 ? '—' : fmtInr(r.deal_net_value, true)}</span>, mobile: 'value' },
  { id: 'inst', header: 'Institutions', title: 'Distinct institutions buying / selling via bulk or block deals', align: 'right', value: (r) => r.inst_buyers - r.inst_sellers, cell: (r) => <span className="num"><span className="text-profit">{r.inst_buyers}</span><span className="text-faint"> / </span><span className="text-loss">{r.inst_sellers}</span></span> },
  { id: 'famous', header: 'Well-known', value: (r) => [...r.famous_buyers, ...r.famous_sellers].join(', '), cell: (r) => <span className="block max-w-[200px] truncate" title={[...r.famous_buyers.map((x) => `${x} bought`), ...r.famous_sellers.map((x) => `${x} sold`)].join(', ')}>{[...r.famous_buyers, ...r.famous_sellers].join(', ') || '—'}</span>, hideBelow: 1100 },
  { id: 'insider', header: 'Promoter / insider', align: 'right', value: (r) => r.insider_buy_value - r.insider_sell_value, cell: (r) => <span className={cn('num', toneClass(r.insider_buy_value - r.insider_sell_value))}>{r.insider_buy_value || r.insider_sell_value ? fmtInr(r.insider_buy_value - r.insider_sell_value, true) : '—'}</span> },
  { id: 'fii', header: 'FII Δ', title: 'Change in FII/FPI holding, latest quarter vs the one before (percentage points)', align: 'right', value: (r) => r.fii_chg_pts, cell: (r) => <Pts v={r.fii_chg_pts} /> },
  { id: 'mf', header: 'MF Δ', align: 'right', value: (r) => r.mf_chg_pts, cell: (r) => <Pts v={r.mf_chg_pts} />, mobile: 'change' },
  { id: 'prom', header: 'Promoter Δ', align: 'right', value: (r) => r.promoter_chg_pts, cell: (r) => <Pts v={r.promoter_chg_pts} />, hideBelow: 1180 },
  { id: 'exits', header: 'Exits', align: 'right', value: (r) => r.exits, cell: (r) => <span className="num">{r.exits || '—'}</span>, defaultHidden: view === 'accumulating' },
  { id: 'last', header: 'Latest', value: (r) => r.last_date, cell: (r) => <span className="num text-muted">{date(r.last_date, { year: false })}</span>, hideBelow: 1240 },
]
```
   `DataTable id={`sm.${view}`}`, row click -> `/chart/SYMBOL`, `exportName`, `filterable`, `pageSize={50}`.
   (`cols` built inside the component because of `view`; wrap in `useMemo([view])`.)

2. Events card - title `view === 'accumulating' ? 'What they did (buying)' : 'What they did (selling and exits)'`.

```ts
const SOURCE_LABEL: Record<SmSourceKind, string> = { bulk: 'Bulk deal', block: 'Block deal', insider: 'Insider filing', shareholding: 'Shareholding' }
const eventCols: Col<SmEvent>[] = [
  { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })}</span>, width: 72 },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 140, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.who ?? ''} ${r.investor ?? ''}` },
  { id: 'what', header: 'What happened', value: (r) => r.text, sortable: false, cell: (r) => <span className="block min-w-[280px] max-w-[560px] whitespace-normal py-1 leading-snug">{r.text}</span>, minWidth: 320, mobile: 'secondary', label: 'What' },
  { id: 'cat', header: 'Type', value: (r) => r.category_label, cell: (r) => <CategoryBadge category={r.category} subLabel={r.sub_label} /> },
  { id: 'exit', header: 'Exit?', value: (r) => r.exit_kind, cell: (r) => <ExitChip kind={r.exit_kind} />, defaultHidden: view === 'accumulating' },
  { id: 'src', header: 'Source', value: (r) => r.source, cell: (r) => <span className="text-muted">{SOURCE_LABEL[r.source]}</span>, hideBelow: 1100 },
]
```
   (`whitespace-normal` goes on the inner span: `cn` does not merge Tailwind classes and the cell is
   `whitespace-nowrap`.) `pageSize={50}`, row click -> chart. Empty: `EmptyState compact` with title
   `"Nothing in this window"` and body `"Shareholding changes appear after companies file (within 21 days of the
   quarter end); deals and insider trades after each refresh."`.

**Tab `flows` (`FlowsTab`)** - Segmented `30` "1 M" default, `90` "3 M", `365` "1 Y". Query `useSmFlows(days)`.
KpiStrip: "FII/FPI net (latest)" `fmtCr(rows[0].fii_net_cr)` coloured, sub `date(rows[0].date)`; "DII net
(latest)"; "FII streak" `streakText(fii_streak)` (`3` -> "3 days buying", `-2` -> "2 days selling", `0` -> "—");
"DII streak"; "FII net ({days} d)" `fmtCr(fii_net_cr_total)`; "DII net ({days} d)". Then two cards side by side
(`grid gap-3 lg:grid-cols-2`) "FII/FPI net, ₹ crore" and "DII net, ₹ crore", each a local `FlowBars` component
(do **not** use `SignedBars`: it prints percent) - one row per day (newest first, max 30): date label, a centred
bar scaled to the largest absolute value (green right for buying, red left for selling, like SignedBars' markup),
`fmtCr(v)` on the right. Then a `DataTable id="sm.flows"` with columns Date, FII buy, FII sell, FII net (coloured),
DII buy, DII sell, DII net (coloured) using `fmtCr(v, false)` for buy/sell. Card subtitle = `note` + `first_date ?
" History since " + date(first_date) + "." : ""`. Empty: `EmptyState compact title="No FII/DII figures yet"`.

Every query: `error` -> `<div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>`;
no data yet -> `<div className="card"><SkeletonRows /></div>` (exactly as Market.tsx).

UI constants in the page (exact text):

```ts
const HONEST_NOTE = 'What you see here are deals and holdings that big investors must report by law. It is not live, and it is not a tip. Bulk and block deals show up after the market closes. Insider trades can be reported up to about 4 trading days late, and shareholding only once a quarter, up to 3 weeks late. Many "bulk deals" are trading firms that buy and sell the same day: we mark those as "intraday" and leave them out of the buyer and seller lists. Studies on Indian stocks find most of the price move around bulk deals happens before or on the deal day. Promoter buying in small companies has been followed by gains on average, but averages hide many losers, and those stocks can be hard to trade. A famous name buying does not mean the price will rise. Big investors also lose money, and they can sell without anyone knowing until the next filing. A stock dropping off the shareholding list only means they now hold less than 1%, not always a full exit. Use this as one clue next to your own analysis, never as a buy or sell signal. This is not investment advice.'
const RULES = [
  'Bulk deal: one client trades more than 0.5% of a company\'s shares in a day. Published after the close.',
  'Block deal: a single trade of at least ₹25 crore in NSE\'s 8:45–9:00 or 2:05–2:20 window, within 3% of the reference price.',
  'Insider trade: promoters, directors and key staff report trades over ₹10 lakh a quarter, within about 4 trading days.',
  'Shareholding: every company files it within 21 days of each quarter end; only holders with 1% or more are named.',
  'FII/DII: market-wide cash-market figures for the day, provisional, in ₹ crore.',
  'Names are matched to types (mutual fund, FII, promoter, …) by rules; a name that looks like a famous investor can be someone else - the filed name is always shown.',
]
```

Imports the page will need (keep only what you use): `useMemo, useEffect, useRef, useState` from react;
`useNavigate, useParams, useSearchParams` from react-router-dom; `useQueryClient`; lucide `ChevronDown,
ChevronLeft, ChevronRight, RefreshCw, X`; `isFailure` from `@/api/client`; everything from `@/api/smartMoney`;
`SidePill, WarnChip` from badges; `DataTable, SymbolCell, type Col`; `KpiStrip, KpiTile, PageHeader` from domain;
`EmptyState, ErrorState, SkeletonKpis, SkeletonRows` from feedback; `Price, Pts` from num; `useToast`; `Button,
Card, Chip, IconButton, MenuItem, Popover, Segmented, SelectButton, Spinner, Switch, Tabs, Tip` from ui; `cn` from
`@/lib/csv`; `date, monthYear, num, qty, relative, toneClass` from format; `useLocalStorage`; `CategoryBadge,
ExitChip` from `@/components/SmartMoneyPanel`.

---------------------------------------------------------------------------------------------------------------------

## 8. Acceptance checklist per builder

**A:** module imports only the listed modules; no network at import; all paths via `files()`; every network call
through `_fetch`; refresh never raises on network/data errors; loaders return exact columns when files are
missing; parsers handle BOM, comma quantities, mixed-case dates, header-only files, `-`/`Nil`, both
`afterAcq`/`aftAcq` spellings; no default BUY; tests 1-15 present and offline.

**B:** routes exactly as 6.2 under `/api/smart-money`; response models exactly as 6.1; GET handlers never call
`sm.refresh`; caches keyed by file identity; refresh thread + lock + 409 SCAN_BUSY; NaN never reaches JSON
(`num`/`inum`/`_s`); notes verbatim.

**C:** `smartMoney.ts` types match 6.1 field-for-field; no `any`; all type imports with `import type`; page and
panel handle loading, error, empty and first-run states; the honest note is visible on every tab; every symbol
links to `/chart/SYMBOL`; filed names are always visible next to labels; no new packages.

---------------------------------------------------------------------------------------------------------------------

## 9. Later wiring (for the record - NOT done by the builders)

1. `web/api/main.py`: `from .routers import ..., smart_money` and add `smart_money` to the `include_router` loop.
   Optionally add a warm-up step `smart_money_svc._base` (cheap when no files).
2. `web/api/models/__init__.py`: `from .smart_money import *  # noqa: F401,F403` (names are `Sm*`-prefixed, no
   clashes).
3. `web/api/paths.py`: optional `P.smart_money` property (`self.data / "smart_money"`); the service already uses
   `P.data / "smart_money"`, so `configure()` needs no change.
4. `web/ui/src/app/router.tsx`: `const SmartMoney = lazy(() => import('@/pages/SmartMoney'))`; routes
   `{ path: 'smart-money', element: <Navigate to="/smart-money/today" replace /> }` and
   `{ path: 'smart-money/:tab', element: <SmartMoney /> }` (not scan-gated: it does not need a scan).
5. `web/ui/src/app/nav.ts`: `{ id: 'smart-money', label: 'Smart money', to: '/smart-money', icon: Landmark,
   keys: 'g b', match: (p) => p.startsWith('/smart-money') }` after Market; `G_KEYS.b = '/smart-money'`.
6. `web/ui/src/pages/Chart.tsx` `SidePanel`: for `s.kind === 'stock'` add `<div className="p-4"><SmartMoneyPanel
   symbol={s.symbol} /></div>` in the second column after "Your holding".
7. Daily scan: in `run_scan.py` `main()`, after `run_daily` returned and only when `not args.no_update`:
   `try: smart_money.refresh(days=365, log=log)` / `except Exception: log(...)` - it never fails or blocks the
   scan (own lock, released scan lock); `symbols` defaults to the cached universe + holdings minus ETFs; the
   shareholding download continues incrementally each day. **Not** inside `scanner/daily._run_daily`:
   `tests/test_store.py::test_daily_result_keeps_refresh_info_when_a_strategy_has_actions` calls
   `_run_daily(cfg, True, ...)` with only the price download faked, so a refresh there would hit NSE and write
   data/smart_money from a test.
8. Telegram: in `run_scan.py`, inside the `try` right after `format_daily(...)`: append
   `smart_money.summary_lines()` (a blank line before; `[]` adds nothing). `scanner/alerts.format_daily` stays pure
   (its tests must not read data/smart_money).
9. Regenerate `web/api/openapi.json` (`python -m web.api.main --openapi`) - `test_openapi_file_is_current` fails
   until then; extend `tests/test_api_contract.py` with the new endpoints on an empty data folder (every GET returns
   200 with empty lists, `has_data` false): add them to `GET_ENDPOINTS` (so the shape and no-network tests cover
   them) and `/api/smart-money/refresh` to the POST paths of `test_openapi_lists_every_contract_path`.
10. Optional: mock handlers in `web/ui/src/api/mock/server.ts`; a Command Palette entry.

---------------------------------------------------------------------------------------------------------------------

## 10. To verify live after wiring (assumptions with medium/low confidence)

- Exact bulk.csv / block.csv header spelling (the parser normalises headers, so small changes are tolerated).
- `historicalOR` CSV vs JSON completeness (JSON reportedly stops at 70 rows; we request `csv=true`).
- PIT field spellings and the `personCategory` / `acqMode` vocabularies.
- Whether `corporate-share-holdings-master` date-range mode filters by broadcast date (the per-symbol fallback
  covers the other case).
- SHP XBRL member names (`InstitutionsDomestic`, `InstitutionsForeign`, `MutualFund`, ...) and the percent scale -
  check `unmatched_names.json`, `state.json` errors and a few stocks by hand against NSE's shareholding page.

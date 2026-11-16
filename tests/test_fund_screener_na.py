"""The fundamentals screener with pandas' missing values: a new listing has no 200-day average yet, so the scan stores
<NA> in its nullable boolean columns - and once its quarterly results are stored it reaches the screener's rows."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from web.api.services import company_svc, data, fund_svc


def test_screener_rows_survive_missing_averages_and_prices(monkeypatch):
    sc = pd.DataFrame({"symbol": ["NEWCO", "OLDCO"], "company": ["New Co", "Old Co"], "industry": ["X", "X"],
                       "price": pd.array([None, 120.5], dtype="Float64"),
                       "ret_3m": [float("nan"), 4.0], "ret_12m": [float("nan"), 9.0], "rs": [None, 80.0],
                       "above_sma200": pd.array([None, True], dtype="boolean"),
                       "pct_from_52w_high": [-3.0, -1.0], "turnover_cr": [5.0, 7.0], "scan_id": ["s", "s"]})
    seen: list = []
    monkeypatch.setattr(data, "screener", lambda: sc)
    monkeypatch.setattr(company_svc, "scores", lambda: {})
    monkeypatch.setattr(fund_svc.fu, "load", lambda s: {"quarters": [{"qe": "2026-09-30"}]})
    monkeypatch.setattr(fund_svc.fu, "summary", lambda rec, price: seen.append(price) or {"latest": {"qe": "2026-09-30",
                                                                                                    "pe": 20.0}})
    monkeypatch.setattr(fund_svc.fin, "_file", lambda s: Path("no-such-folder") / f"{s}.json")
    out = fund_svc.screener()
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["NEWCO"]["above_sma200"] is None and by["NEWCO"]["price"] is None and by["NEWCO"]["rs"] is None
    assert by["OLDCO"]["above_sma200"] is True and by["OLDCO"]["price"] == 120.5
    assert seen == [None, 120.5]


def test_json_responses_turn_pandas_missing_values_and_numpy_scalars_into_plain_json():
    import json

    import numpy as np

    from web.api.errors import SafeJSONResponse
    body = {"na": pd.NA, "nat": pd.NaT, "nan": float("nan"), "i": np.int64(3), "b": np.bool_(True),
            "f": np.float32(1.5), "ts": pd.Timestamp("2026-11-16 09:15"), "rows": [{"x": pd.NA}, (np.int64(1),)]}
    out = json.loads(SafeJSONResponse(body).body)
    assert out == {"na": None, "nat": None, "nan": None, "i": 3, "b": True, "f": 1.5, "ts": "2026-11-16T09:15:00",
                   "rows": [{"x": None}, [1]]}
    assert json.loads(SafeJSONResponse({"a": 1, "b": [1.5, "x"]}).body) == {"a": 1, "b": [1.5, "x"]}

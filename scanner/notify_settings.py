"""Your Telegram notification choices (data/notify_settings.json), shared by the dashboard and the background jobs:

  brief    the 08:45 morning brief (with the login reminder's task): off unless you switch it on
  setups   live setups from the live service while the market is open: off unless switched on;
           scope "mine" (watchlists and holdings) or "all", and which kinds of event
"""
from __future__ import annotations

import json

from .settings import DATA_DIR

FILE = "notify_settings.json"
DEFAULT = {"brief": False, "setups": {"on": False, "scope": "mine",
                                      "kinds": ["gap_up", "gap_down", "orb_up", "orb_down", "high_52w", "low_52w",
                                                "volume_spike"]}}


def read() -> dict:
    try:
        v = json.loads((DATA_DIR / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        v = {}
    out = json.loads(json.dumps(DEFAULT))
    if isinstance(v, dict):
        out["brief"] = bool(v.get("brief", out["brief"]))
        s = v.get("setups") if isinstance(v.get("setups"), dict) else {}
        out["setups"].update({k: s[k] for k in ("on", "scope", "kinds") if k in s})
    return out


def write(v: dict) -> dict:
    cur = read()
    if "brief" in v:
        cur["brief"] = bool(v["brief"])
    if isinstance(v.get("setups"), dict):
        s = v["setups"]
        if "on" in s:
            cur["setups"]["on"] = bool(s["on"])
        if s.get("scope") in ("mine", "all"):
            cur["setups"]["scope"] = s["scope"]
        if isinstance(s.get("kinds"), list):
            cur["setups"]["kinds"] = [str(k) for k in s["kinds"]][:20]
    p = DATA_DIR / FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    tmp.replace(p)
    return cur

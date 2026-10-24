"""Every file the API reads or writes, in one place.

Defaults come from scanner.settings (the checkout's ROOT and its data/ folder). `configure()` repoints
everything - including the module globals of the scanner functions the API calls - so the contract tests
can run against fixture copies of the real files without touching data/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scanner import settings


@dataclass
class Paths:
    root: Path
    data: Path

    @property
    def results(self) -> Path: return self.data / "results"
    @property
    def latest(self) -> Path: return self.results / "latest.json"
    @property
    def curves(self) -> Path: return self.results / "curves.parquet"
    @property
    def trades(self) -> Path: return self.results / "trades.parquet"
    @property
    def screener(self) -> Path: return self.results / "screener.parquet"
    @property
    def status(self) -> Path: return self.results / "status.json"
    @property
    def intraday(self) -> Path: return self.results / "intraday.json"
    @property
    def intraday_status(self) -> Path: return self.results / "intraday_status.json"
    @property
    def nse(self) -> Path: return self.data / "nse"
    @property
    def index_history(self) -> Path: return self.nse / "index_history.parquet"
    @property
    def store(self) -> Path: return self.data / "history" / "store"
    @property
    def pit(self) -> Path: return self.data / "history" / "pit"
    @property
    def journal(self) -> Path: return self.data / "journal.sqlite"
    @property
    def logs(self) -> Path: return self.data / "logs"
    @property
    def scan_log(self) -> Path: return self.logs / "scanner.log"
    @property
    def lock(self) -> Path: return self.data / ".scan.lock"
    @property
    def lock_info(self) -> Path: return self.data / ".scan.lock.json"
    @property
    def token(self) -> Path: return self.data / "fyers_token.json"
    @property
    def fyers_usage(self) -> Path: return self.data / "fyers_usage.json"
    @property
    def fyers_usage_lock(self) -> Path: return self.data / ".fyers_usage.lock"
    @property
    def intraday_lock(self) -> Path: return self.results / ".intraday.lock"
    @property
    def holdings(self) -> Path: return self.root / "holdings.csv"
    @property
    def config(self) -> Path: return self.root / "config.yaml"
    @property
    def login_bat(self) -> Path: return self.root / "1_login.bat"
    @property
    def run_scan(self) -> Path: return self.root / "run_scan.py"

    def universe(self, name: str) -> Path:
        return self.data / f"universe_{name}.csv"


P = Paths(settings.ROOT, settings.DATA_DIR)


def configure(root: Path, data: Path) -> None:
    """Repoint the API and the scanner modules it calls at another root/data folder (tests)."""
    from scanner import fyers_limits, holdings, lock, paper, providers, store

    from . import errors        # lazy: errors imports this module

    P.root, P.data = Path(root), Path(data)
    store.STORE_DIR = P.store
    paper.JOURNAL_FILE = P.journal
    holdings.HOLDINGS_FILE = P.holdings
    lock.LOCK_FILE, lock.INFO_FILE = P.lock, P.lock_info
    providers.TOKEN_FILE = P.token
    fyers_limits.STATE_FILE, fyers_limits.LOCK_FILE = P.fyers_usage, P.fyers_usage_lock
    settings.CONFIG_FILE = P.config
    settings.HOLDINGS_FILE = P.holdings
    settings.TOKEN_FILE = P.token
    errors.setup_logging()      # api.log moves with the data folder

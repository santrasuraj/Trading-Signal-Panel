"""In-process caches keyed by file identity (mtime + size) or by derived keys.

Every loader runs under the cache's lock so concurrent requests never compute the same thing twice.
Routes are plain `def` (FastAPI runs them in its threadpool) because the pandas work is blocking.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable


def file_key(path: Path) -> tuple:
    """Identity of a file on disk: (path, mtime_ns, size), or (path, None) when it does not exist."""
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), None)


class FileCache:
    """Value derived from one file, recomputed only when the file changes. Missing file -> `missing`."""

    def __init__(self, loader: Callable[[Path], Any], missing: Any = None):
        self.loader, self.missing = loader, missing
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._val: Any = None

    def get(self, path: Path) -> Any:
        key = file_key(path)
        with self._lock:
            if key != self._key:
                if key[1] is None:
                    self._val = self.missing
                else:
                    try:
                        self._val = self.loader(path)
                    except Exception:
                        # a file caught mid-write by another process: retry on the next request
                        self._key = None
                        return self.missing
                self._key = key
            return self._val

    def clear(self) -> None:
        with self._lock:
            self._key, self._val = None, None


class KeyedCache:
    """Small LRU of derived values: get(key, compute)."""

    def __init__(self, maxsize: int = 8):
        self.maxsize = maxsize
        self._lock = threading.Lock()
        self._data: OrderedDict = OrderedDict()

    def get(self, key, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            val = compute()
            self._data[key] = val
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
            return val

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class TTLCache:
    """One value refreshed at most every `ttl` seconds (e.g. the store version re-check)."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._at = 0.0
        self._val: Any = None

    def get(self, compute: Callable[[], Any]) -> Any:
        with self._lock:
            now = time.monotonic()
            if now - self._at > self.ttl or self._val is None:
                self._val, self._at = compute(), now
            return self._val

    def clear(self) -> None:
        with self._lock:
            self._at, self._val = 0.0, None


_ALL: list = []


def register(*caches):
    _ALL.extend(caches)
    return caches[0] if len(caches) == 1 else caches


def clear_all() -> None:
    for c in _ALL:
        c.clear()

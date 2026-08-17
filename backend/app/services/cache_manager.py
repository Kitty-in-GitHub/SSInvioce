"""Unified on-disk cache registry: register stores, get/put, TTL cleanup."""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from ..config import CACHE_DIR, EXPORTS_DIR, ensure_dirs
from ..logging_config import get_logger

log = get_logger("cache")

DEFAULT_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_CLEANUP_INTERVAL_SECONDS = 6 * 3600


class CacheStore(Protocol):
    name: str
    root: Path
    ttl_seconds: int

    def get(self, key: str) -> Path | None: ...

    def put(self, key: str, src: Path) -> Path: ...

    def cleanup(self, now: float | None = None) -> int: ...


@dataclass
class FileCacheStore:
    """Simple one-file-per-key store under ``root / f"{key}{suffix}"``."""

    name: str
    root: Path
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    suffix: str = ".pdf"
    # When putting key "a_b_hash", delete siblings matching this prefix rule.
    # If True, treat key as ``{prefix}_{hash}`` where prefix is everything before last `_`.
    replace_same_prefix: bool = False

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe = key.replace("..", "_").replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}{self.suffix}"

    def get(self, key: str) -> Path | None:
        path = self.path_for(key)
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        return path

    def put(self, key: str, src: Path) -> Path:
        src = src.resolve()
        dest = self.path_for(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        if self.replace_same_prefix:
            self._purge_siblings(key, keep=dest)
        return dest

    def _prefix_of(self, key: str) -> str | None:
        if "_" not in key:
            return None
        return key.rsplit("_", 1)[0]

    def _purge_siblings(self, key: str, keep: Path) -> None:
        prefix = self._prefix_of(key)
        if not prefix:
            return
        keep_res = keep.resolve()
        for p in self.root.glob(f"{prefix}_*{self.suffix}"):
            try:
                if p.resolve() == keep_res:
                    continue
                p.unlink()
                log.info("cache purged sibling store=%s path=%s", self.name, p)
            except OSError:
                log.debug("cache purge sibling failed path=%s", p, exc_info=True)

    def cleanup(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        if not self.root.is_dir():
            return 0
        for p in self.root.iterdir():
            if not p.is_file():
                continue
            try:
                age = now - p.stat().st_mtime
                if age > self.ttl_seconds:
                    p.unlink()
                    removed += 1
            except OSError:
                log.debug("cache cleanup skip path=%s", p, exc_info=True)
        if removed:
            log.info("cache cleanup store=%s removed=%s", self.name, removed)
        return removed


@dataclass
class FormPdfCacheStore(FileCacheStore):
    """Form PDF cache; also sweeps legacy timestamped preview files in exports."""

    name: str = "form_pdf"
    root: Path = field(default_factory=lambda: CACHE_DIR / "form_pdf")
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    suffix: str = ".pdf"
    replace_same_prefix: bool = True

    def cleanup(self, now: float | None = None) -> int:
        removed = super().cleanup(now)
        now = time.time() if now is None else now
        # Legacy: data/exports/group_*_preview_*.pdf
        if EXPORTS_DIR.is_dir():
            for p in EXPORTS_DIR.glob("group_*_preview_*.pdf"):
                try:
                    if now - p.stat().st_mtime > self.ttl_seconds:
                        p.unlink()
                        removed += 1
                except OSError:
                    log.debug("legacy preview cleanup skip path=%s", p, exc_info=True)
        return removed


class CacheRegistry:
    def __init__(self) -> None:
        self._stores: dict[str, CacheStore] = {}
        self._lock = threading.Lock()
        self._last_cleanup: float = 0.0

    def register(self, store: CacheStore) -> None:
        with self._lock:
            self._stores[store.name] = store
            Path(store.root).mkdir(parents=True, exist_ok=True)
            log.info("cache registered name=%s root=%s ttl=%ss", store.name, store.root, store.ttl_seconds)

    def get_store(self, name: str) -> CacheStore:
        store = self._stores.get(name)
        if store is None:
            raise KeyError(f"cache store not registered: {name}")
        return store

    def has_store(self, name: str) -> bool:
        return name in self._stores

    def cleanup_all(self) -> int:
        total = 0
        with self._lock:
            stores = list(self._stores.values())
            self._last_cleanup = time.time()
        for store in stores:
            try:
                total += store.cleanup()
            except Exception:
                log.exception("cache cleanup failed store=%s", store.name)
        if total:
            log.info("cache cleanup_all removed=%s", total)
        return total

    def maybe_cleanup(self, min_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS) -> int:
        now = time.time()
        with self._lock:
            if now - self._last_cleanup < min_interval_seconds:
                return 0
            self._last_cleanup = now
            stores = list(self._stores.values())
        total = 0
        for store in stores:
            try:
                total += store.cleanup(now)
            except Exception:
                log.exception("cache maybe_cleanup failed store=%s", store.name)
        return total

    def get_or_build(self, store_name: str, key: str, builder: Callable[[], Path]) -> Path:
        """Return cached file or build, put, and return."""
        self.maybe_cleanup()
        store = self.get_store(store_name)
        hit = store.get(key)
        if hit is not None:
            log.info("cache hit store=%s key=%s", store_name, key)
            return hit
        log.info("cache miss store=%s key=%s", store_name, key)
        built = builder()
        stored = store.put(key, built)
        try:
            if built.resolve() != stored.resolve() and built.is_file():
                built.unlink()
        except OSError:
            log.debug("cache remove build temp failed path=%s", built, exc_info=True)
        return stored


_registry: CacheRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> CacheRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = CacheRegistry()
    return _registry


def init_caches() -> CacheRegistry:
    """Register default stores (idempotent enough for startup)."""
    ensure_dirs()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    reg = get_registry()
    if not reg.has_store("form_pdf"):
        reg.register(FormPdfCacheStore())
    return reg


def cleanup_all() -> int:
    return get_registry().cleanup_all()


def maybe_cleanup(min_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS) -> int:
    return get_registry().maybe_cleanup(min_interval_seconds)

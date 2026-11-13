from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import DATA_DIR, ensure_dirs

LOG_DIR = DATA_DIR / "logs"
LOGGER_NAME = "star_invoice"

_LEVEL_NAMES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _resolve_level(level_arg: int | str | None) -> int:
    if level_arg is None:
        env = os.environ.get("LOG_LEVEL", "").strip().upper()
        return _LEVEL_NAMES.get(env, logging.INFO)
    if isinstance(level_arg, str):
        return _LEVEL_NAMES.get(level_arg.strip().upper(), logging.INFO)
    return int(level_arg)


def setup_logging(level: int | str | None = None) -> logging.Logger:
    ensure_dirs()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    resolved_level = _resolve_level(level)
    logger.setLevel(resolved_level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(resolved_level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(resolved_level)

    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False

    # Capture uvicorn logs into the same rotating file once
    for name in ("uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.setLevel(resolved_level)
        if not any(isinstance(h, RotatingFileHandler) for h in uv.handlers):
            uv.addHandler(file_handler)
        uv.propagate = False

    logger.info("logging initialized level=%s -> %s", logging.getLevelName(resolved_level), LOG_DIR / "app.log")
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    base = logging.getLogger(LOGGER_NAME)
    if not base.handlers:
        setup_logging()
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return base

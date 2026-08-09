from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import DATA_DIR, ensure_dirs

LOG_DIR = DATA_DIR / "logs"
LOGGER_NAME = "star_invoice"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    ensure_dirs()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(level)
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
    file_handler.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)

    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False

    # Capture uvicorn logs into the same rotating file once
    for name in ("uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.setLevel(level)
        if not any(isinstance(h, RotatingFileHandler) for h in uv.handlers):
            uv.addHandler(file_handler)
        uv.propagate = False

    logger.info("logging initialized -> %s", LOG_DIR / "app.log")
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    base = logging.getLogger(LOGGER_NAME)
    if not base.handlers:
        setup_logging()
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return base

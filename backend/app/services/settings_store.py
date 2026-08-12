from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import DATA_DIR
from ..logging_config import get_logger

log = get_logger("settings")

SETTINGS_PATH = DATA_DIR / "settings.json"
_lock = threading.Lock()

DEFAULT_CLASSIFY_KEYWORDS: dict[str, list[str]] = {
    "invoice": ["发票", "电子发票", "增值税", "价税合计", "发票代码", "发票号码"],
    "order": ["订单", "商品", "规格", "件数", "淘宝", "京东", "拼多多", "天猫", "待收货", "已发货", "order", "taobao", "jd"],
    "payment": [
        "支付成功",
        "付款成功",
        "实付",
        "收款方",
        "支付宝",
        "微信支付",
        "交易成功",
        "转账",
        "支付",
        "微信",
        "付款",
        "收款",
        "账单",
        "alipay",
        "wechat",
        "pay",
    ],
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "classify_keywords": deepcopy(DEFAULT_CLASSIFY_KEYWORDS),
}


def _normalize_keywords(raw: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    src = raw if isinstance(raw, dict) else {}
    for key in ("invoice", "order", "payment"):
        items = src.get(key, DEFAULT_CLASSIFY_KEYWORDS[key])
        if not isinstance(items, list):
            items = DEFAULT_CLASSIFY_KEYWORDS[key]
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            word = str(item).strip()
            if not word or word in seen:
                continue
            seen.add(word)
            cleaned.append(word)
        out[key] = cleaned
    return out


def default_settings() -> dict[str, Any]:
    return {
        "classify_keywords": deepcopy(DEFAULT_CLASSIFY_KEYWORDS),
    }


def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return default_settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("failed reading settings %s", SETTINGS_PATH)
        return default_settings()
    if not isinstance(data, dict):
        return default_settings()
    return {
        "classify_keywords": _normalize_keywords(data.get("classify_keywords")),
    }


def _write_file(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def get_settings() -> dict[str, Any]:
    with _lock:
        return _read_file()


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = _read_file()
        if "classify_keywords" in patch:
            current["classify_keywords"] = _normalize_keywords(patch.get("classify_keywords"))
        _write_file(current)
        log.info("settings updated path=%s", SETTINGS_PATH)
        return current


def get_classify_keywords() -> dict[str, list[str]]:
    return get_settings()["classify_keywords"]


def reset_classify_keywords() -> dict[str, Any]:
    return update_settings({"classify_keywords": deepcopy(DEFAULT_CLASSIFY_KEYWORDS)})

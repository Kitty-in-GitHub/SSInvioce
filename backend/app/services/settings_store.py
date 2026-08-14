from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from typing import Any

from ..config import DATA_DIR
from ..logging_config import get_logger

log = get_logger("settings")

SETTINGS_PATH = DATA_DIR / "settings.json"
_lock = threading.Lock()

SLOT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

DEFAULT_CLASSIFY_KEYWORDS: dict[str, list[str]] = {
    "invoice": ["发票", "电子发票", "增值税", "价税合计", "发票代码", "发票号码"],
    "order": [
        "订单",
        "订单信息",
        "订单编号",
        "收货信息",
        "发货时间",
        "成交时间",
        "加入购物车",
        "申请售后",
        "实付款",
        "实付价",
        "商品",
        "规格",
        "件数",
        "淘宝",
        "京东",
        "拼多多",
        "天猫",
        "天猫积分",
        "待收货",
        "已发货",
        "闲鱼转卖",
        "order",
        "taobao",
        "jd",
    ],
    "payment": [
        "支付成功",
        "付款成功",
        "收款方",
        "微信支付",
        "转账成功",
        "转账",
        "账单详情",
        "账单",
        "当前状态",
        "支付方式：",
        "alipay",
    ],
}

SLOT_COLORS = ["#163a7a", "#2a6b4a", "#8a5a12", "#6b3fa0", "#a11f2c", "#1a6a8c", "#5c4a12", "#3d5a80"]

DEFAULT_LAYOUT: dict[str, Any] = {
    "pages": [
        {
            "regions": [
                {"slot_id": "invoice", "x": 0.044, "y": 0.026, "w": 0.912, "h": 0.43},
                {"slot_id": "order", "x": 0.044, "y": 0.47, "w": 0.448, "h": 0.49},
                {"slot_id": "payment", "x": 0.508, "y": 0.47, "w": 0.448, "h": 0.49},
            ]
        }
    ]
}


def _clean_keywords(raw: Any, fallback: list[str] | None = None) -> list[str]:
    items = raw if isinstance(raw, list) else (fallback or [])
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        word = str(item).strip()
        if not word or word in seen:
            continue
        seen.add(word)
        cleaned.append(word)
    return cleaned


def default_slots() -> list[dict[str, Any]]:
    return [
        {
            "id": "invoice",
            "label": "发票",
            "file_kind": "pdf",
            "required": True,
            "special": "invoice",
            "color": SLOT_COLORS[0],
            "keywords": list(DEFAULT_CLASSIFY_KEYWORDS["invoice"]),
        },
        {
            "id": "order",
            "label": "订单截图",
            "file_kind": "image",
            "required": True,
            "special": None,
            "color": SLOT_COLORS[1],
            "keywords": list(DEFAULT_CLASSIFY_KEYWORDS["order"]),
        },
        {
            "id": "payment",
            "label": "支付记录",
            "file_kind": "image",
            "required": True,
            "special": None,
            "color": SLOT_COLORS[2],
            "keywords": list(DEFAULT_CLASSIFY_KEYWORDS["payment"]),
        },
    ]


def default_layout() -> dict[str, Any]:
    return deepcopy(DEFAULT_LAYOUT)


def default_settings() -> dict[str, Any]:
    slots = default_slots()
    return {
        "slots": slots,
        "layout": default_layout(),
        "custom_colors": [],
        "classify_keywords": _keywords_from_slots(slots),
    }


def _normalize_hex_color(raw: Any) -> str | None:
    color = str(raw or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", color):
        return color
    if re.fullmatch(r"#[0-9a-f]{3}", color):
        return "#" + "".join(ch * 2 for ch in color[1:])
    return None


def _normalize_custom_colors(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else []
    out: list[str] = []
    seen: set[str] = set()
    preset = {c.lower() for c in SLOT_COLORS}
    for item in items:
        color = _normalize_hex_color(item)
        if not color or color in seen or color in preset:
            continue
        seen.add(color)
        out.append(color)
        if len(out) >= 24:
            break
    return out


def _keywords_from_slots(slots: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {s["id"]: list(s.get("keywords") or []) for s in slots}


def _clamp01(val: Any, default: float = 0.0) -> float:
    try:
        n = float(val)
    except (TypeError, ValueError):
        n = default
    return max(0.0, min(1.0, n))


def _normalize_layout(raw: Any, slot_ids: set[str]) -> dict[str, Any]:
    pages_in = []
    if isinstance(raw, dict) and isinstance(raw.get("pages"), list):
        pages_in = raw["pages"]
    pages: list[dict[str, Any]] = []
    for page in pages_in:
        regions_in = page.get("regions") if isinstance(page, dict) else None
        if not isinstance(regions_in, list):
            continue
        regions: list[dict[str, Any]] = []
        for region in regions_in:
            if not isinstance(region, dict):
                continue
            sid = str(region.get("slot_id") or "").strip()
            if sid not in slot_ids:
                continue
            x = _clamp01(region.get("x"), 0.05)
            y = _clamp01(region.get("y"), 0.05)
            w = max(0.04, _clamp01(region.get("w"), 0.4))
            h = max(0.04, _clamp01(region.get("h"), 0.3))
            if x + w > 1:
                w = max(0.04, 1 - x)
            if y + h > 1:
                h = max(0.04, 1 - y)
            regions.append(
                {"slot_id": sid, "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}
            )
        pages.append({"regions": regions})
    if not pages:
        pages = [{"regions": []}]
    return {"pages": pages}


def _normalize_slots(raw: Any, keywords_legacy: Any = None) -> list[dict[str, Any]]:
    src = raw if isinstance(raw, list) else None
    if not src:
        slots = default_slots()
        if isinstance(keywords_legacy, dict):
            for slot in slots:
                if slot["id"] in keywords_legacy:
                    slot["keywords"] = _clean_keywords(keywords_legacy[slot["id"]], slot["keywords"])
        return slots

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    invoice_taken = False
    for i, item in enumerate(src):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip().lower()
        if not SLOT_ID_RE.match(sid) or sid == "unknown" or sid in seen:
            continue
        seen.add(sid)
        file_kind = item.get("file_kind") if item.get("file_kind") in ("pdf", "image") else "image"
        special = item.get("special") if item.get("special") == "invoice" else None
        if special == "invoice":
            if invoice_taken or file_kind != "pdf":
                special = None
            else:
                invoice_taken = True
                file_kind = "pdf"
        label = str(item.get("label") or sid).strip()[:40] or sid
        color = _normalize_hex_color(item.get("color")) or SLOT_COLORS[i % len(SLOT_COLORS)]
        fallback_kw = DEFAULT_CLASSIFY_KEYWORDS.get(sid, [])
        keywords = _clean_keywords(item.get("keywords"), fallback_kw)
        required = bool(item.get("required", True))
        if special == "invoice":
            required = True
        out.append(
            {
                "id": sid,
                "label": label,
                "file_kind": file_kind,
                "required": required,
                "special": special,
                "color": color,
                "keywords": keywords,
            }
        )

    if not any(s.get("special") == "invoice" for s in out):
        inv = next((s for s in default_slots() if s["special"] == "invoice"), None)
        if inv and inv["id"] not in seen:
            out.insert(0, inv)
        elif inv:
            for s in out:
                if s["id"] == inv["id"]:
                    s["special"] = "invoice"
                    s["file_kind"] = "pdf"
                    s["required"] = True
                    break
    return out or default_slots()


def _normalize_all(data: dict[str, Any]) -> dict[str, Any]:
    slots = _normalize_slots(data.get("slots"), data.get("classify_keywords"))
    layout = _normalize_layout(data.get("layout"), {s["id"] for s in slots})
    if not any(r.get("slot_id") for p in layout["pages"] for r in p["regions"]):
        layout = _normalize_layout(default_layout(), {s["id"] for s in slots})
    return {
        "slots": slots,
        "layout": layout,
        "custom_colors": _normalize_custom_colors(data.get("custom_colors")),
        "preset_colors": list(SLOT_COLORS),
        "classify_keywords": _keywords_from_slots(slots),
    }


def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return _normalize_all(default_settings())
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("failed reading settings %s", SETTINGS_PATH)
        return _normalize_all(default_settings())
    if not isinstance(data, dict):
        return _normalize_all(default_settings())
    return _normalize_all(data)


def _write_file(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "slots": data.get("slots") or [],
        "layout": data.get("layout") or default_layout(),
        "custom_colors": data.get("custom_colors") or [],
    }
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def get_settings() -> dict[str, Any]:
    with _lock:
        return _read_file()


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = _read_file()
        merged = dict(current)
        if "slots" in patch and patch["slots"] is not None:
            merged["slots"] = patch["slots"]
        if "layout" in patch and patch["layout"] is not None:
            merged["layout"] = patch["layout"]
        if "custom_colors" in patch and patch["custom_colors"] is not None:
            merged["custom_colors"] = patch["custom_colors"]
        if "classify_keywords" in patch and patch["classify_keywords"] is not None and "slots" not in patch:
            kw = patch["classify_keywords"]
            if isinstance(kw, dict):
                slots = deepcopy(current["slots"])
                for slot in slots:
                    if slot["id"] in kw:
                        slot["keywords"] = kw[slot["id"]]
                merged["slots"] = slots
        current = _normalize_all(merged)
        _write_file(current)
        log.info("settings updated path=%s", SETTINGS_PATH)
        return current


def get_classify_keywords() -> dict[str, list[str]]:
    return get_settings()["classify_keywords"]


def get_slots() -> list[dict[str, Any]]:
    return get_settings()["slots"]


def get_layout() -> dict[str, Any]:
    return get_settings()["layout"]


def invoice_slot_id() -> str:
    for slot in get_slots():
        if slot.get("special") == "invoice":
            return slot["id"]
    return "invoice"


def required_slot_ids() -> list[str]:
    return [s["id"] for s in get_slots() if s.get("required")]


def placed_slot_ids(layout: dict[str, Any] | None = None) -> set[str]:
    spec = layout if layout is not None else get_layout()
    ids: set[str] = set()
    for page in spec.get("pages") or []:
        for region in page.get("regions") or []:
            sid = region.get("slot_id")
            if sid:
                ids.add(sid)
    return ids


def file_kind_for(slot_id: str) -> str:
    for slot in get_slots():
        if slot["id"] == slot_id:
            return slot.get("file_kind") or "image"
    if slot_id == "invoice":
        return "pdf"
    return "image"


def slot_ids() -> set[str]:
    return {s["id"] for s in get_slots()}


def reset_classify_keywords() -> dict[str, Any]:
    return update_settings({"slots": default_slots(), "layout": default_layout()})

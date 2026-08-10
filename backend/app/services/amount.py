from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pymupdf as fitz

from ..logging_config import get_logger
from .storage import resolve_stored

log = get_logger("amount")

# filename like 260509_12.00_中通.pdf or xxx_53.1_yyy
FILENAME_AMOUNT_RE = re.compile(
    r"(?:^|[_\-])(\d+(?:\.\d{1,2})?)(?:[_\-]|$)",
    re.UNICODE,
)
YUAN_RE = re.compile(
    r"(?:价税合计|合计|金额|应付|实付)[^\d￥¥]{0,12}[￥¥]?\s*(\d+(?:\.\d{1,2})?)",
    re.UNICODE,
)
CURRENCY_RE = re.compile(r"[￥¥]\s*(\d+(?:\.\d{1,2})?)")


def _to_decimal(raw: str) -> Decimal | None:
    try:
        val = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if val <= 0 or val > Decimal("10000000"):
        return None
    return val.quantize(Decimal("0.01"))


def parse_amount_from_filename(name: str) -> Decimal | None:
    stem = Path(name).stem
    # Prefer explicit _12.00_ pattern with decimal
    decimal_hits = re.findall(r"[_\-](\d+\.\d{1,2})[_\-]", f"_{stem}_")
    for hit in reversed(decimal_hits):
        val = _to_decimal(hit)
        if val is not None:
            return val
    # Fallback: middle numeric token that looks like money (has decimal or small int)
    for m in FILENAME_AMOUNT_RE.finditer(stem):
        raw = m.group(1)
        if "." in raw:
            val = _to_decimal(raw)
            if val is not None:
                return val
    return None


def parse_amount_from_pdf_text(text: str) -> Decimal | None:
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    for pattern in (YUAN_RE, CURRENCY_RE):
        matches = pattern.findall(compact)
        if matches:
            # Prefer last match (合计 often appears near end)
            for raw in reversed(matches):
                val = _to_decimal(raw)
                if val is not None:
                    return val
    return None


def extract_invoice_amount(*, stored_path: str, original_name: str = "") -> Decimal | None:
    """Heuristic amount from invoice PDF text and/or filename."""
    name = original_name or Path(stored_path).name
    from_name = parse_amount_from_filename(name)
    text = ""
    try:
        path = resolve_stored(stored_path)
        if path.suffix.lower() == ".pdf" and path.exists():
            doc = fitz.open(path)
            try:
                text = doc[0].get_text() or ""
            finally:
                doc.close()
    except Exception:
        log.exception("failed reading invoice text path=%s", stored_path)

    from_pdf = parse_amount_from_pdf_text(text)
    chosen = from_pdf or from_name
    log.info(
        "extract amount name=%r pdf=%s filename=%s -> %s",
        name,
        from_pdf,
        from_name,
        chosen,
    )
    return chosen


def apply_auto_amount(conn, entry_id: int, *, stored_path: str, original_name: str) -> None:
    """Fill amount from invoice when entry is not manually locked."""
    from ..db import now_iso

    row = conn.execute(
        "SELECT amount_source FROM entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        return
    if (row["amount_source"] or "empty") == "manual":
        return
    parsed = extract_invoice_amount(stored_path=stored_path, original_name=original_name)
    if parsed is None:
        return
    val = float(parsed)
    conn.execute(
        """
        UPDATE entries
        SET amount = ?, amount_auto = ?, amount_source = 'auto', updated_at = ?
        WHERE id = ?
        """,
        (val, val, now_iso(), entry_id),
    )
    log.info("auto amount entry_id=%s amount=%s", entry_id, val)

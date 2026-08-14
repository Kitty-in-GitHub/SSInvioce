from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..logging_config import get_logger
from .storage import resolve_stored

log = get_logger("amount")

# filename like 260509_12.00_中通.pdf or xxx_53.1_yyy
FILENAME_AMOUNT_RE = re.compile(
    r"(?:^|[_\-])(\d+(?:\.\d{1,2})?)(?:[_\-]|$)",
    re.UNICODE,
)
# Prefer explicit "actual paid" labels used on order / payment screenshots.
ACTUAL_PRICE_RE = re.compile(r"实付价[￥¥]\s*(\d+(?:\.\d{1,2})?)", re.UNICODE)
ACTUAL_PAY_CHUNK_RE = re.compile(r"实付款(.{0,48})", re.UNICODE)
DISCOUNT_AMOUNT_RE = re.compile(
    r"(?:共减|立减|抵|优惠|减)[￥¥]?\s*\d+(?:\.\d{1,2})?",
    re.UNICODE,
)
YUAN_RE = re.compile(
    r"(?:价税合计|合计金额|应付合计|应付|金额合计)[^\d￥¥]{0,12}[￥¥]?\s*(\d+(?:\.\d{1,2})?)",
    re.UNICODE,
)
CURRENCY_RE = re.compile(r"[￥¥]\s*(\d+(?:\.\d{1,2})?)")
YUAN_UNIT_RE = re.compile(r"(\d+(?:\.\d{1,2})?)\s*元")
# WeChat / Alipay bill pages: large "-30.09" / "+12.00" without ￥
SIGNED_BILL_AMOUNT_RE = re.compile(
    r"(?<![0-9.])[-－−+](\d+\.\d{2})(?![0-9])",
    re.UNICODE,
)


def _to_decimal(raw: str) -> Decimal | None:
    try:
        val = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if val <= 0 or val > Decimal("10000000"):
        return None
    return val.quantize(Decimal("0.01"))


def _parse_actual_pay(compact: str) -> Decimal | None:
    m = ACTUAL_PRICE_RE.search(compact)
    if m:
        val = _to_decimal(m.group(1))
        if val is not None:
            return val

    m = ACTUAL_PAY_CHUNK_RE.search(compact)
    if not m:
        return None
    chunk = DISCOUNT_AMOUNT_RE.sub("", m.group(1))
    amounts = CURRENCY_RE.findall(chunk)
    for raw in reversed(amounts):
        val = _to_decimal(raw)
        if val is not None:
            return val
    return None


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


def _parse_signed_bill_amount(compact: str) -> Decimal | None:
    """Parse WeChat-style bill totals like '-30.09' near payment status."""
    candidates: list[tuple[int, Decimal]] = []
    for m in SIGNED_BILL_AMOUNT_RE.finditer(compact):
        val = _to_decimal(m.group(1))
        if val is None:
            continue
        window = compact[max(0, m.start() - 24) : m.end() + 24]
        score = 0
        if any(k in window for k in ("当前状态", "支付成功", "支付时间", "交易成功", "全部账单")):
            score += 5
        if "商户" in window or "有限公司" in window or "公司" in window:
            score += 2
        # Prefer the first prominent bill amount (usually under merchant name)
        candidates.append((score, val))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0],))
    best_score, best_val = candidates[0]
    if best_score >= 2 or any(k in compact for k in ("支付成功", "当前状态", "全部账单")):
        return best_val
    return None


def parse_amount_from_pdf_text(text: str) -> Decimal | None:
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)

    paid = _parse_actual_pay(compact)
    if paid is not None:
        return paid

    signed = _parse_signed_bill_amount(compact)
    if signed is not None:
        return signed

    for pattern in (YUAN_RE, YUAN_UNIT_RE):
        matches = pattern.findall(compact)
        if matches:
            # Prefer last match (合计 often appears near end)
            for raw in reversed(matches):
                val = _to_decimal(raw)
                if val is not None:
                    return val

    # Bare ￥ amounts: skip discount-like contexts, prefer later candidates
    for m in reversed(list(CURRENCY_RE.finditer(compact))):
        start = max(0, m.start() - 8)
        ctx = compact[start : m.start()]
        if any(x in ctx for x in ("共减", "立减", "抵", "减￥", "减¥")):
            continue
        val = _to_decimal(m.group(1))
        if val is not None:
            return val
    return None


def extract_invoice_amount(*, stored_path: str, original_name: str = "", read_pdf: bool = True) -> Decimal | None:
    """Heuristic amount from invoice PDF text and/or filename."""
    name = original_name or Path(stored_path).name
    from_name = parse_amount_from_filename(name)
    text = ""
    if read_pdf:
        try:
            path = resolve_stored(stored_path)
            if path.suffix.lower() == ".pdf" and path.exists():
                import pymupdf as fitz

                doc = fitz.open(path)
                try:
                    text = doc[0].get_text() or ""
                finally:
                    doc.close()
        except Exception:
            log.exception("failed reading invoice text path=%s", stored_path)

    from_pdf = parse_amount_from_pdf_text(text) if text else None
    # Prefer explicit filename money token when present
    chosen = from_name or from_pdf
    log.info(
        "extract amount name=%r pdf=%s filename=%s -> %s",
        name,
        from_pdf,
        from_name,
        chosen,
    )
    return chosen


def apply_auto_amount(
    conn,
    entry_id: int,
    *,
    stored_path: str,
    original_name: str,
    parsed_amount: float | None = None,
    read_pdf: bool = True,
) -> None:
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
    if parsed_amount is not None:
        val = float(parsed_amount)
    else:
        parsed = extract_invoice_amount(
            stored_path=stored_path,
            original_name=original_name,
            read_pdf=read_pdf,
        )
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

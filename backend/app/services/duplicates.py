from __future__ import annotations

from typing import Any

from .features import normalize_invoice_digits


def find_invoice_duplicate(
    conn,
    invoice_number: str | None,
    *,
    exclude_material_ids: set[int] | None = None,
    only_attached: bool = True,
) -> dict[str, Any] | None:
    """Return first existing invoice material with the same invoice_number.

    ``only_attached`` skips materials that still sit in the inbox (entry_id
    NULL): those are unconfirmed uploads, so they must not warn against
    themselves or against another pending file of the same batch.
    """
    number = normalize_invoice_digits(invoice_number)
    if not number:
        return None
    exclude = exclude_material_ids or set()
    sql = """
        SELECT m.id AS material_id, m.entry_id, m.original_name, m.mime,
               e.title AS entry_title
        FROM materials m
        LEFT JOIN entries e ON e.id = m.entry_id
        WHERE m.type = 'invoice' AND m.invoice_number = ?
    """
    if only_attached:
        sql += " AND m.entry_id IS NOT NULL"
    sql += " ORDER BY m.id ASC"
    rows = conn.execute(sql, (number,)).fetchall()
    for row in rows:
        mid = int(row["material_id"])
        if mid in exclude:
            continue
        return {
            "material_id": mid,
            "entry_id": int(row["entry_id"]) if row["entry_id"] is not None else None,
            "entry_title": row["entry_title"],
            "invoice_number": number,
            "original_name": row["original_name"],
            "mime": row["mime"] or "",
        }
    return None


def find_file_duplicate(
    conn,
    content_sha256: str | None,
    *,
    exclude_material_ids: set[int] | None = None,
    only_attached: bool = True,
) -> dict[str, Any] | None:
    """Return the first material with the same file hash (any slot type).

    An identical file is a duplicate no matter whether it is an invoice, an
    order screenshot or a payment record. This also covers invoices whose
    number cannot be parsed (scanned PDFs, other providers).
    """
    digest = (content_sha256 or "").strip()
    if not digest:
        return None
    exclude = exclude_material_ids or set()
    sql = """
        SELECT m.id AS material_id, m.entry_id, m.type, m.original_name, m.mime,
               m.invoice_number, e.title AS entry_title
        FROM materials m
        LEFT JOIN entries e ON e.id = m.entry_id
        WHERE m.content_sha256 = ?
    """
    if only_attached:
        sql += " AND m.entry_id IS NOT NULL"
    sql += " ORDER BY m.id ASC"
    for row in conn.execute(sql, (digest,)).fetchall():
        mid = int(row["material_id"])
        if mid in exclude:
            continue
        return {
            "material_id": mid,
            "entry_id": int(row["entry_id"]) if row["entry_id"] is not None else None,
            "entry_title": row["entry_title"],
            "type": row["type"],
            "invoice_number": row["invoice_number"],
            "original_name": row["original_name"],
            "mime": row["mime"] or "",
        }
    return None


def warning_from_hit(
    *,
    reason: str,
    invoice_number: str | None = None,
    hit: dict[str, Any] | None = None,
    peer_temp_id: str | None = None,
) -> dict[str, Any]:
    hit = hit or {}
    return {
        "reason": reason,
        "invoice_number": invoice_number or hit.get("invoice_number"),
        "existing_entry_id": hit.get("entry_id"),
        "existing_entry_title": hit.get("entry_title"),
        "existing_material_id": hit.get("material_id"),
        "existing_original_name": hit.get("original_name"),
        "existing_mime": hit.get("mime"),
        "existing_type": hit.get("type"),
        "peer_temp_id": peer_temp_id,
    }

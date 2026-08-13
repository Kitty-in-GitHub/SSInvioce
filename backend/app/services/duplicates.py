from __future__ import annotations

from typing import Any

from .features import normalize_invoice_digits


def find_invoice_duplicate(
    conn,
    invoice_number: str | None,
    *,
    exclude_material_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    """Return first existing invoice material with the same invoice_number."""
    number = normalize_invoice_digits(invoice_number)
    if not number:
        return None
    exclude = exclude_material_ids or set()
    rows = conn.execute(
        """
        SELECT m.id AS material_id, m.entry_id, m.original_name, m.mime,
               e.title AS entry_title
        FROM materials m
        LEFT JOIN entries e ON e.id = m.entry_id
        WHERE m.type = 'invoice' AND m.invoice_number = ?
        ORDER BY m.id ASC
        """,
        (number,),
    ).fetchall()
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
        "peer_temp_id": peer_temp_id,
    }

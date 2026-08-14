from __future__ import annotations

from typing import Any

from ..models import Completeness, DuplicateWarning, MaterialOut
from .settings_store import invoice_slot_id, required_slot_ids


def material_url(material_id: int) -> str:
    return f"/api/materials/{material_id}/file"


def completeness_from_types(types: set[str]) -> Completeness:
    required = required_slot_ids()
    missing = [sid for sid in required if sid not in types]
    inv = invoice_slot_id()
    return Completeness(
        complete=not missing,
        has_invoice=inv in types,
        has_order="order" in types,
        has_payment="payment" in types,
        missing=missing,
    )


def material_to_out(row: dict, *, duplicate_warning: dict[str, Any] | None = None) -> MaterialOut:
    warn = DuplicateWarning(**duplicate_warning) if duplicate_warning else None
    return MaterialOut(
        id=row["id"],
        entry_id=row["entry_id"],
        type=row["type"],
        original_name=row["original_name"],
        stored_path=row["stored_path"],
        mime=row["mime"] or "",
        width=row["width"],
        height=row["height"],
        created_at=row["created_at"],
        url=material_url(row["id"]),
        invoice_number=row.get("invoice_number"),
        invoice_code=row.get("invoice_code"),
        content_sha256=row.get("content_sha256"),
        duplicate_warning=warn,
    )

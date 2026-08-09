from __future__ import annotations

from ..models import Completeness, MaterialOut


def material_url(material_id: int) -> str:
    return f"/api/materials/{material_id}/file"


def completeness_from_types(types: set[str]) -> Completeness:
    has_invoice = "invoice" in types
    has_order = "order" in types
    has_payment = "payment" in types
    missing: list[str] = []
    if not has_invoice:
        missing.append("invoice")
    if not has_order:
        missing.append("order")
    if not has_payment:
        missing.append("payment")
    return Completeness(
        complete=not missing,
        has_invoice=has_invoice,
        has_order=has_order,
        has_payment=has_payment,
        missing=missing,
    )


def material_to_out(row: dict) -> MaterialOut:
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
    )

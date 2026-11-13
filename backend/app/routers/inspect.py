"""Debug inspection router: view OCR lines + extracted fields for any material.

Accessible at /api/inspect/materials (list) and /api/inspect/materials/{id} (detail).
Only enabled when OCR models are available, so endpoints are safe in production.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..services.analyze_jobs import submit_analyze
from ..services.features import feature_from_json

router = APIRouter(prefix="/api/inspect", tags=["inspect"])


@router.get("/materials")
def list_inspect_materials():
    """List ALL materials with their features_json parsed, newest first.

    Each row includes: id, entry_id, original_name, type, stored_path,
    analyze_status, invoice_number, content_sha256, and parsed features_json
    (amount, merchant, product_name, date, order_no, invoice_number,
    invoice_code, text_preview, text_source, ocr_used, ocr_lines).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, entry_id, original_name, type, stored_path,
                   analyze_status, invoice_number, content_sha256, features_json
            FROM materials
            ORDER BY id DESC
            """
        ).fetchall()
    items = []
    for r in rows:
        data = dict(r)
        feat = feature_from_json(data.pop("features_json"))
        items.append(
            {
                "id": int(data["id"]),
                "entry_id": int(data["entry_id"]) if data["entry_id"] is not None else None,
                "original_name": data["original_name"],
                "type": data["type"],
                "stored_path": data["stored_path"],
                "analyze_status": data["analyze_status"],
                "invoice_number": data["invoice_number"],
                "content_sha256": data["content_sha256"],
                "features": feat.to_public() if feat else None,
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/materials/{material_id}")
def get_inspect_material(material_id: int):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, entry_id, original_name, type, stored_path,
                   analyze_status, invoice_number, content_sha256, features_json
            FROM materials WHERE id = ?
            """,
            (material_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="material not found")
    data = dict(row)
    feat = feature_from_json(data.pop("features_json"))
    return {
        "id": int(data["id"]),
        "entry_id": int(data["entry_id"]) if data["entry_id"] is not None else None,
        "original_name": data["original_name"],
        "type": data["type"],
        "stored_path": data["stored_path"],
        "analyze_status": data["analyze_status"],
        "invoice_number": data["invoice_number"],
        "content_sha256": data["content_sha256"],
        "features": feat.to_public() if feat else None,
    }


@router.post("/materials/{material_id}/re-analyze")
def re_analyze_material(material_id: int):
    """Force re-run feature extraction on a single material.

    Clears analyze_status to 'pending' so the backend doesn't skip it,
    then submits the async analyze job. Returns immediately (job runs in
    background). Poll GET /api/inspect/materials/{id} to see new results.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        conn.execute(
            "UPDATE materials SET analyze_status = 'pending' WHERE id = ?",
            (material_id,),
        )
    submit_analyze(material_id)
    return {"ok": True, "material_id": material_id, "queued": True}

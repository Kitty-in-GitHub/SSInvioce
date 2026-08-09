from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..logging_config import get_logger
from ..services.layout import ComposeError, compose_entry_pdf

router = APIRouter(prefix="/api/entries", tags=["compose"])
log = get_logger("compose")


@router.post("/{entry_id}/compose")
def compose_entry(entry_id: int):
    with get_conn() as conn:
        entry = conn.execute("SELECT id, title FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="entry not found")
        mats = conn.execute(
            "SELECT * FROM materials WHERE entry_id = ? ORDER BY id",
            (entry_id,),
        ).fetchall()

    by_type: dict[str, list] = {"invoice": [], "order": [], "payment": []}
    for m in mats:
        if m["type"] in by_type:
            by_type[m["type"]].append(m)

    missing = [t for t, items in by_type.items() if not items]
    if missing:
        log.warning("compose blocked entry_id=%s missing=%s", entry_id, missing)
        raise HTTPException(
            status_code=400,
            detail={"message": "材料不齐套，无法拼版", "missing": missing},
        )

    try:
        out = compose_entry_pdf(
            entry_id=entry_id,
            invoice_rel=by_type["invoice"][0]["stored_path"],
            order_rel=by_type["order"][0]["stored_path"],
            payment_rel=by_type["payment"][0]["stored_path"],
        )
    except ComposeError as exc:
        log.exception("compose failed entry_id=%s", entry_id)
        raise HTTPException(status_code=400, detail={"message": str(exc), "missing": exc.missing}) from exc

    log.info("compose ok entry_id=%s path=%s size=%s", entry_id, out, out.stat().st_size)
    filename = f"{entry['title']}_拼版.pdf"
    return FileResponse(
        out,
        media_type="application/pdf",
        filename=filename,
    )

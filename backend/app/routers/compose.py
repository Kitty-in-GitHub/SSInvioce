from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..logging_config import get_logger
from ..models import ComposeBatchRequest

router = APIRouter(prefix="/api/entries", tags=["compose"])
log = get_logger("compose")


def _materials_by_type(conn, entry_id: int) -> dict[str, list]:
    mats = conn.execute(
        "SELECT * FROM materials WHERE entry_id = ? ORDER BY id",
        (entry_id,),
    ).fetchall()
    by_type: dict[str, list] = {"invoice": [], "order": [], "payment": []}
    for m in mats:
        if m["type"] in by_type:
            by_type[m["type"]].append(m)
    return by_type


def _require_complete(by_type: dict[str, list], entry_id: int, title: str) -> None:
    missing = [t for t, items in by_type.items() if not items]
    if missing:
        log.warning("compose blocked entry_id=%s title=%r missing=%s", entry_id, title, missing)
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"条目「{title}」材料不齐套，无法拼版",
                "entry_id": entry_id,
                "missing": missing,
            },
        )


@router.post("/compose-batch")
def compose_batch(body: ComposeBatchRequest):
    # Preserve request order, drop duplicates
    seen: set[int] = set()
    ordered_ids: list[int] = []
    for eid in body.entry_ids:
        if eid not in seen:
            seen.add(eid)
            ordered_ids.append(eid)

    pages: list[dict[str, str]] = []
    titles: list[str] = []
    with get_conn() as conn:
        for entry_id in ordered_ids:
            entry = conn.execute(
                "SELECT id, title FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if not entry:
                raise HTTPException(status_code=404, detail=f"entry not found: {entry_id}")
            by_type = _materials_by_type(conn, entry_id)
            _require_complete(by_type, entry_id, entry["title"])
            pages.append(
                {
                    "invoice_rel": by_type["invoice"][0]["stored_path"],
                    "order_rel": by_type["order"][0]["stored_path"],
                    "payment_rel": by_type["payment"][0]["stored_path"],
                }
            )
            titles.append(entry["title"])

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"batch_{len(pages)}entries_{stamp}.pdf"
    from ..services.layout import ComposeError, compose_batch_pdf

    try:
        out = compose_batch_pdf(pages, out_name=out_name)
    except ComposeError as exc:
        log.exception("batch compose failed ids=%s", ordered_ids)
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc

    log.info("batch compose ok count=%s titles=%s", len(pages), titles)
    filename = f"报销拼版_{len(pages)}页_{stamp}.pdf"
    return FileResponse(out, media_type="application/pdf", filename=filename)


@router.post("/{entry_id}/compose")
def compose_entry(entry_id: int):
    with get_conn() as conn:
        entry = conn.execute("SELECT id, title FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="entry not found")
        by_type = _materials_by_type(conn, entry_id)

    _require_complete(by_type, entry_id, entry["title"])

    from ..services.layout import ComposeError, compose_entry_pdf

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

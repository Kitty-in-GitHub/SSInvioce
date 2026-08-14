from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..logging_config import get_logger
from ..models import ComposeBatchRequest
from ..services.settings_store import get_layout, placed_slot_ids, required_slot_ids

router = APIRouter(prefix="/api/entries", tags=["compose"])
log = get_logger("compose")


def materials_by_slot(conn, entry_id: int) -> dict[str, str]:
    mats = conn.execute(
        "SELECT type, stored_path FROM materials WHERE entry_id = ? ORDER BY id",
        (entry_id,),
    ).fetchall()
    by_slot: dict[str, str] = {}
    for m in mats:
        sid = m["type"]
        if sid and sid != "unknown" and sid not in by_slot:
            by_slot[sid] = m["stored_path"]
    return by_slot


def require_exportable(files_by_slot: dict[str, str], entry_id: int, title: str) -> None:
    required = required_slot_ids()
    missing = [sid for sid in required if sid not in files_by_slot]
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
    unplaced = [sid for sid in required if sid not in placed_slot_ids()]
    if unplaced:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "有必填槽位尚未放入拼版画板，请到设置 → 拼版中摆放后再导出",
                "entry_id": entry_id,
                "missing": unplaced,
            },
        )


@router.post("/compose-batch")
def compose_batch(body: ComposeBatchRequest):
    seen: set[int] = set()
    ordered_ids: list[int] = []
    for eid in body.entry_ids:
        if eid not in seen:
            seen.add(eid)
            ordered_ids.append(eid)

    items: list[dict[str, str]] = []
    titles: list[str] = []
    with get_conn() as conn:
        for entry_id in ordered_ids:
            entry = conn.execute(
                "SELECT id, title FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if not entry:
                raise HTTPException(status_code=404, detail=f"entry not found: {entry_id}")
            files = materials_by_slot(conn, entry_id)
            require_exportable(files, entry_id, entry["title"])
            items.append(files)
            titles.append(entry["title"])

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"batch_{len(items)}entries_{stamp}.pdf"
    from ..services.layout import ComposeError, compose_batch_pdf

    try:
        out = compose_batch_pdf(items, out_name=out_name, layout=get_layout())
    except ComposeError as exc:
        log.exception("batch compose failed ids=%s", ordered_ids)
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc

    log.info("batch compose ok count=%s titles=%s", len(items), titles)
    filename = f"报销拼版_{len(items)}页_{stamp}.pdf"
    return FileResponse(out, media_type="application/pdf", filename=filename)


@router.post("/{entry_id}/compose")
def compose_entry(entry_id: int):
    with get_conn() as conn:
        entry = conn.execute("SELECT id, title FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="entry not found")
        files = materials_by_slot(conn, entry_id)

    require_exportable(files, entry_id, entry["title"])

    from ..services.layout import ComposeError, compose_entry_pdf

    try:
        out = compose_entry_pdf(entry_id=entry_id, files_by_slot=files, layout=get_layout())
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

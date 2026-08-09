from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn, now_iso, row_to_dict
from ..logging_config import get_logger
from ..models import EntryCreate, EntryOut, EntryUpdate
from ..services.serializers import completeness_from_types, material_to_out
from ..services.storage import delete_file

router = APIRouter(prefix="/api/entries", tags=["entries"])
log = get_logger("entries")


def _entry_payload(conn, entry_id: int, *, with_materials: bool = True) -> EntryOut:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")
    mats = conn.execute(
        "SELECT * FROM materials WHERE entry_id = ? ORDER BY id",
        (entry_id,),
    ).fetchall()
    types = {m["type"] for m in mats}
    materials = [material_to_out(dict(m)) for m in mats] if with_materials else []
    e = dict(row)
    return EntryOut(
        id=e["id"],
        title=e["title"],
        note=e["note"] or "",
        created_at=e["created_at"],
        updated_at=e["updated_at"],
        completeness=completeness_from_types(types),
        materials=materials,
    )


@router.get("", response_model=list[EntryOut])
@router.get("/", response_model=list[EntryOut], include_in_schema=False)
def list_entries():
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM entries ORDER BY id DESC").fetchall()
        log.info("list entries count=%s", len(rows))
        return [_entry_payload(conn, r["id"]) for r in rows]


@router.post("", response_model=EntryOut)
@router.post("/", response_model=EntryOut, include_in_schema=False)
def create_entry(body: EntryCreate):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    ts = now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (title, note, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, body.note or "", ts, ts),
        )
        entry_id = int(cur.lastrowid)
        log.info("created entry id=%s title=%r", entry_id, title)
        return _entry_payload(conn, entry_id)


@router.get("/{entry_id}", response_model=EntryOut)
def get_entry(entry_id: int):
    with get_conn() as conn:
        return _entry_payload(conn, entry_id)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(entry_id: int, body: EntryUpdate):
    with get_conn() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())
        if not existing:
            raise HTTPException(status_code=404, detail="entry not found")
        title = body.title.strip() if body.title is not None else existing["title"]
        note = body.note if body.note is not None else existing["note"]
        conn.execute(
            "UPDATE entries SET title = ?, note = ?, updated_at = ? WHERE id = ?",
            (title, note or "", now_iso(), entry_id),
        )
        log.info("updated entry id=%s", entry_id)
        return _entry_payload(conn, entry_id)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int):
    with get_conn() as conn:
        mats = conn.execute(
            "SELECT stored_path FROM materials WHERE entry_id = ?",
            (entry_id,),
        ).fetchall()
        cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="entry not found")
    for m in mats:
        delete_file(m["stored_path"])
    log.info("deleted entry id=%s materials=%s", entry_id, len(mats))
    return {"ok": True}

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn, now_iso, row_to_dict
from ..logging_config import get_logger
from ..models import GroupCreate, GroupOut, GroupUpdate
from ..services.forms import group_has_form
from ..services.serializers import completeness_from_types

router = APIRouter(prefix="/api/groups", tags=["groups"])
log = get_logger("groups")


def _group_stats(conn, group_id: int) -> dict:
    entries = conn.execute(
        "SELECT id, amount FROM entries WHERE group_id = ? ORDER BY id",
        (group_id,),
    ).fetchall()
    entry_count = len(entries)
    amount_sum = 0.0
    incomplete = 0
    for e in entries:
        if e["amount"] is not None:
            amount_sum += float(e["amount"])
        mats = conn.execute(
            "SELECT type FROM materials WHERE entry_id = ?",
            (e["id"],),
        ).fetchall()
        types = {m["type"] for m in mats}
        if not completeness_from_types(types).complete:
            incomplete += 1
    return {
        "entry_count": entry_count,
        "amount_sum": round(amount_sum, 2),
        "complete": entry_count > 0 and incomplete == 0,
        "incomplete_count": incomplete,
    }


def _group_payload(conn, group_id: int) -> GroupOut:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="group not found")
    g = dict(row)
    stats = _group_stats(conn, group_id)
    # empty group: complete=false for export purposes (cannot export)
    if stats["entry_count"] == 0:
        stats["complete"] = False
    return GroupOut(
        id=g["id"],
        name=g["name"],
        note=g["note"] or "",
        sort_order=g["sort_order"] or 0,
        created_at=g["created_at"],
        updated_at=g["updated_at"],
        has_form=group_has_form(g.get("form_data")),
        **stats,
    )


@router.get("", response_model=list[GroupOut])
@router.get("/", response_model=list[GroupOut], include_in_schema=False)
def list_groups():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM groups ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [_group_payload(conn, r["id"]) for r in rows]


@router.post("", response_model=GroupOut)
@router.post("/", response_model=GroupOut, include_in_schema=False)
def create_group(body: GroupCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    ts = now_iso()
    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="组名已存在")
        max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM groups").fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO groups (name, note, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, body.note or "", int(max_sort) + 1, ts, ts),
        )
        gid = int(cur.lastrowid)
        log.info("created group id=%s name=%r", gid, name)
        return _group_payload(conn, gid)


@router.get("/{group_id}", response_model=GroupOut)
def get_group(group_id: int):
    with get_conn() as conn:
        return _group_payload(conn, group_id)


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(group_id: int, body: GroupUpdate):
    with get_conn() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone())
        if not existing:
            raise HTTPException(status_code=404, detail="group not found")
        name = body.name.strip() if body.name is not None else existing["name"]
        note = body.note if body.note is not None else existing["note"]
        sort_order = body.sort_order if body.sort_order is not None else existing["sort_order"]
        if body.name is not None:
            clash = conn.execute(
                "SELECT id FROM groups WHERE name = ? AND id != ?",
                (name, group_id),
            ).fetchone()
            if clash:
                raise HTTPException(status_code=400, detail="组名已存在")
        conn.execute(
            "UPDATE groups SET name = ?, note = ?, sort_order = ?, updated_at = ? WHERE id = ?",
            (name, note or "", int(sort_order or 0), now_iso(), group_id),
        )
        log.info("updated group id=%s", group_id)
        return _group_payload(conn, group_id)


@router.delete("/{group_id}")
def delete_group(group_id: int):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="group not found")
        conn.execute("UPDATE entries SET group_id = NULL WHERE group_id = ?", (group_id,))
    log.info("deleted group id=%s", group_id)
    return {"ok": True}

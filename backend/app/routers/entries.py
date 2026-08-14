from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn, now_iso, row_to_dict
from ..logging_config import get_logger
from ..models import EntryCreate, EntryOut, EntryUpdate, ReparseAmountRequest
from ..services.amount import apply_auto_amount, extract_invoice_amount
from ..services.serializers import completeness_from_types, material_to_out
from ..services.storage import delete_stored_files
router = APIRouter(prefix="/api/entries", tags=["entries"])
log = get_logger("entries")


def _entry_payload(conn, entry_id: int, *, with_materials: bool = True) -> EntryOut:
    row = conn.execute(
        """
        SELECT e.*, g.name AS group_name
        FROM entries e
        LEFT JOIN groups g ON g.id = e.group_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")
    mats = conn.execute(
        "SELECT * FROM materials WHERE entry_id = ? ORDER BY id",
        (entry_id,),
    ).fetchall()
    types = {m["type"] for m in mats}
    materials = [material_to_out(dict(m)) for m in mats] if with_materials else []
    e = dict(row)
    source = e.get("amount_source") or "empty"
    if source not in ("auto", "manual", "empty"):
        source = "empty"
    return EntryOut(
        id=e["id"],
        title=e["title"],
        note=e["note"] or "",
        created_at=e["created_at"],
        updated_at=e["updated_at"],
        completeness=completeness_from_types(types),
        materials=materials,
        group_id=e.get("group_id"),
        group_name=e.get("group_name"),
        amount=e.get("amount"),
        amount_source=source,
        amount_auto=e.get("amount_auto"),
        expense_row=e.get("expense_row"),
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
        group_id = body.group_id
        if group_id is not None:
            g = conn.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
            if not g:
                raise HTTPException(status_code=404, detail="group not found")
        amount = body.amount
        if amount is not None:
            source = "manual"
        else:
            source = "empty"
        cur = conn.execute(
            """
            INSERT INTO entries (title, note, created_at, updated_at, group_id, amount, amount_source, amount_auto)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (title, body.note or "", ts, ts, group_id, amount, source),
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
    patch = body.model_dump(exclude_unset=True)
    with get_conn() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())
        if not existing:
            raise HTTPException(status_code=404, detail="entry not found")

        title = body.title.strip() if body.title is not None else existing["title"]
        note = body.note if body.note is not None else existing["note"]

        if body.clear_group:
            group_id = None
        elif "group_id" in patch:
            group_id = body.group_id
            if group_id is not None:
                g = conn.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
                if not g:
                    raise HTTPException(status_code=404, detail="group not found")
        else:
            group_id = existing.get("group_id")

        amount = existing.get("amount")
        amount_source = existing.get("amount_source") or "empty"
        amount_auto = existing.get("amount_auto")
        if "amount" in patch:
            amount = body.amount
            if amount is None:
                amount_source = "empty"
            else:
                amount_source = "manual"

        if body.clear_expense_row:
            expense_row = None
        elif "expense_row" in patch:
            expense_row = (body.expense_row or "").strip() or None
        else:
            expense_row = existing.get("expense_row")

        conn.execute(
            """
            UPDATE entries
            SET title = ?, note = ?, group_id = ?, amount = ?, amount_source = ?, amount_auto = ?, expense_row = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title,
                note or "",
                group_id,
                amount,
                amount_source,
                amount_auto,
                expense_row,
                now_iso(),
                entry_id,
            ),
        )
        log.info("updated entry id=%s", entry_id)
        return _entry_payload(conn, entry_id)


@router.post("/{entry_id}/reparse-amount", response_model=EntryOut)
def reparse_amount(entry_id: int, body: ReparseAmountRequest | None = None):
    force = bool(body.force) if body else False
    with get_conn() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())
        if not existing:
            raise HTTPException(status_code=404, detail="entry not found")
        if (existing.get("amount_source") or "empty") == "manual" and not force:
            raise HTTPException(
                status_code=400,
                detail="金额已手改，如需覆盖请传 force=true",
            )
        inv = conn.execute(
            "SELECT stored_path, original_name FROM materials WHERE entry_id = ? AND type = 'invoice' ORDER BY id LIMIT 1",
            (entry_id,),
        ).fetchone()
        if not inv:
            raise HTTPException(status_code=400, detail="无发票，无法识别金额")
        parsed = extract_invoice_amount(
            stored_path=inv["stored_path"],
            original_name=inv["original_name"],
        )
        if parsed is None:
            raise HTTPException(status_code=400, detail="未能识别金额")
        val = float(parsed)
        conn.execute(
            """
            UPDATE entries
            SET amount = ?, amount_auto = ?, amount_source = 'auto', updated_at = ?
            WHERE id = ?
            """,
            (val, val, now_iso(), entry_id),
        )
        log.info("reparsed amount entry_id=%s amount=%s force=%s", entry_id, val, force)
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
    delete_stored_files([m["stored_path"] for m in mats])
    log.info("deleted entry id=%s materials=%s", entry_id, len(mats))
    return {"ok": True}

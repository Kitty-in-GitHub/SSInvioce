from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, now_iso, row_to_dict
from ..logging_config import get_logger
from ..models import AssetCreate, AssetOut, AssetTxnCreate, AssetTxnOut, AssetUpdate

router = APIRouter(prefix="/api/assets", tags=["assets"])
log = get_logger("assets")


def _qty(val: Any) -> float:
    return round(float(val or 0), 4)


def _today() -> str:
    return date.today().isoformat()


def _parse_on(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return _today()
    text = str(raw).strip()[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    return text


def _borrowed_qty(conn, asset_id: int) -> float:
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN action = 'borrow' THEN qty ELSE 0 END), 0)
        - COALESCE(SUM(CASE WHEN action = 'return' THEN qty ELSE 0 END), 0) AS b
        FROM asset_txns WHERE asset_id = ?
        """,
        (asset_id,),
    ).fetchone()
    return max(0.0, _qty(row["b"] if row else 0))


def _asset_out(conn, asset_id: int) -> AssetOut:
    row = conn.execute(
        """
        SELECT a.*, e.title AS entry_title
        FROM assets a
        LEFT JOIN entries e ON e.id = a.entry_id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="物品不存在")
    a = dict(row)
    return AssetOut(
        id=a["id"],
        kind=a["kind"],
        name=a["name"],
        qty=_qty(a["qty"]),
        unit=a["unit"] or "",
        location=a["location"] or "",
        note=a["note"] or "",
        entry_id=a.get("entry_id"),
        entry_title=a.get("entry_title"),
        borrowed_qty=_borrowed_qty(conn, asset_id),
        created_at=a["created_at"],
        updated_at=a["updated_at"],
    )


def _require_entry(conn, entry_id: int | None) -> None:
    if entry_id is None:
        return
    if not conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone():
        raise HTTPException(status_code=404, detail="entry not found")


@router.get("", response_model=list[AssetOut])
@router.get("/", response_model=list[AssetOut], include_in_schema=False)
def list_assets(kind: Optional[str] = Query(default=None)):
    clauses = ["1=1"]
    args: list[Any] = []
    if kind in ("durable", "consumable"):
        clauses.append("a.kind = ?")
        args.append(kind)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT a.id FROM assets a WHERE {' AND '.join(clauses)} ORDER BY a.name COLLATE NOCASE, a.id",
            args,
        ).fetchall()
        return [_asset_out(conn, r["id"]) for r in rows]


@router.post("", response_model=AssetOut)
@router.post("/", response_model=AssetOut, include_in_schema=False)
def create_asset(body: AssetCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写名称")
    qty = _qty(body.qty)
    if qty < 0:
        raise HTTPException(status_code=400, detail="数量不能为负")
    ts = now_iso()
    with get_conn() as conn:
        _require_entry(conn, body.entry_id)
        cur = conn.execute(
            """
            INSERT INTO assets (kind, name, qty, unit, location, note, entry_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.kind,
                name,
                qty,
                (body.unit or "").strip(),
                (body.location or "").strip(),
                body.note or "",
                body.entry_id,
                ts,
                ts,
            ),
        )
        aid = int(cur.lastrowid)
        if qty > 0:
            conn.execute(
                """
                INSERT INTO asset_txns (asset_id, action, qty, person, occurred_on, note, created_at)
                VALUES (?, 'in', ?, '', ?, '登记入库', ?)
                """,
                (aid, qty, _today(), ts),
            )
        log.info("asset created id=%s kind=%s name=%r qty=%s", aid, body.kind, name, qty)
        return _asset_out(conn, aid)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int):
    with get_conn() as conn:
        return _asset_out(conn, asset_id)


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, body: AssetUpdate):
    patch = body.model_dump(exclude_unset=True)
    with get_conn() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone())
        if not existing:
            raise HTTPException(status_code=404, detail="物品不存在")
        name = body.name.strip() if body.name is not None else existing["name"]
        if not name:
            raise HTTPException(status_code=400, detail="请填写名称")
        unit = body.unit.strip() if body.unit is not None else existing["unit"]
        location = body.location.strip() if body.location is not None else existing["location"]
        note = body.note if body.note is not None else existing["note"]
        if body.clear_entry:
            entry_id = None
        elif "entry_id" in patch:
            entry_id = body.entry_id
            _require_entry(conn, entry_id)
        else:
            entry_id = existing.get("entry_id")
        conn.execute(
            """
            UPDATE assets SET name = ?, unit = ?, location = ?, note = ?, entry_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, unit or "", location or "", note or "", entry_id, now_iso(), asset_id),
        )
        return _asset_out(conn, asset_id)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="物品不存在")
        if _borrowed_qty(conn, asset_id) > 0:
            raise HTTPException(status_code=400, detail="仍有未归还的借出，无法删除")
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    log.info("asset deleted id=%s", asset_id)
    return {"ok": True}


@router.get("/{asset_id}/txns", response_model=list[AssetTxnOut])
def list_asset_txns(asset_id: int):
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone():
            raise HTTPException(status_code=404, detail="物品不存在")
        rows = conn.execute(
            "SELECT * FROM asset_txns WHERE asset_id = ? ORDER BY occurred_on DESC, id DESC",
            (asset_id,),
        ).fetchall()
        return [AssetTxnOut(**dict(r)) for r in rows]


@router.post("/{asset_id}/txns", response_model=AssetOut)
def create_asset_txn(asset_id: int, body: AssetTxnCreate):
    qty = _qty(body.qty)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="数量须大于 0")
    person = (body.person or "").strip()
    occurred_on = _parse_on(body.occurred_on)
    note = body.note or ""
    ts = now_iso()
    with get_conn() as conn:
        asset = row_to_dict(conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone())
        if not asset:
            raise HTTPException(status_code=404, detail="物品不存在")
        kind = asset["kind"]
        on_hand = _qty(asset["qty"])
        borrowed = _borrowed_qty(conn, asset_id)
        action = body.action
        new_qty = on_hand

        if action == "in":
            new_qty = on_hand + qty
        elif action == "out":
            if kind != "consumable":
                raise HTTPException(status_code=400, detail="领用仅适用于消耗品，耐用品请用借出")
            if qty > on_hand:
                raise HTTPException(status_code=400, detail="库存不足")
            new_qty = on_hand - qty
        elif action == "borrow":
            if kind != "durable":
                raise HTTPException(status_code=400, detail="借出仅适用于耐用品")
            if not person:
                raise HTTPException(status_code=400, detail="请填写借用人")
            if qty > on_hand:
                raise HTTPException(status_code=400, detail="在库数量不足")
            new_qty = on_hand - qty
        elif action == "return":
            if kind != "durable":
                raise HTTPException(status_code=400, detail="归还仅适用于耐用品")
            if qty > borrowed:
                raise HTTPException(status_code=400, detail="归还数量超过未还件数")
            new_qty = on_hand + qty
        elif action == "adjust":
            new_qty = qty
            qty = abs(new_qty - on_hand) or qty
        else:
            raise HTTPException(status_code=400, detail="未知操作")

        if new_qty < 0:
            raise HTTPException(status_code=400, detail="库存不能为负")

        conn.execute(
            """
            INSERT INTO asset_txns (asset_id, action, qty, person, occurred_on, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (asset_id, action, _qty(body.qty if action != "adjust" else qty), person, occurred_on, note, ts),
        )
        conn.execute(
            "UPDATE assets SET qty = ?, updated_at = ? WHERE id = ?",
            (_qty(new_qty), ts, asset_id),
        )
        log.info("asset txn asset_id=%s action=%s qty=%s", asset_id, action, body.qty)
        return _asset_out(conn, asset_id)

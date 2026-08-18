from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn, now_iso, row_to_dict
from ..logging_config import get_logger
from ..models import (
    LedgerCategoryCreate,
    LedgerCategoryOut,
    LedgerCategoryUpdate,
    LedgerFromEntry,
    LedgerSummary,
    LedgerTxnCreate,
    LedgerTxnOut,
    LedgerTxnUpdate,
)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
log = get_logger("ledger")

_CAT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _money(val: Any) -> float:
    return round(float(val or 0), 2)


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


def _require_category(conn, category_id: str, kind: str | None = None) -> dict:
    row = row_to_dict(
        conn.execute("SELECT * FROM ledger_categories WHERE id = ?", (category_id,)).fetchone()
    )
    if not row:
        raise HTTPException(status_code=400, detail="科目不存在")
    if kind and row["kind"] != kind:
        raise HTTPException(status_code=400, detail="科目类型与收支不符")
    return row


def _require_group(conn, group_id: int | None) -> None:
    if group_id is None:
        return
    g = conn.execute("SELECT id FROM groups WHERE id = ?", (group_id,)).fetchone()
    if not g:
        raise HTTPException(status_code=404, detail="group not found")


def _txn_out(conn, txn_id: int) -> LedgerTxnOut:
    row = conn.execute(
        """
        SELECT t.*, c.name AS category_name, g.name AS group_name, e.title AS entry_title
        FROM ledger_txns t
        JOIN ledger_categories c ON c.id = t.category_id
        LEFT JOIN groups g ON g.id = t.group_id
        LEFT JOIN entries e ON e.id = t.entry_id
        WHERE t.id = ?
        """,
        (txn_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="流水不存在")
    t = dict(row)
    return LedgerTxnOut(
        id=t["id"],
        kind=t["kind"],
        amount=_money(t["amount"]),
        occurred_on=t["occurred_on"],
        title=t["title"],
        note=t["note"] or "",
        group_id=t.get("group_id"),
        group_name=t.get("group_name"),
        category_id=t["category_id"],
        category_name=t["category_name"],
        entry_id=t.get("entry_id"),
        entry_title=t.get("entry_title"),
        created_at=t["created_at"],
    )


def _insert_txn(
    conn,
    *,
    kind: str,
    amount: float,
    occurred_on: str,
    title: str,
    note: str,
    group_id: int | None,
    category_id: str,
    entry_id: int | None,
) -> int:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="金额须大于 0")
    _require_category(conn, category_id, kind)
    _require_group(conn, group_id)
    cur = conn.execute(
        """
        INSERT INTO ledger_txns
            (kind, amount, occurred_on, title, note, group_id, category_id, entry_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            _money(amount),
            occurred_on,
            title.strip(),
            note or "",
            group_id,
            category_id,
            entry_id,
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


@router.get("/summary", response_model=LedgerSummary)
def ledger_summary():
    with get_conn() as conn:
        income = _money(
            conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM ledger_txns WHERE kind = 'income'"
            ).fetchone()["s"]
        )
        expense = _money(
            conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM ledger_txns WHERE kind = 'expense'"
            ).fetchone()["s"]
        )
        groups = conn.execute(
            "SELECT id, name, budget FROM groups ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        exp_by_g = {
            r["group_id"]: _money(r["s"])
            for r in conn.execute(
                """
                SELECT group_id, COALESCE(SUM(amount), 0) AS s
                FROM ledger_txns WHERE kind = 'expense'
                GROUP BY group_id
                """
            ).fetchall()
        }
        inc_by_g = {
            r["group_id"]: _money(r["s"])
            for r in conn.execute(
                """
                SELECT group_id, COALESCE(SUM(amount), 0) AS s
                FROM ledger_txns WHERE kind = 'income'
                GROUP BY group_id
                """
            ).fetchall()
        }
        by_group = []
        for g in groups:
            gid = g["id"]
            budget = g["budget"]
            exp = _money(exp_by_g.get(gid, 0))
            inc = _money(inc_by_g.get(gid, 0))
            remaining = None if budget is None else _money(float(budget) - exp)
            by_group.append(
                {
                    "group_id": gid,
                    "group_name": g["name"],
                    "budget": None if budget is None else _money(budget),
                    "expense_sum": exp,
                    "income_sum": inc,
                    "remaining": remaining,
                }
            )
        ungrouped_exp = _money(exp_by_g.get(None, 0))
        ungrouped_inc = _money(inc_by_g.get(None, 0))
        if ungrouped_exp or ungrouped_inc:
            by_group.append(
                {
                    "group_id": None,
                    "group_name": "未分组",
                    "budget": None,
                    "expense_sum": ungrouped_exp,
                    "income_sum": ungrouped_inc,
                    "remaining": None,
                }
            )
        by_category = []
        cats = conn.execute(
            "SELECT id, kind, name, sort_order FROM ledger_categories ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        sums = {
            r["category_id"]: _money(r["s"])
            for r in conn.execute(
                "SELECT category_id, COALESCE(SUM(amount), 0) AS s FROM ledger_txns GROUP BY category_id"
            ).fetchall()
        }
        for c in cats:
            by_category.append(
                {
                    "category_id": c["id"],
                    "kind": c["kind"],
                    "name": c["name"],
                    "amount_sum": _money(sums.get(c["id"], 0)),
                }
            )
        return LedgerSummary(
            income_sum=income,
            expense_sum=expense,
            balance=_money(income - expense),
            by_group=by_group,
            by_category=by_category,
        )


@router.get("/txns", response_model=list[LedgerTxnOut])
def list_txns(
    kind: Optional[str] = None,
    group_id: Optional[int] = None,
    ungrouped: bool = False,
    category_id: Optional[str] = None,
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
):
    clauses = ["1=1"]
    args: list[Any] = []
    if kind in ("income", "expense"):
        clauses.append("t.kind = ?")
        args.append(kind)
    if category_id:
        clauses.append("t.category_id = ?")
        args.append(category_id)
    if ungrouped:
        clauses.append("t.group_id IS NULL")
    elif group_id is not None:
        clauses.append("t.group_id = ?")
        args.append(group_id)
    if date_from:
        clauses.append("t.occurred_on >= ?")
        args.append(_parse_on(date_from))
    if date_to:
        clauses.append("t.occurred_on <= ?")
        args.append(_parse_on(date_to))
    where = " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT t.id FROM ledger_txns t
            WHERE {where}
            ORDER BY t.occurred_on DESC, t.id DESC
            """,
            args,
        ).fetchall()
        return [_txn_out(conn, r["id"]) for r in rows]


@router.post("/txns", response_model=LedgerTxnOut)
def create_txn(body: LedgerTxnCreate):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="请填写摘要")
    with get_conn() as conn:
        tid = _insert_txn(
            conn,
            kind=body.kind,
            amount=body.amount,
            occurred_on=_parse_on(body.occurred_on),
            title=title,
            note=body.note or "",
            group_id=body.group_id,
            category_id=body.category_id,
            entry_id=None,
        )
        log.info("ledger txn created id=%s kind=%s amount=%s", tid, body.kind, body.amount)
        return _txn_out(conn, tid)


@router.patch("/txns/{txn_id}", response_model=LedgerTxnOut)
def update_txn(txn_id: int, body: LedgerTxnUpdate):
    with get_conn() as conn:
        existing = row_to_dict(
            conn.execute("SELECT * FROM ledger_txns WHERE id = ?", (txn_id,)).fetchone()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="流水不存在")
        from_entry = existing.get("entry_id") is not None
        amount = existing["amount"]
        if body.amount is not None:
            if body.amount <= 0:
                raise HTTPException(status_code=400, detail="金额须大于 0")
            amount = _money(body.amount)
        occurred_on = _parse_on(body.occurred_on) if body.occurred_on is not None else existing["occurred_on"]
        title = body.title.strip() if body.title is not None else existing["title"]
        if not title:
            raise HTTPException(status_code=400, detail="请填写摘要")
        note = body.note if body.note is not None else existing["note"]
        if body.clear_group:
            group_id = None
        elif body.group_id is not None:
            group_id = body.group_id
        else:
            group_id = existing.get("group_id")
        category_id = body.category_id or existing["category_id"]
        kind = existing["kind"]
        if from_entry:
            # Snapshot amount stays unless explicitly changed; kind stays expense.
            pass
        _require_category(conn, category_id, kind)
        _require_group(conn, group_id)
        conn.execute(
            """
            UPDATE ledger_txns
            SET amount = ?, occurred_on = ?, title = ?, note = ?, group_id = ?, category_id = ?
            WHERE id = ?
            """,
            (amount, occurred_on, title, note or "", group_id, category_id, txn_id),
        )
        log.info("ledger txn updated id=%s", txn_id)
        return _txn_out(conn, txn_id)


@router.delete("/txns/{txn_id}")
def delete_txn(txn_id: int):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM ledger_txns WHERE id = ?", (txn_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="流水不存在")
    log.info("ledger txn deleted id=%s", txn_id)
    return {"ok": True}


@router.post("/from-entry/{entry_id}", response_model=LedgerTxnOut)
def from_entry(entry_id: int, body: LedgerFromEntry | None = None):
    body = body or LedgerFromEntry()
    with get_conn() as conn:
        entry = row_to_dict(
            conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        )
        if not entry:
            raise HTTPException(status_code=404, detail="entry not found")
        dup = conn.execute(
            "SELECT id FROM ledger_txns WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="该条目已入账")
        amount = entry.get("amount")
        if amount is None or float(amount) <= 0:
            raise HTTPException(status_code=400, detail="条目没有可入账的金额")
        if body.clear_group:
            group_id = None
        elif body.group_id is not None:
            group_id = body.group_id
        else:
            group_id = entry.get("group_id")
        cat_id = body.category_id or entry.get("expense_row") or "other"
        cat = row_to_dict(
            conn.execute("SELECT * FROM ledger_categories WHERE id = ?", (cat_id,)).fetchone()
        )
        if not cat or cat["kind"] != "expense":
            cat_id = "other"
            _require_category(conn, cat_id, "expense")
        note = (body.note or "").strip() or (entry.get("note") or "")
        tid = _insert_txn(
            conn,
            kind="expense",
            amount=float(amount),
            occurred_on=_parse_on(body.occurred_on),
            title=entry["title"],
            note=note,
            group_id=group_id,
            category_id=cat_id,
            entry_id=entry_id,
        )
        log.info("ledger from entry id=%s txn=%s amount=%s", entry_id, tid, amount)
        return _txn_out(conn, tid)


@router.get("/categories", response_model=list[LedgerCategoryOut])
def list_categories():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ledger_categories ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [LedgerCategoryOut(**dict(r)) for r in rows]


@router.post("/categories", response_model=LedgerCategoryOut)
def create_category(body: LedgerCategoryCreate):
    cid = body.id.strip()
    if not _CAT_ID_RE.match(cid):
        raise HTTPException(status_code=400, detail="科目 ID 须为小写字母开头的字母数字下划线")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写科目名称")
    with get_conn() as conn:
        if conn.execute("SELECT id FROM ledger_categories WHERE id = ?", (cid,)).fetchone():
            raise HTTPException(status_code=400, detail="科目 ID 已存在")
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM ledger_categories WHERE kind = ?",
            (body.kind,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO ledger_categories (id, kind, name, sort_order) VALUES (?, ?, ?, ?)",
            (cid, body.kind, name, int(max_sort) + 10),
        )
        log.info("ledger category created id=%s", cid)
        row = conn.execute("SELECT * FROM ledger_categories WHERE id = ?", (cid,)).fetchone()
        return LedgerCategoryOut(**dict(row))


@router.patch("/categories/{category_id}", response_model=LedgerCategoryOut)
def update_category(category_id: str, body: LedgerCategoryUpdate):
    with get_conn() as conn:
        existing = row_to_dict(
            conn.execute("SELECT * FROM ledger_categories WHERE id = ?", (category_id,)).fetchone()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="科目不存在")
        name = body.name.strip() if body.name is not None else existing["name"]
        sort_order = body.sort_order if body.sort_order is not None else existing["sort_order"]
        conn.execute(
            "UPDATE ledger_categories SET name = ?, sort_order = ? WHERE id = ?",
            (name, int(sort_order or 0), category_id),
        )
        row = conn.execute("SELECT * FROM ledger_categories WHERE id = ?", (category_id,)).fetchone()
        return LedgerCategoryOut(**dict(row))


@router.delete("/categories/{category_id}")
def delete_category(category_id: str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM ledger_categories WHERE id = ?", (category_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="科目不存在")
        used = conn.execute(
            "SELECT COUNT(*) AS c FROM ledger_txns WHERE category_id = ?",
            (category_id,),
        ).fetchone()["c"]
        if used:
            raise HTTPException(status_code=400, detail="该科目已有流水，无法删除")
        conn.execute("DELETE FROM ledger_categories WHERE id = ?", (category_id,))
    log.info("ledger category deleted id=%s", category_id)
    return {"ok": True}

"""Keep reimbursement-linked ledger rows in sync with their entries."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger

log = get_logger("ledger")


def _money(val: Any) -> float:
    return round(float(val), 2)


def sync_entry_ledger(conn, entry_id: int) -> None:
    """Update or drop the ledger txn linked to this entry.

    Amount, title, and group follow the entry. Expense-row maps to category when
    that subject still exists. Clearing a non-positive amount removes the txn.
    """
    txn = conn.execute(
        "SELECT id, category_id FROM ledger_txns WHERE entry_id = ?",
        (entry_id,),
    ).fetchone()
    if not txn:
        return
    entry = conn.execute(
        "SELECT title, amount, group_id, expense_row FROM entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not entry:
        conn.execute("DELETE FROM ledger_txns WHERE entry_id = ?", (entry_id,))
        log.info("ledger unlink missing entry_id=%s", entry_id)
        return
    amount = entry["amount"]
    if amount is None or float(amount) <= 0:
        conn.execute("DELETE FROM ledger_txns WHERE entry_id = ?", (entry_id,))
        log.info("ledger unlink empty amount entry_id=%s", entry_id)
        return
    category_id = txn["category_id"]
    row_id = (entry["expense_row"] or "").strip()
    if row_id:
        cat = conn.execute(
            "SELECT id FROM ledger_categories WHERE id = ? AND kind = 'expense'",
            (row_id,),
        ).fetchone()
        if cat:
            category_id = row_id
    conn.execute(
        """
        UPDATE ledger_txns
        SET amount = ?, title = ?, group_id = ?, category_id = ?
        WHERE entry_id = ?
        """,
        (_money(amount), entry["title"], entry["group_id"], category_id, entry_id),
    )
    log.info("ledger sync entry_id=%s txn_id=%s amount=%s", entry_id, txn["id"], amount)


def delete_entry_ledger(conn, entry_id: int) -> None:
    conn.execute("DELETE FROM ledger_txns WHERE entry_id = ?", (entry_id,))

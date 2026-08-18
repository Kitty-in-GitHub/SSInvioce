from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH, ensure_dirs


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] if isinstance(r, sqlite3.Row) else r[1] for r in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def init_db() -> None:
    ensure_dirs()
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                note TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER,
                type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime TEXT NOT NULL DEFAULT '',
                width INTEGER,
                height INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_materials_entry_id ON materials(entry_id);
            CREATE INDEX IF NOT EXISTS idx_materials_type ON materials(type);
            CREATE INDEX IF NOT EXISTS idx_groups_sort ON groups(sort_order, id);

            CREATE TABLE IF NOT EXISTS ledger_categories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ledger_txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                occurred_on TEXT NOT NULL,
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                group_id INTEGER,
                category_id TEXT NOT NULL,
                entry_id INTEGER UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL,
                FOREIGN KEY(category_id) REFERENCES ledger_categories(id),
                FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ledger_txns_occurred ON ledger_txns(occurred_on, id);
            CREATE INDEX IF NOT EXISTS idx_ledger_txns_group ON ledger_txns(group_id);
            CREATE INDEX IF NOT EXISTS idx_ledger_txns_category ON ledger_txns(category_id);

            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                qty REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                entry_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS asset_txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                qty REAL NOT NULL,
                person TEXT NOT NULL DEFAULT '',
                occurred_on TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
            CREATE INDEX IF NOT EXISTS idx_asset_txns_asset ON asset_txns(asset_id, id);
            """
        )
        _ensure_column(conn, "entries", "group_id", "INTEGER")
        _ensure_column(conn, "entries", "amount", "REAL")
        _ensure_column(conn, "entries", "amount_source", "TEXT NOT NULL DEFAULT 'empty'")
        _ensure_column(conn, "entries", "amount_auto", "REAL")
        _ensure_column(conn, "entries", "expense_row", "TEXT")
        _ensure_column(conn, "groups", "form_data", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "groups", "budget", "REAL")
        _ensure_column(conn, "materials", "invoice_number", "TEXT")
        _ensure_column(conn, "materials", "invoice_code", "TEXT")
        _ensure_column(conn, "materials", "content_sha256", "TEXT")
        _ensure_column(conn, "materials", "analyze_status", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_group_id ON entries(group_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_materials_invoice_number ON materials(invoice_number)"
        )
        _seed_ledger_categories(conn)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def now_iso() -> str:
    return _utc_now()


_LEDGER_CATEGORY_SEEDS: tuple[tuple[str, str, str, int], ...] = (
    ("grant", "income", "拨款", 10),
    ("sponsor", "income", "赞助", 20),
    ("dues", "income", "会费", 30),
    ("other_income", "income", "其它收入", 40),
    ("materials", "expense", "材料费", 110),
    ("rental", "expense", "租赁费", 120),
    ("traffic", "expense", "交通费", 130),
    ("printing", "expense", "资料、印刷费", 140),
    ("venue", "expense", "场租费", 150),
    ("meals", "expense", "工作餐、食品", 160),
    ("souvenirs", "expense", "奖品、纪念品", 170),
    ("expert", "expense", "专家评审费、讲课费", 180),
    ("small_prize", "expense", "小额奖品", 190),
    ("contest_prize", "expense", "比赛奖金", 200),
    ("other", "expense", "其他", 210),
)


def _seed_ledger_categories(conn: sqlite3.Connection) -> None:
    existing = {r["id"] for r in conn.execute("SELECT id FROM ledger_categories").fetchall()}
    for cid, kind, name, sort_order in _LEDGER_CATEGORY_SEEDS:
        if cid in existing:
            continue
        conn.execute(
            "INSERT INTO ledger_categories (id, kind, name, sort_order) VALUES (?, ?, ?, ?)",
            (cid, kind, name, sort_order),
        )

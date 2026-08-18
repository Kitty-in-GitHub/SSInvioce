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
            """
        )
        _ensure_column(conn, "entries", "group_id", "INTEGER")
        _ensure_column(conn, "entries", "amount", "REAL")
        _ensure_column(conn, "entries", "amount_source", "TEXT NOT NULL DEFAULT 'empty'")
        _ensure_column(conn, "entries", "amount_auto", "REAL")
        _ensure_column(conn, "entries", "expense_row", "TEXT")
        _ensure_column(conn, "groups", "form_data", "TEXT NOT NULL DEFAULT '{}'")
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

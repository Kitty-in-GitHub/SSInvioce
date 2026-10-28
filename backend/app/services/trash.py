"""Recycle bin: soft-delete materials into data/trash, restore or purge them."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from .storage import move_to_trash, purge_trash_file, restore_from_trash

log = get_logger("trash")

TRASH_RETENTION_DAYS = 30


class TrashError(Exception):
    pass


def _entry_title(conn, entry_id: int | None) -> str | None:
    if entry_id is None:
        return None
    row = conn.execute("SELECT title FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return row["title"] if row else None


def trash_material(conn, row: dict, *, reason: str, batch_id: str | None = None) -> bool:
    """Move one material's file into the trash and record a row. Returns success."""
    moved = move_to_trash(row.get("stored_path") or "")
    if moved is None:
        return False
    entry_id = row.get("entry_id")
    conn.execute(
        """
        INSERT INTO trash (
            batch_id, trash_path, original_path, entry_id, entry_title, type,
            original_name, mime, width, height, size, original_created_at,
            deleted_at, reason, invoice_number, invoice_code, content_sha256, features_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id or uuid.uuid4().hex,
            moved["trash_path"],
            row.get("stored_path") or "",
            entry_id,
            row.get("entry_title") or _entry_title(conn, entry_id),
            row.get("type") or "unknown",
            row.get("original_name") or "",
            row.get("mime") or "",
            row.get("width"),
            row.get("height"),
            moved["size"],
            row.get("created_at"),
            now_iso(),
            reason,
            row.get("invoice_number"),
            row.get("invoice_code"),
            row.get("content_sha256"),
            row.get("features_json"),
        ),
    )
    return True


def trash_materials(conn, rows, *, reason: str, batch_id: str | None = None) -> int:
    bid = batch_id or uuid.uuid4().hex
    count = 0
    for row in rows:
        if trash_material(conn, dict(row), reason=reason, batch_id=bid):
            count += 1
    return count


def list_trash() -> dict:
    with get_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM trash ORDER BY deleted_at DESC, id DESC"
            ).fetchall()
        ]
    groups: list[dict] = []
    by_batch: dict[str, dict] = {}
    for row in rows:
        group = by_batch.get(row["batch_id"])
        if group is None:
            group = {
                "batch_id": row["batch_id"],
                "deleted_at": row["deleted_at"],
                "reason": row["reason"],
                "entry_id": row["entry_id"],
                "entry_title": row["entry_title"],
                "items": [],
            }
            by_batch[row["batch_id"]] = group
            groups.append(group)
        group["items"].append(
            {
                "id": int(row["id"]),
                "original_name": row["original_name"],
                "type": row["type"],
                "mime": row["mime"],
                "size": row["size"],
                "deleted_at": row["deleted_at"],
                "entry_id": row["entry_id"],
                "entry_title": row["entry_title"],
            }
        )
    return {"count": len(rows), "groups": groups}


def restore(ids: list[int]) -> list[dict]:
    """Restore trashed materials. Prefers the original entry when its slot is free."""
    results: list[dict] = []
    with get_conn() as conn:
        for trash_id in ids:
            row = conn.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
            if not row:
                results.append({"id": trash_id, "ok": False, "error": "回收站记录不存在"})
                continue
            data = dict(row)
            target_entry: int | None = None
            if data["entry_id"] is not None:
                entry = conn.execute(
                    "SELECT id FROM entries WHERE id = ?", (data["entry_id"],)
                ).fetchone()
                if entry:
                    taken = conn.execute(
                        "SELECT 1 FROM materials WHERE entry_id = ? AND type = ? LIMIT 1",
                        (data["entry_id"], data["type"]),
                    ).fetchone()
                    if not taken:
                        target_entry = int(data["entry_id"])

            rel = restore_from_trash(data["trash_path"], data["original_name"], target_entry)
            if rel is None:
                results.append({"id": trash_id, "ok": False, "error": "文件已丢失，无法恢复"})
                continue

            ts = now_iso()
            cur = conn.execute(
                """
                INSERT INTO materials (
                    entry_id, type, original_name, stored_path, mime, width, height, created_at,
                    invoice_number, invoice_code, content_sha256, analyze_status, features_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?)
                """,
                (
                    target_entry,
                    data["type"],
                    data["original_name"],
                    rel,
                    data["mime"],
                    data["width"],
                    data["height"],
                    ts,
                    data["invoice_number"],
                    data["invoice_code"],
                    data["content_sha256"],
                    data["features_json"],
                ),
            )
            material_id = int(cur.lastrowid)
            if target_entry is not None:
                conn.execute(
                    "UPDATE entries SET updated_at = ? WHERE id = ?", (ts, target_entry)
                )
            conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
            results.append(
                {
                    "id": trash_id,
                    "ok": True,
                    "material_id": material_id,
                    "restored_to": "entry" if target_entry is not None else "inbox",
                    "entry_id": target_entry,
                    "entry_title": data["entry_title"],
                }
            )
    if results:
        log.info("trash restore requested=%s ok=%s", len(ids), sum(1 for r in results if r["ok"]))
    return results


def purge(ids: list[int]) -> int:
    removed = 0
    with get_conn() as conn:
        for trash_id in ids:
            row = conn.execute("SELECT trash_path FROM trash WHERE id = ?", (trash_id,)).fetchone()
            if not row:
                continue
            purge_trash_file(row["trash_path"])
            conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
            removed += 1
    if removed:
        log.info("trash purged=%s", removed)
    return removed


def purge_all() -> int:
    with get_conn() as conn:
        ids = [int(r["id"]) for r in conn.execute("SELECT id FROM trash").fetchall()]
    return purge(ids)


def cleanup(days: int = TRASH_RETENTION_DAYS) -> int:
    """Drop trash entries older than the retention window (files included)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    with get_conn() as conn:
        ids = [
            int(r["id"])
            for r in conn.execute("SELECT id FROM trash WHERE deleted_at < ?", (cutoff,)).fetchall()
        ]
    if not ids:
        return 0
    removed = purge(ids)
    log.info("trash cleanup days=%s removed=%s", days, removed)
    return removed

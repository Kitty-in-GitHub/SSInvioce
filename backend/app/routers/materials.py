from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from ..models import MaterialAssign, MaterialOut, MaterialType, MaterialTypeUpdate
from ..services.classify import classify_file
from ..services.serializers import material_to_out
from ..services.storage import delete_file, move_inbox_to_entry, probe_image_size, resolve_stored, store_upload

router = APIRouter(prefix="/api/materials", tags=["materials"])
log = get_logger("materials")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _guess_mime(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


@router.get("/inbox", response_model=list[MaterialOut])
def list_inbox():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM materials WHERE entry_id IS NULL ORDER BY id DESC"
        ).fetchall()
        return [material_to_out(dict(r)) for r in rows]


@router.post("/upload", response_model=MaterialOut)
async def upload_material(
    file: UploadFile = File(...),
    entry_id: int | None = Form(default=None),
    type: MaterialType | None = Form(default=None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix}")

    if entry_id is not None:
        with get_conn() as conn:
            exists = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="entry not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    rel, abs_path = store_upload(content, file.filename, entry_id=entry_id)
    width = height = None
    if suffix != ".pdf":
        width, height = probe_image_size(abs_path)

    mat_type = type or classify_file(file.filename, width=width, height=height)
    mime = _guess_mime(file.filename, file.content_type)
    ts = now_iso()

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO materials (entry_id, type, original_name, stored_path, mime, width, height, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, mat_type, file.filename, rel, mime, width, height, ts),
        )
        mid = int(cur.lastrowid)
        if entry_id is not None:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (ts, entry_id))
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
        log.info(
            "uploaded material id=%s type=%s entry_id=%s name=%r bytes=%s",
            mid,
            mat_type,
            entry_id,
            file.filename,
            len(content),
        )
        return material_to_out(dict(row))


@router.patch("/{material_id}", response_model=MaterialOut)
def update_material(material_id: int, body: MaterialAssign):
    patch = body.model_dump(exclude_unset=True)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        data = dict(row)
        new_type = patch.get("type", data["type"])
        new_entry = patch.get("entry_id", data["entry_id"]) if "entry_id" in patch else data["entry_id"]

        if new_entry is not None:
            exists = conn.execute("SELECT id FROM entries WHERE id = ?", (new_entry,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="entry not found")

        new_path = data["stored_path"]
        if new_entry is not None and data["entry_id"] != new_entry:
            new_path = move_inbox_to_entry(data["stored_path"], new_entry)

        conn.execute(
            "UPDATE materials SET entry_id = ?, type = ?, stored_path = ? WHERE id = ?",
            (new_entry, new_type, new_path, material_id),
        )
        if new_entry is not None:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (now_iso(), new_entry))
        updated = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return material_to_out(dict(updated))


@router.patch("/{material_id}/type", response_model=MaterialOut)
def update_material_type(material_id: int, body: MaterialTypeUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        conn.execute("UPDATE materials SET type = ? WHERE id = ?", (body.type, material_id))
        if row["entry_id"] is not None:
            conn.execute(
                "UPDATE entries SET updated_at = ? WHERE id = ?",
                (now_iso(), row["entry_id"]),
            )
        updated = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return material_to_out(dict(updated))


@router.get("/{material_id}/file")
def get_material_file(material_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        path = resolve_stored(row["stored_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="file missing on disk")
        return FileResponse(
            path,
            media_type=row["mime"] or "application/octet-stream",
            filename=row["original_name"],
        )


@router.delete("/{material_id}")
def delete_material(material_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        if row["entry_id"] is not None:
            conn.execute(
                "UPDATE entries SET updated_at = ? WHERE id = ?",
                (now_iso(), row["entry_id"]),
            )
        rel = row["stored_path"]
    delete_file(rel)
    return {"ok": True}

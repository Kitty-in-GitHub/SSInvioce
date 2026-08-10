from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from ..models import ClassifyConfirmRequest, MaterialType
from ..services.amount import apply_auto_amount
from ..services.classify import classify_file
from ..services.storage import move_inbox_to_entry, probe_image_size, store_upload

router = APIRouter(prefix="/api/classify", tags=["classify"])
log = get_logger("classify")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# In-memory staging for classify preview session (local single-user app)
_STAGING: dict[str, dict] = {}


class ClassifiedItem(BaseModel):
    temp_id: str
    original_name: str
    suggested_type: MaterialType
    width: int | None = None
    height: int | None = None
    mime: str = ""
    preview_rel: str


class ClassifyPreviewResponse(BaseModel):
    items: list[ClassifiedItem]


def _guess_mime(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


@router.post("/preview", response_model=ClassifyPreviewResponse)
async def classify_preview(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="no files")
    items: list[ClassifiedItem] = []
    for file in files:
        if not file.filename:
            continue
        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_EXT:
            continue
        content = await file.read()
        if not content:
            continue
        rel, abs_path = store_upload(content, file.filename, entry_id=None)
        width = height = None
        if suffix != ".pdf":
            width, height = probe_image_size(abs_path)
        suggested = classify_file(file.filename, width=width, height=height)
        temp_id = uuid.uuid4().hex
        mime = _guess_mime(file.filename, file.content_type)
        _STAGING[temp_id] = {
            "original_name": file.filename,
            "stored_path": rel,
            "mime": mime,
            "width": width,
            "height": height,
            "suggested_type": suggested,
        }
        items.append(
            ClassifiedItem(
                temp_id=temp_id,
                original_name=file.filename,
                suggested_type=suggested,
                width=width,
                height=height,
                mime=mime,
                preview_rel=rel,
            )
        )
        log.info("classify preview name=%r -> %s", file.filename, suggested)
    log.info("classify preview done count=%s", len(items))
    return ClassifyPreviewResponse(items=items)


@router.post("/confirm")
def classify_confirm(body: ClassifyConfirmRequest):
    created_entry_ids: list[int] = []
    material_ids: list[int] = []
    with get_conn() as conn:
        for item in body.items:
            staged = _STAGING.pop(item.temp_id, None)
            if not staged:
                raise HTTPException(status_code=400, detail=f"unknown temp_id: {item.temp_id}")
            if item.type == "unknown":
                raise HTTPException(
                    status_code=400,
                    detail=f"请为 {staged['original_name']} 指定类型后再入库",
                )

            entry_id = item.entry_id
            if item.create_entry_title:
                ts = now_iso()
                cur = conn.execute(
                    """
                    INSERT INTO entries (title, note, created_at, updated_at, amount_source)
                    VALUES (?, '', ?, ?, 'empty')
                    """,
                    (item.create_entry_title.strip(), ts, ts),
                )
                entry_id = int(cur.lastrowid)
                created_entry_ids.append(entry_id)

            stored_path = staged["stored_path"]
            if entry_id is not None:
                stored_path = move_inbox_to_entry(stored_path, entry_id)

            ts = now_iso()
            cur = conn.execute(
                """
                INSERT INTO materials (entry_id, type, original_name, stored_path, mime, width, height, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    item.type,
                    staged["original_name"],
                    stored_path,
                    staged["mime"],
                    staged["width"],
                    staged["height"],
                    ts,
                ),
            )
            material_ids.append(int(cur.lastrowid))
            if entry_id is not None:
                conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (ts, entry_id))
                if item.type == "invoice":
                    apply_auto_amount(
                        conn,
                        entry_id,
                        stored_path=stored_path,
                        original_name=staged["original_name"],
                    )

    log.info(
        "classify confirm materials=%s created_entries=%s",
        len(material_ids),
        created_entry_ids,
    )
    return {
        "ok": True,
        "created_entry_ids": created_entry_ids,
        "material_ids": material_ids,
    }

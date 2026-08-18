from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from ..models import MaterialAssign, MaterialOut, MaterialType, MaterialTypeUpdate
from ..services.amount import apply_auto_amount
from ..services.classify import classify_file
from ..services.duplicates import find_invoice_duplicate, warning_from_hit
from ..services.features import extract_features, file_sha256, normalize_invoice_digits
from ..services.serializers import material_to_out
from ..services.settings_store import invoice_slot_id
from ..services.storage import delete_file, probe_image_size, resolve_stored, store_upload

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

    inv_id = invoice_slot_id()
    # Slot uploads used to skip OCR; extract when hanging on an entry so amount can auto-fill.
    need_features = type is None or type == inv_id or type == "unknown" or entry_id is not None
    feat = None
    if need_features:
        feat = extract_features(
            temp_id="",
            original_name=file.filename,
            stored_path=rel,
            abs_path=abs_path,
            width=width,
            height=height,
        )
        mat_type = type or feat.suggested_type or classify_file(file.filename, width=width, height=height)
    else:
        mat_type = type
    mime = _guess_mime(file.filename, file.content_type)
    ts = now_iso()
    inv_no = normalize_invoice_digits(feat.invoice_number) if feat and mat_type == inv_id else None
    inv_code = normalize_invoice_digits(feat.invoice_code) if feat and mat_type == inv_id else None
    digest = feat.content_sha256 if feat else file_sha256(abs_path)

    with get_conn() as conn:
        dup_warn = None
        if mat_type == inv_id and inv_no:
            hit = find_invoice_duplicate(conn, inv_no)
            if hit:
                dup_warn = warning_from_hit(reason="invoice_number", hit=hit)
        cur = conn.execute(
            """
            INSERT INTO materials (
                entry_id, type, original_name, stored_path, mime, width, height, created_at,
                invoice_number, invoice_code, content_sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, mat_type, file.filename, rel, mime, width, height, ts, inv_no, inv_code, digest),
        )
        mid = int(cur.lastrowid)
        if entry_id is not None:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (ts, entry_id))
            apply_auto_amount(
                conn,
                entry_id,
                stored_path=rel,
                original_name=file.filename,
                parsed_amount=feat.amount if feat else None,
                read_pdf=suffix == ".pdf" and not (feat and feat.amount is not None),
            )
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
        log.info(
            "uploaded material id=%s type=%s entry_id=%s name=%r bytes=%s inv=%s dup=%s",
            mid,
            mat_type,
            entry_id,
            file.filename,
            len(content),
            inv_no,
            bool(dup_warn),
        )
        return material_to_out(dict(row), duplicate_warning=dup_warn)


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

        inv_no = data.get("invoice_number")
        inv_code = data.get("invoice_code")
        digest = data.get("content_sha256")
        dup_warn = None
        feat_amount = None
        if new_type == invoice_slot_id() and not inv_no:
            feat = extract_features(
                temp_id="",
                original_name=data["original_name"],
                stored_path=new_path,
            )
            inv_no = feat.invoice_number
            inv_code = feat.invoice_code or inv_code
            digest = feat.content_sha256 or digest
            feat_amount = feat.amount
        if new_type != invoice_slot_id():
            inv_no = None
            inv_code = None
        if new_type == invoice_slot_id() and inv_no:
            hit = find_invoice_duplicate(conn, inv_no, exclude_material_ids={material_id})
            if hit:
                dup_warn = warning_from_hit(reason="invoice_number", hit=hit)

        conn.execute(
            """
            UPDATE materials
            SET entry_id = ?, type = ?, stored_path = ?,
                invoice_number = ?, invoice_code = ?, content_sha256 = ?
            WHERE id = ?
            """,
            (
                new_entry,
                new_type,
                new_path,
                normalize_invoice_digits(inv_no) if new_type == invoice_slot_id() else None,
                normalize_invoice_digits(inv_code) if new_type == invoice_slot_id() else None,
                digest,
                material_id,
            ),
        )
        if new_entry is not None:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (now_iso(), new_entry))
            apply_auto_amount(
                conn,
                new_entry,
                stored_path=new_path,
                original_name=data["original_name"],
                parsed_amount=feat_amount,
                read_pdf=feat_amount is None,
            )
        updated = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return material_to_out(dict(updated), duplicate_warning=dup_warn)

@router.patch("/{material_id}/type", response_model=MaterialOut)
def update_material_type(material_id: int, body: MaterialTypeUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        data = dict(row)
        inv_no = data.get("invoice_number")
        inv_code = data.get("invoice_code")
        digest = data.get("content_sha256")
        dup_warn = None
        feat_amount = None
        if body.type == invoice_slot_id() and not inv_no:
            feat = extract_features(
                temp_id="",
                original_name=data["original_name"],
                stored_path=data["stored_path"],
            )
            inv_no = feat.invoice_number
            inv_code = feat.invoice_code or inv_code
            digest = feat.content_sha256 or digest
            feat_amount = feat.amount
        if body.type != invoice_slot_id():
            inv_no = None
            inv_code = None
        if body.type == invoice_slot_id() and inv_no:
            hit = find_invoice_duplicate(conn, inv_no, exclude_material_ids={material_id})
            if hit:
                dup_warn = warning_from_hit(reason="invoice_number", hit=hit)
        conn.execute(
            """
            UPDATE materials
            SET type = ?, invoice_number = ?, invoice_code = ?, content_sha256 = ?
            WHERE id = ?
            """,
            (
                body.type,
                normalize_invoice_digits(inv_no) if body.type == invoice_slot_id() else None,
                normalize_invoice_digits(inv_code) if body.type == invoice_slot_id() else None,
                digest,
                material_id,
            ),
        )
        if row["entry_id"] is not None:
            conn.execute(
                "UPDATE entries SET updated_at = ? WHERE id = ?",
                (now_iso(), row["entry_id"]),
            )
            apply_auto_amount(
                conn,
                row["entry_id"],
                stored_path=row["stored_path"],
                original_name=row["original_name"],
                parsed_amount=feat_amount,
                read_pdf=feat_amount is None,
            )
        updated = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        return material_to_out(dict(updated), duplicate_warning=dup_warn)


@router.get("/{material_id}/file")
def get_material_file(material_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="material not found")
        path = resolve_stored(row["stored_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="file missing on disk")
        name = row["original_name"] or path.name
        mime = row["mime"] or _guess_mime(name, None)
        if path.suffix.lower() == ".pdf" or (mime or "").lower() == "application/pdf":
            mime = "application/pdf"
        return FileResponse(
            path,
            media_type=mime or "application/octet-stream",
            filename=name,
            content_disposition_type="inline",
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

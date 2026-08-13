from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from ..models import (
    ClassifyConfirmRequest,
    DuplicateWarning,
    MaterialType,
)
from ..services.amount import apply_auto_amount
from ..services.cluster import cluster_features
from ..services.duplicates import find_invoice_duplicate, warning_from_hit
from ..services.features import FileFeatures, extract_features, normalize_invoice_digits
from ..services.ocr import ocr_available
from ..services.storage import delete_file, move_inbox_to_entry, probe_image_size, resolve_stored, store_upload

router = APIRouter(prefix="/api/classify", tags=["classify"])
log = get_logger("classify")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# In-memory staging for classify preview session (local single-user app)
_STAGING: dict[str, dict] = {}


class FeatureOut(BaseModel):
    amount: float | None = None
    merchant: str | None = None
    product_name: str | None = None
    date: str | None = None
    order_no: str | None = None
    invoice_number: str | None = None
    invoice_code: str | None = None
    content_sha256: str | None = None
    text_preview: str = ""
    ocr_used: bool = False
    text_source: str = "none"


class ClassifiedItem(BaseModel):
    temp_id: str
    original_name: str
    suggested_type: MaterialType
    width: int | None = None
    height: int | None = None
    mime: str = ""
    preview_rel: str
    features: FeatureOut = Field(default_factory=FeatureOut)
    proposed_cluster_id: str | None = None


class ProposedClusterOut(BaseModel):
    cluster_id: str
    title: str
    amount: float | None = None
    temp_ids: list[str]
    types: dict[str, MaterialType]
    complete: bool = False
    missing: list[str] = []
    merchant: str | None = None
    duplicate_warning: DuplicateWarning | None = None


class ClassifyPreviewResponse(BaseModel):
    items: list[ClassifiedItem]
    clusters: list[ProposedClusterOut] = []
    unmatched_temp_ids: list[str] = []
    ocr_available: bool = False


def _guess_mime(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _features_from_staging(temp_ids: list[str] | None = None) -> list[FileFeatures]:
    ids = temp_ids if temp_ids is not None else list(_STAGING.keys())
    out: list[FileFeatures] = []
    for tid in ids:
        staged = _STAGING.get(tid)
        if not staged:
            continue
        feat = staged.get("features")
        if isinstance(feat, FileFeatures):
            out.append(feat)
            continue
        out.append(
            extract_features(
                temp_id=tid,
                original_name=staged["original_name"],
                stored_path=staged["stored_path"],
                width=staged.get("width"),
                height=staged.get("height"),
            )
        )
    return out


def _invoice_feats_in_cluster(cluster, by_tid: dict[str, FileFeatures]) -> list[FileFeatures]:
    out: list[FileFeatures] = []
    for tid in cluster.temp_ids:
        feat = by_tid.get(tid)
        if not feat:
            continue
        typ = cluster.types.get(tid) or feat.suggested_type
        if typ == "invoice":
            out.append(feat)
    return out


def _duplicate_for_cluster(cluster, by_tid: dict[str, FileFeatures], batch_ids: list[str]) -> dict | None:
    invoices = _invoice_feats_in_cluster(cluster, by_tid)
    if not invoices:
        return None

    # Prefer DB lookup so UI can link / delete the existing entry
    with get_conn() as conn:
        for inv in invoices:
            hit = find_invoice_duplicate(conn, inv.invoice_number)
            if hit:
                return warning_from_hit(reason="invoice_number", hit=hit)

    # Same-batch invoice number collision with another staged file outside this cluster
    for inv in invoices:
        number = normalize_invoice_digits(inv.invoice_number)
        if not number:
            continue
        for tid in batch_ids:
            if tid in cluster.temp_ids:
                continue
            other = by_tid.get(tid)
            if not other or other.suggested_type != "invoice":
                continue
            if normalize_invoice_digits(other.invoice_number) == number:
                return warning_from_hit(
                    reason="same_batch_number",
                    invoice_number=number,
                    peer_temp_id=tid,
                )

    # Same-batch file hash when numbers missing
    for inv in invoices:
        digest = inv.content_sha256
        if not digest:
            continue
        for tid in batch_ids:
            if tid in cluster.temp_ids:
                continue
            other = by_tid.get(tid)
            if not other or other.suggested_type != "invoice":
                continue
            if other.content_sha256 and other.content_sha256 == digest:
                return warning_from_hit(
                    reason="file_hash",
                    invoice_number=inv.invoice_number,
                    peer_temp_id=tid,
                )

    return None


def _build_preview_payload(temp_ids: list[str] | None = None) -> ClassifyPreviewResponse:
    """Cluster staged files and return a full snapshot for the given (or all) temp_ids."""
    ids = temp_ids if temp_ids is not None else list(_STAGING.keys())
    feats = _features_from_staging(ids)
    by_tid = {f.temp_id: f for f in feats}
    clusters, unmatched = cluster_features(feats)
    cluster_of: dict[str, str] = {}
    for c in clusters:
        for tid in c.temp_ids:
            cluster_of[tid] = c.cluster_id

    items: list[ClassifiedItem] = []
    for tid in ids:
        staged = _STAGING.get(tid)
        if not staged:
            continue
        feat: FileFeatures = staged["features"]
        items.append(
            ClassifiedItem(
                temp_id=tid,
                original_name=staged["original_name"],
                suggested_type=feat.suggested_type,
                width=staged.get("width"),
                height=staged.get("height"),
                mime=staged["mime"],
                preview_rel=staged["stored_path"],
                features=FeatureOut(**feat.to_public()),
                proposed_cluster_id=cluster_of.get(tid),
            )
        )

    cluster_outs: list[ProposedClusterOut] = []
    for c in clusters:
        pub = c.to_public()
        warn = _duplicate_for_cluster(c, by_tid, ids)
        cluster_outs.append(
            ProposedClusterOut(
                **pub,
                duplicate_warning=DuplicateWarning(**warn) if warn else None,
            )
        )

    return ClassifyPreviewResponse(
        items=items,
        clusters=cluster_outs,
        unmatched_temp_ids=unmatched,
        ocr_available=ocr_available(),
    )


@router.post("/preview", response_model=ClassifyPreviewResponse)
async def classify_preview(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="no files")
    new_ids: list[str] = []
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
        temp_id = uuid.uuid4().hex
        mime = _guess_mime(file.filename, file.content_type)
        feat = extract_features(
            temp_id=temp_id,
            original_name=file.filename,
            stored_path=rel,
            abs_path=abs_path,
            width=width,
            height=height,
        )
        _STAGING[temp_id] = {
            "original_name": file.filename,
            "stored_path": rel,
            "mime": mime,
            "width": width,
            "height": height,
            "suggested_type": feat.suggested_type,
            "features": feat,
            "invoice_number": feat.invoice_number,
            "invoice_code": feat.invoice_code,
            "content_sha256": feat.content_sha256,
        }
        new_ids.append(temp_id)
        log.info(
            "classify preview name=%r -> %s amount=%s inv=%s",
            file.filename,
            feat.suggested_type,
            feat.amount,
            feat.invoice_number,
        )

    payload = _build_preview_payload()
    log.info(
        "classify preview done new=%s total=%s clusters=%s unmatched=%s ocr=%s",
        len(new_ids),
        len(payload.items),
        len(payload.clusters),
        len(payload.unmatched_temp_ids),
        payload.ocr_available,
    )
    return payload


class ReclusterRequest(BaseModel):
    temp_ids: list[str] | None = None


class DiscardRequest(BaseModel):
    temp_ids: list[str] = Field(min_length=1)


def _drop_staged(temp_ids: list[str]) -> int:
    removed = 0
    for tid in temp_ids:
        staged = _STAGING.pop(tid, None)
        if not staged:
            continue
        rel = staged.get("stored_path")
        if rel:
            try:
                delete_file(rel)
            except Exception:
                log.warning("failed to delete staged file temp_id=%s path=%s", tid, rel)
        removed += 1
    return removed


@router.post("/discard", response_model=ClassifyPreviewResponse)
def classify_discard(body: DiscardRequest):
    """Remove staged files and return an updated preview snapshot."""
    n = _drop_staged(body.temp_ids)
    log.info("classify discard count=%s remaining=%s", n, len(_STAGING))
    return _build_preview_payload()


@router.get("/staging/{temp_id}/file")
def get_staging_file(temp_id: str):
    """Serve a staged classify file for in-dialog preview."""
    staged = _STAGING.get(temp_id)
    if not staged:
        raise HTTPException(status_code=404, detail="staged file not found")
    rel = staged.get("stored_path")
    if not rel:
        raise HTTPException(status_code=404, detail="staged path missing")
    path = resolve_stored(rel)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing on disk")
    name = staged.get("original_name") or path.name
    mime = staged.get("mime") or _guess_mime(name, None)
    if path.suffix.lower() == ".pdf" or (mime or "").lower() == "application/pdf":
        mime = "application/pdf"
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        filename=name,
        content_disposition_type="inline",
    )


@router.post("/recluster", response_model=ClassifyPreviewResponse)
def classify_recluster(body: ReclusterRequest | None = None):
    """Re-run clustering over staged files (optionally subset)."""
    temp_ids = body.temp_ids if body else None
    if temp_ids:
        missing = [t for t in temp_ids if t not in _STAGING]
        if missing:
            raise HTTPException(status_code=400, detail=f"unknown temp_id: {missing[0]}")
        ids = temp_ids
    else:
        ids = list(_STAGING.keys())
    return _build_preview_payload(ids)


def _insert_material(conn, *, entry_id: int | None, mat_type: MaterialType, staged: dict) -> int:
    stored_path = staged["stored_path"]
    if entry_id is not None:
        stored_path = move_inbox_to_entry(stored_path, entry_id)
    ts = now_iso()
    feat = staged.get("features")
    invoice_number = staged.get("invoice_number")
    invoice_code = staged.get("invoice_code")
    content_sha256 = staged.get("content_sha256")
    if isinstance(feat, FileFeatures):
        invoice_number = invoice_number or feat.invoice_number
        invoice_code = invoice_code or feat.invoice_code
        content_sha256 = content_sha256 or feat.content_sha256
    if mat_type != "invoice":
        # Keep hash for any file; clear invoice ids for non-invoice types
        invoice_number = None
        invoice_code = None

    cur = conn.execute(
        """
        INSERT INTO materials (
            entry_id, type, original_name, stored_path, mime, width, height, created_at,
            invoice_number, invoice_code, content_sha256
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            mat_type,
            staged["original_name"],
            stored_path,
            staged["mime"],
            staged["width"],
            staged["height"],
            ts,
            normalize_invoice_digits(invoice_number) if mat_type == "invoice" else None,
            normalize_invoice_digits(invoice_code) if mat_type == "invoice" else None,
            content_sha256,
        ),
    )
    material_id = int(cur.lastrowid)
    if entry_id is not None:
        conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (ts, entry_id))
        if mat_type == "invoice":
            apply_auto_amount(
                conn,
                entry_id,
                stored_path=stored_path,
                original_name=staged["original_name"],
            )
    return material_id


@router.post("/confirm")
def classify_confirm(body: ClassifyConfirmRequest):
    created_entry_ids: list[int] = []
    material_ids: list[int] = []
    warnings: list[dict] = []
    with get_conn() as conn:
        # 1) Cluster-based create + attach
        for cluster in body.clusters:
            if not cluster.materials:
                continue
            for m in cluster.materials:
                if m.type == "unknown":
                    raise HTTPException(status_code=400, detail=f"簇「{cluster.title}」含未分类材料")
                if m.temp_id not in _STAGING:
                    raise HTTPException(status_code=400, detail=f"unknown temp_id: {m.temp_id}")

            for m in cluster.materials:
                if m.type != "invoice":
                    continue
                staged = _STAGING[m.temp_id]
                feat = staged.get("features")
                number = staged.get("invoice_number")
                if isinstance(feat, FileFeatures):
                    number = number or feat.invoice_number
                hit = find_invoice_duplicate(conn, number)
                if hit:
                    warnings.append(
                        warning_from_hit(
                            reason="invoice_number",
                            hit=hit,
                        )
                    )

            ts = now_iso()
            title = (cluster.title or "").strip() or "未命名报销"
            amount = cluster.amount
            amount_source = "empty"
            amount_auto = None
            if amount is not None:
                amount_source = "auto"
                amount_auto = float(amount)
            cur = conn.execute(
                """
                INSERT INTO entries (title, note, created_at, updated_at, amount, amount_source, amount_auto)
                VALUES (?, '', ?, ?, ?, ?, ?)
                """,
                (title, ts, ts, amount, amount_source, amount_auto),
            )
            entry_id = int(cur.lastrowid)
            created_entry_ids.append(entry_id)

            for m in cluster.materials:
                staged = _STAGING.pop(m.temp_id)
                material_ids.append(_insert_material(conn, entry_id=entry_id, mat_type=m.type, staged=staged))
                if amount is not None:
                    row = conn.execute(
                        "SELECT amount_source, amount FROM entries WHERE id = ?",
                        (entry_id,),
                    ).fetchone()
                    if row and (row["amount_source"] or "empty") != "manual" and row["amount"] is None:
                        conn.execute(
                            """
                            UPDATE entries
                            SET amount = ?, amount_auto = ?, amount_source = 'auto', updated_at = ?
                            WHERE id = ?
                            """,
                            (float(amount), float(amount), now_iso(), entry_id),
                        )

        # 2) Legacy per-file items (inbox / existing / single new)
        for item in body.items:
            staged = _STAGING.pop(item.temp_id, None)
            if not staged:
                raise HTTPException(status_code=400, detail=f"unknown temp_id: {item.temp_id}")
            if item.type == "unknown":
                raise HTTPException(
                    status_code=400,
                    detail=f"请为 {staged['original_name']} 指定类型后再入库",
                )

            if item.type == "invoice":
                feat = staged.get("features")
                number = staged.get("invoice_number")
                if isinstance(feat, FileFeatures):
                    number = number or feat.invoice_number
                hit = find_invoice_duplicate(conn, number)
                if hit:
                    warnings.append(warning_from_hit(reason="invoice_number", hit=hit))

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

            material_ids.append(
                _insert_material(conn, entry_id=entry_id, mat_type=item.type, staged=staged)
            )

    log.info(
        "classify confirm materials=%s created_entries=%s clusters=%s loose_items=%s warnings=%s",
        len(material_ids),
        created_entry_ids,
        len(body.clusters),
        len(body.items),
        len(warnings),
    )
    return {
        "ok": True,
        "created_entry_ids": created_entry_ids,
        "material_ids": material_ids,
        "warnings": warnings,
    }

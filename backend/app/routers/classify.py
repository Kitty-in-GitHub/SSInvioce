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
from ..services.duplicates import find_file_duplicate, find_invoice_duplicate, warning_from_hit
from ..services.features import (
    FileFeatures,
    extract_features,
    feature_from_json,
    feature_to_json,
    normalize_invoice_digits,
)
from ..services.ledger_link import sync_entry_ledger
from ..services.ocr import ocr_available
from ..services.settings_store import get_slots, invoice_slot_id
from ..services.storage import delete_file, probe_image_size, resolve_stored, store_upload
from ..services.trash import trash_material

router = APIRouter(prefix="/api/classify", tags=["classify"])
log = get_logger("classify")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# Staged files are plain inbox materials: `materials.entry_id IS NULL`,
# `analyze_status = 'staged'` and features cached in `features_json`.
# `temp_id` in the API payloads is the material id as a string (kept for
# frontend compatibility).


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
    duplicate_of: str | None = None


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
    duplicate_temp_ids: list[str] = []
    ocr_available: bool = False


class ReclusterRequest(BaseModel):
    temp_ids: list[str] | None = None


class DiscardRequest(BaseModel):
    temp_ids: list[str] = Field(min_length=1)


def _guess_mime(filename: str, content_type: str | None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _as_id(raw: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"unknown temp_id: {raw}") from None


def _parse_ids(raw: list[str] | None) -> list[int] | None:
    if not raw:
        return None
    return [_as_id(item) for item in raw]


def _inbox_rows(conn, ids: list[int] | None = None) -> list[dict]:
    sql = "SELECT * FROM materials WHERE entry_id IS NULL"
    params: list[int] = []
    if ids:
        sql += " AND id IN (" + ", ".join("?" for _ in ids) + ")"
        params.extend(ids)
    sql += " ORDER BY id"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _feature_for_row(conn, row: dict) -> FileFeatures:
    """Current features for an inbox material; cached on first use."""
    feat = feature_from_json(row.get("features_json"))
    if feat is None:
        try:
            feat = extract_features(
                temp_id="",
                original_name=row["original_name"],
                stored_path=row["stored_path"],
                width=row.get("width"),
                height=row.get("height"),
            )
        except Exception:
            log.exception("feature extraction failed material=%s", row.get("id"))
            feat = FileFeatures(
                original_name=row.get("original_name") or "",
                stored_path=row.get("stored_path") or "",
                suggested_type="unknown",
            )
        conn.execute(
            "UPDATE materials SET features_json = ? WHERE id = ?",
            (feature_to_json(feat), row["id"]),
        )
    feat.temp_id = str(row["id"])
    feat.original_name = row.get("original_name") or feat.original_name
    feat.stored_path = row.get("stored_path") or feat.stored_path
    row_type = (row.get("type") or "").strip()
    if row_type and row_type != "unknown":
        # A manual / already-known type wins over the suggested one.
        feat.suggested_type = row_type
    elif row.get("analyze_status") == "raw":
        # Fast-uploaded material: classify lazily on the first organize run.
        if feat.suggested_type != "unknown":
            conn.execute(
                "UPDATE materials SET type = ?, analyze_status = 'done' WHERE id = ?",
                (feat.suggested_type, row["id"]),
            )
        else:
            conn.execute(
                "UPDATE materials SET analyze_status = 'done' WHERE id = ?", (row["id"],)
            )
    else:
        feat.suggested_type = row_type or "unknown"
    return feat


def _db_invoice_warning(conn, invoice_number, digest) -> dict | None:
    """Duplicate against materials already filed into entries."""
    hit = find_invoice_duplicate(conn, invoice_number)
    if hit:
        return warning_from_hit(reason="invoice_number", hit=hit)
    hit = find_file_duplicate(conn, digest)
    if hit:
        return warning_from_hit(reason="existing_file_hash", hit=hit)
    return None


def _duplicate_for_cluster(conn, cluster, by_tid: dict[str, FileFeatures]) -> dict | None:
    """Duplicate check for a proposed cluster.

    Invoice numbers only apply to invoices, but an identical file is a
    duplicate for any slot type (order screenshot, payment record, ...).
    """
    inv_id = invoice_slot_id()
    members = [by_tid[tid] for tid in cluster.temp_ids if by_tid.get(tid) is not None]
    if not members:
        return None
    own = set(cluster.temp_ids)

    # 1) Already filed into an entry: same invoice number or same file content
    for feat in members:
        if feat.suggested_type == inv_id:
            hit = find_invoice_duplicate(conn, feat.invoice_number)
            if hit:
                return warning_from_hit(reason="invoice_number", hit=hit)
        if feat.content_sha256:
            hit = find_file_duplicate(conn, feat.content_sha256)
            if hit:
                return warning_from_hit(reason="existing_file_hash", hit=hit)

    # 2) Another not-yet-filed file in the inbox
    for feat in members:
        if feat.suggested_type == inv_id:
            number = normalize_invoice_digits(feat.invoice_number)
            if number:
                for tid, other in by_tid.items():
                    if tid in own or other.suggested_type != inv_id:
                        continue
                    if normalize_invoice_digits(other.invoice_number) == number:
                        return warning_from_hit(
                            reason="same_batch_number",
                            invoice_number=number,
                            peer_temp_id=tid,
                        )
        digest = feat.content_sha256
        if not digest:
            continue
        for tid, other in by_tid.items():
            if tid in own:
                continue
            if other.content_sha256 and other.content_sha256 == digest:
                return warning_from_hit(
                    reason="file_hash",
                    invoice_number=feat.invoice_number,
                    peer_temp_id=tid,
                )

    return None


def _fold_duplicates(
    feats: list[FileFeatures],
) -> tuple[list[FileFeatures], dict[str, str]]:
    """Keep one representative per identical inbox file; return (reps, dup_of).

    Invoices are grouped by invoice number (same number = same invoice, even if
    the bytes differ after a re-download); other files by content hash + type.
    """
    inv_id = invoice_slot_id()
    groups: dict[tuple, list[FileFeatures]] = {}
    for feat in feats:
        number = (
            normalize_invoice_digits(feat.invoice_number)
            if feat.suggested_type == inv_id
            else None
        )
        if number:
            key: tuple = ("no", number)
        elif feat.content_sha256:
            key = ("sha", feat.content_sha256, feat.suggested_type)
        else:
            continue
        groups.setdefault(key, []).append(feat)

    duplicate_of: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        rep = group[0]
        for feat in group[1:]:
            duplicate_of[feat.temp_id] = rep.temp_id

    reps = [feat for feat in feats if feat.temp_id not in duplicate_of]
    return reps, duplicate_of


def _build_preview_payload(temp_ids: list[str] | None = None) -> ClassifyPreviewResponse:
    """Cluster inbox materials and return a full snapshot for the given (or all) ids."""
    ids = _parse_ids(temp_ids)
    with get_conn() as conn:
        rows = _inbox_rows(conn, ids)
        feats = [_feature_for_row(conn, row) for row in rows]
        reps, duplicate_of = _fold_duplicates(feats)
        by_tid = {f.temp_id: f for f in reps}
        clusters, unmatched = cluster_features(reps)
        cluster_of: dict[str, str] = {}
        for c in clusters:
            for tid in c.temp_ids:
                cluster_of[tid] = c.cluster_id

        items: list[ClassifiedItem] = []
        for row, feat in zip(rows, feats):
            items.append(
                ClassifiedItem(
                    temp_id=feat.temp_id,
                    original_name=row["original_name"],
                    suggested_type=feat.suggested_type,
                    width=row.get("width"),
                    height=row.get("height"),
                    mime=row.get("mime") or "",
                    preview_rel=row["stored_path"],
                    features=FeatureOut(**feat.to_public()),
                    proposed_cluster_id=cluster_of.get(feat.temp_id),
                    duplicate_of=duplicate_of.get(feat.temp_id),
                )
            )

        cluster_outs: list[ProposedClusterOut] = []
        for c in clusters:
            pub = c.to_public()
            warn = _duplicate_for_cluster(conn, c, by_tid)
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
        duplicate_temp_ids=sorted(duplicate_of),
        ocr_available=ocr_available(),
    )


@router.post("/preview", response_model=ClassifyPreviewResponse)
async def classify_preview(files: list[UploadFile] = File(...)):
    """Store uploads into the inbox, extract features, then cluster the inbox."""
    if not files:
        raise HTTPException(status_code=400, detail="no files")
    new_ids: list[int] = []
    inv_id = invoice_slot_id()
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
        mime = _guess_mime(file.filename, file.content_type)
        try:
            feat = extract_features(
                temp_id="",
                original_name=file.filename,
                stored_path=rel,
                abs_path=abs_path,
                width=width,
                height=height,
            )
        except Exception:
            log.exception("feature extraction failed on upload name=%r", file.filename)
            feat = FileFeatures(
                original_name=file.filename,
                stored_path=rel,
                suggested_type="unknown",
            )
        mat_type = feat.suggested_type
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO materials (
                    entry_id, type, original_name, stored_path, mime, width, height, created_at,
                    invoice_number, invoice_code, content_sha256, analyze_status, features_json
                )
                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?)
                """,
                (
                    mat_type,
                    file.filename,
                    rel,
                    mime,
                    width,
                    height,
                    now_iso(),
                    normalize_invoice_digits(feat.invoice_number) if mat_type == inv_id else None,
                    normalize_invoice_digits(feat.invoice_code) if mat_type == inv_id else None,
                    feat.content_sha256,
                    feature_to_json(feat),
                ),
            )
            material_id = int(cur.lastrowid)
        new_ids.append(material_id)
        log.info(
            "classify staged material=%s name=%r -> %s amount=%s inv=%s",
            material_id,
            file.filename,
            mat_type,
            feat.amount,
            feat.invoice_number,
        )

    if not new_ids:
        raise HTTPException(status_code=400, detail="没有可识别的文件（仅支持 PDF / JPG / PNG 等）")

    payload = _build_preview_payload()
    log.info(
        "classify preview new=%s inbox=%s clusters=%s unmatched=%s ocr=%s",
        len(new_ids),
        len(payload.items),
        len(payload.clusters),
        len(payload.unmatched_temp_ids),
        payload.ocr_available,
    )
    return payload


@router.post("/discard", response_model=ClassifyPreviewResponse)
def classify_discard(body: DiscardRequest):
    """Move inbox materials to the recycle bin (restorable)."""
    batch_id = uuid.uuid4().hex
    removed = 0
    ids = _parse_ids(body.temp_ids) or []
    with get_conn() as conn:
        # Validate everything first so a rejected id cannot leave moved files behind.
        rows: list[dict] = []
        for mid in ids:
            row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
            if not row:
                continue
            if row["entry_id"] is not None:
                raise HTTPException(status_code=400, detail="材料已挂到条目，不能在此丢弃")
            rows.append(dict(row))
        for data in rows:
            if not trash_material(conn, data, reason="classify_discard", batch_id=batch_id):
                # File already gone: still drop the row so the inbox stays clean.
                delete_file(data["stored_path"])
            conn.execute("DELETE FROM materials WHERE id = ?", (data["id"],))
            removed += 1
    log.info("classify discard count=%s batch=%s", removed, batch_id)
    return _build_preview_payload()


@router.get("/staging/{temp_id}/file")
def get_staging_file(temp_id: str):
    """Serve an inbox material for in-dialog preview."""
    mid = _as_id(temp_id)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="staged file not found")
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


@router.post("/recluster", response_model=ClassifyPreviewResponse)
def classify_recluster(body: ReclusterRequest | None = None):
    """Re-run clustering over inbox materials (optionally a subset)."""
    temp_ids = body.temp_ids if body else None
    ids = _parse_ids(temp_ids)
    if ids:
        with get_conn() as conn:
            found = {int(row["id"]) for row in _inbox_rows(conn, ids)}
        missing = [str(mid) for mid in ids if mid not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"unknown temp_id: {missing[0]}")
    return _build_preview_payload(ids)


def _feature_amount(row: dict) -> float | None:
    feat = feature_from_json(row.get("features_json"))
    return feat.amount if feat else None


def _slot_labels() -> dict[str, str]:
    try:
        return {s["id"]: (s.get("label") or s["id"]) for s in get_slots()}
    except Exception:
        return {}


@router.post("/confirm")
def classify_confirm(body: ClassifyConfirmRequest):
    """File inbox materials into entries (or keep them in the inbox).

    A cluster either creates a new entry or, when ``entry_id`` is given, is
    merged into an existing entry (补传材料). Merging never overwrites an
    occupied slot and never overwrites the entry amount.
    """
    created_entry_ids: list[int] = []
    updated_entry_ids: list[int] = []
    material_ids: list[int] = []
    warnings: list[dict] = []
    inv_id = invoice_slot_id()

    with get_conn() as conn:
        # 1) Cluster-based create + attach
        for cluster in body.clusters:
            if not cluster.materials:
                continue
            picked: list[tuple[dict, str]] = []
            for m in cluster.materials:
                if m.type == "unknown":
                    raise HTTPException(status_code=400, detail=f"簇「{cluster.title}」含未分类材料")
                mid = _as_id(m.temp_id)
                row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail=f"unknown temp_id: {m.temp_id}")
                data = dict(row)
                if data.get("entry_id") is not None:
                    raise HTTPException(status_code=400, detail=f"材料 #{mid} 已入库，不能重复确认")
                picked.append((data, m.type))

            for data, typ in picked:
                if typ != inv_id:
                    continue
                warn = _db_invoice_warning(conn, data.get("invoice_number"), data.get("content_sha256"))
                if warn:
                    warnings.append(warn)

            ts = now_iso()
            amount = cluster.amount
            target_id = cluster.entry_id
            if target_id is None:
                title = (cluster.title or "").strip()
                if not title:
                    raise HTTPException(status_code=400, detail="拟建条目标题不能为空")
                amount_source = "auto" if amount is not None else "empty"
                amount_auto = float(amount) if amount is not None else None
                cur = conn.execute(
                    """
                    INSERT INTO entries (title, note, created_at, updated_at, amount, amount_source, amount_auto)
                    VALUES (?, '', ?, ?, ?, ?, ?)
                    """,
                    (title, ts, ts, amount, amount_source, amount_auto),
                )
                entry_id = int(cur.lastrowid)
                created_entry_ids.append(entry_id)
            else:
                # 并入已有条目：只补缺失槽位，不覆盖已有金额
                target = conn.execute(
                    "SELECT * FROM entries WHERE id = ?", (int(target_id),)
                ).fetchone()
                if not target:
                    raise HTTPException(status_code=404, detail="entry not found")
                taken = {
                    row["type"]
                    for row in conn.execute(
                        "SELECT type FROM materials WHERE entry_id = ?", (int(target_id),)
                    ).fetchall()
                }
                conflicts = sorted({typ for _, typ in picked if typ in taken})
                if conflicts:
                    labels = _slot_labels()
                    names = "、".join(labels.get(c, c) for c in conflicts)
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": (
                                f"条目「{target['title']}」已有{names}材料，"
                                "请先在条目里删除旧材料，或改成新建条目"
                            ),
                            "conflicts": conflicts,
                        },
                    )
                entry_id = int(target_id)
                updated_entry_ids.append(entry_id)
                conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (ts, entry_id))
                if (
                    amount is not None
                    and target["amount"] is None
                    and (target["amount_source"] or "empty") != "manual"
                ):
                    conn.execute(
                        """
                        UPDATE entries
                        SET amount = ?, amount_auto = ?, amount_source = 'auto', updated_at = ?
                        WHERE id = ?
                        """,
                        (float(amount), float(amount), ts, entry_id),
                    )
                    sync_entry_ledger(conn, entry_id)

            for data, typ in picked:
                conn.execute(
                    "UPDATE materials SET entry_id = ?, type = ?, analyze_status = 'done' WHERE id = ?",
                    (entry_id, typ, data["id"]),
                )
                material_ids.append(int(data["id"]))
                if target_id is None:
                    apply_auto_amount(
                        conn,
                        entry_id,
                        stored_path=data["stored_path"],
                        original_name=data["original_name"],
                        parsed_amount=_feature_amount(data),
                        read_pdf=False,
                    )

        # 2) Loose items (inbox / existing entry / single new entry)
        for item in body.items:
            mid = _as_id(item.temp_id)
            row = conn.execute("SELECT * FROM materials WHERE id = ?", (mid,)).fetchone()
            if not row:
                raise HTTPException(status_code=400, detail=f"unknown temp_id: {item.temp_id}")
            data = dict(row)
            if data.get("entry_id") is not None:
                raise HTTPException(status_code=400, detail=f"材料 #{mid} 已入库，不能重复确认")

            if item.type == "unknown":
                # Inbox may stay unclassified; attaching to an entry still needs a type.
                if item.entry_id is not None or (item.create_entry_title or "").strip():
                    raise HTTPException(
                        status_code=400,
                        detail=f"请为 {data['original_name']} 指定类型后再入库",
                    )

            if item.type == inv_id:
                warn = _db_invoice_warning(conn, data.get("invoice_number"), data.get("content_sha256"))
                if warn:
                    warnings.append(warn)

            entry_id = item.entry_id
            if entry_id is not None:
                exists = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
                if not exists:
                    raise HTTPException(status_code=404, detail="entry not found")
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

            conn.execute(
                "UPDATE materials SET entry_id = ?, type = ?, analyze_status = 'done' WHERE id = ?",
                (entry_id, item.type, mid),
            )
            material_ids.append(mid)
            if entry_id is not None:
                apply_auto_amount(
                    conn,
                    entry_id,
                    stored_path=data["stored_path"],
                    original_name=data["original_name"],
                    parsed_amount=_feature_amount(data),
                    read_pdf=False,
                )

    log.info(
        "classify confirm materials=%s created_entries=%s updated_entries=%s clusters=%s loose_items=%s warnings=%s",
        len(material_ids),
        created_entry_ids,
        updated_entry_ids,
        len(body.clusters),
        len(body.items),
        len(warnings),
    )
    return {
        "ok": True,
        "created_entry_ids": created_entry_ids,
        "updated_entry_ids": updated_entry_ids,
        "material_ids": material_ids,
        "warnings": warnings,
    }

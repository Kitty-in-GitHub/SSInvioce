from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from .amount import apply_auto_amount
from .duplicates import find_invoice_duplicate, warning_from_hit
from .features import extract_features, normalize_invoice_digits
from .settings_store import invoice_slot_id
from .storage import resolve_stored

log = get_logger("analyze_jobs")

_lock = Lock()
_claimed: set[int] = set()
_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analyze")
        return _executor


def is_material_processing(material_id: int) -> bool:
    return material_id in _claimed


def list_pending_jobs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, entry_id, original_name
            FROM materials
            WHERE analyze_status = 'pending'
            ORDER BY id
            """
        ).fetchall()
    claimed = set(_claimed)
    return [
        {
            "material_id": int(r["id"]),
            "entry_id": int(r["entry_id"]) if r["entry_id"] is not None else None,
            "filename": r["original_name"],
            "status": "running" if int(r["id"]) in claimed else "queued",
        }
        for r in rows
    ]


def submit_analyze(material_id: int) -> None:
    with _lock:
        if material_id in _claimed:
            return
        _claimed.add(material_id)
    _pool().submit(_run, material_id)


def resume_pending_analyze_jobs() -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM materials WHERE analyze_status = 'pending' ORDER BY id"
        ).fetchall()
    ids = [int(r["id"]) for r in rows]
    for mid in ids:
        submit_analyze(mid)
    if ids:
        log.info("resumed pending analyze jobs count=%s", len(ids))
    return len(ids)


def shutdown_analyze_jobs() -> None:
    global _executor
    with _lock:
        pool = _executor
        _executor = None
    if pool is None:
        return
    log.info("waiting for analyze jobs to finish claimed=%s", len(_claimed))
    try:
        pool.shutdown(wait=True, cancel_futures=False)
    except TypeError:
        pool.shutdown(wait=True)


def _set_status(material_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE materials SET analyze_status = ? WHERE id = ?",
            (status, material_id),
        )


def _run(material_id: int) -> None:
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
            if not row:
                log.info("analyze skipped missing material id=%s", material_id)
                return
            data = dict(row)
        path = resolve_stored(data["stored_path"])
        feat = extract_features(
            temp_id="",
            original_name=data["original_name"],
            stored_path=data["stored_path"],
            abs_path=path,
            width=data.get("width"),
            height=data.get("height"),
        )
        inv_id = invoice_slot_id()
        mat_type = data["type"]
        inv_no = normalize_invoice_digits(feat.invoice_number) if mat_type == inv_id else None
        inv_code = normalize_invoice_digits(feat.invoice_code) if mat_type == inv_id else None
        digest = feat.content_sha256
        entry_id = data.get("entry_id")
        with get_conn() as conn:
            still = conn.execute("SELECT id FROM materials WHERE id = ?", (material_id,)).fetchone()
            if not still:
                log.info("analyze skipped deleted material id=%s", material_id)
                return
            conn.execute(
                """
                UPDATE materials
                SET invoice_number = ?, invoice_code = ?, content_sha256 = ?, analyze_status = 'done'
                WHERE id = ?
                """,
                (inv_no, inv_code, digest, material_id),
            )
            if entry_id is not None:
                conn.execute(
                    "UPDATE entries SET updated_at = ? WHERE id = ?",
                    (now_iso(), entry_id),
                )
                apply_auto_amount(
                    conn,
                    int(entry_id),
                    stored_path=data["stored_path"],
                    original_name=data["original_name"],
                    parsed_amount=feat.amount,
                    read_pdf=feat.amount is None,
                )
            dup = None
            if mat_type == inv_id and inv_no:
                hit = find_invoice_duplicate(conn, inv_no, exclude_material_ids={material_id})
                if hit:
                    dup = warning_from_hit(reason="invoice_number", hit=hit)
        log.info(
            "analyze done id=%s type=%s amount=%s inv=%s dup=%s",
            material_id,
            mat_type,
            feat.amount,
            inv_no,
            bool(dup),
        )
    except Exception:
        log.exception("analyze failed id=%s", material_id)
        try:
            _set_status(material_id, "error")
        except Exception:
            log.exception("analyze status update failed id=%s", material_id)
    finally:
        with _lock:
            _claimed.discard(material_id)

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import get_conn, now_iso
from ..logging_config import get_logger
from ..services.forms import (
    DEFAULT_FORM_ID,
    FormError,
    apply_auto_reimburse,
    auto_reimburse_map,
    dump_form_data,
    expense_table,
    form_totals,
    get_form_template,
    merge_form_values,
    parse_form_data,
    render_docx,
    render_form_pdf,
)

router = APIRouter(prefix="/api/groups", tags=["group-forms"])
log = get_logger("group-forms")


class FormRowIn(BaseModel):
    amount: Any = ""
    reimburse: Any = ""
    remark: str = ""
    reimburse_manual: bool = False


class GroupFormUpdate(BaseModel):
    template_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    rows: dict[str, FormRowIn] = Field(default_factory=dict)
    entry_rows: dict[int, Optional[str]] = Field(default_factory=dict)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" ._")
    return cleaned or "group"


def _load_group(conn, group_id: int) -> dict:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="group not found")
    return dict(row)


def _group_entries(conn, group_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, amount, expense_row FROM entries WHERE group_id = ? ORDER BY id",
        (group_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _form_payload(conn, group_id: int, template_id: str | None = None) -> dict:
    group = _load_group(conn, group_id)
    try:
        template = get_form_template(template_id)
    except FormError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    saved_all = parse_form_data(group.get("form_data"))
    saved = saved_all.get(template["id"])
    entries = _group_entries(conn, group_id)
    values = merge_form_values(template, saved)
    auto_map = auto_reimburse_map(entries, template)
    values = apply_auto_reimburse(values, auto_map)
    from ..services.forms import has_user_docx

    return {
        "template": template,
        "values": values,
        "auto_reimburse": auto_map,
        "totals": form_totals(values),
        "entries": [
            {
                "id": e["id"],
                "title": e["title"],
                "amount": e.get("amount"),
                "expense_row": e.get("expense_row"),
            }
            for e in entries
        ],
        "saved": isinstance(saved, dict),
        "has_user_docx": has_user_docx(template),
    }


@router.get("/{group_id}/forms")
def read_group_form(group_id: int, template_id: str | None = None):
    with get_conn() as conn:
        return _form_payload(conn, group_id, template_id)


@router.put("/{group_id}/forms")
def save_group_form(group_id: int, body: GroupFormUpdate):
    tid = body.template_id or DEFAULT_FORM_ID
    try:
        template = get_form_template(tid)
    except FormError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tbl = expense_table(template)
    valid_rows = {r["id"] for r in (tbl["rows"] if tbl else [])}
    remark_by_row = {
        rid: (row.remark or "")
        for rid, row in body.rows.items()
        if rid in valid_rows
    }
    fields_out = {}
    valid_fields = {f["id"] for f in template.get("fields") or []}
    for fid, val in body.fields.items():
        if fid in valid_fields:
            fields_out[fid] = "" if val is None else str(val)
    with get_conn() as conn:
        group = _load_group(conn, group_id)
        entry_ids = {e["id"] for e in _group_entries(conn, group_id)}
        for eid, rid in body.entry_rows.items():
            if eid not in entry_ids:
                continue
            row_id = (rid or "").strip() or None
            if row_id and row_id not in valid_rows:
                row_id = None
            conn.execute(
                "UPDATE entries SET expense_row = ?, updated_at = ? WHERE id = ?",
                (row_id, now_iso(), eid),
            )
        entries = _group_entries(conn, group_id)
        auto_map = auto_reimburse_map(entries, template)
        draft = {"fields": fields_out, "rows": {}}
        for row_def in tbl["rows"] if tbl else []:
            rid = row_def["id"]
            draft["rows"][rid] = {
                "amount": "",
                "reimburse": "",
                "remark": remark_by_row.get(rid, row_def.get("remark") or ""),
                "reimburse_manual": False,
            }
        draft = apply_auto_reimburse(draft, auto_map)
        data = parse_form_data(group.get("form_data"))
        data[template["id"]] = {"fields": fields_out, "rows": draft["rows"]}
        conn.execute(
            "UPDATE groups SET form_data = ?, updated_at = ? WHERE id = ?",
            (dump_form_data(data), now_iso(), group_id),
        )
        log.info("saved group form group_id=%s template=%s", group_id, template["id"])
        return _form_payload(conn, group_id, template["id"])


def _draft_values(conn, group_id: int, body: GroupFormUpdate) -> tuple[dict, dict]:
    tid = body.template_id or DEFAULT_FORM_ID
    try:
        template = get_form_template(tid)
    except FormError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tbl = expense_table(template)
    valid_rows = {r["id"] for r in (tbl["rows"] if tbl else [])}
    valid_fields = {f["id"] for f in template.get("fields") or []}
    fields_out = {
        fid: ("" if val is None else str(val))
        for fid, val in body.fields.items()
        if fid in valid_fields
    }
    for f in template.get("fields") or []:
        fields_out.setdefault(f["id"], "")
    remark_by_row = {
        rid: (row.remark or "")
        for rid, row in body.rows.items()
        if rid in valid_rows
    }
    entries = _group_entries(conn, group_id)
    for e in entries:
        if e["id"] in body.entry_rows:
            rid = body.entry_rows[e["id"]]
            rid = (rid or "").strip() or None
            if rid and rid not in valid_rows:
                rid = None
            e["expense_row"] = rid
    auto_map = auto_reimburse_map(entries, template)
    draft = {"fields": fields_out, "rows": {}}
    for row_def in tbl["rows"] if tbl else []:
        rid = row_def["id"]
        draft["rows"][rid] = {
            "amount": "",
            "reimburse": "",
            "remark": remark_by_row.get(rid, row_def.get("remark") or ""),
            "reimburse_manual": False,
        }
    return apply_auto_reimburse(draft, auto_map), template


@router.post("/{group_id}/forms/preview-pdf")
def preview_group_form_pdf(group_id: int, body: GroupFormUpdate):
    """Render filled form as PDF for on-screen preview (no Microsoft Word)."""
    with get_conn() as conn:
        _load_group(conn, group_id)
        values, template = _draft_values(conn, group_id, body)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    from ..config import EXPORTS_DIR, ensure_dirs

    ensure_dirs()
    pdf_path = EXPORTS_DIR / f"group_{group_id}_{template['id']}_preview_{stamp}.pdf"
    try:
        out = render_form_pdf(template, values, pdf_path)
    except FormError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("preview form pdf group_id=%s path=%s", group_id, out)
    return FileResponse(
        out,
        media_type="application/pdf",
        filename=f"{template['name']}_预览.pdf",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{group_id}/forms/docx")
def download_group_form_docx(group_id: int, template_id: str | None = None):
    with get_conn() as conn:
        group = _load_group(conn, group_id)
        try:
            template = get_form_template(template_id)
        except FormError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        saved_all = parse_form_data(group.get("form_data"))
        saved = saved_all.get(template["id"])
        if not isinstance(saved, dict):
            raise HTTPException(status_code=400, detail="请先保存表格再下载 Word")
        entries = _group_entries(conn, group_id)
        values = apply_auto_reimburse(merge_form_values(template, saved), auto_reimburse_map(entries, template))
        gname = _safe_filename(group["name"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    from ..config import EXPORTS_DIR, ensure_dirs

    ensure_dirs()
    dest = EXPORTS_DIR / f"group_{group_id}_{template['id']}_{stamp}.docx"
    try:
        render_docx(template, values, dest)
    except FormError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{gname}_{template['name']}.docx"
    quoted = quote(filename)
    log.info("download form docx group_id=%s path=%s", group_id, dest)
    return FileResponse(
        dest,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )

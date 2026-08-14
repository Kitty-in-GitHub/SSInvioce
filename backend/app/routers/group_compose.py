from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..logging_config import get_logger
from ..routers.compose import materials_by_slot, require_exportable
from ..services.settings_store import get_layout

router = APIRouter(prefix="/api/groups", tags=["groups-compose"])
log = get_logger("groups")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" ._")
    return cleaned or "group"


@router.post("/{group_id}/compose")
def compose_group(group_id: int):
    with get_conn() as conn:
        group = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="group not found")

        entries = conn.execute(
            "SELECT id, title FROM entries WHERE group_id = ? ORDER BY id",
            (group_id,),
        ).fetchall()
        if not entries:
            raise HTTPException(status_code=400, detail="该组没有条目，无法导出")

        incomplete = []
        items: list[dict[str, str]] = []
        for e in entries:
            files = materials_by_slot(conn, e["id"])
            try:
                require_exportable(files, e["id"], e["title"])
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"missing": []}
                incomplete.append(
                    {
                        "entry_id": e["id"],
                        "title": e["title"],
                        "missing": detail.get("missing") or [],
                    }
                )
                continue
            items.append(files)

        if incomplete:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "组内存在不齐套条目，禁止导出",
                    "incomplete": incomplete,
                },
            )
        group_name = group["name"]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    gname = _safe_filename(group_name)
    out_name = f"group_{group_id}_{len(items)}entries_{stamp}.pdf"
    from ..services.layout import ComposeError, compose_batch_pdf

    try:
        out = compose_batch_pdf(items, out_name=out_name, layout=get_layout())
    except ComposeError as exc:
        log.exception("group compose failed group_id=%s", group_id)
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc

    log.info("group compose ok group_id=%s items=%s", group_id, len(items))
    filename = f"{gname}_拼版_{len(items)}页_{stamp}.pdf"
    return FileResponse(out, media_type="application/pdf", filename=filename)

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..logging_config import get_logger
from ..services.layout import ComposeError, compose_batch_pdf

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
        pages: list[dict[str, str]] = []
        for e in entries:
            mats = conn.execute(
                "SELECT * FROM materials WHERE entry_id = ? ORDER BY id",
                (e["id"],),
            ).fetchall()
            by_type: dict[str, list] = {"invoice": [], "order": [], "payment": []}
            for m in mats:
                if m["type"] in by_type:
                    by_type[m["type"]].append(m)
            missing = [t for t, items in by_type.items() if not items]
            if missing:
                incomplete.append(
                    {"entry_id": e["id"], "title": e["title"], "missing": missing}
                )
                continue
            pages.append(
                {
                    "invoice_rel": by_type["invoice"][0]["stored_path"],
                    "order_rel": by_type["order"][0]["stored_path"],
                    "payment_rel": by_type["payment"][0]["stored_path"],
                }
            )

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
    out_name = f"group_{group_id}_{len(pages)}entries_{stamp}.pdf"
    try:
        out = compose_batch_pdf(pages, out_name=out_name)
    except ComposeError as exc:
        log.exception("group compose failed group_id=%s", group_id)
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "missing": exc.missing},
        ) from exc

    log.info("group compose ok group_id=%s pages=%s", group_id, len(pages))
    filename = f"{gname}_拼版_{len(pages)}页_{stamp}.pdf"
    return FileResponse(out, media_type="application/pdf", filename=filename)

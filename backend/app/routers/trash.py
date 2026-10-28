from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from ..services import trash as trash_service

router = APIRouter(prefix="/api/trash", tags=["trash"])
log = get_logger("trash")


class RestoreRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class PurgeRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


@router.get("")
def list_trash():
    return trash_service.list_trash()


@router.post("/restore")
def restore_trash(body: RestoreRequest):
    results = trash_service.restore(body.ids)
    restored = sum(1 for r in results if r.get("ok"))
    log.info("trash restore ids=%s restored=%s", len(body.ids), restored)
    return {"ok": True, "restored": restored, "results": results}


@router.post("/purge")
def purge_trash(body: PurgeRequest):
    return {"ok": True, "purged": trash_service.purge(body.ids)}


@router.delete("")
def purge_all_trash():
    return {"ok": True, "purged": trash_service.purge_all()}


@router.delete("/{trash_id}")
def purge_trash_item(trash_id: int):
    removed = trash_service.purge([trash_id])
    if not removed:
        raise HTTPException(status_code=404, detail="回收站记录不存在")
    return {"ok": True}

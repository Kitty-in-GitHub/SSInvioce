from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_conn
from ..services.settings_store import (
    default_layout,
    default_slots,
    get_settings,
    reset_classify_keywords,
    update_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SlotIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    file_kind: str = "image"
    required: bool = True
    special: str | None = None
    color: str = "#163a7a"
    keywords: list[str] = Field(default_factory=list)


class RegionIn(BaseModel):
    slot_id: str
    x: float
    y: float
    w: float
    h: float


class PageIn(BaseModel):
    regions: list[RegionIn] = Field(default_factory=list)


class LayoutIn(BaseModel):
    pages: list[PageIn] = Field(default_factory=list)


class AppSettings(BaseModel):
    slots: list[SlotIn]
    layout: LayoutIn
    classify_keywords: dict[str, list[str]] = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    slots: list[SlotIn] | None = None
    layout: LayoutIn | None = None
    classify_keywords: dict[str, list[str]] | None = None


def _to_out(data: dict) -> AppSettings:
    return AppSettings(
        slots=[SlotIn(**s) for s in data["slots"]],
        layout=LayoutIn(**data["layout"]),
        classify_keywords=data.get("classify_keywords") or {},
    )


@router.get("", response_model=AppSettings)
def read_settings():
    return _to_out(get_settings())


@router.put("", response_model=AppSettings)
def put_settings(body: SettingsUpdate):
    patch: dict = {}
    if body.slots is not None:
        new_ids = {s.id for s in body.slots}
        with get_conn() as conn:
            used = {
                row["type"]
                for row in conn.execute("SELECT DISTINCT type FROM materials").fetchall()
                if row["type"] and row["type"] != "unknown"
            }
        missing = used - new_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"无法删除仍有材料的槽位：{', '.join(sorted(missing))}",
            )
        patch["slots"] = [s.model_dump() for s in body.slots]
    if body.layout is not None:
        patch["layout"] = body.layout.model_dump()
    if body.classify_keywords is not None:
        patch["classify_keywords"] = body.classify_keywords
    data = update_settings(patch) if patch else get_settings()
    return _to_out(data)


@router.post("/classify-keywords/reset", response_model=AppSettings)
def reset_keywords():
    data = reset_classify_keywords()
    return _to_out(data)


@router.get("/classify-keywords/defaults")
def keyword_defaults():
    slots = default_slots()
    return {s["id"]: s["keywords"] for s in slots}


@router.post("/layout/reset", response_model=AppSettings)
def reset_layout():
    data = update_settings({"layout": default_layout()})
    return _to_out(data)

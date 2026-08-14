from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..db import get_conn
from ..services.forms import (
    default_form_templates,
    get_form_template,
    has_user_docx,
    reset_user_docx,
    save_user_docx,
    FormError,
)
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


class FormFieldIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    type: str = "text"


class FormColumnIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    type: str = "text"


class FormRowDefIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    remark: str = ""


class FormTableIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = "支出"
    columns: list[FormColumnIn] = Field(default_factory=list)
    rows: list[FormRowDefIn] = Field(default_factory=list)
    total: bool = True


class FormTemplateIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=40)
    docx: str = ""
    fields: list[FormFieldIn] = Field(default_factory=list)
    tables: list[FormTableIn] = Field(default_factory=list)
    has_user_docx: bool = False


class AppSettings(BaseModel):
    slots: list[SlotIn]
    layout: LayoutIn
    custom_colors: list[str] = Field(default_factory=list)
    preset_colors: list[str] = Field(default_factory=list)
    form_templates: list[FormTemplateIn] = Field(default_factory=list)
    classify_keywords: dict[str, list[str]] = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    slots: list[SlotIn] | None = None
    layout: LayoutIn | None = None
    custom_colors: list[str] | None = None
    form_templates: list[FormTemplateIn] | None = None
    classify_keywords: dict[str, list[str]] | None = None


def _template_out(t: dict) -> FormTemplateIn:
    return FormTemplateIn(
        **{k: v for k, v in t.items() if k != "has_user_docx"},
        has_user_docx=has_user_docx(t),
    )


def _to_out(data: dict) -> AppSettings:
    return AppSettings(
        slots=[SlotIn(**s) for s in data["slots"]],
        layout=LayoutIn(**data["layout"]),
        custom_colors=list(data.get("custom_colors") or []),
        preset_colors=list(data.get("preset_colors") or []),
        form_templates=[_template_out(t) for t in data.get("form_templates") or []],
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
    if body.custom_colors is not None:
        patch["custom_colors"] = body.custom_colors
    if body.form_templates is not None:
        patch["form_templates"] = [
            t.model_dump(exclude={"has_user_docx"}) for t in body.form_templates
        ]
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


@router.post("/forms/{template_id}/reset", response_model=AppSettings)
def reset_form_template(template_id: str):
    current = get_settings()
    defaults = {t["id"]: t for t in default_form_templates()}
    if template_id not in defaults:
        raise HTTPException(status_code=400, detail="只能恢复内置表格模板")
    templates = [t for t in current.get("form_templates") or [] if t["id"] != template_id]
    templates.insert(0, defaults[template_id])
    data = update_settings({"form_templates": templates})
    reset_user_docx(template_id)
    return _to_out(data)


@router.post("/forms/{template_id}/docx", response_model=AppSettings)
async def upload_form_docx(template_id: str, file: UploadFile):
    name = (file.filename or "").lower()
    if not name.endswith(".docx"):
        raise HTTPException(status_code=400, detail="请上传 .docx 文件")
    raw = await file.read()
    if len(raw) < 100 or len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Word 模板文件无效或过大")
    try:
        get_form_template(template_id)
        save_user_docx(template_id, raw)
    except FormError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(get_settings())


@router.delete("/forms/{template_id}/docx", response_model=AppSettings)
def delete_form_docx(template_id: str):
    try:
        get_form_template(template_id)
        reset_user_docx(template_id)
    except FormError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(get_settings())

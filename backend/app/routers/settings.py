from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.settings_store import (
    DEFAULT_CLASSIFY_KEYWORDS,
    get_settings,
    reset_classify_keywords,
    update_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ClassifyKeywords(BaseModel):
    invoice: list[str] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)
    payment: list[str] = Field(default_factory=list)


class AppSettings(BaseModel):
    classify_keywords: ClassifyKeywords


class SettingsUpdate(BaseModel):
    classify_keywords: ClassifyKeywords | None = None


@router.get("", response_model=AppSettings)
def read_settings():
    data = get_settings()
    return AppSettings(classify_keywords=ClassifyKeywords(**data["classify_keywords"]))


@router.put("", response_model=AppSettings)
def put_settings(body: SettingsUpdate):
    patch = {}
    if body.classify_keywords is not None:
        patch["classify_keywords"] = body.classify_keywords.model_dump()
    data = update_settings(patch) if patch else get_settings()
    return AppSettings(classify_keywords=ClassifyKeywords(**data["classify_keywords"]))


@router.post("/classify-keywords/reset", response_model=AppSettings)
def reset_keywords():
    data = reset_classify_keywords()
    return AppSettings(classify_keywords=ClassifyKeywords(**data["classify_keywords"]))


@router.get("/classify-keywords/defaults", response_model=ClassifyKeywords)
def keyword_defaults():
    return ClassifyKeywords(**DEFAULT_CLASSIFY_KEYWORDS)

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MaterialType = Literal["invoice", "order", "payment", "unknown"]


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = ""


class EntryUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    note: Optional[str] = None


class MaterialOut(BaseModel):
    id: int
    entry_id: Optional[int]
    type: MaterialType
    original_name: str
    stored_path: str
    mime: str
    width: Optional[int]
    height: Optional[int]
    created_at: str
    url: str


class Completeness(BaseModel):
    complete: bool
    has_invoice: bool
    has_order: bool
    has_payment: bool
    missing: list[str]


class EntryOut(BaseModel):
    id: int
    title: str
    note: str
    created_at: str
    updated_at: str
    completeness: Completeness
    materials: list[MaterialOut] = []


class MaterialTypeUpdate(BaseModel):
    type: MaterialType


class MaterialAssign(BaseModel):
    entry_id: Optional[int] = None
    type: Optional[MaterialType] = None


class ClassifyConfirmItem(BaseModel):
    temp_id: str
    type: MaterialType
    entry_id: Optional[int] = None
    create_entry_title: Optional[str] = None


class ClassifyConfirmRequest(BaseModel):
    items: list[ClassifyConfirmItem]

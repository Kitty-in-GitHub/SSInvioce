from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MaterialType = Literal["invoice", "order", "payment", "unknown"]
AmountSource = Literal["auto", "manual", "empty"]


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = ""
    group_id: Optional[int] = None
    amount: Optional[float] = None


class EntryUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    note: Optional[str] = None
    group_id: Optional[int] = None
    amount: Optional[float] = None
    clear_group: bool = False


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
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    amount: Optional[float] = None
    amount_source: AmountSource = "empty"
    amount_auto: Optional[float] = None


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


class ComposeBatchRequest(BaseModel):
    entry_ids: list[int] = Field(min_length=1)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    note: str = ""


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    note: Optional[str] = None
    sort_order: Optional[int] = None


class GroupOut(BaseModel):
    id: int
    name: str
    note: str
    sort_order: int
    created_at: str
    updated_at: str
    entry_count: int = 0
    amount_sum: float = 0.0
    complete: bool = True
    incomplete_count: int = 0


class ReparseAmountRequest(BaseModel):
    force: bool = False

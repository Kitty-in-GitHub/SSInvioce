from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MaterialType = str
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
    expense_row: Optional[str] = None
    clear_expense_row: bool = False


class DuplicateWarning(BaseModel):
    reason: str
    invoice_number: Optional[str] = None
    existing_entry_id: Optional[int] = None
    existing_entry_title: Optional[str] = None
    existing_material_id: Optional[int] = None
    existing_original_name: Optional[str] = None
    existing_mime: Optional[str] = None
    peer_temp_id: Optional[str] = None


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
    invoice_number: Optional[str] = None
    invoice_code: Optional[str] = None
    content_sha256: Optional[str] = None
    duplicate_warning: Optional[DuplicateWarning] = None
    processing: bool = False


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
    expense_row: Optional[str] = None
    ledger_txn_id: Optional[int] = None


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


class ClassifyClusterMaterial(BaseModel):
    temp_id: str
    type: MaterialType


class ClassifyClusterConfirm(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: Optional[float] = None
    materials: list[ClassifyClusterMaterial] = Field(min_length=1)


class ClassifyConfirmRequest(BaseModel):
    items: list[ClassifyConfirmItem] = []
    clusters: list[ClassifyClusterConfirm] = []


class ComposeBatchRequest(BaseModel):
    entry_ids: list[int] = Field(min_length=1)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    note: str = ""


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    note: Optional[str] = None
    sort_order: Optional[int] = None
    budget: Optional[float] = None
    clear_budget: bool = False


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
    has_form: bool = False
    budget: Optional[float] = None


LedgerKind = Literal["income", "expense"]


class LedgerCategoryOut(BaseModel):
    id: str
    kind: LedgerKind
    name: str
    sort_order: int


class LedgerCategoryCreate(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    kind: LedgerKind
    name: str = Field(min_length=1, max_length=40)


class LedgerCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    sort_order: Optional[int] = None


class LedgerTxnOut(BaseModel):
    id: int
    kind: LedgerKind
    amount: float
    occurred_on: str
    title: str
    note: str
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    category_id: str
    category_name: str
    entry_id: Optional[int] = None
    entry_title: Optional[str] = None
    created_at: str


class LedgerTxnCreate(BaseModel):
    kind: LedgerKind
    amount: float
    occurred_on: Optional[str] = None
    title: str = Field(min_length=1, max_length=200)
    note: str = ""
    group_id: Optional[int] = None
    category_id: str


class LedgerTxnUpdate(BaseModel):
    amount: Optional[float] = None
    occurred_on: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    note: Optional[str] = None
    group_id: Optional[int] = None
    clear_group: bool = False
    category_id: Optional[str] = None


class LedgerFromEntry(BaseModel):
    category_id: Optional[str] = None
    occurred_on: Optional[str] = None
    note: str = ""
    group_id: Optional[int] = None
    clear_group: bool = False


class LedgerGroupBucket(BaseModel):
    group_id: Optional[int] = None
    group_name: str
    budget: Optional[float] = None
    expense_sum: float = 0.0
    income_sum: float = 0.0
    remaining: Optional[float] = None


class LedgerCategoryBucket(BaseModel):
    category_id: str
    kind: LedgerKind
    name: str
    amount_sum: float = 0.0


class LedgerSummary(BaseModel):
    income_sum: float
    expense_sum: float
    balance: float
    by_group: list[LedgerGroupBucket]
    by_category: list[LedgerCategoryBucket]


class ReparseAmountRequest(BaseModel):
    force: bool = False


AssetKind = Literal["durable", "consumable"]
AssetAction = Literal["in", "out", "borrow", "return", "adjust"]


class AssetOut(BaseModel):
    id: int
    kind: AssetKind
    name: str
    qty: float
    unit: str
    location: str
    note: str
    entry_id: Optional[int] = None
    entry_title: Optional[str] = None
    borrowed_qty: float = 0.0
    created_at: str
    updated_at: str


class AssetCreate(BaseModel):
    kind: AssetKind
    name: str = Field(min_length=1, max_length=200)
    qty: float = 0
    unit: str = ""
    location: str = ""
    note: str = ""
    entry_id: Optional[int] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    unit: Optional[str] = None
    location: Optional[str] = None
    note: Optional[str] = None
    entry_id: Optional[int] = None
    clear_entry: bool = False


class AssetTxnOut(BaseModel):
    id: int
    asset_id: int
    action: AssetAction
    qty: float
    person: str
    occurred_on: str
    note: str
    created_at: str


class AssetTxnCreate(BaseModel):
    action: AssetAction
    qty: float = 1
    person: str = ""
    occurred_on: Optional[str] = None
    note: str = ""

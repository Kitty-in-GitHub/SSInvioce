from __future__ import annotations

from pathlib import Path

from ..models import MaterialType
from .settings_store import get_slots, invoice_slot_id


def classify_file(
    filename: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> MaterialType:
    """Filename / extension heuristics only (no image aspect-ratio guessing)."""
    del width, height
    name = filename.lower()
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return invoice_slot_id()

    slots = [s for s in get_slots() if s.get("file_kind") == "image"]
    for slot in slots:
        for word in slot.get("keywords") or []:
            w = word.strip()
            if not w:
                continue
            if w in filename or w.lower() in name:
                return slot["id"]

    return "unknown"

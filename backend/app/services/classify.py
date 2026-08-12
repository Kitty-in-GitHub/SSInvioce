from __future__ import annotations

from pathlib import Path

from ..models import MaterialType
from .settings_store import get_classify_keywords


def classify_file(
    filename: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> MaterialType:
    """Filename / extension heuristics only (no image aspect-ratio guessing)."""
    del width, height  # kept for call-site compatibility
    name = filename.lower()
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return "invoice"

    keywords = get_classify_keywords()
    for word in keywords.get("payment", []):
        w = word.strip()
        if not w:
            continue
        if w in filename or w.lower() in name:
            return "payment"
    for word in keywords.get("order", []):
        w = word.strip()
        if not w:
            continue
        if w in filename or w.lower() in name:
            return "order"

    return "unknown"

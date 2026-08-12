from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymupdf as fitz

from ..logging_config import get_logger
from ..models import MaterialType
from .amount import parse_amount_from_filename, parse_amount_from_pdf_text
from .classify import classify_file
from .ocr import ocr_available, ocr_image
from .settings_store import get_classify_keywords
from .storage import resolve_stored

log = get_logger("features")

MERCHANT_RE = re.compile(
    r"(?:销售方|销\s*方|商家|店铺|收款方|商户名称)[:：\s]*([^\n\r]{2,40})",
    re.UNICODE,
)
DATE_RE = re.compile(
    r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})",
    re.UNICODE,
)
ORDER_NO_RE = re.compile(
    r"(?:订单号|订单编号|交易号|流水号|商户单号)[:：\s]*([A-Za-z0-9\-_]{6,40})",
    re.UNICODE,
)


@dataclass
class FileFeatures:
    temp_id: str = ""
    original_name: str = ""
    stored_path: str = ""
    suggested_type: MaterialType = "unknown"
    amount: float | None = None
    merchant: str | None = None
    date: str | None = None
    order_no: str | None = None
    text_preview: str = ""
    ocr_used: bool = False
    text_source: str = "none"  # pdf | ocr | filename | none

    def to_public(self) -> dict:
        return {
            "amount": self.amount,
            "merchant": self.merchant,
            "date": self.date,
            "order_no": self.order_no,
            "text_preview": self.text_preview[:240],
            "ocr_used": self.ocr_used,
            "text_source": self.text_source,
        }


def _pick_type_from_text(text: str, filename: str, width: int | None, height: int | None) -> MaterialType:
    compact = re.sub(r"\s+", "", text or "")
    keywords = get_classify_keywords()
    scores = {"invoice": 0, "order": 0, "payment": 0}
    for kind in ("invoice", "order", "payment"):
        for w in keywords.get(kind, []):
            word = (w or "").strip()
            if not word:
                continue
            if word in compact:
                scores[kind] += 2
            elif word in filename or word.lower() in filename.lower():
                scores[kind] += 1

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best  # type: ignore[return-value]

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "invoice"
    return classify_file(filename, width=width, height=height)


def _extract_merchant(text: str) -> str | None:
    m = MERCHANT_RE.search(text or "")
    if not m:
        return None
    name = re.sub(r"\s+", "", m.group(1)).strip(" :：|-_")
    return name[:40] or None


def _extract_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    return f"{y}-{mo:02d}-{d:02d}"


def _extract_order_no(text: str) -> str | None:
    m = ORDER_NO_RE.search(text or "")
    return m.group(1) if m else None


def _amount_float(val: Decimal | None) -> float | None:
    return float(val) if val is not None else None


def extract_text_for_file(*, abs_path: Path, original_name: str) -> tuple[str, str, bool]:
    """Returns (text, source, ocr_used)."""
    suffix = abs_path.suffix.lower()
    if suffix == ".pdf":
        try:
            doc = fitz.open(abs_path)
            try:
                pages = []
                for i in range(min(len(doc), 2)):
                    pages.append(doc[i].get_text() or "")
                text = "\n".join(pages).strip()
            finally:
                doc.close()
            if text:
                return text, "pdf", False
        except Exception:
            log.exception("pdf text failed name=%r", original_name)
        return "", "none", False

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        if ocr_available():
            text = ocr_image(abs_path).strip()
            if text:
                return text, "ocr", True
            return "", "ocr", True
        return "", "none", False
    return "", "none", False


def extract_features(
    *,
    temp_id: str,
    original_name: str,
    stored_path: str,
    abs_path: Path | None = None,
    width: int | None = None,
    height: int | None = None,
) -> FileFeatures:
    path = abs_path or resolve_stored(stored_path)
    text, source, ocr_used = extract_text_for_file(abs_path=path, original_name=original_name)
    from_text = _amount_float(parse_amount_from_pdf_text(text)) if text else None
    from_name = _amount_float(parse_amount_from_filename(original_name))
    # Prefer explicit filename money token when present (e.g. 260509_12.00_xxx.pdf)
    amount = from_name if from_name is not None else from_text

    suggested = _pick_type_from_text(text, original_name, width, height)
    feat = FileFeatures(
        temp_id=temp_id,
        original_name=original_name,
        stored_path=stored_path,
        suggested_type=suggested,
        amount=amount,
        merchant=_extract_merchant(text) if text else None,
        date=_extract_date(text) if text else None,
        order_no=_extract_order_no(text) if text else None,
        text_preview=(text or "")[:400],
        ocr_used=ocr_used,
        text_source=source,
    )
    log.info(
        "features name=%r type=%s amount=%s source=%s ocr=%s",
        original_name,
        suggested,
        amount,
        source,
        ocr_used,
    )
    return feat

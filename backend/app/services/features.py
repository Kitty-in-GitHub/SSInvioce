from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..logging_config import get_logger
from ..models import MaterialType
from .amount import parse_amount_from_filename, parse_amount_from_pdf_text
from .classify import classify_file
from .ocr import ocr_available, ocr_image
from .settings_store import get_classify_keywords
from .storage import resolve_stored

log = get_logger("features")

MERCHANT_FULL_RE = re.compile(
    r"商户全称[:：\s]*([^\n\r收单支付交易]{2,40})",
    re.UNICODE,
)
# Require delimiter after label so "销售方信息项目名称…" is not captured.
MERCHANT_LABELED_RE = re.compile(
    r"(?:商户名称|店铺|收款方|商家(?!小程序)|销售方|销\s*方)[:：]\s*([^\n\r]{2,40})",
    re.UNICODE,
)
# E-invoice: buyer then seller blocks each have 名称:XXX
INVOICE_NAME_RE = re.compile(
    r"名称[:：]\s*([^\n\r统一社会信用]{2,40})",
    re.UNICODE,
)
INVOICE_NAME_COMPACT_RE = re.compile(
    r"名称[:：]([\u4e00-\u9fffA-Za-z0-9（）()]{2,40}?)(?=统一社会信用代码|纳税人识别号|$)",
    re.UNICODE,
)
TAX_PRODUCT_RE = re.compile(r"\*([^*\n]{1,30})\*([^*\n]{1,40})", re.UNICODE)
INVOICE_DATE_RE = re.compile(
    r"开票日期[:：\s]*(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})",
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
INVOICE_NUMBER_RE = re.compile(r"发票号码[:：\s]*([0-9０-９]{8,30})", re.UNICODE)
INVOICE_CODE_RE = re.compile(r"发票代码[:：\s]*([0-9０-９]{8,20})", re.UNICODE)

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

_HEADER_NOISE = (
    "项目名称",
    "规格型号",
    "单位",
    "数量",
    "单价",
    "金额",
    "税率",
    "税额",
    "合计",
    "价税合计",
    "购买方",
    "销售方",
    "信息",
)


@dataclass
class FileFeatures:
    temp_id: str = ""
    original_name: str = ""
    stored_path: str = ""
    suggested_type: MaterialType = "unknown"
    amount: float | None = None
    merchant: str | None = None
    product_name: str | None = None
    date: str | None = None
    order_no: str | None = None
    invoice_number: str | None = None
    invoice_code: str | None = None
    content_sha256: str | None = None
    text_preview: str = ""
    ocr_used: bool = False
    text_source: str = "none"  # pdf | ocr | filename | none

    def to_public(self) -> dict:
        return {
            "amount": self.amount,
            "merchant": self.merchant,
            "product_name": self.product_name,
            "date": self.date,
            "order_no": self.order_no,
            "invoice_number": self.invoice_number,
            "invoice_code": self.invoice_code,
            "content_sha256": self.content_sha256,
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


def _clean_org_name(name: str) -> str | None:
    name = re.sub(r"\s+", "", name or "").strip(" :：|-_")
    for stop in (
        "收单机构",
        "支付方式",
        "交易单号",
        "商户单号",
        "当前状态",
        "支付时间",
        "统一社会信用代码",
        "纳税人识别号",
        "项目名称",
    ):
        if stop in name:
            name = name.split(stop, 1)[0]
    name = name[:40]
    if not name or name in {"小程序", "商家小程序"}:
        return None
    if any(tok in name for tok in ("项目名称", "规格型号", "价税合计", "¥", "￥")):
        return None
    if not re.search(r"(公司|店|中心|厂|行|局|院|所|部|社|集团|大学|学院)", name):
        # Allow short shop-like names without suffix only if mostly CJK and short
        if not (2 <= len(name) <= 16 and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()]+", name)):
            return None
    return name


def _extract_merchant(text: str) -> str | None:
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)

    m = MERCHANT_FULL_RE.search(raw) or MERCHANT_FULL_RE.search(compact)
    if m:
        name = _clean_org_name(m.group(1))
        if name:
            return name

    m = MERCHANT_LABELED_RE.search(raw) or MERCHANT_LABELED_RE.search(compact)
    if m:
        name = _clean_org_name(m.group(1))
        if name:
            return name

    # E-invoice: prefer seller = last 名称: block (buyer first, seller second)
    names = INVOICE_NAME_COMPACT_RE.findall(compact) or [
        x for x in INVOICE_NAME_RE.findall(raw)
    ]
    cleaned = [_clean_org_name(n) for n in names]
    cleaned = [n for n in cleaned if n]
    if cleaned:
        return cleaned[-1]

    # WeChat bill: merchant line sits above signed amount "-30.09"
    m = re.search(r"([\u4e00-\u9fff]{4,40}(?:公司|店|中心))[-－−+]\d+\.\d{2}", compact)
    if m:
        return _clean_org_name(m.group(1))
    return None


def _extract_product_name(text: str) -> str | None:
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)

    # Tax-class abbreviation: *快递服务*快递费
    m = TAX_PRODUCT_RE.search(raw) or TAX_PRODUCT_RE.search(compact)
    if m:
        product = re.sub(r"\s+", "", m.group(2)).strip(" :：|-_*")
        if product and not any(h in product for h in _HEADER_NOISE):
            return product[:40]

    # After 项目名称 header, take first plausible Chinese goods phrase
    m = re.search(
        r"项目名称.{0,80}?([\u4e00-\u9fff]{2,20})(?=PCS|规格|数量|单价|金额|\d|¥|￥|$)",
        compact,
    )
    if m:
        product = m.group(1)
        if product and not any(h in product for h in _HEADER_NOISE):
            return product[:40]
    return None


def _format_date(y: str, mo: str | int, d: str | int) -> str:
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _extract_date(text: str) -> str | None:
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)
    m = INVOICE_DATE_RE.search(raw) or INVOICE_DATE_RE.search(compact)
    if m:
        return _format_date(m.group(1), m.group(2), m.group(3))
    m = DATE_RE.search(raw) or DATE_RE.search(compact)
    if not m:
        return None
    return _format_date(m.group(1), m.group(2), m.group(3))


def _extract_order_no(text: str) -> str | None:
    m = ORDER_NO_RE.search(text or "")
    return m.group(1) if m else None


def normalize_invoice_digits(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\s+", "", str(raw)).translate(_FULLWIDTH_DIGITS)
    s = re.sub(r"[^\d]", "", s)
    return s or None


def _extract_invoice_number(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    m = INVOICE_NUMBER_RE.search(text or "") or INVOICE_NUMBER_RE.search(compact)
    return normalize_invoice_digits(m.group(1)) if m else None


def _extract_invoice_code(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    m = INVOICE_CODE_RE.search(text or "") or INVOICE_CODE_RE.search(compact)
    return normalize_invoice_digits(m.group(1)) if m else None


def file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 256), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        log.exception("sha256 failed path=%s", path)
        return None


def _amount_float(val: Decimal | None) -> float | None:
    return float(val) if val is not None else None


def extract_text_for_file(*, abs_path: Path, original_name: str) -> tuple[str, str, bool]:
    """Returns (text, source, ocr_used)."""
    suffix = abs_path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pymupdf as fitz

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
    merchant = _extract_merchant(text) if text else None
    product_name = _extract_product_name(text) if text else None
    date = _extract_date(text) if text else None
    invoice_number = _extract_invoice_number(text) if text else None
    invoice_code = _extract_invoice_code(text) if text else None
    content_sha256 = file_sha256(path) if path.exists() else None
    feat = FileFeatures(
        temp_id=temp_id,
        original_name=original_name,
        stored_path=stored_path,
        suggested_type=suggested,
        amount=amount,
        merchant=merchant,
        product_name=product_name,
        date=date,
        order_no=_extract_order_no(text) if text else None,
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        content_sha256=content_sha256,
        text_preview=(text or "")[:400],
        ocr_used=ocr_used,
        text_source=source,
    )
    log.info(
        "features name=%r type=%s amount=%s product=%s merchant=%s date=%s inv=%s source=%s ocr=%s",
        original_name,
        suggested,
        amount,
        product_name,
        merchant,
        date,
        invoice_number,
        source,
        ocr_used,
    )
    return feat

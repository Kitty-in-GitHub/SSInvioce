from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..logging_config import get_logger
from ..models import MaterialType
from .amount import parse_amount_from_filename, parse_amount_from_pdf_text
from .classify import classify_file
from .ocr import ocr_available, ocr_image, ocr_image_with_lines
from .settings_store import invoice_slot_id
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
ORDER_NO_LABELS = (
    "订单编号", "订单号", "支付宝交易号", "微信支付交易单号",
    "交易号", "流水号", "商户单号", "商家订单号",
)
ORDER_NO_RE = re.compile(
    r"(?:订单编号|订单号|支付宝交易号|微信支付交易单号|交易号|流水号|商户单号|商家订单号)"
    r"[^\d]{0,40}([A-Za-z0-9\-_]{6,40})",
    re.UNICODE,
)
# Order number candidates must NOT look like a masked phone, date, or other noise.
_ORDER_NO_SKIP = re.compile(r"[*]|^\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}")
# Pure numeric: >= 12 digits (typical order nos are 16-28 digits)
# Alphanumeric: >= 8 chars, must have at least 2 letters
_ORDER_NO_PURE_DIGIT = re.compile(r"^\d{12,}$")
_ORDER_NO_ALNUM = re.compile(r"^[A-Za-z0-9]{8,}$")
INVOICE_NUMBER_RE = re.compile(r"发票号码[:：\s]*([0-9０-９]{8,30})", re.UNICODE)
# 新版电子发票把标签和值分到不同文本块，号码会与开票日期粘在一起：
# "<20位号码><YYYY>年<MM>月<DD>日"
INVOICE_NUMBER_MERGED_RE = re.compile(
    r"(?<!\d)(\d{20})(?=20\d{2}年\d{1,2}月\d{1,2}日)",
    re.UNICODE,
)
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
    ocr_lines: list[dict] = None  # type: ignore[assignment]  # populated when source=="ocr"

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
            "ocr_lines": self.ocr_lines or [],
        }


def feature_to_json(feat: FileFeatures) -> str:
    """Serialize features into materials.features_json (used by staging/inbox)."""
    payload = feat.to_public()
    payload["suggested_type"] = feat.suggested_type
    return json.dumps(payload, ensure_ascii=False)


def feature_from_json(raw: str | None) -> FileFeatures | None:
    """Rebuild FileFeatures from materials.features_json; None when absent/broken."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return FileFeatures(
        temp_id="",
        suggested_type=str(data.get("suggested_type") or "unknown"),
        amount=data.get("amount"),
        merchant=data.get("merchant"),
        product_name=data.get("product_name"),
        date=data.get("date"),
        order_no=data.get("order_no"),
        invoice_number=data.get("invoice_number"),
        invoice_code=data.get("invoice_code"),
        content_sha256=data.get("content_sha256"),
        text_preview=str(data.get("text_preview") or ""),
        ocr_used=bool(data.get("ocr_used")),
        text_source=str(data.get("text_source") or "none"),
        ocr_lines=data.get("ocr_lines") if isinstance(data.get("ocr_lines"), list) else None,
    )


def _pick_type_from_text(text: str, filename: str, width: int | None, height: int | None) -> MaterialType:
    compact = re.sub(r"\s+", "", text or "")
    from .settings_store import file_kind_for, get_slots, invoice_slot_id

    suffix = Path(filename).suffix.lower()
    want_kind = "pdf" if suffix == ".pdf" else "image"
    slots = [s for s in get_slots() if s.get("file_kind") == want_kind]
    if not slots:
        slots = get_slots()

    scores = {s["id"]: 0 for s in slots}
    for slot in slots:
        for w in slot.get("keywords") or []:
            word = (w or "").strip()
            if not word:
                continue
            if word in compact:
                scores[slot["id"]] += 2
            elif word in filename or word.lower() in filename.lower():
                scores[slot["id"]] += 1

    best = max(scores, key=scores.get) if scores else None
    if best and scores[best] > 0:
        return best

    if suffix == ".pdf":
        return invoice_slot_id()
    return classify_file(filename, width=width, height=height)


def _clean_org_name(name: str) -> str | None:
    name = re.sub(r"\s+", "", name or "").strip(" :：|-_")
    # 标签本身被当成"名称:"的值抓到时丢弃
    if name in {"名称", "购买方", "销售方", "信息", "购买方信息", "销售方信息", "销方", "购方"}:
        return None
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
    log.debug("merchant input=%s", compact[:200])

    m = MERCHANT_FULL_RE.search(raw) or MERCHANT_FULL_RE.search(compact)
    if m:
        name = _clean_org_name(m.group(1))
        log.debug("merchant hit MERCHANT_FULL_RE group1=%s → %s", m.group(1), name)
        if name:
            return name

    m = MERCHANT_LABELED_RE.search(raw) or MERCHANT_LABELED_RE.search(compact)
    if m:
        name = _clean_org_name(m.group(1))
        log.debug("merchant hit MERCHANT_LABELED_RE group1=%s → %s", m.group(1), name)
        if name:
            return name

    # E-invoice: prefer seller = last 名称: block (buyer first, seller second)
    names = INVOICE_NAME_COMPACT_RE.findall(compact) or [
        x for x in INVOICE_NAME_RE.findall(raw)
    ]
    cleaned = [_clean_org_name(n) for n in names]
    cleaned = [n for n in cleaned if n]
    if cleaned:
        log.debug("merchant hit INVOICE_NAME_RE names=%s → %s", names, cleaned[-1])
        return cleaned[-1]

    # WeChat bill: merchant line sits above signed amount "-30.09"
    m = re.search(r"([\u4e00-\u9fff]{4,40}(?:公司|店|中心))[-－−+]\d+\.\d{2}", compact)
    if m:
        return _clean_org_name(m.group(1))
    return None


def _extract_product_name(text: str) -> str | None:
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)
    log.debug("product input=%s", compact[:200])

    # Tax-class abbreviation: *快递服务*快递费
    m = TAX_PRODUCT_RE.search(raw) or TAX_PRODUCT_RE.search(compact)
    if m:
        product = re.sub(r"\s+", "", m.group(2)).strip(" :：|-_*")
        if product and not any(h in product for h in _HEADER_NOISE):
            log.debug("product hit TAX_PRODUCT_RE group2=%s → %s", m.group(2), product)
            return product[:40]

    # After 项目名称 header, take first plausible Chinese goods phrase
    m = re.search(
        r"项目名称.{0,80}?([\u4e00-\u9fff]{2,20})(?=PCS|规格|数量|单价|金额|\d|¥|￥|$)",
        compact,
    )
    if m:
        product = m.group(1)
        if product and not any(h in product for h in _HEADER_NOISE):
            log.debug("product hit 项目名称 rule group1=%s → %s", m.group(1), product)
            return product[:40]
    log.debug("product no match")
    return None


def _format_date(y: str, mo: str | int, d: str | int) -> str:
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _extract_date(text: str) -> str | None:
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)
    log.debug("date input=%s", compact[:200])
    m = INVOICE_DATE_RE.search(raw) or INVOICE_DATE_RE.search(compact)
    if m:
        res = _format_date(m.group(1), m.group(2), m.group(3))
        log.debug("date hit INVOICE_DATE_RE → %s", res)
        return res
    m = DATE_RE.search(raw) or DATE_RE.search(compact)
    if not m:
        log.debug("date no match")
        return None
    res = _format_date(m.group(1), m.group(2), m.group(3))
    log.debug("date hit DATE_RE → %s", res)
    return res


def _extract_order_no(text: str) -> str | None:
    m = ORDER_NO_RE.search(text or "")
    if m:
        val = m.group(1)
        if _is_plausible_order_no(val):
            log.debug("order_no regex hit=%s", val)
            return val
    log.debug("order_no regex no match")
    return None


def _is_plausible_order_no(val: str) -> bool:
    """Post-filter: reject masked phones, dates, too-short strings."""
    if not val or len(val) < 6 or len(val) > 40:
        return False
    if _ORDER_NO_SKIP.search(val):
        return False
    # Pure digit must be long enough (>=12 digits); avoid matching 11-digit phones
    if _ORDER_NO_PURE_DIGIT.match(val):
        return True
    # Alphanumeric: needs at least 1 letter to distinguish from plain numbers
    if _ORDER_NO_ALNUM.match(val) and re.search(r"[A-Za-z]", val):
        return True
    return False


def _extract_order_no_via_bbox(blocks: list[dict]) -> str | None:
    """Find order number by bbox spatial matching.

    Strategy:
      1. Find label blocks matching ORDER_NO_LABELS (dedupe: prefer longest hit)
      2. Sort labels by y-center (top of page first — 订单编号 > 支付宝交易号)
      3. For each label, look in a y-window of ±30px for plausible candidates
      4. Pick the closest candidate by x-distance to the label
      5. Return the FIRST label's result (topmost label wins)
    """
    if not blocks:
        return None

    # Step 1: find label blocks, deduplicated — prefer the longest matching label
    # (e.g. "订单编号" over "订单号", since "订单号" is a substring of "订单编号")
    label_blocks: list[tuple[float, dict]] = []  # (y_center, block)
    seen_blocks: set[int] = set()  # block id for dedup
    for lb in sorted(ORDER_NO_LABELS, key=len, reverse=True):
        for idx, b in enumerate(blocks):
            if idx in seen_blocks:
                continue
            t = b.get("text", "").strip()
            if lb in t:
                yc = (b["y0"] + b["y1"]) / 2
                label_blocks.append((yc, b))
                seen_blocks.add(idx)
                break

    if not label_blocks:
        log.debug("order_no bbox: no label blocks found")
        return None

    # Step 2: sort by y-center (top of page first)
    label_blocks.sort(key=lambda x: x[0])

    # Step 3: try each label in y-order; first one with a candidate wins
    for _yc, lbl in label_blocks:
        lbl_y_center = (lbl["y0"] + lbl["y1"]) / 2
        lbl_x1 = lbl["x1"]

        best_val: str | None = None
        best_dist = float("inf")

        for b in blocks:
            if b is lbl:
                continue
            if b.get("x0") is None:
                continue
            byc = (b["y0"] + b["y1"]) / 2
            if abs(byc - lbl_y_center) > 30.0:
                continue
            t = b.get("text", "").strip()
            if not t:
                continue
            if t in ORDER_NO_LABELS:
                continue

            if not _is_plausible_order_no(t):
                continue

            # Prefer values that are clearly to the right and close
            x_dist = b["x0"] - lbl_x1
            if -10 <= x_dist <= 250 and x_dist < best_dist:
                best_dist = x_dist
                best_val = t

        if best_val:
            log.info("order_no via bbox label=%r → %s", lbl["text"], best_val)
            return best_val

    return None


def normalize_invoice_digits(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\s+", "", str(raw)).translate(_FULLWIDTH_DIGITS)
    s = re.sub(r"[^\d]", "", s)
    return s or None


def _extract_invoice_number(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    log.debug("inv_number input=%s", compact[:200])
    m = INVOICE_NUMBER_RE.search(text or "") or INVOICE_NUMBER_RE.search(compact)
    if m:
        res = normalize_invoice_digits(m.group(1))
        log.debug("inv_number hit INVOICE_NUMBER_RE group1=%s → %s", m.group(1), res)
        return res
    m = INVOICE_NUMBER_MERGED_RE.search(compact)
    if m:
        res = normalize_invoice_digits(m.group(1))
        log.debug("inv_number hit INVOICE_NUMBER_MERGED_RE group1=%s → %s", m.group(1), res)
        return res
    # 标签存在但值被排版拆开时，退化为唯一的独立 20 位号码
    if "发票号码" in (text or ""):
        hits = set(re.findall(r"(?<!\d)(\d{20})(?!\d)", compact))
        log.debug("inv_number fallback label-present hits=%s", hits)
        if len(hits) == 1:
            return normalize_invoice_digits(hits.pop())
    log.debug("inv_number no match")
    return None


def _extract_invoice_code(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    m = INVOICE_CODE_RE.search(text or "") or INVOICE_CODE_RE.search(compact)
    res = normalize_invoice_digits(m.group(1)) if m else None
    log.debug("inv_code input=%s hit=%s → %s", compact[:120], m.group(1) if m else None, res)
    return res


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


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _merge_vertical_labels(blocks: list[dict]) -> list[dict]:
    """Merge vertical label fragments (e.g. 销/售/方/信/息 → 销售方信息).

    Finds sequences of blocks that share roughly the same x-range, have
    small y gaps (6-14 px), and each span only 1-2 CJK chars.
    """
    if len(blocks) < 2:
        return blocks

    blocks_sorted = sorted(blocks, key=lambda b: ((b["y0"] + b["y1"]) / 2))
    merged: list[dict] = []
    i = 0
    while i < len(blocks_sorted):
        cur = blocks_sorted[i]
        # 1-2 CJK chars only
        if len(cur["text"]) > 2 or not _CJK_RE.fullmatch(cur["text"]):
            merged.append(cur)
            i += 1
            continue

        x_center_cur = (cur["x0"] + cur["x1"]) / 2
        fragments = [cur]
        j = i + 1
        while j < len(blocks_sorted):
            nxt = blocks_sorted[j]
            # next must also be 1-2 CJK chars
            if len(nxt["text"]) > 2 or not _CJK_RE.fullmatch(nxt["text"]):
                break
            # x must be roughly the same vertical column (±25px)
            x_center_nxt = (nxt["x0"] + nxt["x1"]) / 2
            if abs(x_center_cur - x_center_nxt) > 25:
                break
            # y gap small enough to be vertical stacking
            y_gap = nxt["y0"] - fragments[-1]["y1"]
            if y_gap < -5 or y_gap > 18:
                break
            fragments.append(nxt)
            j += 1

        if len(fragments) >= 3:
            # merge into one semantic block
            merged_text = "".join(f["text"] for f in fragments)
            merged_block = {
                "text": merged_text,
                "source": cur.get("source", "pdf"),
                "score": cur.get("score"),
                "box": None,
                "x0": min(f["x0"] for f in fragments),
                "y0": min(f["y0"] for f in fragments),
                "x1": max(f["x1"] for f in fragments),
                "y1": max(f["y1"] for f in fragments),
            }
            merged.append(merged_block)
            i = j
        else:
            merged.append(cur)
            i += 1

    return merged


def _blocks_to_text(blocks: list[dict]) -> str:
    """Reconstruct human-readable text from blocks with bbox coordinates.

    Pipeline:
      1. Merge vertical labels (销/售/方/信/息 → 销售方信息).
      2. Sort blocks by y-center, cluster into visual rows via gap threshold.
      3. Within each row, sort left→right by x0 and join with space.
    """
    if not blocks:
        return ""

    # step 1: filter + merge vertical labels
    filtered = [
        b for b in blocks
        if b.get("text", "").strip() and b.get("y0") is not None
    ]
    if not filtered:
        return ""

    filtered = _merge_vertical_labels(filtered)

    # step 2: sort by y-center
    filtered.sort(key=lambda b: (b["y0"] + b["y1"]) / 2)

    # step 3: find row-cutting gap threshold
    y_centers = [(b["y0"] + b["y1"]) / 2 for b in filtered]
    gaps = [y_centers[i + 1] - y_centers[i] for i in range(len(y_centers) - 1)]
    avg_gap = sum(gaps) / len(gaps) if gaps else 8.0
    cut_threshold = avg_gap * 1.8

    # step 4: cluster into rows
    rows: list[list[dict]] = []
    current_row: list[dict] = [filtered[0]]
    for idx in range(len(gaps)):
        if gaps[idx] > cut_threshold:
            rows.append(current_row)
            current_row = [filtered[idx + 1]]
        else:
            current_row.append(filtered[idx + 1])
    rows.append(current_row)

    # step 5: within each row sort left→right and join
    lines: list[str] = []
    for row in rows:
        row_sorted = sorted(row, key=lambda b: b["x0"])
        line = " ".join(b["text"].strip() for b in row_sorted)
        if line:
            lines.append(line)

    return "\n".join(lines)


def extract_text_for_file(*, abs_path: Path, original_name: str) -> tuple[str, str, bool, list[dict]]:
    """Returns (text, source, ocr_used, text_blocks).

    text_blocks: unified row dicts for BOTH sources — each has text, source,
    score (None for pdf), box (None for pdf), and x0/y0/x1/y1 for spatial matching.
    For PDF we extract per-span bbox; for OCR we convert RapidOCR's 4-corner box.
    """
    suffix = abs_path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pymupdf as fitz

            doc = fitz.open(abs_path)
            try:
                pages_blocks: list[dict] = []
                for i in range(min(len(doc), 2)):
                    page = doc[i]
                    d = page.get_text("dict")
                    for block in d.get("blocks", []):
                        if "lines" not in block:
                            continue
                        for ln in block["lines"]:
                            for span in ln["spans"]:
                                t = span["text"].strip()
                                if not t:
                                    continue
                                bb = span["bbox"]  # (x0, y0, x1, y1)
                                pages_blocks.append({
                                    "text": t,
                                    "source": "pdf",
                                    "score": None,
                                    "box": None,
                                    "x0": round(bb[0], 1),
                                    "y0": round(bb[1], 1),
                                    "x1": round(bb[2], 1),
                                    "y1": round(bb[3], 1),
                                })
                text = _blocks_to_text(pages_blocks)
            finally:
                doc.close()
            if text:
                return text, "pdf", False, pages_blocks
        except Exception:
            log.exception("pdf text failed name=%r", original_name)
            return "", "none", False, []

        # 扫描版 PDF 没有文本层 → 渲染页面做 OCR
        if ocr_available():
            try:
                import pymupdf as fitz

                doc = fitz.open(abs_path)
                try:
                    pix = doc[0].get_pixmap(dpi=300)
                    with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False
                    ) as f:
                        tmp_png = f.name
                    try:
                        pix.save(tmp_png)
                        _ocr_text, lines = ocr_image_with_lines(tmp_png)
                    finally:
                        try:
                            os.unlink(tmp_png)
                        except OSError:
                            pass
                finally:
                    doc.close()
                for r in lines:
                    r["source"] = "ocr"
                    box = r.get("box")
                    if box and len(box) >= 4:
                        # RapidOCR returns [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        r["x0"] = round(min(xs), 1)
                        r["y0"] = round(min(ys), 1)
                        r["x1"] = round(max(xs), 1)
                        r["y1"] = round(max(ys), 1)
                    else:
                        r["x0"] = r["y0"] = r["x1"] = r["y1"] = None
                text = _blocks_to_text(lines)
                return text, "ocr", True, lines
            except Exception:
                log.exception("pdf ocr failed name=%r", original_name)

        return "", "none", False, []

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        if ocr_available():
            _ocr_text, lines = ocr_image_with_lines(abs_path)
            for r in lines:
                r["source"] = "ocr"
                box = r.get("box")
                if box and len(box) >= 4:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    r["x0"] = round(min(xs), 1)
                    r["y0"] = round(min(ys), 1)
                    r["x1"] = round(max(xs), 1)
                    r["y1"] = round(max(ys), 1)
                else:
                    r["x0"] = r["y0"] = r["x1"] = r["y1"] = None
            text = _blocks_to_text(lines)
            if text:
                return text, "ocr", True, lines
            return "", "ocr", True, lines
        return "", "none", False, []
    return "", "none", False, []


# ── Layout-based field extractor (for templates) ─────────────────────
# Splits invoice into spatial zones by y-coordinate, then uses label→value
# row matching within each zone. Independent of text ordering.
#
# Template constants below are loaded from settings when available, or
# fall back to defaults for Chinese electronic invoices (普票 / 专票).
# Future: user-editable templates in Settings.vue.

ZONE_HEADER = "header"         # y < 60:     title, invoice number, date
ZONE_BUYER_SELLER = "bs"       # y 60-145:   buyer(left) + seller(right)
ZONE_TABLE = "table"           # y 145-270:  goods table
ZONE_TOTALS = "totals"         # y 270-305:  合计, 价税合计(大写/小写)
ZONE_FOOTER = "footer"         # y > 305:    备注, 开票人


def _classify_zones(blocks: list[dict]) -> tuple[dict[str, list[dict]], float]:
    """Group blocks into 5 spatial zones by y-center.

    Returns (zone_blocks dict, page_width).
    """
    zones: dict[str, list[dict]] = {
        ZONE_HEADER: [], ZONE_BUYER_SELLER: [], ZONE_TABLE: [],
        ZONE_TOTALS: [], ZONE_FOOTER: [],
    }
    page_w = 0.0
    for b in blocks:
        if b.get("y0") is None:
            continue
        page_w = max(page_w, b.get("x1", 0) or 0)
        yc = (b["y0"] + b["y1"]) / 2
        if yc < 60:
            zones[ZONE_HEADER].append(b)
        elif yc < 145:
            zones[ZONE_BUYER_SELLER].append(b)
        elif yc < 270:
            zones[ZONE_TABLE].append(b)
        elif yc < 305:
            zones[ZONE_TOTALS].append(b)
        else:
            zones[ZONE_FOOTER].append(b)
    return zones, page_w


def _split_buyer_seller(blocks: list[dict], page_w: float) -> tuple[list[dict], list[dict]]:
    """Split the buyer+seller zone into left (buyer) and right (seller) by page mid-x."""
    mid = page_w / 2 if page_w else 300
    buyer = [b for b in blocks if (b["x0"] + b["x1"]) / 2 < mid]
    seller = [b for b in blocks if (b["x0"] + b["x1"]) / 2 >= mid]
    return buyer, seller


def _find_value_after_label(
    zone_blocks: list[dict],
    labels: list[str],
    *,
    same_row_tol: float = 12.0,
    digit_only: bool = False,
    date_match: bool = False,
) -> str | None:
    """Find the value block that sits to the right of any of the given labels.

    Search:
      1. Find all label blocks whose text starts_with one of `labels`
      2. For each label, find blocks on the same row, to the right
      3. Apply post-filter: digit_only (8-30 digits), date_match (date regex)
      4. Return the first match
    """
    label_blocks: list[dict] = []
    for lb in labels:
        label_blocks.extend(_find_block_by_text(zone_blocks, lb, starts_with=True, exclude_text=None) for _ in [1])
    # _find_block_by_text returns one; collect fresh per-label
    label_blocks = []
    for lb in labels:
        found = _find_block_by_text(zone_blocks, lb, starts_with=True)
        if found:
            label_blocks.append(found)

    if not label_blocks:
        return None

    for lbl in label_blocks:
        right_vals = _blocks_right_of(zone_blocks, lbl, skip_self=False)
        for v in right_vals:
            t = v["text"].strip()
            if not t:
                continue
            if digit_only:
                digits = re.sub(r"\D", "", t)
                if 8 <= len(digits) <= 30:
                    res = normalize_invoice_digits(digits)
                    if res:
                        log.debug("layout label=%r → value=%r → %s", lbl["text"], t, res)
                        return res
            elif date_match:
                m = INVOICE_DATE_RE.search(t) or DATE_RE.search(t)
                if m:
                    return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
            else:
                # free-form value: skip known header-like noise
                SKIP = {"项目名称", "规格型号", "单位", "数量", "单价", "金额",
                        "税率/征收率", "税额", "合", "计", "名称", "名称："}
                if t in SKIP or len(t) < 2:
                    continue
                res = _clean_org_name(t)
                if res:
                    log.debug("layout label=%r → value=%r → %s", lbl["text"], t, res)
                    return res
    return None


def _extract_amount_via_layout(totals_blocks: list[dict]) -> float | None:
    """Find the grand total (价税合计小写) from the totals zone.

    Strategy (in order of preference):
      1. Find '（小写）' or '小写' label → right neighbor on same row
      2. Find the LAST '¥' label in the zone (top-to-bottom, right-to-left)
         → right neighbor on same row
      3. Find '价税合计' label → nearest numeric value on the same row
    """
    if not totals_blocks:
        return None

    # 1. Prefer 小写 label
    xiaoxie = _find_block_by_text(totals_blocks, "小写", starts_with=False)
    if xiaoxie:
        right_vals = _blocks_right_of(totals_blocks, xiaoxie)
        for v in right_vals:
            t = v["text"].strip().lstrip("¥￥")
            try:
                val = float(t)
                log.debug("layout amount via 小写 label → %s", val)
                return val
            except ValueError:
                pass

    # 2. Last ¥ label (bottom-rightmost)
    yen_labels = [b for b in totals_blocks if b["text"].strip() in ("¥", "￥")]
    if yen_labels:
        # bottom-most first; within same y, right-most first
        yen_labels.sort(key=lambda b: ((b["y0"] + b["y1"]) / 2, b["x0"]), reverse=True)
        for lbl in yen_labels:
            right_vals = _blocks_right_of(totals_blocks, lbl)
            for v in right_vals:
                t = v["text"].strip()
                try:
                    val = float(t)
                    log.debug("layout amount via last ¥ label → %s", val)
                    return val
                except ValueError:
                    pass

    # 3. 价税合计 label + right numeric
    jiahui = _find_block_by_text(totals_blocks, "价税合计", starts_with=False)
    if jiahui:
        right_vals = _blocks_right_of(totals_blocks, jiahui)
        for v in right_vals:
            t = v["text"].strip().lstrip("¥￥")
            try:
                val = float(t)
                log.debug("layout amount via 价税合计 → %s", val)
                return val
            except ValueError:
                pass

    log.debug("layout amount no match in totals zone")
    return None


def _extract_product_via_layout(table_blocks: list[dict]) -> str | None:
    """Find the first tax-class product name from the goods table.

    Table columns are (roughly): 项目名称 | 规格型号 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额
    We look for blocks that start with '*' (tax-class marker) — standard
    electronic invoice product format: *大类*细类商品名.
    """
    if not table_blocks:
        return None

    # Prefer blocks starting with '*' — that's the tax-class line
    stars = [b for b in table_blocks if b["text"].strip().startswith("*")]
    stars.sort(key=lambda b: (b["y0"] + b["y1"]) / 2)
    if stars:
        val = stars[0]["text"].strip()
        if len(val) < 40:
            log.debug("layout product via tax-class marker → %s", val)
            return val

    # Fallback: first non-header, non-numeric CJK phrase in the table
    HEADER = {"项目名称", "规格型号", "单  位", "单位", "数  量", "数量",
              "单  价", "单价", "金  额", "金额", "税率/征收率", "税  额", "税额"}
    for b in table_blocks:
        t = b["text"].strip()
        if not t or t in HEADER:
            continue
        # Must contain CJK and be plausible length
        if 2 <= len(t) <= 40 and _CJK_RE.search(t):
            # skip pure numbers
            if re.fullmatch(r"[\d.]+", t):
                continue
            log.debug("layout product fallback → %s", t)
            return t
    return None


def extract_invoice_fields_by_layout(blocks: list[dict]) -> dict:
    """Main entry: extract invoice fields purely from spatial layout.

    Returns dict with keys: invoice_number, invoice_code, date,
    buyer_name, buyer_tax_id, seller_name, seller_tax_id,
    product_name, amount. Missing values are None.
    """
    result: dict[str, str | float | None] = {
        "invoice_number": None, "invoice_code": None, "date": None,
        "buyer_name": None, "buyer_tax_id": None,
        "seller_name": None, "seller_tax_id": None,
        "product_name": None, "amount": None,
    }
    if len(blocks) < 5:
        log.debug("layout extractor: too few blocks (%d), giving up", len(blocks))
        return result

    zones, page_w = _classify_zones(blocks)
    buyer, seller = _split_buyer_seller(zones[ZONE_BUYER_SELLER], page_w)

    # --- header zone ---
    result["invoice_number"] = _find_value_after_label(
        zones[ZONE_HEADER], ["发票号码"], digit_only=True)
    result["invoice_code"] = _find_value_after_label(
        zones[ZONE_HEADER], ["发票代码"], digit_only=True)
    result["date"] = _find_value_after_label(
        zones[ZONE_HEADER], ["开票日期"], date_match=True)

    # --- buyer zone (left of mid-x) ---
    result["buyer_name"] = _find_value_after_label(
        buyer, ["名称"])
    result["buyer_tax_id"] = _find_value_after_label(
        buyer, ["统一社会信用代码", "纳税人识别号", "统一社会信用代码/纳税人识别号"])

    # --- seller zone (right of mid-x) ---
    result["seller_name"] = _find_value_after_label(
        seller, ["名称"])
    result["seller_tax_id"] = _find_value_after_label(
        seller, ["统一社会信用代码", "纳税人识别号", "统一社会信用代码/纳税人识别号"])

    # --- table zone ---
    result["product_name"] = _extract_product_via_layout(zones[ZONE_TABLE])

    # --- totals zone ---
    result["amount"] = _extract_amount_via_layout(zones[ZONE_TOTALS])

    log.debug("layout extractor result: %s", {k: str(v)[:40] for k, v in result.items()})
    return result


# ── Legacy bbox helpers (kept for reference, replaced by layout extractor) ─


def _row_of(block: dict) -> float | None:
    """Return the y-center of a block, or None if no coords."""
    if block.get("y0") is None or block.get("y1") is None:
        return None
    return (block["y0"] + block["y1"]) / 2


def _same_row(a: dict, b: dict, tol: float = 12.0) -> bool:
    """Two blocks are on the same visual row if their y-centers are close."""
    ra, rb = _row_of(a), _row_of(b)
    if ra is None or rb is None:
        return False
    return abs(ra - rb) <= tol


def _blocks_right_of(blocks: list[dict], ref: dict, *,
                     skip_self: bool = True,
                     min_text: int = 0) -> list[dict]:
    """All blocks on the same row as ref, ordered left-to-right.

    We DO NOT strictly require x0 >= ref.x1 — in PDF text layer the value often
    overlaps the label's right edge (rendering artifact). We just require the
    block to not be to the LEFT of ref.x0 (so label '名称：' x=317..344 and
    value '深圳拓竹' x=340..430 both qualify on the same row).
    """
    out = []
    for b in blocks:
        if skip_self and b is ref:
            continue
        if b.get("x0") is None:
            continue
        if not _same_row(b, ref):
            continue
        # Must be to the right of (or overlapping the right edge of) ref
        # Allow up to 10px leftward overlap
        if b["x0"] < ref["x0"] - 2:
            continue
        if min_text and len(b.get("text", "").strip()) < min_text:
            continue
        out.append(b)
    out.sort(key=lambda x: x["x0"])
    return out


def _find_block_by_text(blocks: list[dict], needle: str, *,
                        starts_with: bool = False,
                        exclude_text: str | None = None) -> dict | None:
    for b in blocks:
        t = b.get("text", "")
        if starts_with:
            if t.startswith(needle):
                if exclude_text and exclude_text in t:
                    continue
                return b
        else:
            if needle in t:
                if exclude_text and exclude_text in t:
                    continue
                return b
    return None


def _extract_merchant_via_bbox(blocks: list[dict]) -> str | None:
    """Find seller name by spatial layout.

    Strategy: electronic invoice always has two '名称：' labels — buyer (left)
    and seller (right). The one with larger x is the seller. The value sits
    on the same row, to the right of the label.
    """
    # Find ALL "名称：" label blocks
    name_labels = [b for b in blocks if b.get("text", "").strip().startswith("名称")
                   and (b["x0"], b["y0"], b["x1"], b["y1"]) != (None, None, None, None)]
    if not name_labels:
        return None

    # Sort by x0 ascending → seller is the rightmost one
    name_labels.sort(key=lambda b: b["x0"])
    seller_label = name_labels[-1]

    # Find value blocks on the same row, to the right of seller_label
    right_vals = _blocks_right_of(blocks, seller_label)
    if not right_vals:
        return None

    # Pick the first value (largest text, or just first)
    # Filter: skip things that look like header labels (项目名称, etc.)
    SKIP = {"项目名称", "规格型号", "单位", "数量", "单价", "金额",
            "税率/征收率", "税额", "合", "计"}
    value_block = None
    for v in right_vals:
        t = v["text"].strip()
        if t in SKIP:
            continue
        # Must look like an org name (has suffix or is long enough)
        if len(t) >= 2:
            value_block = v
            break
    if not value_block:
        value_block = right_vals[0]

    name = _clean_org_name(value_block["text"].strip())
    if name:
        log.debug("bbox merchant label=%r(x=%.1f) → value=%r(x=%.1f)",
                  seller_label["text"], seller_label["x0"],
                  value_block["text"], value_block["x0"])
    return name


def _extract_invoice_number_via_bbox(blocks: list[dict]) -> str | None:
    label = _find_block_by_text(blocks, "发票号码", starts_with=True)
    if not label:
        return None
    # Value on same row, to the right
    right_vals = _blocks_right_of(blocks, label)
    for v in right_vals:
        t = v["text"].strip()
        digits = re.sub(r"\D", "", t)
        if 8 <= len(digits) <= 30:
            res = normalize_invoice_digits(digits)
            log.debug("bbox inv_number label=%r → value=%r → %s", label["text"], t, res)
            return res
    return None


def _extract_date_via_bbox(blocks: list[dict]) -> str | None:
    label = _find_block_by_text(blocks, "开票日期", starts_with=True)
    if not label:
        return None
    right_vals = _blocks_right_of(blocks, label)
    for v in right_vals:
        t = v["text"].strip()
        m = INVOICE_DATE_RE.search(t) or DATE_RE.search(t)
        if m:
            return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return None


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
    text, source, ocr_used, blocks = extract_text_for_file(abs_path=path, original_name=original_name)

    # ── Layout-based extraction (bbox spatial matching) ──────────
    # First try: extract invoice fields purely from spatial layout.
    # This handles most Chinese electronic invoices (普票/专票) correctly
    # regardless of PDF text-layer ordering or OCR noise.
    layout_fields: dict = {}
    layout_succeeded = False
    if blocks and len(blocks) >= 5:
        try:
            layout_fields = extract_invoice_fields_by_layout(blocks)
            # Consider it "succeeded" if at least seller+inv_num populated
            layout_succeeded = bool(layout_fields.get("seller_name")
                                    and layout_fields.get("invoice_number"))
            log.debug("layout extractor: success=%s fields=%s",
                      layout_succeeded, {k: str(v)[:30] for k, v in layout_fields.items()})
        except Exception:
            log.exception("layout extractor failed, falling back to regex")
            layout_succeeded = False

    # ── Amount chain (layout first, then text/filename regex) ────
    amount = None
    if layout_succeeded and layout_fields.get("amount") is not None:
        amount = _amount_float(layout_fields["amount"])
        log.debug("amount from layout → %s", amount)
    else:
        from_text = _amount_float(parse_amount_from_pdf_text(text)) if text else None
        from_name = _amount_float(parse_amount_from_filename(original_name))
        amount = from_name if from_name is not None else from_text

    # ── Suggest type ──────────────────────────────────────────────
    suggested = _pick_type_from_text(text, original_name, width, height)

    # ── Field consolidation (layout → regex fallback) ────────────
    merchant = (layout_fields.get("seller_name") if layout_succeeded else None) \
               or (_extract_merchant(text) if text else None)
    date = (layout_fields.get("date") if layout_succeeded else None) \
           or (_extract_date(text) if text else None)
    invoice_number = (layout_fields.get("invoice_number") if layout_succeeded else None) \
                     or (_extract_invoice_number(text) if text else None)
    product_name = (layout_fields.get("product_name") if layout_succeeded else None) \
                   or (_extract_product_name(text) if text else None)
    invoice_code = (layout_fields.get("invoice_code") if layout_succeeded else None) \
                   or (_extract_invoice_code(text) if text else None)

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
        order_no=(
            _extract_order_no_via_bbox(blocks)
            or (_extract_order_no(text) if text else None)
        ),
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        content_sha256=content_sha256,
        text_preview=(text or "")[:400],
        ocr_used=ocr_used,
        text_source=source,
        ocr_lines=blocks,
    )
    log.info(
        "features name=%r type=%s amount=%s product=%s merchant=%s date=%s inv=%s source=%s ocr=%s layout_ok=%s",
        original_name,
        suggested,
        amount,
        product_name,
        merchant,
        date,
        invoice_number,
        source,
        ocr_used,
        layout_succeeded,
    )
    if text:
        log.info("features text name=%r source=%s len=%d text=%s", original_name, source, len(text), text[:2000])
    else:
        log.info("features text name=%r source=%s empty", original_name, source)
    return feat

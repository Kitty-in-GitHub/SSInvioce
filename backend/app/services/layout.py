from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from ..config import EXPORTS_DIR, ensure_dirs
from .storage import resolve_stored

# A4 at 72 dpi points
A4_WIDTH = 595.0
A4_HEIGHT = 842.0
MARGIN = 28.0  # ~10mm
GAP = 8.0
TOP_RATIO = 0.55


class ComposeError(Exception):
    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []


def _fit_rect(box_x: float, box_y: float, box_w: float, box_h: float, img_w: float, img_h: float) -> fitz.Rect:
    if img_w <= 0 or img_h <= 0:
        return fitz.Rect(box_x, box_y, box_x + box_w, box_y + box_h)
    scale = min(box_w / img_w, box_h / img_h)
    w = img_w * scale
    h = img_h * scale
    x = box_x + (box_w - w) / 2
    y = box_y + (box_h - h) / 2
    return fitz.Rect(x, y, x + w, y + h)


def _load_pixmap(path: Path, max_side: int = 2000) -> fitz.Pixmap:
    if path.suffix.lower() == ".pdf":
        doc = fitz.open(path)
        try:
            page = doc[0]
            zoom = min(2.0, max_side / max(page.rect.width, page.rect.height))
            mat = fitz.Matrix(zoom, zoom)
            return page.get_pixmap(matrix=mat, alpha=False)
        finally:
            doc.close()
    pix = fitz.Pixmap(path)
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    elif pix.n > 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    # Downscale very large images
    if max(pix.width, pix.height) > max_side:
        scale = max_side / max(pix.width, pix.height)
        new_w = max(1, int(pix.width * scale))
        new_h = max(1, int(pix.height * scale))
        pix = fitz.Pixmap(pix, new_w, new_h, None)
    return pix


def compose_entry_pdf(
    *,
    entry_id: int,
    invoice_rel: str,
    order_rel: str,
    payment_rel: str,
) -> Path:
    ensure_dirs()
    invoice_path = resolve_stored(invoice_rel)
    order_path = resolve_stored(order_rel)
    payment_path = resolve_stored(payment_rel)

    for label, p in (("invoice", invoice_path), ("order", order_path), ("payment", payment_path)):
        if not p.exists():
            raise ComposeError(f"missing file for {label}", missing=[label])

    content_w = A4_WIDTH - 2 * MARGIN
    content_h = A4_HEIGHT - 2 * MARGIN
    top_h = content_h * TOP_RATIO
    bottom_h = content_h - top_h - GAP
    top_box = (MARGIN, MARGIN, content_w, top_h)

    inv_pix = _load_pixmap(invoice_path)
    order_pix = _load_pixmap(order_path)
    pay_pix = _load_pixmap(payment_path)

    doc = fitz.open()
    page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)

    # Top: invoice
    inv_rect = _fit_rect(*top_box, inv_pix.width, inv_pix.height)
    page.insert_image(inv_rect, pixmap=inv_pix)

    # Bottom: order | payment, same height then fit width
    bottom_y = MARGIN + top_h + GAP
    avail_w = (content_w - GAP) / 2

    def pair_size(pix: fitz.Pixmap) -> tuple[float, float]:
        # Scale both to same height first (use bottom_h), then shrink if too wide
        if pix.width <= 0 or pix.height <= 0:
            return avail_w, bottom_h
        h = bottom_h
        w = pix.width * (h / pix.height)
        if w > avail_w:
            w = avail_w
            h = pix.height * (w / pix.width)
        return w, h

    ow, oh = pair_size(order_pix)
    pw, ph = pair_size(pay_pix)
    common_h = min(oh, ph)
    # Recompute widths at common height
    ow = order_pix.width * (common_h / order_pix.height) if order_pix.height else avail_w
    pw = pay_pix.width * (common_h / pay_pix.height) if pay_pix.height else avail_w
    if ow > avail_w:
        scale = avail_w / ow
        ow *= scale
        common_h *= scale
        pw = pay_pix.width * (common_h / pay_pix.height) if pay_pix.height else pw
    if pw > avail_w:
        scale = avail_w / pw
        pw *= scale
        common_h *= scale
        ow = order_pix.width * (common_h / order_pix.height) if order_pix.height else ow

    order_x = MARGIN + (avail_w - ow) / 2
    pay_x = MARGIN + avail_w + GAP + (avail_w - pw) / 2
    order_y = bottom_y + (bottom_h - common_h) / 2
    pay_y = order_y

    page.insert_image(fitz.Rect(order_x, order_y, order_x + ow, order_y + common_h), pixmap=order_pix)
    page.insert_image(fitz.Rect(pay_x, pay_y, pay_x + pw, pay_y + common_h), pixmap=pay_pix)

    out = EXPORTS_DIR / f"entry_{entry_id}.pdf"
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    return out

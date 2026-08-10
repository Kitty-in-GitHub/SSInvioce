from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from ..config import EXPORTS_DIR, ensure_dirs
from ..logging_config import get_logger
from .storage import resolve_stored

# A4 at 72 dpi points
A4_WIDTH = 595.0
A4_HEIGHT = 842.0
MARGIN_TOP = 22.0  # ~7.8mm
MARGIN_SIDE = 26.0  # ~9.2mm
MARGIN_BOTTOM = 28.0  # ~10mm — keep clear space under screenshots
ZONE_GAP = 0.0
PAIR_GAP = 2.0
TOP_MAX_RATIO = 0.46
BOTTOM_MIN_RATIO = 0.38
CONTENT_SCALE = 0.90  # draw invoice & screenshots slightly smaller than max fit

log = get_logger("layout")


class ComposeError(Exception):
    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []


def _load_image_pixmap(path: Path, max_side: int = 2200) -> fitz.Pixmap:
    pix = fitz.Pixmap(path)
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    elif pix.n > 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if max(pix.width, pix.height) > max_side:
        scale = max_side / max(pix.width, pix.height)
        new_w = max(1, int(pix.width * scale))
        new_h = max(1, int(pix.height * scale))
        pix = fitz.Pixmap(pix, new_w, new_h, None)
    return pix


def _pixmap_to_pil(pix: fitz.Pixmap) -> Image.Image:
    src = pix
    if src.alpha or src.n != 3:
        src = fitz.Pixmap(fitz.csRGB, src)
    if hasattr(src, "pil_image"):
        return src.pil_image().convert("RGB")
    return Image.frombytes("RGB", (src.width, src.height), src.samples, "raw", "RGB", src.stride)


def _pil_to_pixmap(img: Image.Image) -> fitz.Pixmap:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return fitz.Pixmap(buf.getvalue())


def _trim_image_whitespace(pix: fitz.Pixmap, *, white_level: int = 252, pad: int = 1) -> fitz.Pixmap:
    """Crop near-pure-white margins on raster screenshots."""
    img = _pixmap_to_pil(pix)
    px = img.load()
    w, h = img.size

    def is_bg(x: int, y: int) -> bool:
        r, g, b = px[x, y]
        return r >= white_level and g >= white_level and b >= white_level

    top = 0
    while top < h and all(is_bg(x, top) for x in range(w)):
        top += 1
    bottom = h - 1
    while bottom >= top and all(is_bg(x, bottom) for x in range(w)):
        bottom -= 1
    left = 0
    while left < w and all(is_bg(left, y) for y in range(top, bottom + 1)):
        left += 1
    right = w - 1
    while right >= left and all(is_bg(right, y) for y in range(top, bottom + 1)):
        right -= 1

    if top >= bottom or left >= right:
        return pix

    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w - 1, right + pad)
    bottom = min(h - 1, bottom + pad)
    cropped = img.crop((left, top, right + 1, bottom + 1))
    if cropped.size == img.size:
        return pix
    log.info("trimmed image %sx%s -> %sx%s", w, h, cropped.size[0], cropped.size[1])
    return _pil_to_pixmap(cropped)


def _invoice_content_clip(page: fitz.Page, pad: float = 2.0) -> fitz.Rect:
    """
    Union of drawings / images / text on an invoice PDF page.
    Skips near-full-page background fills so empty margins can be clipped away.
    """
    page_rect = fitz.Rect(page.rect)
    page_area = max(page_rect.get_area(), 1.0)
    rects: list[fitz.Rect] = []

    for d in page.get_drawings():
        r = fitz.Rect(d.get("rect"))
        if r.is_empty or r.is_infinite:
            continue
        # Ignore full-page (or nearly) background rectangles
        if r.get_area() >= page_area * 0.85:
            continue
        rects.append(r)

    try:
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"])
            if not r.is_empty:
                rects.append(r)
    except Exception:
        pass

    for block in page.get_text("dict").get("blocks", []):
        r = fitz.Rect(block["bbox"])
        if not r.is_empty:
            rects.append(r)

    if not rects:
        return page_rect

    u = fitz.Rect(rects[0])
    for r in rects[1:]:
        u |= r
    u.x0 -= pad
    u.y0 -= pad
    u.x1 += pad
    u.y1 += pad
    clipped = u & page_rect
    # Safety: if something went wrong and clip is tiny, fall back
    if clipped.get_area() < page_area * 0.2:
        return page_rect
    return clipped


def _fit_size(box_w: float, box_h: float, img_w: float, img_h: float) -> tuple[float, float]:
    if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
        return max(box_w, 1.0), max(box_h, 1.0)
    scale = min(box_w / img_w, box_h / img_h)
    return img_w * scale, img_h * scale


def _pair_same_height(
    order_pix: fitz.Pixmap,
    pay_pix: fitz.Pixmap,
    *,
    max_w: float,
    max_h: float,
    gap: float,
) -> tuple[float, float, float, float]:
    if order_pix.height <= 0 or pay_pix.height <= 0:
        half = max((max_w - gap) / 2, 1.0)
        return half, half, max_h, max_w

    ar_o = order_pix.width / order_pix.height
    ar_p = pay_pix.width / pay_pix.height
    h_by_width = (max_w - gap) / (ar_o + ar_p) if (ar_o + ar_p) > 0 else max_h
    common_h = min(max_h, h_by_width)
    ow = common_h * ar_o
    pw = common_h * ar_p
    return ow, pw, common_h, ow + gap + pw


def append_entry_page(
    doc: fitz.Document,
    *,
    invoice_rel: str,
    order_rel: str,
    payment_rel: str,
) -> None:
    """Append one A4 reimbursement page to an existing document."""
    invoice_path = resolve_stored(invoice_rel)
    order_path = resolve_stored(order_rel)
    payment_path = resolve_stored(payment_rel)

    for label, p in (("invoice", invoice_path), ("order", order_path), ("payment", payment_path)):
        if not p.exists():
            raise ComposeError(f"missing file for {label}", missing=[label])

    content_w = A4_WIDTH - 2 * MARGIN_SIDE
    content_top = MARGIN_TOP
    content_bottom = A4_HEIGHT - MARGIN_BOTTOM
    content_h = content_bottom - content_top
    top_max_h = content_h * TOP_MAX_RATIO
    bottom_min_h = content_h * BOTTOM_MIN_RATIO

    order_pix = _trim_image_whitespace(_load_image_pixmap(order_path))
    pay_pix = _trim_image_whitespace(_load_image_pixmap(payment_path))

    page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)

    inv_doc = fitz.open(invoice_path)
    try:
        inv_page = inv_doc[0]
        clip = _invoice_content_clip(inv_page, pad=1.0)
        clip_w, clip_h = clip.width, clip.height

        inv_w, inv_h = _fit_size(content_w, top_max_h, clip_w, clip_h)
        if content_h - inv_h < bottom_min_h:
            inv_w, inv_h = _fit_size(content_w, content_h - bottom_min_h, clip_w, clip_h)
        inv_w *= CONTENT_SCALE
        inv_h *= CONTENT_SCALE

        inv_x = MARGIN_SIDE + (content_w - inv_w) / 2
        inv_y = content_top
        inv_rect = fitz.Rect(inv_x, inv_y, inv_x + inv_w, inv_y + inv_h)
        page.show_pdf_page(inv_rect, inv_doc, 0, clip=clip)
    finally:
        inv_doc.close()

    bottom_y = inv_y + inv_h + ZONE_GAP
    bottom_h = content_bottom - bottom_y
    ow, pw, common_h, pair_w = _pair_same_height(
        order_pix,
        pay_pix,
        max_w=content_w * CONTENT_SCALE,
        max_h=bottom_h * CONTENT_SCALE,
        gap=PAIR_GAP,
    )
    pair_x = MARGIN_SIDE + (content_w - pair_w) / 2
    pair_y = bottom_y

    page.insert_image(
        fitz.Rect(pair_x, pair_y, pair_x + ow, pair_y + common_h),
        pixmap=order_pix,
        keep_proportion=True,
    )
    page.insert_image(
        fitz.Rect(pair_x + ow + PAIR_GAP, pair_y, pair_x + ow + PAIR_GAP + pw, pair_y + common_h),
        pixmap=pay_pix,
        keep_proportion=True,
    )


def compose_entry_pdf(
    *,
    entry_id: int,
    invoice_rel: str,
    order_rel: str,
    payment_rel: str,
) -> Path:
    ensure_dirs()
    doc = fitz.open()
    append_entry_page(
        doc,
        invoice_rel=invoice_rel,
        order_rel=order_rel,
        payment_rel=payment_rel,
    )
    out = EXPORTS_DIR / f"entry_{entry_id}.pdf"
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    log.info("compose single entry_id=%s path=%s", entry_id, out)
    return out


def compose_batch_pdf(
    pages: list[dict[str, str]],
    *,
    out_name: str = "batch_compose.pdf",
) -> Path:
    """
    pages: [{invoice_rel, order_rel, payment_rel}, ...]
    One A4 page per item, merged into a single PDF.
    """
    if not pages:
        raise ComposeError("no pages to compose")
    ensure_dirs()
    doc = fitz.open()
    for i, spec in enumerate(pages):
        try:
            append_entry_page(
                doc,
                invoice_rel=spec["invoice_rel"],
                order_rel=spec["order_rel"],
                payment_rel=spec["payment_rel"],
            )
        except ComposeError:
            doc.close()
            raise
        log.info("batch page %s/%s ok", i + 1, len(pages))
    out = EXPORTS_DIR / out_name
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    log.info("compose batch pages=%s path=%s size=%s", len(pages), out, out.stat().st_size)
    return out

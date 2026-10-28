"""回归哨兵：电子发票的红色印章必须出现在 A4 拼版件里。

背景
----
国内电子发票把「全国统一发票监制章」存成 PDF 的 /Stamp 注释（/Annots），
而 ``Page.show_pdf_page()`` 只复制页面内容流，注释会被整块丢掉，导出件上
就没有章了。``backend/app/services/layout.py::_place_pdf_page()`` 在放置前
把注释烘焙进页面内容，本脚本用同样的放置流程检查印章区域的红色像素是否
被保留。

用法
----
    python scripts/check_invoice_seal.py                  # 扫描 data/uploads
    python scripts/check_invoice_seal.py a.pdf b.pdf      # 指定文件
    python scripts/check_invoice_seal.py --legacy         # 关闭修复（模拟旧版）
                                                          # 预期：必须失败

退出码：0 全部通过；1 有失败；2 没有可检查的红章发票。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf as fitz
from PIL import Image

from backend.app.services import layout

DPI = 200
ZOOM = DPI / 72.0

# 与 settings_store.DEFAULT_LAYOUT 的发票区域一致（A4 比例）
INVOICE_REGION = {"slot_id": "invoice", "x": 0.044, "y": 0.026, "w": 0.912, "h": 0.43}

MIN_SEAL_RED = 0.01  # 印章框内至少要有 1% 的高饱和红色像素
KEEP_RATIO = 0.5  # 且不少于原件的 50%
HIDDEN_FLAGS = 2 | 32  # Hidden | NoView
SKIP_ANNOT_TYPES = {"Link", "Popup", "Widget", "Screen", "Movie", "Sound", "FileAttachment"}


def _fit_rect(clip) -> "fitz.Rect":
    """与 append_entry_page() 相同的发票区域缩放规则，便于独立检查。"""
    content_w = layout.A4_WIDTH - 2 * layout.MARGIN_SIDE
    content_h = layout.A4_HEIGHT - layout.MARGIN_TOP - layout.MARGIN_BOTTOM
    top_max_h = content_h * layout.TOP_MAX_RATIO
    bottom_min_h = content_h * layout.BOTTOM_MIN_RATIO
    inv_w, inv_h = layout._fit_size(content_w, top_max_h, clip.width, clip.height)
    if content_h - inv_h < bottom_min_h:
        inv_w, inv_h = layout._fit_size(content_w, content_h - bottom_min_h, clip.width, clip.height)
    inv_w *= layout.CONTENT_SCALE
    inv_h *= layout.CONTENT_SCALE
    x = layout.MARGIN_SIDE + (content_w - inv_w) / 2
    return fitz.Rect(x, layout.MARGIN_TOP, x + inv_w, layout.MARGIN_TOP + inv_h)


def _legacy_place(page, rect, src, clip=None) -> None:
    """修复前的行为：直接 show_pdf_page()，注释（印章）会丢。"""
    page.show_pdf_page(rect, src, 0, clip=clip)


def _img(page) -> Image.Image:
    return page.get_pixmap(dpi=DPI).pil_image().convert("RGB")


def _crop(img: Image.Image, rect) -> Image.Image:
    box = (
        max(0, int(rect.x0 * ZOOM)),
        max(0, int(rect.y0 * ZOOM)),
        min(img.width, int(rect.x1 * ZOOM)),
        min(img.height, int(rect.y1 * ZOOM)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return Image.new("RGB", (1, 1), (255, 255, 255))
    return img.crop(box)


def _ratio(img: Image.Image, predicate) -> float:
    img = img.convert("RGB")
    px = img.load()
    step = max(1, min(img.width, img.height) // 400)
    total = hit = 0
    for y in range(0, img.height, step):
        for x in range(0, img.width, step):
            total += 1
            if predicate(*px[x, y]):
                hit += 1
    return hit / max(total, 1)


def _red(img: Image.Image) -> float:
    return _ratio(img, lambda r, g, b: r >= 165 and g <= 95 and b <= 95)


def _ink(img: Image.Image) -> float:
    return _ratio(img, lambda r, g, b: min(r, g, b) < 200)


def _map_rect(r, clip, dest) -> "fitz.Rect":
    sx = dest.width / clip.width
    sy = dest.height / clip.height
    return fitz.Rect(
        dest.x0 + (r.x0 - clip.x0) * sx,
        dest.y0 + (r.y0 - clip.y0) * sy,
        dest.x0 + (r.x1 - clip.x0) * sx,
        dest.y0 + (r.y1 - clip.y0) * sy,
    )


def check(path: Path, *, legacy: bool) -> tuple[str, str, dict]:
    """返回 (status, detail, metrics)，status ∈ pass / fail / skip。"""
    try:
        src_doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - 报告任何打不开的文件
        return "fail", f"打不开：{exc}", {}

    try:
        if src_doc.page_count == 0:
            return "skip", "空 PDF", {}
        src_page = src_doc[0]

        annots = []
        for annot in src_page.annots() or []:
            if annot.type[1] in SKIP_ANNOT_TYPES:
                continue
            if annot.flags & HIDDEN_FLAGS:
                continue
            if annot.rect.is_empty or annot.rect.is_infinite:
                continue
            annots.append(annot)

        if not annots:
            return "skip", "无注释（印章在页面内容里，不受影响）", {"annots": 0}

        clip = layout._invoice_content_clip(src_page, pad=1.0)
        clip = layout._clip_with_annots(src_page, clip)
        dest = _fit_rect(clip)

        out_doc = fitz.open()
        out_page = out_doc.new_page(width=layout.A4_WIDTH, height=layout.A4_HEIGHT)
        place = _legacy_place if legacy else layout._place_pdf_page
        src_place = fitz.open(path)  # bake() 会改内存副本，参考渲染另开
        try:
            place(out_page, dest, src_place, clip)
        finally:
            src_place.close()

        src_img = _img(src_page)
        out_img = _img(out_page)
        leftover = len(list(out_page.annots() or []))

        worst = ""
        ok = leftover == 0
        metrics = {"annots": len(annots), "leftover": leftover, "src_red": 0.0, "out_red": 0.0}
        for annot in annots:
            src_crop = _crop(src_img, annot.rect)
            out_crop = _crop(out_img, _map_rect(annot.rect, clip, dest))
            s_red, o_red = _red(src_crop), _red(out_crop)
            metrics["src_red"] = max(metrics["src_red"], s_red)
            metrics["out_red"] = max(metrics["out_red"], o_red)
            if s_red >= 0.01:  # 红色印章：按红色像素判断
                if o_red < max(MIN_SEAL_RED, KEEP_RATIO * s_red):
                    ok = False
                    worst = worst or f"红色印章丢失（原件 {s_red:.1%} → 导出 {o_red:.1%}）"
            else:  # 非红色注释（如黑色签章）：退回墨迹量判断
                s_ink, o_ink = _ink(src_crop), _ink(out_crop)
                if o_ink < KEEP_RATIO * s_ink:
                    ok = False
                    worst = worst or f"注释内容丢失（原件墨迹 {s_ink:.1%} → 导出 {o_ink:.1%}）"

        out_chars, src_chars = len(out_page.get_text()), len(src_page.get_text())
        metrics["text"] = (out_chars, src_chars)
        if src_chars and out_chars < src_chars * 0.9:
            ok = False
            worst = worst or f"文字层丢失（原件 {src_chars} 字 → 导出 {out_chars} 字）"

        if leftover:
            ok = False
            worst = worst or f"导出页仍残留 {leftover} 个注释（未展平）"

        return ("pass" if ok else "fail"), worst or "印章已保留，文字层完整", metrics
    finally:
        src_doc.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="检查拼版后发票印章是否保留")
    parser.add_argument("files", nargs="*", type=Path, help="发票 PDF；缺省扫描 data/uploads")
    parser.add_argument("--legacy", action="store_true", help="关闭注释展平（模拟修复前），应当失败")
    args = parser.parse_args()

    files = args.files or sorted((ROOT / "data" / "uploads").rglob("*.pdf"))
    files = [f for f in files if f.is_file()]
    if not files:
        print("没有找到发票 PDF")
        return 2

    mode = "legacy（修复前）" if args.legacy else "fixed（当前）"
    print(f"检查模式：{mode}，共 {len(files)} 个 PDF\n")
    header = f"{'文件':46s} {'注释':>3s} {'原件红':>7s} {'导出红':>7s} {'文字':>9s}  结果"
    print(header)
    print("-" * len(header.encode("gbk", errors="replace")))

    failed = passed = skipped = 0
    for path in files:
        status, detail, m = check(path, legacy=args.legacy)
        name = path.name
        if len(name) > 44:
            name = name[:20] + "…" + name[-23:]
        text = f"{m['text'][0]}/{m['text'][1]}" if "text" in m else "-"
        print(
            f"{name:46s} {m.get('annots', 0):3d} {m.get('src_red', 0):7.2%} "
            f"{m.get('out_red', 0):7.2%} {text:>9s}  {status.upper():4s} {detail}"
        )
        if status == "pass":
            passed += 1
        elif status == "fail":
            failed += 1
        else:
            skipped += 1

    print(f"\n汇总：通过 {passed}，失败 {failed}，跳过 {skipped}")
    if args.legacy:
        print("提示：--legacy 是修复前行为，出现失败才说明本脚本能拦住该缺陷。")
    return 1 if failed else (0 if passed else 2)


if __name__ == "__main__":
    raise SystemExit(main())

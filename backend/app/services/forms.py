from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import BUILTIN_FORM_TEMPLATES_DIR, EXPORTS_DIR, TEMPLATES_DIR, ensure_dirs
from ..logging_config import get_logger

log = get_logger("forms")

FORM_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DEFAULT_FORM_ID = "student_activity_budget"


class FormError(Exception):
    pass


def default_form_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": DEFAULT_FORM_ID,
            "name": "学生活动预决算表",
            "docx": "student_activity_budget.docx",
            "fields": [
                {"id": "fund_code", "label": "经费项目号码", "type": "text"},
                {"id": "year", "label": "年", "type": "text"},
                {"id": "month", "label": "月", "type": "text"},
                {"id": "day", "label": "日", "type": "text"},
                {"id": "activity_name", "label": "活动名称", "type": "text"},
                {"id": "organizer", "label": "主办单位", "type": "text"},
                {"id": "participants", "label": "参加人数", "type": "text"},
                {"id": "activity_date", "label": "活动日期", "type": "text"},
                {"id": "contestants", "label": "参赛人数/队数", "type": "text"},
                {"id": "location", "label": "活动地点", "type": "text"},
                {"id": "winners", "label": "获奖人数/队数", "type": "text"},
            ],
            "tables": [
                {
                    "id": "expenses",
                    "label": "支出",
                    "columns": [
                        {"id": "item", "label": "支出内容", "type": "label"},
                        {"id": "amount", "label": "金额", "type": "money"},
                        {"id": "reimburse", "label": "核销金额", "type": "money"},
                        {"id": "remark", "label": "备注", "type": "text"},
                    ],
                    "rows": [
                        {"id": "materials", "label": "材料费", "remark": ""},
                        {"id": "rental", "label": "租赁费", "remark": ""},
                        {"id": "traffic", "label": "交通费", "remark": ""},
                        {"id": "printing", "label": "资料、印刷费", "remark": ""},
                        {"id": "venue", "label": "场租费", "remark": ""},
                        {"id": "meals", "label": "工作餐、食品", "remark": ""},
                        {"id": "souvenirs", "label": "奖品、纪念品", "remark": ""},
                        {"id": "expert", "label": "专家评审费、讲课费", "remark": "附相关发放表"},
                        {"id": "small_prize", "label": "小额奖品", "remark": "附简要说明"},
                        {"id": "contest_prize", "label": "比赛奖金", "remark": "附发放明细"},
                        {"id": "other", "label": "其他", "remark": ""},
                    ],
                    "total": True,
                }
            ],
        }
    ]


def _clean_id(raw: Any) -> str | None:
    sid = str(raw or "").strip().lower()
    if FORM_ID_RE.fullmatch(sid):
        return sid
    return None


def _clean_label(raw: Any, fallback: str) -> str:
    label = str(raw or "").strip()[:40]
    return label or fallback


def _clean_type(raw: Any, allowed: tuple[str, ...], default: str) -> str:
    t = str(raw or "").strip().lower()
    return t if t in allowed else default


def _normalize_fields(raw: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) and raw else fallback
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        fid = _clean_id(item.get("id"))
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append(
            {
                "id": fid,
                "label": _clean_label(item.get("label"), fid),
                "type": _clean_type(item.get("type"), ("text", "date", "number", "money"), "text"),
            }
        )
        if len(out) >= 40:
            break
    return out or deepcopy(fallback)


def _normalize_table(raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else fallback
    tid = _clean_id(src.get("id")) or fallback["id"]
    cols_in = src.get("columns") if isinstance(src.get("columns"), list) and src.get("columns") else fallback["columns"]
    columns: list[dict[str, Any]] = []
    seen_c: set[str] = set()
    for col in cols_in:
        if not isinstance(col, dict):
            continue
        cid = _clean_id(col.get("id"))
        if not cid or cid in seen_c:
            continue
        seen_c.add(cid)
        columns.append(
            {
                "id": cid,
                "label": _clean_label(col.get("label"), cid),
                "type": _clean_type(col.get("type"), ("label", "text", "money", "number"), "text"),
            }
        )
    if not columns:
        columns = deepcopy(fallback["columns"])
    rows_in = src.get("rows") if isinstance(src.get("rows"), list) else fallback["rows"]
    rows: list[dict[str, Any]] = []
    seen_r: set[str] = set()
    for row in rows_in:
        if not isinstance(row, dict):
            continue
        rid = _clean_id(row.get("id"))
        if not rid or rid in seen_r:
            continue
        seen_r.add(rid)
        rows.append(
            {
                "id": rid,
                "label": _clean_label(row.get("label"), rid),
                "remark": str(row.get("remark") or "")[:80],
            }
        )
        if len(rows) >= 40:
            break
    if not rows:
        rows = deepcopy(fallback["rows"])
    return {
        "id": tid,
        "label": _clean_label(src.get("label"), fallback.get("label") or tid),
        "columns": columns,
        "rows": rows,
        "total": bool(src.get("total", fallback.get("total", True))),
    }


def normalize_form_templates(raw: Any) -> list[dict[str, Any]]:
    defaults = {t["id"]: t for t in default_form_templates()}
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tid = _clean_id(item.get("id"))
        if not tid or tid in seen:
            continue
        seen.add(tid)
        fb = defaults.get(tid) or default_form_templates()[0]
        docx = str(item.get("docx") or fb.get("docx") or f"{tid}.docx").strip()
        if not docx.endswith(".docx"):
            docx = f"{tid}.docx"
        tables_in = item.get("tables") if isinstance(item.get("tables"), list) else fb.get("tables") or []
        fb_tables = {t["id"]: t for t in (fb.get("tables") or [])}
        tables = []
        for i, tbl in enumerate(tables_in):
            fallback_tbl = fb_tables.get((tbl or {}).get("id") if isinstance(tbl, dict) else "") 
            if fallback_tbl is None:
                fallback_tbl = (fb.get("tables") or [None])[min(i, len(fb.get("tables") or []) - 1)] if fb.get("tables") else {
                    "id": "expenses",
                    "label": "支出",
                    "columns": [
                        {"id": "item", "label": "支出内容", "type": "label"},
                        {"id": "amount", "label": "金额", "type": "money"},
                        {"id": "reimburse", "label": "核销金额", "type": "money"},
                        {"id": "remark", "label": "备注", "type": "text"},
                    ],
                    "rows": [{"id": "other", "label": "其他", "remark": ""}],
                    "total": True,
                }
            tables.append(_normalize_table(tbl, fallback_tbl))
        if not tables and fb.get("tables"):
            tables = deepcopy(fb["tables"])
        out.append(
            {
                "id": tid,
                "name": _clean_label(item.get("name"), fb.get("name") or tid),
                "docx": Path(docx).name,
                "fields": _normalize_fields(item.get("fields"), fb.get("fields") or []),
                "tables": tables,
            }
        )
        if len(out) >= 8:
            break
    if not out:
        return default_form_templates()
    if DEFAULT_FORM_ID not in seen:
        out.insert(0, deepcopy(defaults[DEFAULT_FORM_ID]))
    return out


def get_form_template(template_id: str | None = None) -> dict[str, Any]:
    from .settings_store import get_form_templates

    templates = get_form_templates()
    if template_id:
        for t in templates:
            if t["id"] == template_id:
                return t
        raise FormError(f"未找到表格模板：{template_id}")
    return templates[0]


def builtin_docx_path(template: dict[str, Any]) -> Path:
    return BUILTIN_FORM_TEMPLATES_DIR / template["docx"]


def resolve_docx_path(template: dict[str, Any]) -> Path:
    user = TEMPLATES_DIR / template["docx"]
    if user.is_file():
        return user
    builtin = builtin_docx_path(template)
    if builtin.is_file():
        return builtin
    raise FormError(f"缺少 Word 模板文件：{template['docx']}")


def has_user_docx(template: dict[str, Any]) -> bool:
    return (TEMPLATES_DIR / template["docx"]).is_file()


def save_user_docx(template_id: str, data: bytes) -> Path:
    ensure_dirs()
    template = get_form_template(template_id)
    dest = TEMPLATES_DIR / template["docx"]
    dest.write_bytes(data)
    return dest


def reset_user_docx(template_id: str) -> None:
    template = get_form_template(template_id)
    dest = TEMPLATES_DIR / template["docx"]
    if dest.is_file():
        dest.unlink()


def _money_text(val: Any) -> str:
    if val is None or val == "":
        return ""
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val).strip()
    if abs(n) < 1e-9:
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}"


def parse_money(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def expense_table(template: dict[str, Any]) -> dict[str, Any] | None:
    tables = template.get("tables") or []
    return tables[0] if tables else None


def auto_reimburse_map(entries: list[dict[str, Any]], template: dict[str, Any]) -> dict[str, float]:
    tbl = expense_table(template)
    totals: dict[str, float] = {r["id"]: 0.0 for r in (tbl["rows"] if tbl else [])}
    for e in entries:
        rid = e.get("expense_row")
        if rid not in totals:
            continue
        amt = parse_money(e.get("amount"))
        if amt is not None:
            totals[rid] += amt
    return {k: round(v, 2) for k, v in totals.items()}


def empty_form_values(template: dict[str, Any]) -> dict[str, Any]:
    fields = {f["id"]: "" for f in template.get("fields") or []}
    rows: dict[str, dict[str, Any]] = {}
    tbl = expense_table(template)
    if tbl:
        for row in tbl["rows"]:
            rows[row["id"]] = {
                "amount": "",
                "reimburse": "",
                "remark": row.get("remark") or "",
                "reimburse_manual": False,
            }
    return {"fields": fields, "rows": rows}


def merge_form_values(template: dict[str, Any], saved: Any) -> dict[str, Any]:
    base = empty_form_values(template)
    src = saved if isinstance(saved, dict) else {}
    src_fields = src.get("fields") if isinstance(src.get("fields"), dict) else {}
    src_rows = src.get("rows") if isinstance(src.get("rows"), dict) else {}
    for fid in base["fields"]:
        if fid in src_fields and src_fields[fid] is not None:
            base["fields"][fid] = str(src_fields[fid])
    for rid, row in base["rows"].items():
        raw = src_rows.get(rid)
        if not isinstance(raw, dict):
            continue
        if "amount" in raw and raw["amount"] is not None:
            row["amount"] = raw["amount"] if isinstance(raw["amount"], str) else _money_text(raw["amount"])
        if "reimburse" in raw and raw["reimburse"] is not None:
            row["reimburse"] = raw["reimburse"] if isinstance(raw["reimburse"], str) else _money_text(raw["reimburse"])
        if "remark" in raw and raw["remark"] is not None:
            row["remark"] = str(raw["remark"])
        row["reimburse_manual"] = bool(raw.get("reimburse_manual"))
    return base


def apply_auto_reimburse(values: dict[str, Any], auto_map: dict[str, float]) -> dict[str, Any]:
    """Force amount & reimburse from assigned entry sums (no manual override)."""
    out = deepcopy(values)
    for rid, row in out["rows"].items():
        auto = auto_map.get(rid)
        text = _money_text(auto) if auto else ""
        row["amount"] = text
        row["reimburse"] = text
        row["reimburse_manual"] = False
    return out


def form_totals(values: dict[str, Any]) -> dict[str, str]:
    amount = 0.0
    reimburse = 0.0
    for row in (values.get("rows") or {}).values():
        a = parse_money(row.get("amount"))
        r = parse_money(row.get("reimburse"))
        if a is not None:
            amount += a
        if r is not None:
            reimburse += r
    return {"amount": _money_text(amount), "reimburse": _money_text(reimburse)}


def build_context(template: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    ctx: dict[str, Any] = {f["id"]: values.get("fields", {}).get(f["id"], "") or "" for f in template.get("fields") or []}
    tbl = expense_table(template)
    expenses: dict[str, dict[str, str]] = {}
    if tbl:
        for row in tbl["rows"]:
            saved = (values.get("rows") or {}).get(row["id"]) or {}
            expenses[row["id"]] = {
                "amount": _money_text(saved.get("amount")) if saved.get("amount") not in (None, "") else "",
                "reimburse": _money_text(saved.get("reimburse")) if saved.get("reimburse") not in (None, "") else "",
                "remark": str(saved.get("remark") or row.get("remark") or ""),
            }
    ctx["expenses"] = expenses
    totals = form_totals(values)
    ctx["total_amount"] = totals["amount"]
    ctx["total_reimburse"] = totals["reimburse"]
    return ctx


def parse_form_data(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def dump_form_data(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def group_has_form(raw: Any, template_id: str | None = None) -> bool:
    data = parse_form_data(raw)
    tid = template_id or DEFAULT_FORM_ID
    return isinstance(data.get(tid), dict)


def render_docx(template: dict[str, Any], values: dict[str, Any], dest: Path | None = None) -> Path:
    try:
        from docxtpl import DocxTemplate
    except ImportError as exc:
        raise FormError("未安装 docxtpl，无法填写 Word 表格") from exc
    src = resolve_docx_path(template)
    ensure_dirs()
    if dest is None:
        dest = Path(tempfile.mkstemp(suffix=".docx", prefix="form_", dir=str(EXPORTS_DIR))[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = DocxTemplate(str(src))
    doc.render(build_context(template, values))
    doc.save(str(dest))
    return dest


def _cjk_font(fitz_mod: Any) -> Any:
    """Prefer local Windows CJK fonts; fall back to PyMuPDF built-in china-s."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = ("msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc", "simkai.ttf")
    for name in candidates:
        p = windir / "Fonts" / name
        if not p.is_file():
            continue
        try:
            return fitz_mod.Font(fontfile=str(p))
        except Exception:
            log.debug("skip CJK font %s", p, exc_info=True)
    return fitz_mod.Font("china-s")


def render_form_pdf(template: dict[str, Any], values: dict[str, Any], dest: Path | None = None) -> Path:
    """Draw filled form as A4 PDF with PyMuPDF — no Microsoft Word required."""
    import pymupdf as fitz

    ensure_dirs()
    if dest is None:
        dest = Path(tempfile.mkstemp(suffix=".pdf", prefix="form_", dir=str(EXPORTS_DIR))[1])
    dest.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = 595.0, 842.0
    margin_x, margin_top = 40.0, 36.0
    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    font = _cjk_font(fitz)
    tw = fitz.TextWriter(page.rect)

    fields = values.get("fields") or {}
    title = str(template.get("name") or "表格")
    y = margin_top
    content_w = page_w - 2 * margin_x

    def text(x: float, yy: float, s: str, size: float = 10) -> None:
        tw.append((x, yy), s or "", font=font, fontsize=size)

    def draw_box(x0: float, y0: float, x1: float, y1: float) -> None:
        page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0.15, 0.15, 0.15), width=0.6)

    # Title
    title_w = font.text_length(title, fontsize=16)
    text(margin_x + max(0, (content_w - title_w) / 2), y + 14, title, size=16)
    y += 28

    # Header line: fund + date
    fund = str(fields.get("fund_code") or "")
    year = str(fields.get("year") or "")
    month = str(fields.get("month") or "")
    day = str(fields.get("day") or "")
    header = f"经费项目号码：{fund}　　时间：{year} 年 {month} 月 {day} 日"
    text(margin_x, y + 11, header, size=10)
    y += 20

    # Field pairs table (activity info)
    pair_ids = [
        ("activity_name", None),
        ("organizer", "participants"),
        ("activity_date", "contestants"),
        ("location", "winners"),
    ]
    label_of = {f["id"]: f["label"] for f in template.get("fields") or []}
    row_h = 22.0
    label_w = 88.0
    for left_id, right_id in pair_ids:
        if left_id not in label_of and left_id not in fields:
            continue
        if right_id is None:
            draw_box(margin_x, y, margin_x + label_w, y + row_h)
            draw_box(margin_x + label_w, y, margin_x + content_w, y + row_h)
            text(margin_x + 4, y + 15, label_of.get(left_id, left_id), size=9)
            text(margin_x + label_w + 4, y + 15, str(fields.get(left_id) or ""), size=10)
            y += row_h
        else:
            mid = margin_x + content_w / 2
            draw_box(margin_x, y, margin_x + label_w, y + row_h)
            draw_box(margin_x + label_w, y, mid, y + row_h)
            text(margin_x + 4, y + 15, label_of.get(left_id, left_id), size=9)
            text(margin_x + label_w + 4, y + 15, str(fields.get(left_id) or ""), size=10)
            draw_box(mid, y, mid + label_w, y + row_h)
            draw_box(mid + label_w, y, margin_x + content_w, y + row_h)
            text(mid + 4, y + 15, label_of.get(right_id, right_id), size=9)
            text(mid + label_w + 4, y + 15, str(fields.get(right_id) or ""), size=10)
            y += row_h

    shown = {"fund_code", "year", "month", "day"}
    for left_id, right_id in pair_ids:
        shown.add(left_id)
        if right_id:
            shown.add(right_id)
    extra = [f for f in template.get("fields") or [] if f["id"] not in shown]
    for f in extra:
        draw_box(margin_x, y, margin_x + label_w, y + row_h)
        draw_box(margin_x + label_w, y, margin_x + content_w, y + row_h)
        text(margin_x + 4, y + 15, f["label"], size=9)
        text(margin_x + label_w + 4, y + 15, str(fields.get(f["id"]) or ""), size=10)
        y += row_h

    y += 8
    tbl = expense_table(template)
    col_w = [content_w * 0.34, content_w * 0.18, content_w * 0.18, content_w * 0.30]
    headers = ["支出内容", "金额", "核销金额", "备注"]
    exp_h = 18.0

    def col_x(i: int) -> float:
        return margin_x + sum(col_w[:i])

    for i, h in enumerate(headers):
        x0 = col_x(i)
        draw_box(x0, y, x0 + col_w[i], y + exp_h)
        text(x0 + 3, y + 13, h, size=9)
    y += exp_h

    row_vals = values.get("rows") or {}
    for row in (tbl["rows"] if tbl else []):
        saved = row_vals.get(row["id"]) or {}
        cells = [
            str(row.get("label") or row["id"]),
            str(saved.get("amount") or ""),
            str(saved.get("reimburse") or ""),
            str(saved.get("remark") or ""),
        ]
        for i, cell in enumerate(cells):
            x0 = col_x(i)
            draw_box(x0, y, x0 + col_w[i], y + exp_h)
            s = cell
            if len(s) > 28:
                s = s[:27] + "…"
            text(x0 + 3, y + 13, s, size=9)
        y += exp_h
        if y > page_h - 70:
            break

    totals = form_totals(values)
    cells = ["合计", totals["amount"], totals["reimburse"], ""]
    for i, cell in enumerate(cells):
        x0 = col_x(i)
        draw_box(x0, y, x0 + col_w[i], y + exp_h)
        text(x0 + 3, y + 13, cell, size=9)
    y += exp_h + 16

    text(margin_x, y + 12, "院系（单位）负责人（签字）：　　　　　　经办人（签字）：", size=10)
    y += 22
    text(margin_x, y + 12, "（公章）：", size=10)
    y += 22
    text(margin_x, y + 12, "备注：附活动方案（或通知）、活动总结或新闻稿等相关材料。", size=9)

    tw.write_text(page)
    doc.subset_fonts()
    doc.save(dest, garbage=4, deflate=True)
    doc.close()
    log.info("render form pdf template=%s path=%s", template.get("id"), dest)
    return dest


def docx_to_pdf(docx_path: Path, pdf_path: Path | None = None) -> Path:
    """Optional Word conversion — prefer render_form_pdf for preview/compose."""
    src = docx_path.resolve()
    if not src.is_file():
        raise FormError("填写后的 Word 文件不存在")
    out = (pdf_path or src.with_suffix(".pdf")).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise FormError("未安装 pywin32，无法将表格转为 PDF。仍可下载 Word，或使用程序内 PDF 预览。") from exc
    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), ReadOnly=True)
        doc.SaveAs(str(out), FileFormat=17)
    except Exception as exc:
        log.exception("docx to pdf failed src=%s", src)
        raise FormError(f"Word 未能将表格转为 PDF：{exc}") from exc
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    if not out.is_file():
        raise FormError("Word 转 PDF 未生成文件。请确认本机已安装 Microsoft Word。")
    return out

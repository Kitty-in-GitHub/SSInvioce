from pathlib import Path

from backend.app.db import get_conn
from backend.app.services.layout import _load_pixmap, _trim_whitespace, compose_entry_pdf

with get_conn() as conn:
    rows = [
        dict(r)
        for r in conn.execute(
            "select id, entry_id, type, stored_path from materials where entry_id=4 order by id"
        ).fetchall()
    ]
print("materials", rows)

inv = next(r for r in rows if r["type"] == "invoice")
pix = _load_pixmap(Path("data/uploads") / inv["stored_path"])
print("before", pix.width, pix.height)
trimmed = _trim_whitespace(pix, white_level=250, pad=2)
print("after", trimmed.width, trimmed.height)

by = {r["type"]: r["stored_path"] for r in rows}
out = compose_entry_pdf(
    entry_id=4,
    invoice_rel=by["invoice"],
    order_rel=by["order"],
    payment_rel=by["payment"],
)
print("wrote", out, out.stat().st_size)

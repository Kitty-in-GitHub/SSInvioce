from backend.app.db import get_conn, init_db, now_iso
from backend.app.main import app
from backend.app.services.amount import parse_amount_from_filename

init_db()
print("filename", parse_amount_from_filename("260509_12.00_demo.pdf"))
with get_conn() as conn:
    existing = conn.execute("SELECT id FROM groups WHERE name=?", ("测试组",)).fetchone()
    if not existing:
        cur = conn.execute(
            "INSERT INTO groups (name, note, sort_order, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("测试组", "", 1, now_iso(), now_iso()),
        )
        print("group", cur.lastrowid)
    else:
        print("group exists", existing["id"])
    cols = [r[1] for r in conn.execute("PRAGMA table_info(entries)").fetchall()]
    print("entry cols", cols)

paths = []
for r in app.routes:
    p = getattr(r, "path", None)
    if p and ("group" in p or "entries" in p):
        paths.append(p)
print("routes", sorted(set(paths))[:30])

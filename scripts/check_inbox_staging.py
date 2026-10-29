"""校验收件箱即暂存：批量上传直接进收件箱，关闭/重启后仍可继续整理。

隔离运行：把 config 的数据目录指向系统临时目录，不碰项目 data/。
用真实发票 PDF + 合成截图 PDF/PNG 走一遍 preview → recluster → confirm →
discard 流程，并对数据库/文件系统做断言。

用法：
    python scripts/check_inbox_staging.py
    python scripts/check_inbox_staging.py --keep   # 保留临时数据便于排查
"""

from __future__ import annotations

import asyncio
import io
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- 必须在导入业务模块之前把数据目录改到临时目录 -------------------------
import backend.app.config as config  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="ssinv_staging_"))
config.DATA_DIR = TMP / "data"
config.UPLOADS_DIR = config.DATA_DIR / "uploads"
config.EXPORTS_DIR = config.DATA_DIR / "exports"
config.CACHE_DIR = config.DATA_DIR / "cache"
config.TEMPLATES_DIR = config.DATA_DIR / "templates"
config.INBOX_DIR = config.UPLOADS_DIR / "inbox"
config.TRASH_DIR = config.DATA_DIR / "trash"
config.DB_PATH = config.DATA_DIR / "app.db"

from PIL import Image  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.app.db import get_conn, init_db  # noqa: E402
from backend.app.models import (  # noqa: E402
    ClassifyClusterConfirm,
    ClassifyClusterMaterial,
    ClassifyConfirmItem,
    ClassifyConfirmRequest,
    EntryCreate,
    MaterialAssign,
)
from backend.app.routers import classify as classify_router  # noqa: E402
from backend.app.routers import entries as entries_router  # noqa: E402
from backend.app.routers import materials as materials_router  # noqa: E402
from backend.app.routers.classify import DiscardRequest  # noqa: E402
from backend.app.services import trash as trash_service  # noqa: E402
from backend.app.services.storage import resolve_stored  # noqa: E402

PASSED = 0
FAILED = 0


def check(ok: bool, name: str, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}   {detail}")


def upload(name: str, data: bytes, mime: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers=Headers({"content-type": mime}))


def png_bytes(size=(420, 620), color=(255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def db_rows(where: str = "", params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        sql = "SELECT * FROM materials"
        if where:
            sql += f" WHERE {where}"
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", params).fetchall()]


def main() -> int:
    init_db()
    samples = sorted((ROOT / "data" / "uploads").rglob("*.pdf"))
    if len(samples) < 4:
        print("需要至少 4 份发票样本（data/uploads/**/*.pdf）")
        return 2
    inv_a = samples[0].read_bytes()
    inv_b = samples[1].read_bytes()
    inv_c = samples[2].read_bytes()
    blank = png_bytes()
    blank2 = png_bytes((410, 610), (252, 252, 252))

    print("\n[1] 批量上传：三个文件直接进收件箱并自动聚类")
    p1 = asyncio.run(
        classify_router.classify_preview(
            files=[
                upload("发票A.pdf", inv_a, "application/pdf"),
                upload("订单截图.png", blank, "image/png"),
                upload("微信支付账单.png", blank, "image/png"),
            ]
        )
    )
    check(len(p1.items) == 3, "收件箱快照含 3 个材料", f"items={len(p1.items)}")
    check(len(p1.clusters) == 1, "归成 1 个拟建条目", f"clusters={len(p1.clusters)}")
    cluster = p1.clusters[0] if p1.clusters else None
    check(bool(cluster and cluster.complete), "拟建条目齐套", f"missing={cluster.missing if cluster else '?'}")
    check(cluster is not None and cluster.duplicate_warning is None, "首次上传不误报重复")

    rows = db_rows("entry_id IS NULL")
    check(len(rows) == 3, "数据库里 3 行未挂条目", f"rows={len(rows)}")
    check(all(r["analyze_status"] == "staged" for r in rows), "状态都是 staged")
    check(all(r["features_json"] for r in rows), "特征已缓存到 features_json")

    inbox = materials_router.list_inbox()
    check(len(inbox) == 3 and all(m.staged for m in inbox), "收件箱接口也能看到这 3 个材料")

    print("\n[2] 关闭窗口再打开：重新聚类应拿到同一批材料")
    p2 = classify_router.classify_recluster(None)
    ids1 = sorted(i.temp_id for i in p1.items)
    ids2 = sorted(i.temp_id for i in p2.items)
    check(ids1 == ids2, "材料 id 完全一致", f"{ids1} vs {ids2}")
    check(len(p2.clusters) == 1 and p2.clusters[0].complete, "重新打开后仍归为 1 个齐套簇")

    print("\n[3] 在收件箱里改类型：应持久化并影响归组")
    order_id = next((i.temp_id for i in p2.items if i.suggested_type == "order"), None)
    check(order_id is not None, "找到订单材料")
    if order_id is not None:
        materials_router.update_material(int(order_id), MaterialAssign(type="payment"))
        p3 = classify_router.classify_recluster(None)
        changed = next((i for i in p3.items if i.temp_id == order_id), None)
        check(changed is not None and changed.suggested_type == "payment", "改类型后重新聚类能读到新类型")
        check(next(c for c in p3.clusters if order_id in c.temp_ids).missing, "改类型后该簇缺 order")
        materials_router.update_material(int(order_id), MaterialAssign(type="order"))

    print("\n[4] 确认入库：建条目、材料挂上去、收件箱清空")
    p4 = classify_router.classify_recluster(None)
    c = p4.clusters[0]
    payload = ClassifyConfirmRequest(
        clusters=[
            ClassifyClusterConfirm(
                title="测试报销",
                amount=c.amount,
                materials=[ClassifyClusterMaterial(temp_id=t, type=c.types[t]) for t in c.temp_ids],
            )
        ]
    )
    res = classify_router.classify_confirm(payload)
    check(len(res["created_entry_ids"]) == 1, "创建了 1 个条目", str(res))
    entry_id = res["created_entry_ids"][0]
    entry = entries_router.get_entry(entry_id)
    check(entry.completeness.complete, "条目齐套")
    check(len(entry.materials) == 3, "条目有 3 个材料", f"materials={len(entry.materials)}")
    check(all(not m.staged for m in entry.materials), "材料不再是 staged")
    check(all(m.entry_id == entry_id for m in entry.materials), "材料都指向新条目")
    check(len(materials_router.list_inbox()) == 0, "收件箱已清空")

    print("\n[5] 重复发票：同一张再上传应提示与已有条目重复")
    p5 = asyncio.run(
        classify_router.classify_preview(files=[upload("发票A-再传.pdf", inv_a, "application/pdf")])
    )
    check(len(p5.items) == 1, "新增 1 个材料")
    warn = p5.clusters[0].duplicate_warning if p5.clusters else None
    check(warn is not None and warn.reason == "invoice_number", "识别为发票号码重复", str(warn))
    check(warn is not None and warn.existing_entry_id == entry_id, "指向刚创建的条目", str(warn))

    print("\n[6] 丢弃暂存：进回收站，可恢复，可彻底删除")
    dup_id = p5.items[0].temp_id
    before = next(r for r in db_rows() if r["id"] == int(dup_id))
    dup_path = resolve_stored(before["stored_path"])
    check(dup_path.exists(), "丢弃前文件存在")
    classify_router.classify_discard(DiscardRequest(temp_ids=[dup_id]))
    check(not any(r["id"] == int(dup_id) for r in db_rows()), "材料行已移出收件箱")
    check(not dup_path.exists(), "原位置文件已移走")
    tr = trash_service.list_trash()
    check(tr["count"] == 1, "回收站里有 1 个文件", str(tr["count"]))
    item = tr["groups"][0]["items"][0]
    check(item["original_name"] == before["original_name"], "回收站记录了原文件名")

    restored = trash_service.restore([item["id"]])
    check(bool(restored) and restored[0]["ok"], "从回收站恢复成功", str(restored))
    rid = restored[0]["material_id"] if restored else None
    restored_row = next((r for r in db_rows() if r["id"] == rid), None)
    check(restored_row is not None, "材料行已恢复")
    check(restored_row is not None and resolve_stored(restored_row["stored_path"]).exists(), "文件已恢复到 uploads")
    check(len(materials_router.list_inbox()) == 1, "恢复到收件箱")

    materials_router.delete_material(rid)
    check(len(materials_router.list_inbox()) == 0, "再次删除后收件箱为空")
    trash_service.purge_all()
    check(trash_service.list_trash()["count"] == 0, "彻底删除后回收站为空")

    print("\n[7] 确认时选择「先放收件箱」：材料留下但不属于任何条目")
    p6 = asyncio.run(
        classify_router.classify_preview(files=[upload("发票B.pdf", inv_b, "application/pdf")])
    )
    tid_b = p6.items[0].temp_id
    classify_router.classify_confirm(
        ClassifyConfirmRequest(items=[ClassifyConfirmItem(temp_id=tid_b, type="invoice")])
    )
    row_b = next(r for r in db_rows() if r["id"] == int(tid_b))
    check(row_b["entry_id"] is None, "entry_id 仍为空")
    check(row_b["analyze_status"] == "done", "状态改为 done（不再显示待整理）")
    inbox = materials_router.list_inbox()
    check(len(inbox) == 1 and not inbox[0].staged, "收件箱里保留该材料且不标 staged")

    print("\n[8] 收件箱里直接挂到已有条目")
    entry2 = entries_router.create_entry(EntryCreate(title="挂载测试"))
    materials_router.update_material(int(tid_b), MaterialAssign(entry_id=entry2.id, type="invoice"))
    row_b = next(r for r in db_rows() if r["id"] == int(tid_b))
    check(row_b["entry_id"] == entry2.id, "已挂到条目")
    check(row_b["analyze_status"] == "done", "状态为 done")
    check(len(materials_router.list_inbox()) == 0, "收件箱已清空")

    print("\n[9] 同一批两张同号发票：自动折叠为 1 个代表 + 1 个副本")
    p7 = asyncio.run(
        classify_router.classify_preview(
            files=[
                upload("同号1.pdf", inv_c, "application/pdf"),
                upload("同号2.pdf", inv_c, "application/pdf"),
            ]
        )
    )
    check(len(p7.duplicate_temp_ids) == 1, "折叠 1 个重复副本", str(p7.duplicate_temp_ids))
    dup_id7 = p7.duplicate_temp_ids[0]
    dup_item7 = next(i for i in p7.items if i.temp_id == dup_id7)
    check(dup_item7.duplicate_of is not None, "副本指向代表文件")
    cluster_ids7 = {t for c in p7.clusters for t in c.temp_ids}
    check(dup_id7 not in cluster_ids7, "副本不参与聚类")
    check(
        len(p7.clusters) == 1 and len(p7.clusters[0].temp_ids) == 1,
        "只保留一个代表文件成簇",
        str([c.temp_ids for c in p7.clusters]),
    )
    classify_router.classify_discard(DiscardRequest(temp_ids=[i.temp_id for i in p7.items]))

    print("\n[10] 已入库材料不能重复确认")
    try:
        classify_router.classify_confirm(payload)
        check(False, "重复确认应被拒绝")
    except HTTPException as exc:
        check(exc.status_code == 400, "重复确认返回 400", f"{exc.status_code} {exc.detail}")

    print("\n[11] 把新上传的材料并入已有条目（补传订单）")
    inv_d = samples[3].read_bytes()
    p8 = asyncio.run(
        classify_router.classify_preview(
            files=[
                upload("发票D.pdf", inv_d, "application/pdf"),
                upload("微信支付账单2.png", blank, "image/png"),
            ]
        )
    )
    c8 = p8.clusters[0]
    res8 = classify_router.classify_confirm(
        ClassifyConfirmRequest(
            clusters=[
                ClassifyClusterConfirm(
                    title="补传测试甲",
                    amount=c8.amount,
                    materials=[ClassifyClusterMaterial(temp_id=t, type=c8.types[t]) for t in c8.temp_ids],
                )
            ]
        )
    )
    entry3 = res8["created_entry_ids"][0]
    e3 = entries_router.get_entry(entry3)
    check(not e3.completeness.complete, "甲暂时不齐套", str(e3.completeness.missing))
    amount_before = e3.amount

    p9 = asyncio.run(
        classify_router.classify_preview(files=[upload("订单_999.00.png", blank, "image/png")])
    )
    tid_order = p9.items[0].temp_id
    res9 = classify_router.classify_confirm(
        ClassifyConfirmRequest(
            clusters=[
                ClassifyClusterConfirm(
                    title="订单",
                    entry_id=entry3,
                    materials=[ClassifyClusterMaterial(temp_id=tid_order, type="order")],
                )
            ]
        )
    )
    check(res9["created_entry_ids"] == [], "没有新建条目", str(res9))
    check(res9["updated_entry_ids"] == [entry3], "记录了并入的条目", str(res9))
    e3 = entries_router.get_entry(entry3)
    check(e3.completeness.complete, "并入后条目齐套", str(e3.completeness.missing))
    check(float(e3.amount) == float(amount_before), "已有金额未被覆盖", f"{amount_before} -> {e3.amount}")
    check(len(e3.materials) == 3, "条目有 3 个材料", f"materials={len(e3.materials)}")

    print("\n[12] 并入时槽位已占用应被拒绝")
    p10 = asyncio.run(
        classify_router.classify_preview(files=[upload("订单_888.00.png", blank, "image/png")])
    )
    tid2 = p10.items[0].temp_id
    try:
        classify_router.classify_confirm(
            ClassifyConfirmRequest(
                clusters=[
                    ClassifyClusterConfirm(
                        title="订单2",
                        entry_id=entry3,
                        materials=[ClassifyClusterMaterial(temp_id=tid2, type="order")],
                    )
                ]
            )
        )
        check(False, "槽位冲突应被拒绝")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        check(
            exc.status_code == 400 and "已有" in (detail.get("message") or ""),
            "槽位冲突返回 400",
            str(exc.detail),
        )
    classify_router.classify_discard(DiscardRequest(temp_ids=[tid2]))

    print("\n[13] 非发票材料重复：同一张订单/支付截图再次上传应提示")
    p11 = asyncio.run(
        classify_router.classify_preview(
            files=[
                upload("订单截图A.png", blank2, "image/png"),
                upload("微信支付账单A.png", blank2, "image/png"),
            ]
        )
    )
    c11 = p11.clusters[0]
    res11 = classify_router.classify_confirm(
        ClassifyConfirmRequest(
            clusters=[
                ClassifyClusterConfirm(
                    title="重复测试乙",
                    amount=c11.amount,
                    materials=[ClassifyClusterMaterial(temp_id=t, type=c11.types[t]) for t in c11.temp_ids],
                )
            ]
        )
    )
    entry4 = res11["created_entry_ids"][0]

    p12 = asyncio.run(
        classify_router.classify_preview(
            files=[
                upload("订单截图A.png", blank2, "image/png"),
                upload("微信支付账单A.png", blank2, "image/png"),
            ]
        )
    )
    warn12 = next((c.duplicate_warning for c in p12.clusters if c.duplicate_warning), None)
    check(warn12 is not None and warn12.reason == "existing_file_hash", "非发票重复也能识别", str(warn12))
    check(warn12 is not None and warn12.existing_entry_id == entry4, "指向已有条目", str(warn12))
    check(warn12 is not None and warn12.existing_type in ("order", "payment"), "带上材料类型", str(warn12))

    print("\n[14] 历史发票缺号码时，仍按文件内容识别重复")
    with get_conn() as conn:
        inv_row = conn.execute(
            "SELECT id FROM materials WHERE entry_id = ? AND type = 'invoice' ORDER BY id LIMIT 1",
            (entry_id,),
        ).fetchone()
        conn.execute("UPDATE materials SET invoice_number = NULL WHERE id = ?", (inv_row["id"],))
    p13 = asyncio.run(
        classify_router.classify_preview(files=[upload("发票A-再传3.pdf", inv_a, "application/pdf")])
    )
    new_tid = p13.items[-1].temp_id
    cluster13 = next(c for c in p13.clusters if new_tid in c.temp_ids)
    warn13 = cluster13.duplicate_warning
    check(warn13 is not None and warn13.reason == "existing_file_hash", "按哈希识别历史发票重复", str(warn13))
    check(warn13 is not None and warn13.existing_entry_id == entry_id, "指向原条目", str(warn13))
    check(warn13 is not None and warn13.existing_type == "invoice", "带上 invoice 类型", str(warn13))

    print("\n[15] 删除条目：材料进回收站，恢复到收件箱")
    before_inbox = len(materials_router.list_inbox())
    entries_router.delete_entry(entry4)
    tr = trash_service.list_trash()
    entry_groups = [g for g in tr["groups"] if g["reason"] == "entry_deleted"]
    entry_items = [i for g in entry_groups for i in g["items"]]
    check(len(entry_items) == 2, "条目材料进回收站", str(len(entry_items)))
    check(all(g["entry_title"] == "重复测试乙" for g in entry_groups), "记录了原条目名")
    restored = trash_service.restore([i["id"] for i in entry_items])
    check(
        all(r["ok"] and r["restored_to"] == "inbox" for r in restored),
        "原条目已删除，恢复到收件箱",
        str(restored),
    )
    check(
        len(materials_router.list_inbox()) == before_inbox + 2,
        "收件箱多出 2 个恢复的材料",
    )

    print("\n[17] 快速上传：只入库不识别，整理时才归类")
    with get_conn() as conn:
        leftover = [
            str(r["id"]) for r in conn.execute("SELECT id FROM materials WHERE entry_id IS NULL").fetchall()
        ]
    if leftover:
        classify_router.classify_discard(DiscardRequest(temp_ids=leftover))

    res_fast = asyncio.run(
        materials_router.upload_materials_fast(
            files=[
                upload("快速_发票.pdf", inv_a, "application/pdf"),
                upload("快速_订单.png", blank, "image/png"),
            ]
        )
    )
    check(res_fast["count"] == 2, "快速上传 2 个文件", str(res_fast["count"]))
    rows_fast = db_rows("entry_id IS NULL")
    check(len(rows_fast) == 2, "收件箱有 2 行", str(len(rows_fast)))
    check(all(r["type"] == "unknown" for r in rows_fast), "类型保持 unknown（不归类）")
    check(all(r["analyze_status"] == "raw" for r in rows_fast), "状态为 raw")
    check(all(r["content_sha256"] for r in rows_fast), "已记录内容哈希")
    check(all(m.raw for m in materials_router.list_inbox()), "收件箱接口标记 raw")

    p_fast = classify_router.classify_recluster(None)
    by_name = {i.original_name: i for i in p_fast.items}
    check(by_name["快速_发票.pdf"].suggested_type == "invoice", "整理时识别出发票")
    check(by_name["快速_订单.png"].suggested_type == "order", "整理时识别出订单")
    rows_fast = db_rows("entry_id IS NULL")
    check(all(r["analyze_status"] == "done" for r in rows_fast), "识别后状态转为 done")
    check(any(r["type"] == "invoice" for r in rows_fast), "类型已回写")

    print(f"\n汇总：通过 {PASSED}，失败 {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    keep = "--keep" in sys.argv
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        if not keep:
            shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(code)

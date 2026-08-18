from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..config import DATA_DIR, DB_PATH, TEMPLATES_DIR, UPLOADS_DIR, ensure_dirs
from ..db import init_db
from ..logging_config import get_logger
from ..services.settings_store import SETTINGS_PATH

router = APIRouter(prefix="/api/backup", tags=["backup"])
log = get_logger("backup")

BACKUP_SERVICE = "star-invoice-helper"
BACKUP_FORMAT = 1
MANIFEST_NAME = "manifest.json"


def _included_dirs() -> dict[str, Path]:
    return {"uploads": UPLOADS_DIR, "templates": TEMPLATES_DIR}


def _sqlite_copy(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    if not DB_PATH.is_file():
        return
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    src = sqlite3.connect(uri, uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _add_tree(zf: zipfile.ZipFile, root: Path, arc_prefix: str) -> None:
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file():
            zf.write(path, f"{arc_prefix}/{path.relative_to(root).as_posix()}")


def _build_zip(zip_path: Path) -> None:
    ensure_dirs()
    work = Path(tempfile.mkdtemp(prefix="sih_bak_"))
    try:
        db_copy = work / "app.db"
        _sqlite_copy(db_copy)
        manifest = {
            "service": BACKUP_SERVICE,
            "format": BACKUP_FORMAT,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (work / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(work / MANIFEST_NAME, MANIFEST_NAME)
            if db_copy.is_file():
                zf.write(db_copy, "app.db")
            if SETTINGS_PATH.is_file():
                zf.write(SETTINGS_PATH, "settings.json")
            for arc, folder in _included_dirs().items():
                _add_tree(zf, folder, arc)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="不是本软件的备份文件（缺少 manifest.json）") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="备份清单无法解析") from exc
    if data.get("service") != BACKUP_SERVICE:
        raise HTTPException(status_code=400, detail="备份文件与本软件不匹配")
    return data


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/") or not name:
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise HTTPException(status_code=400, detail="备份文件路径不合法")
        target = (dest / name).resolve()
        if dest_res not in target.parents and target != dest_res:
            raise HTTPException(status_code=400, detail="备份文件路径不合法")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _swap_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)


def _replace_file(src: Path | None, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    if src and src.is_file():
        shutil.copy2(src, dest)


def _snapshot_live(bak: Path) -> None:
    bak.mkdir(parents=True, exist_ok=True)
    if DB_PATH.is_file():
        shutil.copy2(DB_PATH, bak / "app.db")
    if SETTINGS_PATH.is_file():
        shutil.copy2(SETTINGS_PATH, bak / "settings.json")
    if UPLOADS_DIR.is_dir():
        shutil.copytree(UPLOADS_DIR, bak / "uploads")
    if TEMPLATES_DIR.is_dir():
        shutil.copytree(TEMPLATES_DIR, bak / "templates")


def _restore_snapshot(bak: Path) -> None:
    ensure_dirs()
    _replace_file(bak / "app.db" if (bak / "app.db").is_file() else None, DB_PATH)
    _replace_file(bak / "settings.json" if (bak / "settings.json").is_file() else None, SETTINGS_PATH)
    if (bak / "uploads").is_dir():
        _swap_dir(bak / "uploads", UPLOADS_DIR)
    if (bak / "templates").is_dir():
        _swap_dir(bak / "templates", TEMPLATES_DIR)


def _drop_wal() -> None:
    for suffix in ("-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                log.debug("could not remove %s", p, exc_info=True)


@router.get("")
def download_backup():
    tmp = Path(tempfile.mkdtemp(prefix="sih_zip_"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"报销助手备份_{stamp}.zip"
    zip_path = tmp / "backup.zip"
    try:
        _build_zip(zip_path)
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        log.exception("backup zip failed")
        raise HTTPException(status_code=500, detail="生成备份失败") from exc
    log.info("backup zip ready bytes=%s", zip_path.stat().st_size)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
        background=BackgroundTask(lambda: shutil.rmtree(tmp, ignore_errors=True)),
    )


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    name = file.filename or ""
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 备份文件")
    tmp = Path(tempfile.mkdtemp(prefix="sih_rst_"))
    zip_path = tmp / "in.zip"
    extract = tmp / "extract"
    bak = DATA_DIR / ".restore_bak"
    try:
        zip_path.write_bytes(await file.read())
        with zipfile.ZipFile(zip_path, "r") as zf:
            if zf.testzip() is not None:
                raise HTTPException(status_code=400, detail="备份 zip 已损坏")
            _read_manifest(zf)
            _safe_extract(zf, extract)
        if bak.exists():
            shutil.rmtree(bak, ignore_errors=True)
        _snapshot_live(bak)
        try:
            _drop_wal()
            db_src = extract / "app.db"
            if not db_src.is_file():
                raise HTTPException(status_code=400, detail="备份中缺少数据库")
            _replace_file(db_src, DB_PATH)
            _drop_wal()
            settings_src = extract / "settings.json"
            _replace_file(settings_src if settings_src.is_file() else None, SETTINGS_PATH)
            ensure_dirs()
            _swap_dir(extract / "uploads", UPLOADS_DIR)
            _swap_dir(extract / "templates", TEMPLATES_DIR)
            init_db()
        except HTTPException:
            _restore_snapshot(bak)
            raise
        except Exception as exc:
            log.exception("restore apply failed")
            _restore_snapshot(bak)
            raise HTTPException(status_code=500, detail="恢复失败，已尝试还原原数据") from exc
        shutil.rmtree(bak, ignore_errors=True)
        log.info("restore ok from %r", name)
        return {"ok": True}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

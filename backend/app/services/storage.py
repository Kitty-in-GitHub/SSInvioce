from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from PIL import Image

from ..config import DATA_DIR, TRASH_DIR, UPLOADS_DIR, ensure_dirs
from ..logging_config import get_logger

log = get_logger("storage")

SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+", re.UNICODE)


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = SAFE_NAME_RE.sub("_", base).strip("._")
    return cleaned or "file"


def store_upload(
    content: bytes,
    original_name: str,
    *,
    entry_id: int | None = None,
) -> tuple[str, Path]:
    """Save bytes to disk. Returns (relative_stored_path, absolute_path)."""
    ensure_dirs()
    folder = UPLOADS_DIR / (str(entry_id) if entry_id is not None else "inbox")
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}_{safe_filename(original_name)}"
    abs_path = folder / fname
    abs_path.write_bytes(content)
    rel = abs_path.relative_to(UPLOADS_DIR).as_posix()
    return rel, abs_path


def resolve_stored(rel_path: str) -> Path:
    path = (UPLOADS_DIR / rel_path).resolve()
    if not str(path).startswith(str(UPLOADS_DIR.resolve())):
        raise ValueError("invalid stored path")
    return path


def probe_image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def delete_stored_files(rel_paths: list[str]) -> None:
    for rel in rel_paths:
        delete_file(rel)


def delete_file(rel_path: str) -> None:
    if not rel_path:
        return
    try:
        path = resolve_stored(rel_path)
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def move_to_trash(rel_path: str) -> dict | None:
    """Move an uploads-relative file into data/trash; returns path+size or None."""
    if not rel_path:
        return None
    try:
        src = resolve_stored(rel_path)
    except ValueError:
        return None
    if not src.is_file():
        return None
    ensure_dirs()
    dest = TRASH_DIR / f"{uuid.uuid4().hex}_{src.name}"
    try:
        size = src.stat().st_size
        shutil.move(str(src), str(dest))
    except OSError:
        log.exception("move to trash failed path=%s", rel_path)
        return None
    return {"trash_path": dest.relative_to(DATA_DIR).as_posix(), "size": size}


def resolve_trash(trash_path: str) -> Path | None:
    if not trash_path:
        return None
    try:
        path = (DATA_DIR / trash_path).resolve()
    except OSError:
        return None
    if not str(path).startswith(str(TRASH_DIR.resolve())):
        return None
    return path


def restore_from_trash(trash_path: str, original_name: str, entry_id: int | None) -> str | None:
    """Move a trashed file back under data/uploads; returns new stored_path."""
    src = resolve_trash(trash_path)
    if src is None or not src.is_file():
        return None
    ensure_dirs()
    folder = UPLOADS_DIR / (str(entry_id) if entry_id is not None else "inbox")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex}_{safe_filename(original_name)}"
    try:
        shutil.move(str(src), str(dest))
    except OSError:
        log.exception("restore from trash failed path=%s", trash_path)
        return None
    return dest.relative_to(UPLOADS_DIR).as_posix()


def purge_trash_file(trash_path: str) -> None:
    path = resolve_trash(trash_path)
    if path is None or not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        log.exception("purge trash file failed path=%s", trash_path)

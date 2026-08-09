from __future__ import annotations

import re
import uuid
from pathlib import Path

from PIL import Image

from ..config import UPLOADS_DIR, ensure_dirs

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


def delete_file(rel_path: str) -> None:
    try:
        path = resolve_stored(rel_path)
        if path.exists():
            path.unlink()
    except Exception:
        pass


def move_inbox_to_entry(rel_path: str, entry_id: int) -> str:
    src = resolve_stored(rel_path)
    dest_dir = UPLOADS_DIR / str(entry_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        src.replace(dest)
    return dest.relative_to(UPLOADS_DIR).as_posix()

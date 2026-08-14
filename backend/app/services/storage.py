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

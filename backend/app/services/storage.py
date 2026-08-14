from __future__ import annotations

import os
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


def _recycle_windows(paths: list[Path]) -> bool:
    """Send files to Recycle Bin (Explorer-style). Returns True if Shell accepted the op."""
    import ctypes
    from ctypes import wintypes

    existing = [p.resolve() for p in paths if p.exists() and p.is_file()]
    if not existing:
        return True

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_void_p),
            ("pTo", ctypes.c_void_p),
            ("fFlags", wintypes.USHORT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400
    flags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI

    joined = "\0".join(str(p) for p in existing) + "\0\0"
    buf = ctypes.create_unicode_buffer(joined)
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.addressof(buf)
    op.pTo = None
    op.fFlags = flags
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted


def delete_stored_files(rel_paths: list[str]) -> None:
    """Remove stored uploads. On Windows, prefer Recycle Bin to avoid 360 ransomware heuristics."""
    abs_paths: list[Path] = []
    for rel in rel_paths:
        if not rel:
            continue
        try:
            abs_paths.append(resolve_stored(rel))
        except Exception:
            continue
    if not abs_paths:
        return
    recycled = False
    if os.name == "nt":
        try:
            recycled = _recycle_windows(abs_paths)
        except Exception:
            recycled = False
    if recycled:
        return
    for path in abs_paths:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def delete_file(rel_path: str) -> None:
    delete_stored_files([rel_path])

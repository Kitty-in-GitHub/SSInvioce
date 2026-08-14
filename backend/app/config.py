from __future__ import annotations

from pathlib import Path

# Project root: StarInvoiceHelper/
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORTS_DIR = DATA_DIR / "exports"
TEMPLATES_DIR = DATA_DIR / "templates"
INBOX_DIR = UPLOADS_DIR / "inbox"
BUILTIN_FORM_TEMPLATES_DIR = Path(__file__).resolve().parent / "form_templates"
DB_PATH = DATA_DIR / "app.db"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
VENDOR_OCR_DIR = ROOT_DIR / "vendor" / "ocr"

# Dedicated port — avoid colliding with unrelated services on :8000
API_HOST = "127.0.0.1"
API_PORT = 8765


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOADS_DIR, EXPORTS_DIR, TEMPLATES_DIR, INBOX_DIR):
        path.mkdir(parents=True, exist_ok=True)

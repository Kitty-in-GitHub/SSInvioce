from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import VENDOR_OCR_DIR
from ..logging_config import get_logger

log = get_logger("ocr")

_DET = "ch_PP-OCRv3_det_infer.onnx"
_CLS = "ch_ppocr_mobile_v2.0_cls_infer.onnx"
_REC = "ch_PP-OCRv3_rec_infer.onnx"


def ocr_models_ready(base: Path | None = None) -> bool:
    root = base or VENDOR_OCR_DIR
    models = root / "models"
    return all((models / name).is_file() for name in (_DET, _CLS, _REC))


@lru_cache(maxsize=1)
def _engine():
    if not ocr_models_ready():
        log.warning("OCR models missing under %s — image OCR disabled", VENDOR_OCR_DIR)
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        log.warning("rapidocr-onnxruntime not installed — image OCR disabled")
        return None
    models = VENDOR_OCR_DIR / "models"
    engine = RapidOCR(
        det_model_path=str(models / _DET),
        cls_model_path=str(models / _CLS),
        rec_model_path=str(models / _REC),
    )
    log.info("RapidOCR ready models=%s", models)
    return engine


def ocr_available() -> bool:
    return _engine() is not None


def ocr_image(path: Path | str) -> str:
    """Return concatenated OCR text, or empty string if unavailable/failed."""
    engine = _engine()
    if engine is None:
        return ""
    try:
        result, _ = engine(str(path))
    except Exception:
        log.exception("OCR failed path=%s", path)
        return ""
    if not result:
        return ""
    # result rows: [box, text, score]
    parts: list[str] = []
    for row in result:
        if not row or len(row) < 2:
            continue
        text = str(row[1]).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)

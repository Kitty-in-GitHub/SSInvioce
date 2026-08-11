# OCR models (ONNX) for portable / green builds

Place PP-OCR ONNX weights under `models/`:

- `ch_PP-OCRv3_det_infer.onnx`
- `ch_ppocr_mobile_v2.0_cls_infer.onnx`
- `ch_PP-OCRv3_rec_infer.onnx`

The app loads RapidOCR with these paths. If models are missing, image OCR is disabled and classification falls back to filename / size heuristics (PDF text extraction still works).

These files are intentionally vendored (~13MB) so the whole project folder can be copied without downloading models at runtime.

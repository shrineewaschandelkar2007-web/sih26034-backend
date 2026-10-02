# models_data

- `compliance_rules.json` - the data-driven rule set the compliance engine evaluates (mirrors the `compliance_rules` table).
- `reference_products.seed.json` - demo reference catalogue. **Only Parle-G has real values; the rest are placeholders.**
- `ocr/`, `barcode/`, `tampering/` - reserved for locally bundled weights. Currently empty on purpose:
  - PaddleOCR downloads and caches its own weights on first run (needs internet once; set `PADDLE_PDX_CACHE_HOME` to control where).
  - pyzbar/ZBar is a classical decoder - it has no weights.
  - The tampering heuristic has no weights. A real ManTraNet would put its `.h5` weights under `tampering/` in its own service.

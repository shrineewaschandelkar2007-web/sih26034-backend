# SIH26034 Backend — AI-Powered Packaged Commodity Compliance System

Backend for the Legal Metrology (Packaged Commodities) Rules, 2011 compliance
checker. Built against `SIH26034_BACKEND_SPEC_FOR_CLAUDE.pdf`.

**Core idea (spec section 1):** the AI components (OCR, barcode, tampering)
only extract *evidence*. A separate, deterministic, data-driven compliance
engine interprets that evidence against rules. The AI never decides
compliance itself.

## Status — what is real vs. what is a documented placeholder

Every part below was actually run, not just written. Commands to reproduce
each result are given so you can re-verify.

| Component | Status | Notes |
|---|---|---|
| FastAPI app, all routes, CORS, error handling | ✅ Working | `TestClient` used to hit every endpoint |
| Image validation/preprocessing | ✅ Working | rejects corrupt/oversized/tiny/non-image uploads |
| Barcode (pyzbar/ZBar) | ✅ Working | decoded a real generated EAN-13 (`8901719123870`) |
| OCR (PaddleOCR) | ✅ Code works, ⚠️ **needs internet once** | PaddleOCR downloads ~100MB of model weights on first run. In this sandboxed build environment that download was blocked ("No available model hosting platforms detected"), so the end-to-end smoke test below shows `OCR: UNAVAILABLE` — that is the *documented, expected* failure mode (see `ocr_model.py`), not a crash. On a normal internet connection this resolves itself the first time you run the server. The extraction regex logic itself (`field_extractor.py`) was unit-tested separately against real OCR text the team captured from an actual Parle-G packet, and passes. |
| Field extraction + normalization | ✅ Working, tuned on real data | patterns were built and iterated against real OCR output from a Parle-G packet (MRP, net quantity with the "+extra=total" format, PKD/USE BY dates, consumer care, manufacturer) |
| Product matching (barcode + fuzzy) | ✅ Working | |
| Field-level reference comparison | ✅ Working | compares on normalized values (e.g. net quantity in `(value, unit)` form), never on raw OCR strings |
| Compliance engine | ✅ Working, deterministic | rules are data (`models_data/compliance_rules.json`), not if/else chains; same input always gives same output (tested) |
| Tampering detection | ⚠️ **Not ManTraNet** — see below | a working classical-CV heuristic, clearly labelled `engine="heuristic"` |
| Supabase persistence | ⚠️ **Column names verified against the real live schema; not exercised against the live project** | repository code was rewritten to match an `information_schema.columns` dump of the team's actual "Docai780" project (see "Database schema" below), and every payload key was checked against that real column list; repository logic is tested with a fake in-memory client (`tests/integration/test_supabase_repository.py`); the one test that touches a *real* Supabase project is skipped until you add real credentials — see that file |
| Local-disk fallback (no Supabase configured) | ✅ Working | the whole pipeline runs and returns a full response with zero Supabase configuration |
| Docker build | ⚠️ **Not built in this environment** (no Docker daemon available in the sandbox that produced this backend) | Dockerfile was written and reviewed against the verified `requirements.txt`; **build and run it yourself before the demo** — see "Verify the Docker build" below |
| Tests | ✅ 76 passed, 1 skipped (the live-Supabase test) | |

### Database schema: aligned to the REAL live project, not a fresh design

This backend originally shipped against a schema drafted from the spec PDF alone
(`products`, `scans`, `field_extractions`, `reference_comparisons`, `compliance_checks`).
The team then shared an `information_schema.columns` dump of their actual, already-live
Supabase project ("Docai780"), which turned out to have a different, simpler shape:
**8 real tables** - `product_reference`, `nutrition_ocr_raw`, `scan_records`, `ocr_results`,
`barcode_results`, `tampering_results`, `compliance_rules`, `compliance_results`. Every
repository, schema, and the compliance engine's output shape in this codebase were rewritten
to match that real schema exactly (verified programmatically - every payload key this code
writes was checked against the real column list; see the "SCHEMA MISMATCH" check the team
can rerun with `python -c "..."` scripts used during that realignment, or just trust the
passing test suite, which exercises the same repository functions).

Key structural differences from a from-scratch design, worth knowing before you touch this
code:
- **`scan_id` is the bigint `scan_records.id`**, not a UUID. Because of this, `scan_records`
  is written ONCE, only after the whole pipeline has already run in memory and has a full
  summary to write (detected_barcode, detected_product_name, ocr_confidence,
  tampering_score, status) - not upfront like a typical "create a row, then fill it in"
  flow. See the module docstring in `app/api/routes/scan.py`.
- There is **no separate table for extracted fields, reference comparisons, or per-rule
  check rows.** Extracted fields live in `ocr_results.structured_data` (jsonb); individual
  rule outcomes live in `compliance_results.rule_results` (jsonb list) instead of a child
  table.
- `compliance_rules` uses a generic **operator + expected_value** model (e.g.
  `operator="field_present"`, `operator="reference_field_match", expected_value="mrp"`)
  rather than the `condition_type`/`condition_value` shape from the original draft -
  `app/services/compliance_engine.py`'s module docstring documents the vocabulary.
- A few output semantics (`reference_match`, the `risk_level` scale) aren't fully specified
  by the column list alone - `compliance_engine.py`'s docstring documents the exact
  assumption made for each, so the team can correct them if they mean something different.

### Tampering detection: what is and isn't real

ManTraNet's own repo pins **Keras 2.2.0 + TensorFlow 1.8.0** and states other
versions are untested. Forcing that into the same process as modern
PaddleOCR (needs current numpy/opencv) is exactly the dependency conflict
the spec (5.3, 30.14) says to avoid.

So `app/models/tampering_model.py` implements `TAMPERING_SERVICE_MODE=heuristic`
(the default): a real, working classical-CV check —

1. rectangular/sticker-shaped overlay detection (Canny + polygon
   approximation + rectangularity), and
2. local noise-consistency analysis (a pasted patch usually has a different
   noise profile than the surrounding photo, measured only over textured,
   non-text tiles so it doesn't false-positive on dense print).

This is **evidence, not proof** — the API reports it as
`engine="heuristic"`, never as ManTraNet, with wording like *"possible
manipulation detected — review required"*, never a legal claim.

Two other modes are wired and ready if the team wants real ManTraNet later:
- `TAMPERING_SERVICE_MODE=mantranet_remote` + `TAMPERING_REMOTE_URL=...` — calls
  out to a **separate** microservice/container running the legacy stack
  (not included here — it needs its own legacy Python env; see the commented
  `tampering:` service in `docker-compose.yml`).
- `TAMPERING_SERVICE_MODE=disabled` — reports `status="unavailable"` cleanly.

The heuristic's thresholds are **not calibrated against a large real-photo
dataset** — treat scores as a starting point and tune
`heuristic_tampering_score()` against your own tampered/genuine pairs.

### Reference product data — what's real vs. placeholder

Per spec section 13/28, "never invent" reference values. Only
**Parle-G** (`mrp=30.00`, `net_quantity="250 g"`,
`barcode=8901719123870`) has real values — read from an actual packet the
team scanned during development. The other four demo products (Monaco,
Bourbon, Britannia Bourbon, Britannia Good Day) are seeded with
`source_note="PLACEHOLDER..."` and null values. **Fill these from your own
reference photos before the demo** — edit
`models_data/reference_products.seed.json` or `migrations/004_seed_demo_products.sql`.

## Quick start (local, no Supabase, no Docker)

```bash
cd backend
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
# ZBar's system library is needed by pyzbar (not a pip package):
#   Ubuntu/Debian: sudo apt-get install libzbar0
#   macOS:         brew install zbar
#   Windows:       usually works out of the box with the pyzbar wheel
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive OpenAPI docs.

First call to `/api/v1/scans` will be slow (PaddleOCR downloads model
weights, ~100MB, needs internet **once**; cached after that under
`~/.paddlex` or wherever `PADDLE_PDX_CACHE_HOME` points).

## Run the tests

```bash
pytest                                  # 76 passed, 1 skipped (live Supabase)
ruff check .                            # lint
python scripts/smoke_test.py --inprocess              # no server needed
python scripts/smoke_test.py --base-url http://localhost:8000   # against a running server
```

## Two-laptop development (frontend on a different machine)

**Backend laptop:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Find its LAN IP (`ipconfig` / `ifconfig`), e.g. `192.168.1.20`. Open an
inbound firewall rule for TCP port 8000 on the private network profile if
Windows blocks it.

Set `.env`:
```
CORS_ALLOWED_ORIGINS=http://192.168.1.15:5173
```
(the **frontend laptop's** origin — CORS is never `*` here, per spec section 22).

**Frontend laptop**, in the frontend's own `.env`:
```
VITE_API_BASE_URL=http://192.168.1.20:8000/api/v1
```
Test with `GET http://192.168.1.20:8000/api/v1/health` before wiring up the
upload form.

Frontend and backend do **not** need to share a folder while developing —
see section 23 of the spec for combining them into one repo later.

## Supabase setup

1. Create a Supabase project.
2. Run the SQL in `migrations/` **in numeric order** (SQL editor or `psql`) —
   see `migrations/README.md`.
3. Fill `.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_ANON_KEY=...
   SUPABASE_SERVICE_ROLE_KEY=...   # server-side only — never in the frontend
   ```
4. `python scripts/seed_demo_products.py` to load the demo catalogue into
   `product_reference` (edit the placeholder rows first with your real
   reference photo values). `migrations/005_seed_compliance_rules.sql`
   loads the rule set the same way if you'd rather manage rules in the DB
   than in `models_data/compliance_rules.json`.
5. Re-run `pytest` — the previously-skipped live Supabase test
   (`test_live_supabase_roundtrip`) will now run and must pass.

Without Supabase configured, the backend still runs end-to-end: images go
to `local_storage/`, reference products come from the local JSON seed, and
scan history returns empty (persistence is best-effort everywhere — see
`app/db/repositories/*.py`).

## API

Interactive docs at `/docs` (Swagger) and `/redoc`. Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health`, `/health/models`, `/health/storage`, `/health/database` | health checks |
| POST | `/api/v1/scans?mode=consumer\|inspector` | run the full pipeline on an uploaded image |
| GET | `/api/v1/scans/{scan_id}` | fetch one persisted scan |
| GET | `/api/v1/scans` | recent scan history |
| GET | `/api/v1/products/{reference_product_id}`, `/api/v1/products/search?q=` | reference product lookup |
| GET | `/api/v1/auth/status` | whether auth is currently enforced (it isn't, by default) |

Response shape follows spec section 16 exactly (`scan_id`, `product`, `ocr`,
`barcode`, `tampering`, `extracted_fields`, `reference_comparison`,
`compliance`, `warnings`). `python scripts/export_openapi.py` writes the
full schema to `openapi.json` for the frontend team to generate a typed
client from.

## Architecture notes

- **Never crashes on a partial failure.** Barcode, tampering, product
  matching and reference comparison are each wrapped (`_safe()` in
  `app/api/routes/scan.py`) so one failing stage degrades that one field in
  the response instead of turning the whole request into a 500 (spec
  section 15). OCR failing does **not** get mis-reported as "the product is
  unlabeled" — see `compliance_engine.py`'s `ocr_succeeded` handling and its
  regression tests.
- **Rules are data, not code.** `models_data/compliance_rules.json` mirrors
  the `compliance_rules` table; `compliance_engine.py` only *evaluates*
  entries, it never hard-codes a specific product's logic.
- **Raw values are never overwritten.** Every `ExtractedFieldValue` keeps
  `.raw` (what OCR actually said) separate from `.value` (the normalized,
  typed value) — see `app/services/normalizer.py`.
- **No secrets in the frontend.** `SUPABASE_SERVICE_ROLE_KEY` never leaves
  this backend; the frontend only ever talks to this API.

## Verify the Docker build

Not built in the sandbox that produced this code (no Docker daemon
available there). Before the demo:

```bash
cd backend
docker compose build
docker compose up
curl http://localhost:8000/api/v1/health
```

If the build fails, it's most likely the PaddleOCR/PaddlePaddle install
step (it's a large wheel) — check the container's network access and
Docker's available disk/RAM first.

## Known limitations (be upfront about these with judges)

- This implements a **partial, practically-useful subset** of Legal
  Metrology (Packaged Commodities) Rules, 2011 — not full legal coverage.
  Which checks are implemented is explicit in
  `models_data/compliance_rules.json` (`category` field).
- OCR accuracy depends heavily on photo quality — low-resolution or
  glare-heavy photos degrade extraction. The pipeline includes an
  automatic zoomed-crop retry for small printed dates, but very low-res
  source photos (below roughly 300px on the long side) are still hard.
- The tampering heuristic is unvalidated at scale — treat its score as a
  hint for manual review, not a verdict.
- Reference catalogue currently has one real product (Parle-G) and four
  placeholders — fill them in before presenting "reference comparison" as
  a feature that works for those products.

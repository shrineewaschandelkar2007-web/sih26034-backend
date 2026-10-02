"""
Persistence tests against the REAL confirmed schema (see migrations/001_initial_schema.sql
and its README for how that schema was confirmed).

Most tests here use an in-memory fake Supabase client: they verify OUR repository code
(payload shapes, error handling, graceful degradation), not Supabase itself. The single
live test at the bottom talks to a real Supabase project and is SKIPPED unless
SUPABASE_URL and a key are set - so a green run without credentials does NOT prove real
Supabase persistence works. Run it against your project before the demo.
"""

import os

import pytest

from app.core.errors import DatabaseError
from app.db.repositories import products as products_repo
from app.db.repositories import results as results_repo
from app.db.repositories import scans as scans_repo


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self.store, self.table = store, table
        self._filters, self._single, self._limit = [], False, None
        self._pending_insert, self._pending_update = None, None

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def select(self, *_):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        rows = self.store.setdefault(self.table, [])

        if self._pending_insert is not None:
            payload = self._pending_insert if isinstance(self._pending_insert, list) else [self._pending_insert]
            inserted = []
            for p in payload:
                row = {"id": len(rows) + 1, **p}
                rows.append(row)
                inserted.append(row)
            return _Result(inserted)

        if self._pending_update is not None:
            matched = [r for r in rows if all(r.get(c) == v for c, v in self._filters)]
            for r in matched:
                r.update(self._pending_update)
            return _Result(matched)

        out = [r for r in rows if all(r.get(c) == v for c, v in self._filters)]
        if self._limit:
            out = out[: self._limit]
        if self._single:
            if not out:
                raise LookupError("no rows")
            return _Result(out[0])
        return _Result(out)


class FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Query(self.store, name)


@pytest.fixture
def fake(monkeypatch):
    client = FakeSupabase()
    for module in (products_repo, results_repo, scans_repo):
        monkeypatch.setattr(module, "get_client", lambda c=client: c)
    return client


def test_create_scan_record_returns_generated_bigint_id(fake):
    scan_id = scans_repo.create_scan_record(
        image_path="scan-images/abc/label.jpg",
        image_url=None,
        detected_barcode="8901719123870",
        detected_product_name="Parle-G",
        detected_brand="Parle",
        reference_product_id="demo-parle-g-003",
        ocr_confidence=0.95,
        tampering_score=0.05,
        status="PASS",
    )
    assert isinstance(scan_id, int)
    row = scans_repo.get_scan(scan_id)
    assert row["detected_product_name"] == "Parle-G"
    assert row["status"] == "PASS"
    assert scans_repo.get_scan(999999) is None


def test_list_recent_scans(fake):
    for i in range(3):
        scans_repo.create_scan_record(
            image_path=None,
            image_url=None,
            detected_barcode=None,
            detected_product_name=f"p{i}",
            detected_brand=None,
            reference_product_id=None,
            ocr_confidence=None,
            tampering_score=None,
            status="PASS",
        )
    assert len(scans_repo.list_recent_scans(limit=10)) == 3


def test_detail_results_are_saved_against_the_right_scan_id(fake):
    scan_id = scans_repo.create_scan_record(
        image_path=None,
        image_url=None,
        detected_barcode=None,
        detected_product_name=None,
        detected_brand=None,
        reference_product_id=None,
        ocr_confidence=None,
        tampering_score=None,
        status="PASS",
    )
    results_repo.save_ocr_result(scan_id, raw_text="MRP 30", confidence=0.9, structured_data={"mrp": {"value": 30}})
    results_repo.save_barcode_result(scan_id, barcode="8901719123870", detected=True, confidence=1.0)
    results_repo.save_tampering_result(scan_id, tampering_score=0.05, status="success", heatmap_path=None)
    results_repo.save_compliance_result(
        scan_id,
        {
            "overall_status": "PASS",
            "risk_level": "NONE",
            "reference_match": True,
            "matched_fields": {},
            "mismatched_fields": {},
            "missing_fields": [],
            "rule_results": [{"rule_id": "LM-001", "status": "PASS"}],
            "explanation": "ok",
            "engine_version": "1.0.0",
            "rules_version": "1",
            "processing_time_ms": 3,
        },
    )
    for table in ("ocr_results", "barcode_results", "tampering_results", "compliance_results"):
        assert fake.store[table][0]["scan_id"] == scan_id

    assert fake.store["ocr_results"][0]["structured_data"] == {"mrp": {"value": 30}}
    assert fake.store["barcode_results"][0]["detected"] is True
    assert fake.store["compliance_results"][0]["rule_results"] == [{"rule_id": "LM-001", "status": "PASS"}]
    assert "warnings" not in fake.store["compliance_results"][0]  # not a real column - must never be sent


def test_fetch_reference_products_maps_real_column_names(fake):
    fake.store["product_reference"] = [
        {
            "reference_product_id": "p1",
            "brand": "Parle",
            "product_name": "Parle-G",
            "barcode": "8901719123870",
            "mrp": 30.0,
            "net_weight": "250 g",
        }
    ]
    products = products_repo.fetch_all_reference_products()
    assert products[0].product_name == "Parle-G"
    assert products[0].net_weight == "250 g"
    fetched = products_repo.fetch_product_by_reference_id("p1")
    assert fetched.barcode == "8901719123870"
    assert products_repo.fetch_product_by_reference_id("nope") is None


def test_insert_reference_product_inserts_when_missing_then_updates_when_present(fake):
    products_repo.insert_reference_product({"reference_product_id": "p2", "brand": "Britannia", "product_name": "Bourbon"})
    assert len(fake.store["product_reference"]) == 1

    products_repo.insert_reference_product({"reference_product_id": "p2", "brand": "Britannia", "product_name": "Bourbon", "mrp": 25.0})
    assert len(fake.store["product_reference"]) == 1  # updated in place, not duplicated
    assert fake.store["product_reference"][0]["mrp"] == 25.0


def test_persistence_is_skipped_quietly_when_supabase_unconfigured(monkeypatch):
    for module in (products_repo, results_repo, scans_repo):
        monkeypatch.setattr(module, "get_client", lambda: None)
    assert (
        scans_repo.create_scan_record(
            image_path=None,
            image_url=None,
            detected_barcode=None,
            detected_product_name=None,
            detected_brand=None,
            reference_product_id=None,
            ocr_confidence=None,
            tampering_score=None,
            status="PASS",
        )
        is None
    )
    results_repo.save_ocr_result(1, raw_text="x", confidence=None, structured_data={})  # no raise
    assert scans_repo.list_recent_scans() == []
    with pytest.raises(DatabaseError):
        products_repo.fetch_all_reference_products()


@pytest.mark.skipif(
    not (os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"))),
    reason="Live Supabase credentials not configured - this is the only test that touches a real project.",
)
def test_live_supabase_roundtrip():
    from app.db.supabase_client import get_client

    assert get_client() is not None
    scan_id = scans_repo.create_scan_record(
        image_path=None,
        image_url=None,
        detected_barcode=None,
        detected_product_name="pytest-live-check",
        detected_brand=None,
        reference_product_id=None,
        ocr_confidence=None,
        tampering_score=None,
        status="PASS",
    )
    assert scan_id is not None
    assert scans_repo.get_scan(scan_id) is not None

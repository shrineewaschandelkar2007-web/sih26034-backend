def test_health_returns_200_and_version(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_health_models_reports_component_statuses(client):
    r = client.get("/api/v1/health/models")
    assert r.status_code == 200
    components = r.json()["components"]
    # Whatever the environment, every optional component must be *reported*,
    # never silently omitted (spec section 26).
    for key in ("ocr", "barcode", "tampering"):
        assert components[key] != "unknown"


def test_health_storage_and_database_endpoints_exist(client):
    assert client.get("/api/v1/health/storage").status_code == 200
    assert client.get("/api/v1/health/database").status_code == 200


def test_openapi_docs_available(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/v1/scans" in paths
    assert "/api/v1/health" in paths


def test_cors_allows_configured_frontend_origin(client):
    r = client.options(
        "/api/v1/scans",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unknown_origin(client):
    r = client.options(
        "/api/v1/scans",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") != "http://evil.example.com"

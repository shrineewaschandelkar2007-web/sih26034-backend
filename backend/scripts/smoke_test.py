"""
Demo smoke test (spec section 27).

Uploads one known demo image to the scan endpoint and prints a one-line
verdict per component. Exits non-zero if the API itself is unhealthy.

    python scripts/smoke_test.py                                   # against http://localhost:8000
    python scripts/smoke_test.py --base-url http://192.168.1.20:8000   # backend on another laptop
    python scripts/smoke_test.py --image path/to/your_label.jpg
    python scripts/smoke_test.py --inprocess                       # no server needed (uses TestClient)

"OK" for a component means it returned a real result. "UNAVAILABLE" / "FAILED" is reported honestly rather than
hidden - e.g. OCR is UNAVAILABLE until PaddleOCR has downloaded its model weights (needs internet once).
"""

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = BACKEND_ROOT / "tests" / "fixtures" / "sample_label.png"


def _verdict(status: str) -> str:
    return {"success": "OK", "completed": "OK"}.get(status, status.upper())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE))
    parser.add_argument("--mode", default="inspector", choices=["consumer", "inspector"])
    parser.add_argument("--inprocess", action="store_true", help="run the app in-process instead of over HTTP")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        return 2
    image_bytes = image_path.read_bytes()

    if args.inprocess:
        sys.path.insert(0, str(BACKEND_ROOT))
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        base = ""
    else:
        import httpx

        client = httpx.Client(base_url=args.base_url, timeout=120)
        base = ""

    try:
        health = client.get(f"{base}/api/v1/health")
    except Exception as exc:  # noqa: BLE001
        print(f"API: FAILED - cannot reach {args.base_url} ({exc!r})")
        return 1
    if health.status_code != 200:
        print(f"API: FAILED - /health returned {health.status_code}")
        return 1

    resp = client.post(
        f"{base}/api/v1/scans?mode={args.mode}",
        files={"file": (image_path.name, image_bytes, "image/png" if image_path.suffix == ".png" else "image/jpeg")},
    )
    if resp.status_code != 200:
        print(f"API: FAILED - /scans returned {resp.status_code}: {resp.text[:300]}")
        return 1

    body = resp.json()
    ocr, barcode, tamper = body["ocr"], body["barcode"], body["tampering"]
    print(f"scan_id: {body['scan_id']}")
    print(f"OCR: {_verdict(ocr['status'])}" + (f" (avg confidence {ocr['average_confidence']})" if ocr.get("average_confidence") else ""))
    print(f"Barcode: {'OK (' + barcode['value'] + ')' if barcode['found'] else 'NOT_FOUND'}")
    print(f"Tampering: {_verdict(tamper['status'])} ({tamper.get('engine')}, score={tamper.get('tampering_score')})")
    product = body["product"]
    if product["reference_found"]:
        print(f"Reference: FOUND ({product['name']} via {product['match_method']})")
    else:
        print("Reference: NOT_FOUND")
    compliance = body["compliance"]
    print(f"Compliance: {compliance['overall_status']} (risk {compliance['risk_level']})")
    for warning in body["warnings"]:
        print(f"  warning: {warning}")
    print("API: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

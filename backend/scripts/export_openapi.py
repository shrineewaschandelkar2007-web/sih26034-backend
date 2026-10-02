"""Write the OpenAPI schema to openapi.json so the frontend team can generate a typed client from it."""

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402

out = BACKEND_ROOT / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"Wrote {out} ({len(app.openapi()['paths'])} paths)")

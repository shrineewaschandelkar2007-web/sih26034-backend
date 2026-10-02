from pathlib import Path

from dotenv import load_dotenv
import pytest
from fastapi.testclient import TestClient


# Load backend .env before pytest imports/collects the application.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env", override=True)


from app.main import app


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def sample_label_bytes() -> bytes:
    return (FIXTURES / "sample_label.png").read_bytes()


@pytest.fixture(scope="session")
def unlabeled_bytes() -> bytes:
    return (FIXTURES / "unlabeled_product.png").read_bytes()


@pytest.fixture(scope="session")
def tampered_bytes() -> bytes:
    return (FIXTURES / "tampered_label.png").read_bytes()

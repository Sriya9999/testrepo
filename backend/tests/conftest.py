import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="marketingos-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "10000"
os.environ["AI_PROVIDER"] = "offline"
os.environ["PAYMENTS_MODE"] = "test"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_test"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("PERPLEXITY_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services import jobs, ratelimit  # noqa: E402
from app.services.email import OUTBOX  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    yield
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            conn.execute(text(f"TRUNCATE {names} CASCADE"))
        else:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
            conn.execute(text("PRAGMA foreign_keys=ON"))
    with SessionLocal() as db:
        seed(db)
    OUTBOX.clear()
    ratelimit.reset()


class Api:
    """A signed-in user acting in one workspace."""

    def __init__(self, client: TestClient, session: dict, workspace_id: str | None = None):
        self.client = client
        self.session = session
        self.token = session["access_token"]
        self.user = session["user"]
        self.workspace_id = workspace_id or session["user"]["workspaces"][0]["id"]

    def headers(self, workspace_id: str | None = None) -> dict:
        return {"Authorization": f"Bearer {self.token}", "X-Workspace-Id": workspace_id or self.workspace_id}

    def in_workspace(self, workspace_id: str) -> "Api":
        return Api(self.client, self.session, workspace_id)

    def get(self, path, **kw):
        return self.client.get(f"/api/v1{path}", headers=self.headers(), **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(f"/api/v1{path}", json=json if json is not None else {}, headers=self.headers(), **kw)

    def patch(self, path, json=None, **kw):
        return self.client.patch(f"/api/v1{path}", json=json or {}, headers=self.headers(), **kw)

    def delete(self, path, **kw):
        return self.client.delete(f"/api/v1{path}", headers=self.headers(), **kw)

    def upload(self, data: bytes = PNG, mime: str = "image/png", name: str = "image.png") -> dict:
        r = self.client.post("/api/v1/media", files={"file": (name, data, mime)}, headers=self.headers())
        assert r.status_code == 201, r.text
        return r.json()


def register(client: TestClient, email: str, account_type: str = "business", org: str = "Spice Garden") -> Api:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "Str0ngPassword!", "full_name": email.split("@")[0],
                                                    "account_type": account_type, "organization_name": org})
    assert r.status_code == 201, r.text
    return Api(client, r.json())


def login(client: TestClient, email: str) -> Api:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ngPassword!"})
    assert r.status_code == 200, r.text
    return Api(client, r.json())


def run_jobs() -> int:
    return jobs.run_pending(max_jobs=200, include_delayed=True)


def grant(workspace_id: str, amount: int) -> None:
    import uuid

    from app.services import credits

    with SessionLocal() as db:
        credits.grant(db, uuid.UUID(workspace_id), amount, description="test grant")
        db.commit()


@pytest.fixture
def owner(client) -> Api:
    api = register(client, "owner@spicegarden.in")
    r = api.post("/brands", {
        "name": "Spice Garden", "industry": "restaurant", "description": "Family restaurant serving coastal food.",
        "website_url": "https://spicegarden.example", "colors": ["#7C2D12", "#F59E0B"], "target_customers": "families in Pune",
        "products": [{"name": "weekend thali", "description": "Unlimited coastal thali"}], "voice": "warm, friendly",
        "prohibited_claims": ["best in the world"], "approved_ctas": ["Book a table"], "locations": ["Pune"],
        "competitor_references": ["Coastal Kitchen"],
    })
    assert r.status_code == 201, r.text
    return api

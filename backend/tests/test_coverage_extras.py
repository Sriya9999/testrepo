import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.db import SessionLocal
from app.engines import seo_crawler
from app.models import AdInsight, Campaign, Report, SocialPost
from tests.conftest import login, register, run_jobs
from tests.test_search import site_transport


def test_auth_endpoints_are_rate_limited(client, monkeypatch):
    register(client, "rl@biz.in")
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "rl@biz.in", "password": "wrong-Passw0rd"}).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_rescheduling_an_approved_post_keeps_its_approval(owner):
    acct = owner.post("/integrations/instagram/connect", {"mode": "sandbox"}).json()["accounts"][0]
    media = owner.upload()
    post = owner.post("/social/posts", {"connected_account_id": acct["id"], "caption": "Diwali thali", "media_asset_ids": [media["id"]]}).json()
    first = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    a = owner.post(f"/social/posts/{post['id']}/schedule", {"scheduled_at": first}).json()["approval_id"]
    owner.post(f"/approvals/{a}/approve", {})
    later = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
    out = owner.patch(f"/social/posts/{post['id']}", {"scheduled_at": later.isoformat()}).json()
    assert out["status"] == "scheduled" and out["approval_id"] == a
    assert datetime.fromisoformat(out["scheduled_at"]) == later
    assert owner.patch(f"/social/posts/{post['id']}", {"scheduled_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}).status_code == 400
    assert "social.rescheduled" in [e["action"] for e in owner.get("/audit-logs").json()]


def test_competitor_audit_is_compared_with_own_site(owner, monkeypatch):
    real = seo_crawler.crawl
    monkeypatch.setattr(seo_crawler, "crawl", lambda domain, max_pages, *a, **k: real(
        domain, max_pages, client=httpx.Client(transport=httpx.MockTransport(site_transport))))
    site = owner.post("/seo/websites", {"domain": "spice.example", "competitors": ["rival.example"]}).json()
    owner.post("/seo/audits", {"website_id": site["id"], "include_pagespeed": False})
    comp_id = site["competitors"][0]["id"]
    r = owner.post("/seo/audits", {"website_id": site["id"], "include_pagespeed": False, "competitor_id": comp_id}).json()
    run_jobs()
    assert owner.get(f"/seo/audits/{r['audit_id']}").json()["config"]["domain"] == "rival.example"
    out = owner.get(f"/seo/competitors?website_id={site['id']}").json()
    assert out["own"]["score"] is not None
    assert out["competitors"][0]["latest_audit"]["score"] is not None
    # A competitor audit must not overwrite the site's own score.
    assert owner.get("/seo/websites").json()[0]["latest_score"] == out["own"]["score"]


def test_agency_client_comparison_flags_underperformers(client):
    agency = register(client, "cmp@agency.in", "agency", "Compare Agency")
    good = agency.post("/agency/clients", {"name": "Steady Cafe"}).json()
    bad = agency.post("/agency/clients", {"name": "Falling Gym"}).json()
    today = datetime.now(UTC).date()
    with SessionLocal() as db:
        for c, recent_leads in ((good, 10), (bad, 2)):
            ws = uuid.UUID(c["workspace_id"])
            camp = Campaign(workspace_id=ws, platform="meta", name="Leads", objective="leads", status="active")
            db.add(camp)
            db.flush()
            for d in range(60):
                db.add(AdInsight(workspace_id=ws, campaign_id=camp.id, platform="meta", date=today - timedelta(days=d), entity_level="campaign",
                                 impressions=1000, clicks=50, spend_minor=100_000, leads=recent_leads if d < 30 else 10, source="demo"))
        db.commit()
    rows = {r["name"]: r for r in agency.get("/analytics/clients").json()}
    assert rows["Falling Gym"]["underperforming"] and "CPA up more than 20%" in rows["Falling Gym"]["flags"]
    assert not rows["Steady Cafe"]["underperforming"]
    # Account managers only see the clients assigned to them.
    register(client, "am2@agency.in", org="x")
    agency.post(f"/workspaces/{agency.workspace_id}/members", {"email": "am2@agency.in", "role": "account_manager"})
    agency.patch(f"/agency/clients/{good['id']}", {"account_manager_id": login(client, "am2@agency.in").user["id"]})
    am = login(client, "am2@agency.in").in_workspace(agency.workspace_id)
    assert [r["name"] for r in am.get("/analytics/clients").json()] == ["Steady Cafe"]


def pdf_text(pdf: bytes) -> bytes:
    """Decode ReportLab's ASCII85+Flate page streams so the drawn text can be searched."""
    import base64
    import re
    import zlib

    out = b""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            out += zlib.decompress(base64.a85decode(raw.strip(), adobe=True))
        except ValueError:
            try:
                out += zlib.decompress(raw)
            except zlib.error:
                continue
    return out


def test_white_label_pdf_and_scheduled_reports(client):
    agency = register(client, "wl@agency.in", "agency", "Brightside Agency")
    assert agency.patch(f"/workspaces/{agency.workspace_id}/white-label", {"agency_name": "Brightside", "primary_color": "#2F5D9E"}).status_code == 200
    r = agency.post("/analytics/reports", {"name": "Weekly", "format": "pdf", "white_label": True, "schedule": "weekly"}).json()
    run_jobs()
    pdf = agency.get(f"/analytics/reports/{r['id']}/download").content
    assert pdf.startswith(b"%PDF") and b"prepared by Brightside" in pdf_text(pdf)
    with SessionLocal() as db:
        db.get(Report, uuid.UUID(r["id"])).next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        from app.api.analytics import enqueue_scheduled_reports

        assert enqueue_scheduled_reports(db) == 1
    assert run_jobs() == 1


def test_agent_run_websocket_streams_logs(client, owner):
    run = owner.post("/agents/run", {"instruction": "Create 1 Instagram post"}).json()
    run_jobs()
    url = f"/api/v1/ws/agents/runs/{run['id']}?token={owner.token}&workspace_id={owner.workspace_id}"
    with client.websocket_connect(url) as ws:
        msg = ws.receive_json()
    assert msg["status"] in ("completed", "awaiting_approval") and any("Drafted" in entry["message"] for entry in msg["logs"])
    other = register(client, "intruder@else.in", org="Else")
    bad = f"/api/v1/ws/agents/runs/{run['id']}?token={other.token}&workspace_id={owner.workspace_id}"
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(bad) as ws:
            ws.receive_json()
    assert closed.value.code == 4403
    with SessionLocal() as db:
        assert db.query(SocialPost).count() == 1

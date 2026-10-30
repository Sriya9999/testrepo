import uuid
from datetime import date, timedelta

import httpx
import respx

from app.db import SessionLocal
from app.engines import ads_optimizer
from app.models import AdAccount, AdInsight, Campaign, ConnectedAccount
from app.services import integrations
from tests.conftest import run_jobs


def _meta_account(api):
    api.post("/integrations/meta/connect", {"mode": "sandbox"})
    return api.get("/ads/meta/accounts").json()[0]


def _valid_meta_draft(api, acct, **overrides):
    media = api.upload()
    body = {
        "ad_account_id": acct["id"], "name": "Weekend thali", "objective": "traffic", "daily_budget_minor": 100_000,
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
        "config": {"copy": {"primary_text": "Unlimited coastal thali", "headline": "Book a table", "link_url": "https://spicegarden.example",
                            "cta_type": "LEARN_MORE"},
                   "media_asset_ids": [media["id"]], "page_id": acct["pages"][0]["id"]},
        **overrides,
    }
    r = api.post("/ads/meta/campaigns/drafts", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_draft_validation(owner):
    acct = _meta_account(owner)
    c = owner.post("/ads/meta/campaigns/drafts", {"ad_account_id": acct["id"], "name": "Empty"}).json()
    errors = " ".join(c["validation_errors"])
    assert "budget" in errors and "headline" in errors and "image" in errors
    r = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {"activate": True})
    assert r.status_code == 400 and r.json()["error"]["code"] == "campaign_invalid"


def test_spend_limit_enforced(owner):
    acct = _meta_account(owner)
    c = _valid_meta_draft(owner, acct, daily_budget_minor=5_000_000)
    assert any("limit" in e for e in c["validation_errors"])
    owner.patch(f"/workspaces/{owner.workspace_id}", {"settings": {"spend_limits": {"meta_max_daily_budget_minor": 10_000_000}}})
    assert owner.get(f"/ads/meta/campaigns/{c['id']}").json()["validation_errors"] == []


def test_launch_only_after_approval(owner):
    acct = _meta_account(owner)
    c = _valid_meta_draft(owner, acct)
    # Submitting without approval is refused.
    assert owner.post(f"/ads/meta/campaigns/{c['id']}/submit").status_code == 409
    a = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {"activate": True}).json()
    approval = owner.get(f"/approvals/{a['approval_id']}").json()
    assert approval["budget_impact_minor"] == 100_000 * 30 and approval["preview"]["activate"] is True
    run_jobs()
    assert owner.get(f"/ads/meta/campaigns/{c['id']}").json()["status"] == "pending_approval"
    owner.post(f"/approvals/{a['approval_id']}/approve", {})
    run_jobs()
    out = owner.get(f"/ads/meta/campaigns/{c['id']}").json()
    assert out["status"] == "active" and out["external_id"].startswith("sandbox_cmp_")
    assert owner.get(f"/approvals/{a['approval_id']}").json()["status"] == "executed"


def test_editing_after_request_supersedes_approval(owner):
    acct = _meta_account(owner)
    c = _valid_meta_draft(owner, acct)
    a = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {}).json()["approval_id"]
    owner.patch(f"/ads/meta/campaigns/{c['id']}", {"daily_budget_minor": 150_000})
    assert owner.get(f"/approvals/{a}").json()["status"] == "superseded"
    assert owner.post(f"/approvals/{a}/approve", {}).status_code == 409


def _live_campaign(api) -> dict:
    acct = _meta_account(api)
    c = _valid_meta_draft(api, acct)
    a = api.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {"activate": True}).json()["approval_id"]
    api.post(f"/approvals/{a}/approve", {})
    run_jobs()
    return api.get(f"/ads/meta/campaigns/{c['id']}").json()


def test_live_budget_increase_needs_approval_decrease_does_not(owner):
    c = _live_campaign(owner)
    up = owner.patch(f"/ads/meta/campaigns/{c['id']}", {"daily_budget_minor": 200_000}).json()
    assert up["requires_approval"] and up["campaign"]["daily_budget_minor"] == 100_000
    approval = owner.get(f"/approvals/{up['approval_id']}").json()
    assert approval["action_type"] == "increase_budget" and approval["budget_impact_minor"] == 100_000 * 30
    owner.post(f"/approvals/{up['approval_id']}/approve", {})
    run_jobs()
    assert owner.get(f"/ads/meta/campaigns/{c['id']}").json()["daily_budget_minor"] == 200_000

    down = owner.patch(f"/ads/meta/campaigns/{c['id']}", {"daily_budget_minor": 50_000}).json()
    assert down["applied"] is True
    run_jobs()
    assert owner.get(f"/ads/meta/campaigns/{c['id']}").json()["daily_budget_minor"] == 50_000

    bad = owner.patch(f"/ads/meta/campaigns/{c['id']}", {"config": {"copy": {"primary_text": "new copy", "headline": "h",
                                                                               "link_url": "https://x.example", "cta_type": "LEARN_MORE"}}})
    assert bad.status_code == 400


def test_pause_policy_is_configurable(owner):
    c = _live_campaign(owner)
    r = owner.post(f"/ads/meta/campaigns/{c['id']}/pause").json()
    assert r["requires_approval"] is False
    run_jobs()
    assert owner.get(f"/ads/meta/campaigns/{c['id']}").json()["status"] == "paused"
    # Re-activating always needs approval.
    act = owner.post(f"/ads/meta/campaigns/{c['id']}/activate").json()
    assert act["requires_approval"] is True
    owner.post(f"/approvals/{act['approval_id']}/approve", {})
    run_jobs()
    owner.patch(f"/workspaces/{owner.workspace_id}", {"settings": {"approvals": {"require_approval_for_pause": True}}})
    assert owner.post(f"/ads/meta/campaigns/{c['id']}/pause").json()["requires_approval"] is True


def test_viewer_and_creator_cannot_approve_spend(client, owner):
    from tests.conftest import register

    owner.post(f"/workspaces/{owner.workspace_id}/members", {"email": "creator@biz.in", "role": "content_creator"})
    creator = register(client, "creator@biz.in", org="Creator").in_workspace(owner.workspace_id)
    acct = _meta_account(owner)
    c = _valid_meta_draft(owner, acct)
    a = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {}).json()["approval_id"]
    assert creator.post(f"/approvals/{a}/approve", {}).status_code == 403
    assert creator.get("/approvals").json()[0]["can_decide"] is False


def test_self_approval_can_be_disabled(owner):
    owner.patch(f"/workspaces/{owner.workspace_id}", {"settings": {"approvals": {"allow_self_approval": False}}})
    acct = _meta_account(owner)
    c = _valid_meta_draft(owner, acct)
    a = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {}).json()["approval_id"]
    assert owner.post(f"/approvals/{a}/approve", {}).status_code == 403


def test_ai_generated_google_campaign(owner):
    owner.post("/integrations/google_ads/connect", {"mode": "sandbox"})
    r = owner.post("/ads/google/campaigns/generate", {"objective": "traffic", "daily_budget_minor": 80_000, "location": "Pune",
                                                      "keywords": ["thali restaurant", "coastal food"], "website": "https://spicegarden.example"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["created_by_ai"] and c["config"]["ad_groups"]
    for g in c["config"]["ad_groups"]:
        assert all(len(h) <= 30 for h in g["headlines"]) and 3 <= len(g["headlines"]) <= 15
        assert all(len(d) <= 90 for d in g["descriptions"])
    assert "free" in c["config"]["negative_keywords"]
    assert c["validation_errors"] == []
    assert owner.get("/billing/credits").json()["balance"] == 95


def test_meta_live_submission_calls_graph_api(owner):
    with SessionLocal() as db:
        conn = ConnectedAccount(workspace_id=uuid.UUID(owner.workspace_id), provider="meta", external_id="u1", display_name="Meta",
                                mode="live", details={})
        db.add(conn)
        db.flush()
        integrations.store_token(db, conn, "EAAads", None, 5_000_000)
        db.add(AdAccount(workspace_id=conn.workspace_id, connected_account_id=conn.id, platform="meta", external_id="123",
                         name="Spice Ads", details={"pages": [{"id": "P1", "name": "Spice Page"}]}))
        db.commit()
    acct = owner.get("/ads/meta/accounts").json()[0]
    c = _valid_meta_draft(owner, acct)
    a = owner.post(f"/ads/meta/campaigns/{c['id']}/request-approval", {"activate": False}).json()["approval_id"]
    base = "https://graph.facebook.com/v21.0"
    with respx.mock(assert_all_called=True) as mock:
        mock.post(f"{base}/act_123/adimages").mock(return_value=httpx.Response(200, json={"images": {"image.png": {"hash": "H1"}}}))
        camp = mock.post(f"{base}/act_123/campaigns").mock(return_value=httpx.Response(200, json={"id": "C9"}))
        adset = mock.post(f"{base}/act_123/adsets").mock(return_value=httpx.Response(200, json={"id": "S9"}))
        mock.post(f"{base}/act_123/adcreatives").mock(return_value=httpx.Response(200, json={"id": "CR9"}))
        mock.post(f"{base}/act_123/ads").mock(return_value=httpx.Response(200, json={"id": "A9"}))
        owner.post(f"/approvals/{a}/approve", {})
        run_jobs()
        sent = dict(httpx.QueryParams(camp.calls[0].request.content.decode()))
        assert sent["objective"] == "OUTCOME_TRAFFIC" and sent["status"] == "PAUSED" and sent["daily_budget"] == "100000"
        targeting = dict(httpx.QueryParams(adset.calls[0].request.content.decode()))["targeting"]
        assert '"countries": ["IN"]' in targeting
    out = owner.get(f"/ads/meta/campaigns/{c['id']}").json()
    assert out["status"] == "paused" and out["external_id"] == "C9"
    assert {e["level"] for e in out["entities"]} == {"ad_set", "creative", "ad"}


def test_optimizer_flags_use_measured_numbers():
    today = date.today()

    class C:
        def __init__(self, name):
            self.name = name

    rows = []
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for d in range(14):
        day = today - timedelta(days=d)
        rows.append(AdInsight(campaign_id=a, date=day, impressions=5000, clicks=150, spend_minor=300_000, leads=10, purchases=0,
                              conversions=0, revenue_minor=0, reach=2000))
        rows.append(AdInsight(campaign_id=b, date=day, impressions=5000, clicks=20, spend_minor=300_000, leads=0, purchases=0,
                              conversions=0, revenue_minor=0, reach=4000))
        rows.append(AdInsight(campaign_id=c, date=day, impressions=4000, clicks=120, spend_minor=150_000, leads=12, purchases=0,
                              conversions=0, revenue_minor=0, reach=3500))
    recs = ads_optimizer.analyze(rows, {a: C("A"), b: C("B"), c: C("C")}, "INR", today)
    types = {(r["campaign_name"], r["type"]) for r in recs}
    assert ("B", "budget_inefficiency") in types
    assert ("B", "poor_creative") in types
    first = next(r for r in recs if r["type"] == "budget_inefficiency")
    assert first["evidence"]["spend_minor"] == 14 * 300_000 and first["requires_approval"] is True


def test_recommendations_without_data_say_so(owner):
    out = owner.get("/ads/meta/recommendations").json()
    assert out["recommendations"] == [] and "No synced performance data" in out["note"]


def test_discovered_campaigns_from_sync_are_reporting_only(owner):
    with SessionLocal() as db:
        ws = uuid.UUID(owner.workspace_id)
        conn = ConnectedAccount(workspace_id=ws, provider="meta", external_id="u2", display_name="Meta", mode="live", details={})
        db.add(conn)
        db.flush()
        integrations.store_token(db, conn, "EAAads", None, 5_000_000)
        acct = AdAccount(workspace_id=ws, connected_account_id=conn.id, platform="meta", external_id="555", name="Old Ads")
        db.add(acct)
        db.commit()
        acct_id = acct.id
    base = "https://graph.facebook.com/v21.0"
    with respx.mock() as mock:
        mock.get(f"{base}/act_555/campaigns").mock(return_value=httpx.Response(200, json={"data": [
            {"id": "X1", "name": "Diwali promo", "objective": "OUTCOME_LEADS", "status": "ACTIVE", "effective_status": "ACTIVE"}]}))
        mock.get(f"{base}/act_555/insights").mock(return_value=httpx.Response(200, json={"data": [
            {"campaign_id": "X1", "date_start": date.today().isoformat(), "impressions": "1000", "reach": "800", "clicks": "50",
             "spend": "250.50", "actions": [{"action_type": "lead", "value": "4"}]}]}))
        with SessionLocal() as db:
            from app.services import jobs

            jobs.enqueue(db, "ads.sync", {"ad_account_id": acct_id, "days": 7}, workspace_id=ws)
            db.commit()
        run_jobs()
    with SessionLocal() as db:
        camp = db.query(Campaign).filter_by(external_id="X1").one()
        assert camp.status == "active" and camp.objective == "leads" and camp.config == {"discovered": True}
        row = db.query(AdInsight).filter_by(campaign_id=camp.id).one()
        assert row.spend_minor == 25050 and row.leads == 4 and row.source == "meta"

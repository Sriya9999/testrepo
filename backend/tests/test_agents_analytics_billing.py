import json
import uuid
from datetime import date, timedelta

from app.db import SessionLocal
from app.engines.orchestrator import parse_instruction
from app.models import AdInsight, Campaign, ContentAsset, PerformanceSnapshot, SocialPost
from app.security import hmac_sha256_hex
from tests.conftest import grant, run_jobs


def test_parse_prd_example_instruction():
    plan = parse_instruction("Create 15 Instagram posts, 4 Reels and a Meta Ads campaign for November.", today=date(2026, 10, 30))
    assert plan["posts"] == 15 and plan["reels"] == 4 and plan["meta_campaign"] is True and plan["google_campaign"] is False
    assert plan["start_date"] == "2026-11-01" and plan["duration_days"] == 30


def test_parse_vague_growth_instruction_and_budget():
    plan = parse_instruction("Grow my business over the next 30 days. Improve my Google visibility, get my brand mentioned in "
                             "AI search, generate Instagram content and run advertising campaigns with ₹1,000 per day.",
                             today=date(2026, 10, 30))
    assert plan["seo"] and plan["geo"] and plan["meta_campaign"] and plan["posts"] > 0
    assert plan["daily_budget_minor"] == 100_000 and plan["duration_days"] == 30


def test_plan_preview_is_free_and_lists_steps(owner):
    out = owner.post("/agents/plan", {"instruction": "Create 3 Instagram posts and a Meta Ads campaign"}).json()
    assert out["parsed"]["posts"] == 3
    agents = [s["agent"] for s in out["steps"]]
    assert "content" in agents and "meta_ads" in agents
    assert out["estimate"]["total"] > 0
    assert owner.get("/billing/credits").json()["balance"] == 100


def test_agent_run_drafts_everything_and_executes_only_after_approval(owner):
    grant(owner.workspace_id, 500)
    owner.post("/integrations/instagram/connect", {"mode": "sandbox"})
    owner.post("/integrations/meta/connect", {"mode": "sandbox"})
    run = owner.post("/agents/run", {"instruction": "Create 3 Instagram posts, 1 Reel and a Meta Ads campaign for next month"}).json()
    run_jobs()
    detail = owner.get(f"/agents/runs/{run['id']}").json()
    assert detail["status"] == "awaiting_approval", detail.get("error")
    agents = [t["agent"] for t in detail["tasks"]]
    assert agents[:2] == ["orchestrator", "strategy"] and "content" in agents and "creative" in agents and "social" in agents
    assert len(detail["output"]["content_ids"]) == 4 and len(detail["output"]["post_ids"]) == 4
    assert detail["credits_used"] > 0
    # 3 feed posts with visuals + 1 campaign wait for approval; the Reel has no video yet so stays a draft.
    kinds = sorted(a["action_type"] for a in detail["approvals"])
    assert kinds == ["launch_campaign", "schedule_post", "schedule_post", "schedule_post"]
    with SessionLocal() as db:
        assert db.query(SocialPost).filter(SocialPost.status.in_(["published", "scheduled"])).count() == 0
        assert db.query(Campaign).filter(Campaign.external_id.is_not(None)).count() == 0

    r = owner.post("/approvals/bulk-approve", {"ids": [a["id"] for a in detail["approvals"]]}).json()
    assert all(x["ok"] for x in r["results"])
    run_jobs()
    with SessionLocal() as db:
        assert db.query(SocialPost).filter_by(status="scheduled").count() == 3
        camp = db.query(Campaign).filter(Campaign.ai_run_id == uuid.UUID(run["id"])).one()
        assert camp.status == "active" and camp.external_id.startswith("sandbox_")
    assert owner.get(f"/agents/runs/{run['id']}").json()["status"] == "completed"
    logs = owner.get(f"/agents/runs/{run['id']}/logs").json()
    assert any("waiting for approval" in entry["message"] for entry in logs)


def test_agent_run_stops_cleanly_when_credits_run_out(owner):
    run = owner.post("/agents/run", {"instruction": "Create 30 Instagram posts"}).json()
    run_jobs()
    detail = owner.get(f"/agents/runs/{run['id']}").json()
    assert detail["status"] in ("completed", "awaiting_approval")
    assert owner.get("/billing/credits").json()["balance"] >= 0
    with SessionLocal() as db:
        assert db.query(ContentAsset).filter_by(generation_status="pending").count() == 0


def test_cancel_run_and_disable_agent(owner):
    owner.patch("/agents/meta_ads", {"enabled": False})
    agents = {a["id"]: a for a in owner.get("/agents").json()["agents"]}
    assert agents["meta_ads"]["status"] == "disabled"
    assert agents["social"]["actions"][0]["policy"] == "requires_approval"
    assert agents["content"]["actions"][0]["policy"] == "automatic"
    run = owner.post("/agents/run", {"instruction": "Create 2 Instagram posts"}).json()
    out = owner.post(f"/agents/runs/{run['id']}/cancel").json()
    assert out["status"] == "cancelled"
    run_jobs()
    assert owner.get(f"/agents/runs/{run['id']}").json()["tasks"] == []


def _seed_metrics(workspace_id: str):
    ws = uuid.UUID(workspace_id)
    today = date.today()
    with SessionLocal() as db:
        camp = Campaign(workspace_id=ws, platform="meta", name="Thali leads", objective="leads", status="active", external_id="X")
        db.add(camp)
        db.flush()
        for d in range(60):
            day = today - timedelta(days=d)
            recent = d < 30
            db.add(AdInsight(workspace_id=ws, campaign_id=camp.id, platform="meta", date=day, entity_level="campaign",
                             impressions=2000, clicks=80 if recent else 60, spend_minor=150_000, leads=5 if recent else 3,
                             source="demo"))
            db.add(PerformanceSnapshot(workspace_id=ws, channel="organic", date=day, clicks=120 if recent else 100,
                                       impressions=3000, source="demo"))
        db.commit()


def test_overview_kpis_with_provenance_and_comparison(owner):
    _seed_metrics(owner.workspace_id)
    ov = owner.get("/analytics/overview").json()
    k = ov["kpis"]
    assert k["spend"]["value"] == 30 * 150_000 and k["spend"]["kind"] == "measured"
    assert k["paid_traffic"]["value"] == 30 * 80 and k["paid_traffic"]["change_pct"] == round((80 - 60) / 60 * 100, 1)
    assert k["cpl"]["kind"] == "calculated" and k["cpl"]["value"] == round(30 * 150_000 / (30 * 5))
    assert k["organic_traffic"]["value"] == 30 * 120
    assert k["seo_score"]["kind"] == "internal" and k["seo_score"]["value"] is None
    assert ov["contains_demo_data"] is True and ov["summary"]
    dash = owner.get("/dashboard").json()
    assert dash["kpis"]["conversions"]["value"] == 150 and "credits" in dash


def test_reporting_assistant_distinguishes_data_kinds(owner):
    _seed_metrics(owner.workspace_id)
    out = owner.post("/analytics/ask", {"question": "Which campaigns generated the most leads?"}).json()
    assert "Thali leads" in out["answer"]
    kinds = {f["kind"] for f in out["facts"]}
    assert {"measured", "calculated"} <= kinds and set(out["legend"]) == {"measured", "calculated", "internal", "recommendation"}
    assert owner.get("/billing/credits").json()["balance"] == 98


def test_reports_pdf_and_csv(owner):
    _seed_metrics(owner.workspace_id)
    for fmt in ("pdf", "csv"):
        r = owner.post("/analytics/reports", {"name": f"October {fmt}", "format": fmt, "recipients": ["boss@spice.in"]}).json()
        run_jobs()
        meta = owner.get(f"/analytics/reports/{r['id']}").json()
        assert meta["status"] == "ready", meta
        file = owner.get(f"/analytics/reports/{r['id']}/download")
        assert file.status_code == 200
        if fmt == "pdf":
            assert file.content.startswith(b"%PDF")
        else:
            assert b"Ad spend" in file.content
    assert owner.get("/analytics/export.csv").status_code == 200


def test_billing_plans_purchase_and_usage(owner):
    plans = {p["code"]: p for p in owner.get("/billing/plans").json()}
    assert plans["starter"]["price_minor"] == 149_900 and plans["enterprise"]["price_minor"] is None
    r = owner.post("/billing/credits/purchase", {"pack": "starter_pack"}).json()
    assert r["status"] == "paid" and r["balance"] == 600
    sub = owner.post("/billing/subscribe", {"plan_code": "growth"}).json()
    assert sub["status"] == "active"
    usage = owner.get("/billing/usage").json()
    assert usage["subscription"]["plan"]["code"] == "growth" and usage["credits"]["balance"] == 1600
    assert len(owner.get("/billing/invoices").json()) == 2
    est = owner.get("/billing/estimate?operation=image_generation&quantity=3").json()
    assert est["credits"] == 30


def test_payment_webhook_signature_and_idempotency(client, owner):
    from app.models import PaymentOrder

    with SessionLocal() as db:
        ws = uuid.UUID(owner.workspace_id)
        from app.models import Workspace

        org_id = db.get(Workspace, ws).organization_id
        db.add(PaymentOrder(organization_id=org_id, workspace_id=ws, kind="credits", credits=500, amount_minor=49_900,
                            provider="razorpay", provider_order_id="order_123"))
        db.commit()
    body = json.dumps({"event": "order.paid", "payload": {"payment": {"entity": {"id": "pay_1", "order_id": "order_123",
                                                                                "amount": 49_900}}}}).encode()
    bad = client.post("/api/v1/billing/webhooks", content=body, headers={"x-razorpay-signature": "nope", "x-razorpay-event-id": "e1"})
    assert bad.status_code == 401
    sig = hmac_sha256_hex("whsec_test", body)
    for _ in range(2):
        ok = client.post("/api/v1/billing/webhooks", content=body, headers={"x-razorpay-signature": sig, "x-razorpay-event-id": "e1"})
        assert ok.status_code == 200
    assert owner.get("/billing/credits").json()["balance"] == 600


def test_notifications_on_approval_requests(client, owner):
    from tests.conftest import login, register

    owner.post(f"/workspaces/{owner.workspace_id}/members", {"email": "mgr@spice.in", "role": "marketing_manager"})
    register(client, "mgr@spice.in", org="Mgr")
    mgr = login(client, "mgr@spice.in").in_workspace(owner.workspace_id)
    r = mgr.post("/content/generate", {"platform": "instagram", "format": "post", "topic": "monsoon"}).json()
    run_jobs()
    mgr.post(f"/content/{r['content_id']}/submit")
    notes = owner.get("/notifications").json()
    assert notes and notes[0]["kind"] == "approval_requested"

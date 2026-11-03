"""Create a demo agency with one client, sandbox integrations and sample performance data.

    python -m app.seed_demo            # demo@marketingos.local / DemoPassw0rd!

Every metric row it writes is tagged source="demo", and the UI labels such data as demo,
so it is never presented as real results. Do not run this against a production database.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

import app.main  # noqa: F401 - registers models, handlers and approval actions
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.engines import geo_analysis
from app.models import (
    AdAccount,
    AdInsight,
    Brand,
    Campaign,
    Client,
    GeoProject,
    GeoPrompt,
    GeoResult,
    PerformanceSnapshot,
    User,
    Website,
    WorkspaceMember,
)
from app.permissions import Role
from app.security import hash_password
from app.seed import seed
from app.services import accounts, credits, integrations

EMAIL = "demo@northstar-demo.in"
PASSWORD = "DemoPassw0rd!"


def run() -> None:
    if get_settings().is_production:
        raise SystemExit("Refusing to seed demo data in production.")
    if get_settings().auto_create_tables:
        Base.metadata.create_all(engine)
    rng = random.Random(7)
    with SessionLocal() as db:
        seed(db)
        if db.scalar(select(User).where(User.email == EMAIL)):
            print(f"Demo account already exists: {EMAIL} / {PASSWORD}")
            return
        user, agency_ws = accounts.create_account(
            db, email=EMAIL, full_name="Asha Rao", account_type="agency", organization_name="Northstar Digital",
            password_hash=hash_password(PASSWORD), verified=True,
        )
        user.onboarding_completed_at = datetime.now(UTC)
        credits.grant(db, agency_ws.id, 2000, description="Demo credits")
        org = agency_ws.organization
        org.white_label = {"agency_name": "Northstar Digital", "primary_color": "#2F5D9E", "footer": "Prepared by Northstar Digital"}

        ws = accounts.create_workspace(db, org, "Spice Garden", "client", "Restaurant")
        db.add(Client(agency_workspace_id=agency_ws.id, client_workspace_id=ws.id, name="Spice Garden", industry="Restaurant",
                      contact_name="Ravi Shetty", contact_email="ravi@spicegarden.example", account_manager_id=user.id))
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.ACCOUNT_MANAGER.value))
        credits.grant(db, ws.id, 500, description="Demo credits")
        db.add(Brand(
            workspace_id=ws.id, name="Spice Garden", industry="restaurant", is_default=True,
            description="Family-run coastal restaurant in Pune, known for unlimited weekend thalis.",
            website_url="https://spicegarden.example", colors=["#7C2D12", "#E8A317", "#FFF7ED"], voice="warm, generous, a little playful",
            target_customers="families and groups of friends in Pune who eat out on weekends",
            products=[{"name": "weekend thali", "description": "Unlimited coastal thali, Sat–Sun"},
                      {"name": "fish fry platter", "description": "Rava-fried catch of the day"}],
            approved_ctas=["Book a table", "Order on Swiggy"], prohibited_claims=["best in the world", "100% organic"],
            locations=["Pune"], competitor_references=["Coastal Kitchen", "Malvan Tadka"],
        ))
        db.add(Website(workspace_id=ws.id, domain="spicegarden.example", target_country="IN", target_location="Pune", latest_score=68))
        db.flush()
        for provider in ("instagram", "meta", "google_ads"):
            integrations.connect_sandbox(db, ws.id, provider, user.id, None)
        db.flush()

        today = date.today()
        meta_acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == ws.id, AdAccount.platform == "meta"))
        google_acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == ws.id, AdAccount.platform == "google"))
        camps = [
            Campaign(workspace_id=ws.id, platform="meta", ad_account_id=meta_acct.id, name="Weekend thali · Traffic", objective="traffic",
                     status="active", external_id="demo_meta_1", daily_budget_minor=80_000, config={"discovered": True}),
            Campaign(workspace_id=ws.id, platform="meta", ad_account_id=meta_acct.id, name="Lunch combos · Leads", objective="leads",
                     status="active", external_id="demo_meta_2", daily_budget_minor=60_000, config={"discovered": True}),
            Campaign(workspace_id=ws.id, platform="google", ad_account_id=google_acct.id, name="Thali near me · Search", objective="traffic",
                     status="active", external_id="demo_google_1", daily_budget_minor=50_000, config={"discovered": True}),
        ]
        db.add_all(camps)
        db.flush()
        for d in range(60):
            day = today - timedelta(days=d)
            weekend = day.weekday() >= 5
            for i, c in enumerate(camps):
                imps = int(rng.uniform(3000, 6000) * (1.3 if weekend else 1))
                clicks = int(imps * rng.uniform(0.012, 0.03) * (0.5 if i == 1 else 1))
                spend = int((c.daily_budget_minor or 0) * rng.uniform(0.85, 1.0))
                leads = int(clicks * rng.uniform(0.0, 0.04)) if i == 1 else 0
                conv = int(clicks * rng.uniform(0.05, 0.1)) if i == 2 else 0
                db.add(AdInsight(workspace_id=ws.id, campaign_id=c.id, platform=c.platform, date=day, entity_level="campaign",
                                 impressions=imps, reach=int(imps * 0.7) if c.platform == "meta" else None, clicks=clicks,
                                 spend_minor=spend, leads=leads, conversions=conv, revenue_minor=conv * 90_000,
                                 search_impression_share=0.42 if c.platform == "google" else None, source="demo"))
            db.add(PerformanceSnapshot(workspace_id=ws.id, channel="organic", date=day, clicks=int(rng.uniform(80, 140) * (1 + d / 200)),
                                       impressions=int(rng.uniform(2500, 4000)), avg_position=rng.uniform(8, 14), source="demo"))

        project = GeoProject(workspace_id=ws.id, name="Spice Garden AI visibility", brand_name="Spice Garden", domain="spicegarden.example",
                             competitors=[{"name": "Coastal Kitchen", "domain": None, "aliases": []}, {"name": "Malvan Tadka", "domain": None, "aliases": []}],
                             providers=["openai_search", "perplexity"], schedule="off")
        db.add(project)
        db.flush()
        answers = {
            "Best thali in Pune?": "Popular picks include Spice Garden, known for its generous weekend thali, and Coastal Kitchen.",
            "Where can I get good coastal food in Pune?": "Coastal Kitchen and Malvan Tadka are frequently recommended for Malvani dishes.",
            "Spice Garden vs Coastal Kitchen: which is better?":
                "Spice Garden is highly recommended for families; Coastal Kitchen has mixed reviews on service.",
            "Is Spice Garden worth it?": "Yes, reviewers call Spice Garden excellent value with friendly staff.",
        }
        for text, answer in answers.items():
            prompt = GeoPrompt(workspace_id=ws.id, project_id=project.id, text=text, category="local")
            db.add(prompt)
            db.flush()
            for days_ago in (21, 14, 7, 0):
                cites = [{"url": "https://www.zomato.com/pune/spice-garden", "title": "Zomato"}] + (
                    [{"url": "https://spicegarden.example/menu", "title": "Menu"}] if "worth" in text else [])
                a = geo_analysis.analyze(answer, cites, project.brand_name, [], project.domain, project.competitors)
                db.add(GeoResult(workspace_id=ws.id, project_id=project.id, prompt_id=prompt.id, provider="manual:chatgpt",
                                 response_text=answer, citations=cites, brand_mentioned=a["brand_mentioned"], brand_cited=a["brand_cited"],
                                 brand_position=a["brand_position"], competitor_mentions=a["competitor_mentions"], sentiment=a["sentiment"],
                                 observed_at=datetime.now(UTC) - timedelta(days=days_ago)))
        db.commit()
        print(f"Demo agency ready. Sign in as {EMAIL} / {PASSWORD} (demo data is labelled as demo). Workspace {uuid.UUID(str(ws.id))}")


if __name__ == "__main__":
    run()

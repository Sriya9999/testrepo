"""Reference data: plans and credit costs. Safe to run repeatedly (python -m app.seed)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CreditCost, Plan
from app.services.credits import DEFAULT_COSTS

PLANS = [
    {"code": "starter", "name": "Starter", "audience": "Small businesses", "price_minor": 149_900, "monthly_credits": 300,
     "limits": {"workspaces": 1, "members": 2, "client_workspaces": 0, "social_accounts": 2, "ad_accounts": 1,
                "seo_audits_per_month": 4, "crawl_pages": 100, "geo_prompts": 10}},
    {"code": "growth", "name": "Growth", "audience": "Growing SMBs", "price_minor": 399_900, "monthly_credits": 1000,
     "limits": {"workspaces": 1, "members": 5, "client_workspaces": 0, "social_accounts": 5, "ad_accounts": 2,
                "seo_audits_per_month": 10, "crawl_pages": 500, "geo_prompts": 50}},
    {"code": "professional", "name": "Professional", "audience": "Marketing teams", "price_minor": 799_900, "monthly_credits": 2500,
     "limits": {"workspaces": 3, "members": 15, "client_workspaces": 0, "social_accounts": 10, "ad_accounts": 5,
                "seo_audits_per_month": 30, "crawl_pages": 2000, "geo_prompts": 150}},
    {"code": "agency", "name": "Agency", "audience": "Agencies", "price_minor": 1_499_900, "monthly_credits": 6000,
     "limits": {"workspaces": 2, "members": 50, "client_workspaces": 25, "social_accounts": 50, "ad_accounts": 50,
                "seo_audits_per_month": 100, "crawl_pages": 5000, "geo_prompts": 500}},
    {"code": "enterprise", "name": "Enterprise", "audience": "Large organisations", "price_minor": None, "monthly_credits": 0,
     "limits": {}},
]


def seed(db: Session) -> None:
    for p in PLANS:
        plan = db.scalar(select(Plan).where(Plan.code == p["code"]))
        if plan is None:
            db.add(Plan(**p))
        else:
            for k, v in p.items():
                setattr(plan, k, v)
    for op, (credits, desc) in DEFAULT_COSTS.items():
        if db.scalar(select(CreditCost).where(CreditCost.operation == op)) is None:
            db.add(CreditCost(operation=op, credits=credits, description=desc))
    db.commit()


if __name__ == "__main__":
    import app.models  # noqa: F401
    from app.config import get_settings
    from app.db import Base, SessionLocal, engine

    if get_settings().auto_create_tables:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
    print("Seeded plans and credit costs.")

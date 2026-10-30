"""Keyword metrics from a real data source. Returns nothing rather than inventing numbers."""

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdAccount, ConnectedAccount
from app.providers import google
from app.services import integrations

COUNTRY_GEO = {"IN": "2356", "US": "2840", "GB": "2826", "AE": "2784", "SG": "2702", "AU": "2036", "CA": "2124"}
LANGUAGE_IDS = {"en": "1000", "hi": "1023", "ta": "1130", "te": "1131", "mr": "1101", "bn": "1056", "gu": "1072"}


def available_source(db: Session, workspace_id) -> str | None:
    acct = _google_account(db, workspace_id)
    if acct is not None:
        return "google_ads_keyword_planner"
    s = get_settings()
    if s.dataforseo_login and s.dataforseo_password:
        return "dataforseo"
    return None


def _google_account(db: Session, workspace_id):
    for acct in db.scalars(select(AdAccount).where(AdAccount.workspace_id == workspace_id, AdAccount.platform == "google",
                                                   AdAccount.status == "active")):
        conn = db.get(ConnectedAccount, acct.connected_account_id)
        if conn and conn.mode == "live":
            return acct
    return None


def fetch_metrics(db: Session, workspace_id, keywords: list[str], country: str = "IN", language: str = "en") -> tuple[str | None, dict]:
    """Returns (source, {keyword_lower: {"search_volume", "cpc_minor", "competition", "difficulty"}})."""
    acct = _google_account(db, workspace_id)
    if acct is not None:
        conn = db.get(ConnectedAccount, acct.connected_account_id)
        client = google.GoogleAdsClient(integrations.access_token(db, conn))
        out = {}
        for i in range(0, len(keywords), 20):
            for idea in client.keyword_ideas(acct.external_id, keywords[i:i + 20], LANGUAGE_IDS.get(language, "1000"),
                                             [COUNTRY_GEO.get(country, "2356")]):
                m = idea.get("keywordIdeaMetrics", {})
                high = m.get("highTopOfPageBidMicros")
                out[idea.get("text", "").lower()] = {
                    "search_volume": int(m["avgMonthlySearches"]) if m.get("avgMonthlySearches") else None,
                    "cpc_minor": int(high) // 10_000 if high else None, "competition": (m.get("competition") or "").lower() or None,
                    "difficulty": int(m["competitionIndex"]) if m.get("competitionIndex") else None,
                }
        return "google_ads_keyword_planner", out
    s = get_settings()
    if s.dataforseo_login and s.dataforseo_password:
        resp = httpx.post(
            "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
            auth=(s.dataforseo_login, s.dataforseo_password), timeout=120,
            json=[{"keywords": keywords[:1000], "location_code": int(COUNTRY_GEO.get(country, "2356")), "language_code": language}],
        )
        resp.raise_for_status()
        out = {}
        for task in resp.json().get("tasks", []):
            for item in task.get("result") or []:
                out[item["keyword"].lower()] = {
                    "search_volume": item.get("search_volume"),
                    "cpc_minor": round(item["cpc"] * 100) if item.get("cpc") is not None else None,
                    "competition": (item.get("competition") or "").lower() or None,
                    "difficulty": item.get("competition_index"),
                }
        return "dataforseo", out
    return None, {}

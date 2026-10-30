"""Google OAuth, Google Ads API (REST), Search Console and GA4 Data API clients."""

from datetime import date
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.jobs import RetryableError

SCOPES = {
    "google_ads": ["https://www.googleapis.com/auth/adwords"],
    "search_console": ["https://www.googleapis.com/auth/webmasters.readonly"],
    "google_analytics": ["https://www.googleapis.com/auth/analytics.readonly"],
}


class GoogleError(Exception):
    pass


def authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    q = urlencode({
        "client_id": get_settings().google_client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES[provider] + ["openid", "email"]), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


def _token_request(data: dict) -> dict:
    s = get_settings()
    try:
        resp = httpx.post("https://oauth2.googleapis.com/token", data={
            **data, "client_id": s.google_client_id, "client_secret": s.google_client_secret}, timeout=30)
    except httpx.HTTPError as exc:
        raise RetryableError(f"Google token request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise GoogleError(f"Google token request failed: {resp.text[:300]}")
    return resp.json()


def exchange_code(code: str, redirect_uri: str) -> dict:
    return _token_request({"code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"})


def refresh(refresh_token: str) -> dict:
    return _token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"})


def _call(method: str, url: str, token: str, headers: dict | None = None, **kwargs) -> dict:
    try:
        resp = httpx.request(method, url, headers={"Authorization": f"Bearer {token}", **(headers or {})}, timeout=60, **kwargs)
    except httpx.HTTPError as exc:
        raise RetryableError(f"Google request failed: {exc}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableError(f"Google returned {resp.status_code}", delay_seconds=60)
    if resp.status_code >= 400:
        try:
            message = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            message = resp.text
        raise GoogleError(f"Google: {str(message)[:500]}")
    return resp.json() if resp.content else {}


class GoogleAdsClient:
    def __init__(self, token: str, login_customer_id: str | None = None):
        s = get_settings()
        if not s.google_ads_developer_token:
            raise GoogleError("GOOGLE_ADS_DEVELOPER_TOKEN is not set")
        self.token = token
        self.base = f"https://googleads.googleapis.com/{s.google_ads_api_version}"
        self.headers = {"developer-token": s.google_ads_developer_token}
        login = login_customer_id or s.google_ads_login_customer_id
        if login:
            self.headers["login-customer-id"] = login.replace("-", "")

    def accessible_customers(self) -> list[str]:
        res = _call("GET", f"{self.base}/customers:listAccessibleCustomers", self.token, self.headers)
        return [r.split("/")[-1] for r in res.get("resourceNames", [])]

    def search(self, customer_id: str, query: str) -> list[dict]:
        rows, page_token = [], None
        while True:
            body = {"query": query}
            if page_token:
                body["pageToken"] = page_token
            res = _call("POST", f"{self.base}/customers/{customer_id}/googleAds:search", self.token, self.headers, json=body)
            rows.extend(res.get("results", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                return rows

    def mutate(self, customer_id: str, operations: list[dict]) -> dict:
        return _call("POST", f"{self.base}/customers/{customer_id}/googleAds:mutate", self.token, self.headers,
                     json={"mutateOperations": operations})

    def customer_info(self, customer_id: str) -> dict:
        rows = self.search(customer_id, "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
                                        "customer.time_zone, customer.manager FROM customer LIMIT 1")
        return rows[0].get("customer", {}) if rows else {}

    def keyword_ideas(self, customer_id: str, seeds: list[str], language_id: str = "1000",
                      geo_ids: list[str] | None = None) -> list[dict]:
        body = {
            "language": f"languageConstants/{language_id}",
            "geoTargetConstants": [f"geoTargetConstants/{g}" for g in (geo_ids or ["2356"])],
            "keywordPlanNetwork": "GOOGLE_SEARCH",
            "keywordSeed": {"keywords": seeds[:20]},
        }
        res = _call("POST", f"{self.base}/customers/{customer_id}:generateKeywordIdeas", self.token, self.headers, json=body)
        return res.get("results", [])

    def campaign_insights(self, customer_id: str, since: date, until: date) -> list[dict]:
        return self.search(customer_id, (
            "SELECT campaign.id, campaign.name, campaign.status, segments.date, metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions, metrics.conversions_value, metrics.search_impression_share "
            f"FROM campaign WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'"
        ))

    def campaigns(self, customer_id: str) -> list[dict]:
        return self.search(customer_id, (
            "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
            "campaign_budget.amount_micros FROM campaign WHERE campaign.status != 'REMOVED'"
        ))

    def conversion_actions(self, customer_id: str) -> list[dict]:
        return self.search(customer_id, (
            "SELECT conversion_action.name, conversion_action.status, conversion_action.type, "
            "conversion_action.category FROM conversion_action"
        ))


def search_console_sites(token: str) -> list[dict]:
    return _call("GET", "https://www.googleapis.com/webmasters/v3/sites", token).get("siteEntry", [])


def search_console_query(token: str, site: str, since: date, until: date, dimensions: list[str]) -> list[dict]:
    from urllib.parse import quote

    url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    body = {"startDate": since.isoformat(), "endDate": until.isoformat(), "dimensions": dimensions, "rowLimit": 5000}
    return _call("POST", url, token, json=body).get("rows", [])


def analytics_properties(token: str) -> list[dict]:
    res = _call("GET", "https://analyticsadmin.googleapis.com/v1beta/accountSummaries", token)
    props = []
    for acct in res.get("accountSummaries", []):
        for p in acct.get("propertySummaries", []):
            props.append({"property": p["property"], "name": p.get("displayName"), "account": acct.get("displayName")})
    return props


def analytics_daily(token: str, property_id: str, since: date, until: date) -> list[dict]:
    pid = property_id.split("/")[-1]
    body = {
        "dateRanges": [{"startDate": since.isoformat(), "endDate": until.isoformat()}],
        "dimensions": [{"name": "date"}, {"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "conversions"}, {"name": "totalRevenue"}],
        "limit": 10000,
    }
    res = _call("POST", f"https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport", token, json=body)
    out = []
    for row in res.get("rows", []):
        d = row["dimensionValues"]
        m = row["metricValues"]
        out.append({"date": d[0]["value"], "channel": d[1]["value"], "sessions": int(float(m[0]["value"])),
                    "users": int(float(m[1]["value"])), "conversions": int(float(m[2]["value"])),
                    "revenue": float(m[3]["value"])})
    return out

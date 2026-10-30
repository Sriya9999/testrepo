"""Meta Graph API: Facebook Login, Instagram content publishing, and the Marketing API.

Implemented against Meta's published Graph API reference. Every call is server-side with
the workspace's encrypted token; tokens never reach the browser.
"""

import json
from datetime import date
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.jobs import RetryableError

SCOPES_INSTAGRAM = [
    "instagram_basic", "instagram_content_publish", "instagram_manage_insights",
    "pages_show_list", "pages_read_engagement", "business_management",
]
SCOPES_ADS = ["ads_management", "ads_read", "business_management", "pages_show_list", "pages_read_engagement"]

# Error codes Meta documents as transient / rate limiting.
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 368, 613, 80004, 9007}

OBJECTIVES = {
    "awareness": "OUTCOME_AWARENESS",
    "traffic": "OUTCOME_TRAFFIC",
    "engagement": "OUTCOME_ENGAGEMENT",
    "leads": "OUTCOME_LEADS",
    "sales": "OUTCOME_SALES",
    "app_promotion": "OUTCOME_APP_PROMOTION",
}
OPTIMIZATION_GOALS = {
    "awareness": "REACH",
    "traffic": "LINK_CLICKS",
    "engagement": "POST_ENGAGEMENT",
    "leads": "LEAD_GENERATION",
    "sales": "OFFSITE_CONVERSIONS",
    "app_promotion": "APP_INSTALLS",
}


class MetaError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def graph_base() -> str:
    return f"https://graph.facebook.com/{get_settings().meta_graph_version}"


def authorize_url(redirect_uri: str, state: str, scopes: list[str]) -> str:
    s = get_settings()
    q = urlencode({"client_id": s.meta_app_id, "redirect_uri": redirect_uri, "state": state,
                   "scope": ",".join(scopes), "response_type": "code"})
    return f"https://www.facebook.com/{s.meta_graph_version}/dialog/oauth?{q}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    s = get_settings()
    short = _request("GET", "/oauth/access_token", None, params={
        "client_id": s.meta_app_id, "client_secret": s.meta_app_secret, "redirect_uri": redirect_uri, "code": code})
    long = _request("GET", "/oauth/access_token", None, params={
        "grant_type": "fb_exchange_token", "client_id": s.meta_app_id, "client_secret": s.meta_app_secret,
        "fb_exchange_token": short["access_token"]})
    return long  # {"access_token", "token_type", "expires_in"}


def _request(method: str, path: str, token: str | None, params: dict | None = None, data: dict | None = None,
             files: dict | None = None) -> dict:
    params = dict(params or {})
    if token:
        params["access_token"] = token
    try:
        resp = httpx.request(method, f"{graph_base()}{path}", params=params, data=data, files=files, timeout=60)
    except httpx.HTTPError as exc:
        raise RetryableError(f"Meta request failed: {exc}") from exc
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        code = err.get("code")
        message = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
        if resp.status_code >= 500 or code in TRANSIENT_CODES or err.get("is_transient"):
            raise RetryableError(f"Meta: {message}", delay_seconds=60)
        raise MetaError(f"Meta: {message}", code)
    return body


class MetaClient:
    def __init__(self, token: str):
        self.token = token

    def get(self, path: str, **params) -> dict:
        return _request("GET", path, self.token, params=params)

    def post(self, path: str, data: dict | None = None, files: dict | None = None) -> dict:
        clean = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (data or {}).items() if v is not None}
        return _request("POST", path, self.token, data=clean, files=files)

    # ---- discovery ----
    def me(self) -> dict:
        return self.get("/me", fields="id,name")

    def instagram_accounts(self) -> list[dict]:
        pages = self.get("/me/accounts", fields="id,name,instagram_business_account{id,username,name,profile_picture_url,followers_count}")
        out = []
        for page in pages.get("data", []):
            ig = page.get("instagram_business_account")
            if ig:
                out.append({"page_id": page["id"], "page_name": page.get("name"), **ig})
        return out

    def ad_accounts(self) -> list[dict]:
        return self.get("/me/adaccounts", fields="id,account_id,name,currency,timezone_name,account_status").get("data", [])

    def pages(self) -> list[dict]:
        return self.get("/me/accounts", fields="id,name,instagram_business_account{id,username}").get("data", [])

    # ---- Instagram publishing (container -> status -> publish) ----
    def create_container(self, ig_user_id: str, post_format: str, caption: str, media: list[dict]) -> str:
        if post_format == "carousel":
            children = []
            for m in media:
                key = "video_url" if m["kind"] == "video" else "image_url"
                child = self.post(f"/{ig_user_id}/media", {key: m["url"], "is_carousel_item": "true",
                                                           **({"media_type": "VIDEO"} if m["kind"] == "video" else {})})
                children.append(child["id"])
            res = self.post(f"/{ig_user_id}/media", {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
        elif post_format == "reel":
            res = self.post(f"/{ig_user_id}/media", {"media_type": "REELS", "video_url": media[0]["url"], "caption": caption})
        elif post_format == "story":
            key = "video_url" if media[0]["kind"] == "video" else "image_url"
            res = self.post(f"/{ig_user_id}/media", {"media_type": "STORIES", key: media[0]["url"]})
        else:
            res = self.post(f"/{ig_user_id}/media", {"image_url": media[0]["url"], "caption": caption})
        return res["id"]

    def container_status(self, container_id: str) -> str:
        return self.get(f"/{container_id}", fields="status_code").get("status_code", "IN_PROGRESS")

    def publish_container(self, ig_user_id: str, container_id: str) -> dict:
        media_id = self.post(f"/{ig_user_id}/media_publish", {"creation_id": container_id})["id"]
        info = self.get(f"/{media_id}", fields="id,permalink,timestamp")
        return {"id": media_id, "permalink": info.get("permalink")}

    def media_insights(self, media_id: str) -> dict:
        data = self.get(f"/{media_id}/insights", metric="reach,likes,comments,saved,shares").get("data", [])
        return {row["name"]: (row.get("values") or [{}])[0].get("value", row.get("total_value", {}).get("value")) for row in data}

    def account_insights(self, ig_user_id: str) -> dict:
        return self.get(f"/{ig_user_id}", fields="followers_count,media_count")

    # ---- Marketing API ----
    def upload_image(self, ad_account: str, filename: str, data: bytes) -> str:
        res = self.post(f"/act_{ad_account}/adimages", files={"filename": (filename, data)})
        images = res.get("images", {})
        return next(iter(images.values()))["hash"]

    def create_campaign(self, ad_account: str, name: str, objective: str, daily_budget_minor: int | None,
                        lifetime_budget_minor: int | None) -> str:
        return self.post(f"/act_{ad_account}/campaigns", {
            "name": name, "objective": OBJECTIVES[objective], "status": "PAUSED", "special_ad_categories": [],
            "daily_budget": daily_budget_minor, "lifetime_budget": lifetime_budget_minor,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        })["id"]

    def create_ad_set(self, ad_account: str, campaign_id: str, name: str, objective: str, targeting: dict,
                      start: date | None, end: date | None, promoted_object: dict | None) -> str:
        return self.post(f"/act_{ad_account}/adsets", {
            "name": name, "campaign_id": campaign_id, "billing_event": "IMPRESSIONS",
            "optimization_goal": OPTIMIZATION_GOALS[objective], "targeting": targeting, "status": "PAUSED",
            "start_time": start.isoformat() if start else None, "end_time": end.isoformat() if end else None,
            "promoted_object": promoted_object,
        })["id"]

    def create_creative(self, ad_account: str, name: str, page_id: str, instagram_user_id: str | None, copy: dict,
                        image_hash: str | None) -> str:
        link_data = {
            "message": copy.get("primary_text"), "link": copy.get("link_url"), "name": copy.get("headline"),
            "description": copy.get("description"),
            "call_to_action": {"type": copy.get("cta_type", "LEARN_MORE"), "value": {"link": copy.get("link_url")}},
        }
        if image_hash:
            link_data["image_hash"] = image_hash
        spec = {"page_id": page_id, "link_data": link_data}
        if instagram_user_id:
            spec["instagram_user_id"] = instagram_user_id
        return self.post(f"/act_{ad_account}/adcreatives", {"name": name, "object_story_spec": spec})["id"]

    def create_ad(self, ad_account: str, name: str, ad_set_id: str, creative_id: str) -> str:
        return self.post(f"/act_{ad_account}/ads", {"name": name, "adset_id": ad_set_id,
                                                    "creative": {"creative_id": creative_id}, "status": "PAUSED"})["id"]

    def set_status(self, object_id: str, status: str) -> None:
        self.post(f"/{object_id}", {"status": status})

    def update_campaign(self, campaign_id: str, fields: dict) -> None:
        self.post(f"/{campaign_id}", fields)

    def campaigns(self, ad_account: str) -> list[dict]:
        return self.get(f"/act_{ad_account}/campaigns",
                        fields="id,name,objective,status,effective_status,daily_budget,lifetime_budget,start_time,stop_time",
                        limit=200).get("data", [])

    def insights(self, ad_account: str, since: date, until: date, level: str = "campaign") -> list[dict]:
        rows, after = [], None
        while True:
            params = {
                "level": level, "time_increment": 1,
                "fields": "campaign_id,campaign_name,ad_id,ad_name,impressions,reach,clicks,spend,actions,action_values,frequency",
                "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}), "limit": 500,
            }
            if after:
                params["after"] = after
            page = self.get(f"/act_{ad_account}/insights", **params)
            rows.extend(page.get("data", []))
            after = page.get("paging", {}).get("cursors", {}).get("after") if page.get("paging", {}).get("next") else None
            if not after:
                return rows


def action_value(actions: list[dict] | None, *types: str) -> float:
    total = 0.0
    for a in actions or []:
        if a.get("action_type") in types:
            total += float(a.get("value") or 0)
    return total


LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
PURCHASE_ACTIONS = ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")

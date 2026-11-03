"""Cross-channel reporting. Every figure is tagged with its provenance:
measured (reported by a platform), calculated (derived from measured values), internal
(a MarketingOS indicator such as SEO or GEO score) or estimate."""

import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import as_aware
from app.engines import ads_optimizer, geo_analysis
from app.models import AdInsight, Campaign, GeoProject, GeoResult, PerformanceSnapshot, SocialPost, Website


def _pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def kpi(value, previous, kind: str, sources: list[str], unit: str = "count", lower_is_better: bool = False) -> dict:
    return {"value": value, "previous": previous, "change_pct": _pct(value, previous), "kind": kind,
            "sources": sorted(set(sources)), "unit": unit, "lower_is_better": lower_is_better}


def _ads(db: Session, ws_ids: list[uuid.UUID], start: date, end: date, platform: str | None = None) -> list[AdInsight]:
    stmt = select(AdInsight).where(AdInsight.workspace_id.in_(ws_ids), AdInsight.entity_level == "campaign",
                                   AdInsight.date >= start, AdInsight.date <= end)
    if platform:
        stmt = stmt.where(AdInsight.platform == platform)
    return db.scalars(stmt).all()


def _snaps(db: Session, ws_ids, start, end, channel) -> list[PerformanceSnapshot]:
    return db.scalars(select(PerformanceSnapshot).where(
        PerformanceSnapshot.workspace_id.in_(ws_ids), PerformanceSnapshot.channel == channel,
        PerformanceSnapshot.date >= start, PerformanceSnapshot.date <= end)).all()


def _posts(db: Session, ws_ids, start, end) -> list[SocialPost]:
    return db.scalars(select(SocialPost).where(SocialPost.workspace_id.in_(ws_ids), SocialPost.status == "published",
                                               SocialPost.published_at >= start, SocialPost.published_at < end + timedelta(days=1))).all()


def _engagement(p: SocialPost) -> int:
    m = p.metrics or {}
    return sum(int(m.get(k) or 0) for k in ("likes", "comments", "saved", "shares"))


def _sum(rows, attr) -> int | None:
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return sum(vals) if vals else None


def period_totals(db: Session, ws_ids: list[uuid.UUID], start: date, end: date) -> dict:
    ads = _ads(db, ws_ids, start, end)
    organic = _snaps(db, ws_ids, start, end, "organic")
    website = _snaps(db, ws_ids, start, end, "website")
    posts = _posts(db, ws_ids, start, end)
    t = ads_optimizer.totals(ads)
    measured_posts = [p for p in posts if p.metrics]
    return {
        "ads": t, "ads_sources": [r.source for r in ads],
        "organic_clicks": _sum(organic, "clicks"), "organic_impressions": _sum(organic, "impressions"),
        "organic_sessions": _sum(website, "sessions"), "organic_sources": [r.source for r in organic + website],
        "site_conversions": _sum(website, "conversions"), "site_revenue_minor": _sum(website, "revenue_minor"),
        "engagement": sum(_engagement(p) for p in measured_posts) if measured_posts else None,
        "reach": sum(int((p.metrics or {}).get("reach") or 0) for p in measured_posts) if measured_posts else None,
        "posts_published": len(posts), "social_sources": [p.metrics_source for p in measured_posts if p.metrics_source],
    }


def seo_score(db: Session, ws_ids) -> tuple[int | None, list[str]]:
    scores = [w.latest_score for w in db.scalars(select(Website).where(Website.workspace_id.in_(ws_ids))) if w.latest_score is not None]
    return (round(sum(scores) / len(scores)) if scores else None), (["seo_audit"] if scores else [])


def geo_score(db: Session, ws_ids, start: date, end: date) -> int | None:
    projects = db.scalars(select(GeoProject).where(GeoProject.workspace_id.in_(ws_ids))).all()
    scores = []
    for p in projects:
        rows = db.scalars(select(GeoResult).where(GeoResult.project_id == p.id, GeoResult.observed_at >= start,
                                                  GeoResult.observed_at < end + timedelta(days=1))).all()
        v = geo_analysis.visibility(rows, [c["name"] for c in p.competitors])
        if v.get("geo_score") is not None:
            scores.append(v["geo_score"])
    return round(sum(scores) / len(scores)) if scores else None


def overview(db: Session, ws_ids: list[uuid.UUID], start: date, end: date, currency: str) -> dict:
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur, prev = period_totals(db, ws_ids, start, end), period_totals(db, ws_ids, prev_start, prev_end)
    a, pa = cur["ads"], prev["ads"]
    seo, seo_src = seo_score(db, ws_ids)
    ads_src = cur["ads_sources"] + prev["ads_sources"]
    kpis = {
        "organic_traffic": kpi(cur["organic_sessions"] if cur["organic_sessions"] is not None else cur["organic_clicks"],
                               prev["organic_sessions"] if prev["organic_sessions"] is not None else prev["organic_clicks"],
                               "measured", cur["organic_sources"] + prev["organic_sources"]),
        "paid_traffic": kpi(a["clicks"] if ads_src else None, pa["clicks"] if prev["ads_sources"] else None, "measured", ads_src),
        "seo_score": kpi(seo, None, "internal", seo_src, "score"),
        "geo_visibility": kpi(geo_score(db, ws_ids, start, end), geo_score(db, ws_ids, prev_start, prev_end), "internal",
                              ["geo_monitoring"], "score"),
        "impressions": kpi(a["impressions"] if ads_src else None, pa["impressions"] if prev["ads_sources"] else None, "measured", ads_src),
        "engagement": kpi(cur["engagement"], prev["engagement"], "measured", cur["social_sources"] + prev["social_sources"]),
        "spend": kpi(a["spend_minor"] if ads_src else None, pa["spend_minor"] if prev["ads_sources"] else None, "measured", ads_src, "money"),
        "ctr": kpi(a["ctr"], pa["ctr"], "calculated", ads_src, "ratio"),
        "cpc": kpi(a["cpc_minor"], pa["cpc_minor"], "calculated", ads_src, "money", True),
        "cpl": kpi(a["cpl_minor"], pa["cpl_minor"], "calculated", ads_src, "money", True),
        "cpa": kpi(a["cpa_minor"], pa["cpa_minor"], "calculated", ads_src, "money", True),
        "roas": kpi(a["roas"], pa["roas"], "calculated", ads_src, "ratio"),
        "conversions": kpi(a["results"] if ads_src else None, pa["results"] if prev["ads_sources"] else None, "measured", ads_src),
    }
    demo = "demo" in {s for k in kpis.values() for s in k["sources"]}
    return {"range": {"start": start, "end": end}, "previous_range": {"start": prev_start, "end": prev_end},
            "currency": currency, "kpis": kpis, "contains_demo_data": demo, "posts_published": cur["posts_published"]}


def series(db: Session, ws_ids, start: date, end: date) -> dict:
    ads = _ads(db, ws_ids, start, end)
    by_platform: dict = defaultdict(list)
    for r in ads:
        by_platform[r.platform].append(r)
    organic = {s.date.isoformat(): s for s in _snaps(db, ws_ids, start, end, "organic")}
    website = {s.date.isoformat(): s for s in _snaps(db, ws_ids, start, end, "website")}
    posts = _posts(db, ws_ids, start, end)
    eng: dict = defaultdict(int)
    for p in posts:
        if p.metrics:
            eng[as_aware(p.published_at).date().isoformat()] += _engagement(p)
    out_days = []
    d = start
    while d <= end:
        k = d.isoformat()
        out_days.append({"date": k,
                         "organic_clicks": organic[k].clicks if k in organic else None,
                         "organic_sessions": website[k].sessions if k in website else None,
                         "instagram_engagement": eng.get(k)})
        d += timedelta(days=1)
    return {"days": out_days, "paid": {p: ads_optimizer.daily_series(rs) for p, rs in by_platform.items()}}


def channels(db: Session, ws_ids, start: date, end: date) -> list[dict]:
    out = []
    for platform in ("meta", "google"):
        rows = _ads(db, ws_ids, start, end, platform)
        if rows:
            t = ads_optimizer.totals(rows)
            out.append({"channel": f"{platform}_ads", "spend_minor": t["spend_minor"], "clicks": t["clicks"], "impressions": t["impressions"],
                        "conversions": t["results"], "revenue_minor": t["revenue_minor"], "cpa_minor": t["cpa_minor"], "roas": t["roas"],
                        "sources": sorted({r.source for r in rows})})
    organic = _snaps(db, ws_ids, start, end, "organic")
    if organic:
        out.append({"channel": "organic_search", "spend_minor": 0, "clicks": _sum(organic, "clicks"),
                    "impressions": _sum(organic, "impressions"), "conversions": None, "revenue_minor": None, "cpa_minor": None,
                    "roas": None, "sources": sorted({s.source for s in organic})})
    posts = [p for p in _posts(db, ws_ids, start, end) if p.metrics]
    if posts:
        out.append({"channel": "instagram", "spend_minor": 0, "clicks": None,
                    "impressions": sum(int(p.metrics.get("reach") or 0) for p in posts), "conversions": None,
                    "revenue_minor": None, "cpa_minor": None, "roas": None, "engagement": sum(_engagement(p) for p in posts),
                    "sources": sorted({p.metrics_source for p in posts if p.metrics_source})})
    return out


def top_campaigns(db: Session, ws_ids, start: date, end: date, by: str = "results", limit: int = 5) -> list[dict]:
    rows = _ads(db, ws_ids, start, end)
    groups: dict = defaultdict(list)
    for r in rows:
        groups[r.campaign_id].append(r)
    names = {c.id: c.name for c in db.scalars(select(Campaign).where(Campaign.id.in_(list(groups))))} if groups else {}
    items = [{"campaign_id": str(cid), "name": names.get(cid, ""), **ads_optimizer.totals(rs)} for cid, rs in groups.items()]
    return sorted(items, key=lambda x: x.get(by) or 0, reverse=True)[:limit]


def top_posts(db: Session, ws_ids, start: date, end: date, limit: int = 5) -> list[dict]:
    posts = [p for p in _posts(db, ws_ids, start, end) if p.metrics]
    return [{"id": str(p.id), "caption": p.caption[:120], "engagement": _engagement(p), "reach": p.metrics.get("reach"),
             "published_at": p.published_at, "permalink": p.permalink}
            for p in sorted(posts, key=_engagement, reverse=True)[:limit]]


def summary_text(ov: dict, currency: str) -> list[str]:
    """Plain-language summary derived only from the KPI numbers."""
    k = ov["kpis"]
    lines = []

    def money(v):
        return f"{'₹' if currency == 'INR' else currency + ' '}{v / 100:,.0f}"

    if k["spend"]["value"] is not None:
        line = f"Ad spend was {money(k['spend']['value'])}"
        if k["spend"]["change_pct"] is not None:
            line += f" ({k['spend']['change_pct']:+.0f}% vs previous period)"
        if k["conversions"]["value"]:
            line += f", producing {k['conversions']['value']:,} tracked results"
            if k["cpa"]["value"]:
                line += f" at {money(k['cpa']['value'])} each"
        lines.append(line + ".")
    if k["cpc"]["change_pct"] is not None and abs(k["cpc"]["change_pct"]) >= 10:
        lines.append(f"Cost per click {'rose' if k['cpc']['change_pct'] > 0 else 'fell'} {abs(k['cpc']['change_pct']):.0f}%.")
    if k["organic_traffic"]["value"] is not None:
        line = f"Organic traffic: {k['organic_traffic']['value']:,}"
        if k["organic_traffic"]["change_pct"] is not None:
            line += f" ({k['organic_traffic']['change_pct']:+.0f}%)"
        lines.append(line + ".")
    if k["engagement"]["value"] is not None:
        lines.append(f"Instagram posts earned {k['engagement']['value']:,} interactions.")
    if k["seo_score"]["value"] is not None:
        lines.append(f"Latest SEO health score is {k['seo_score']['value']}/100 (internal indicator).")
    if k["geo_visibility"]["value"] is not None:
        lines.append(f"GEO visibility score is {k['geo_visibility']['value']}/100 (internal indicator).")
    if not lines:
        lines.append("No performance data in this period yet. Connect integrations and sync to see results.")
    return lines

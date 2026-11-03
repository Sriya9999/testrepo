"""Rule-based analysis of synced ad performance. Every recommendation carries the measured
numbers it is based on, so the Ads Agent never recommends from invented data."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def derive(t: dict) -> dict:
    """Calculated metrics from measured totals (spend/revenue in minor units)."""
    results = t.get("conversions", 0) or (t.get("leads", 0) + t.get("purchases", 0))
    return {
        "ctr": _ratio(t.get("clicks", 0), t.get("impressions", 0)),
        "cpc_minor": round(t["spend_minor"] / t["clicks"]) if t.get("clicks") else None,
        "cpm_minor": round(t["spend_minor"] * 1000 / t["impressions"]) if t.get("impressions") else None,
        "cpl_minor": round(t["spend_minor"] / t["leads"]) if t.get("leads") else None,
        "cpa_minor": round(t["spend_minor"] / results) if results else None,
        "roas": _ratio(t.get("revenue_minor", 0), t.get("spend_minor", 0)),
        "frequency": _ratio(t.get("impressions", 0), t.get("reach") or 0) if t.get("reach") else None,
        "results": results,
    }


def totals(rows) -> dict:
    keys = ("impressions", "reach", "clicks", "spend_minor", "leads", "purchases", "conversions", "revenue_minor")
    t = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            t[k] += int(getattr(r, k) or 0)
    return {**t, **derive(t)}


def daily_series(rows) -> list[dict]:
    by_day: dict[date, list] = defaultdict(list)
    for r in rows:
        by_day[r.date].append(r)
    return [{"date": d.isoformat(), **totals(v)} for d, v in sorted(by_day.items())]


def analyze(rows, campaigns: dict, currency: str = "INR", today: date | None = None) -> list[dict]:
    """rows: AdInsight rows (campaign level). campaigns: {campaign_id: Campaign}."""
    today = today or date.today()
    by_campaign: dict = defaultdict(list)
    for r in rows:
        by_campaign[r.campaign_id].append(r)
    if not by_campaign:
        return []
    stats = {cid: totals(rs) for cid, rs in by_campaign.items()}
    total_spend = sum(s["spend_minor"] for s in stats.values()) or 1
    ctrs = [s["ctr"] for s in stats.values() if s["ctr"] is not None and s["impressions"] >= 1000]
    cpas = [s["cpa_minor"] for s in stats.values() if s["cpa_minor"]]
    med_ctr = median(ctrs) if ctrs else None
    med_cpa = median(cpas) if cpas else None
    recs: list[dict] = []

    def money(v):
        return f"{'₹' if currency == 'INR' else currency + ' '}{v / 100:,.0f}"

    for cid, s in stats.items():
        c = campaigns.get(cid)
        name = c.name if c else "Campaign"
        base = {"campaign_id": str(cid), "campaign_name": name}
        if s["spend_minor"] > 0.15 * total_spend and s["results"] == 0 and s["spend_minor"] > 50_000:
            recs.append({**base, "type": "budget_inefficiency", "priority": "high",
                         "title": f"{name} spent {money(s['spend_minor'])} with no tracked results",
                         "evidence": {"spend_minor": s["spend_minor"], "results": 0, "share_of_spend": round(s["spend_minor"] / total_spend, 2)},
                         "action": "Check conversion tracking first; if it works, pause or cut this budget and move it to campaigns that convert.",
                         "requires_approval": True})
        if med_ctr and s["ctr"] is not None and s["impressions"] >= 1000 and s["ctr"] < 0.5 * med_ctr:
            recs.append({**base, "type": "poor_creative", "priority": "medium",
                         "title": f"{name} has a CTR of {s['ctr']:.2%}, under half the account median ({med_ctr:.2%})",
                         "evidence": {"ctr": s["ctr"], "median_ctr": med_ctr, "impressions": s["impressions"]},
                         "action": "Test new creative and a stronger hook; the Content Agent can draft variations.",
                         "requires_approval": False})
        if med_cpa and s["cpa_minor"] and len(cpas) >= 2 and s["cpa_minor"] > 1.5 * med_cpa:
            recs.append({**base, "type": "high_cpa", "priority": "medium",
                         "title": f"{name} costs {money(s['cpa_minor'])} per result vs {money(med_cpa)} median",
                         "evidence": {"cpa_minor": s["cpa_minor"], "median_cpa_minor": med_cpa},
                         "action": "Narrow the audience or placements, or shift budget to lower-CPA campaigns.",
                         "requires_approval": True})
        if s["frequency"] and s["frequency"] > 3.5:
            recs.append({**base, "type": "fatigue", "priority": "medium",
                         "title": f"{name} reaches people {s['frequency']:.1f} times on average",
                         "evidence": {"frequency": s["frequency"], "reach": s["reach"]},
                         "action": "Refresh creative or broaden the audience to avoid ad fatigue.", "requires_approval": False})
        if med_cpa and s["cpa_minor"] and len(cpas) >= 2 and s["cpa_minor"] < 0.7 * med_cpa and s["results"] >= 10:
            recs.append({**base, "type": "scale_opportunity", "priority": "low",
                         "title": f"{name} converts at {money(s['cpa_minor'])} per result, well below the median",
                         "evidence": {"cpa_minor": s["cpa_minor"], "median_cpa_minor": med_cpa, "results": s["results"]},
                         "action": "Consider a gradual budget increase (10–20%); budget increases always need approval.",
                         "requires_approval": True})
        sis = [float(r.search_impression_share) for r in by_campaign[cid] if r.search_impression_share is not None]
        if sis and median(sis) < 0.5:
            recs.append({**base, "type": "low_impression_share", "priority": "low",
                         "title": f"{name} shows for {median(sis):.0%} of eligible searches",
                         "evidence": {"search_impression_share": round(median(sis), 3)},
                         "action": "Raise budget or bids on the best ad groups, or tighten keywords to the most relevant.",
                         "requires_approval": True})
        # Trend: last 7 days vs the 7 days before.
        recent = [r for r in by_campaign[cid] if r.date > today - timedelta(days=7)]
        prior = [r for r in by_campaign[cid] if today - timedelta(days=14) < r.date <= today - timedelta(days=7)]
        if recent and prior:
            a, b = totals(recent), totals(prior)
            if a["cpc_minor"] and b["cpc_minor"] and a["cpc_minor"] > 1.25 * b["cpc_minor"]:
                recs.append({**base, "type": "trend_cpc_up", "priority": "medium",
                             "title": f"{name}: cost per click rose {a['cpc_minor'] / b['cpc_minor'] - 1:.0%} week over week",
                             "evidence": {"cpc_last_7d_minor": a["cpc_minor"], "cpc_prev_7d_minor": b["cpc_minor"]},
                             "action": "Check for new competitors, audience overlap or creative fatigue.", "requires_approval": False})
    order = {"high": 0, "medium": 1, "low": 2}
    for r in recs:
        r["kind"] = "recommendation"
    return sorted(recs, key=lambda r: order[r["priority"]])

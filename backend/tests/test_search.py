import uuid

import httpx

from app.db import SessionLocal
from app.engines import geo_analysis, keywords, seo_crawler, seo_rules
from app.models import GeoResult
from tests.conftest import run_jobs

HOME = """<html lang="en"><head><title>Spice Garden | Coastal thali restaurant in Pune</title>
<meta name="viewport" content="width=device-width"><link rel="canonical" href="https://spice.example/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Restaurant","name":"Spice Garden"}</script>
</head><body><h1>Coastal thali in Pune</h1><img src="/a.jpg"><img src="/b.jpg" alt="Thali">
<a href="/about">About</a> <a href="/menu">Menu</a> <a href="/gone">Old page</a> <a href="https://instagram.com/x">IG</a>
<p>""" + "Fresh coastal food. " * 120 + "</p></body></html>"
ABOUT = """<html><head><title>About</title></head><body><p>Short page.</p><a href="/">Home</a></body></html>"""
MENU = """<html lang="en"><head><title>Spice Garden | Coastal thali restaurant in Pune</title><meta name="viewport" content="x">
<meta name="description" content="Menu"></head><body><h1>Menu</h1><h1>Again</h1><a href="/">Home</a></body></html>"""


def site_transport(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\nSitemap: https://spice.example/sitemap.xml\n")
    if path == "/sitemap.xml":
        return httpx.Response(200, text="<urlset><url><loc>https://spice.example/</loc></url><url><loc>https://spice.example/menu</loc></url></urlset>")
    pages = {"/": HOME, "/about": ABOUT, "/menu": MENU}
    if path in pages:
        return httpx.Response(200, text=pages[path], headers={"content-type": "text/html; charset=utf-8"})
    return httpx.Response(404, text="not found", headers={"content-type": "text/html"})


def crawl_site():
    client = httpx.Client(transport=httpx.MockTransport(site_transport), follow_redirects=False)
    return seo_crawler.crawl("spice.example", max_pages=10, client=client)


def test_crawler_collects_pages_and_signals():
    result = crawl_site()
    urls = {p.url for p in result.pages}
    assert {"https://spice.example/", "https://spice.example/about", "https://spice.example/menu"} <= urls
    home = next(p for p in result.pages if p.url == "https://spice.example/")
    assert home.json_ld_types == ["Restaurant"] and home.word_count > 300 and home.external_links == 1
    assert len(home.images_missing_alt) == 1
    assert result.sitemap["urls"] == 2 and result.robots["status"] == 200


def test_rules_find_real_issues_and_score():
    result = crawl_site()
    issues = seo_rules.issues_from_crawl(result, {"performance_score": 35, "lab": {"lcp_ms": 5200, "cls": 0.02}, "field": None},
                                         ["thali restaurant pune"], "Pune")
    codes = {i["code"] for i in issues}
    assert {"missing_meta_description", "images_missing_alt", "client_error", "broken_internal_link", "thin_content",
            "missing_h1", "multiple_h1", "duplicate_title", "missing_viewport", "slow_lcp", "poor_performance_score"} <= codes
    assert "no_structured_data" not in codes and "no_local_business_schema" not in codes
    broken = next(i for i in issues if i["code"] == "broken_internal_link")
    assert broken["details"]["target"] == "https://spice.example/gone"
    score = seo_rules.score(issues, len(result.pages))
    assert 0 < score < 80
    recs = seo_rules.recommendations(issues)
    assert recs[0]["priority"] in ("critical", "high")
    assert all(r["reason"] and r["steps"] and r["estimated_impact"] for r in recs)


def test_audit_job_through_api(owner, monkeypatch):
    real = seo_crawler.crawl
    monkeypatch.setattr(seo_crawler, "crawl", lambda domain, max_pages, *a, **k: real(
        domain, max_pages, client=httpx.Client(transport=httpx.MockTransport(site_transport))))
    site = owner.post("/seo/websites", {"domain": "https://spice.example/", "target_location": "Pune",
                                        "competitors": ["rival.example"]}).json()
    assert site["domain"] == "spice.example" and site["competitors"][0]["domain"] == "rival.example"
    r = owner.post("/seo/audits", {"website_id": site["id"], "max_pages": 10, "include_pagespeed": False}).json()
    run_jobs()
    audit = owner.get(f"/seo/audits/{r['audit_id']}").json()
    assert audit["status"] == "completed" and audit["pages_crawled"] >= 3 and audit["score"] is not None
    assert audit["issues"] and audit["recommendations"]
    high = owner.get(f"/seo/audits/{r['audit_id']}?severity=high").json()["issues"]
    assert all(i["severity"] == "high" for i in high)
    overview = owner.get(f"/seo/overview?website_id={site['id']}").json()
    assert overview["score"] == audit["score"] and "not a Google metric" in overview["score_note"]


def test_audit_limit_per_plan(owner, monkeypatch):
    monkeypatch.setattr(seo_crawler, "crawl", lambda *a, **k: crawl_site())
    site = owner.post("/seo/websites", {"domain": "spice.example"}).json()
    for _ in range(4):
        assert owner.post("/seo/audits", {"website_id": site["id"], "include_pagespeed": False}).status_code == 202
    r = owner.post("/seo/audits", {"website_id": site["id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "plan_limit"


def test_keywords_have_no_invented_metrics(owner):
    site = owner.post("/seo/websites", {"domain": "spice.example"}).json()
    owner.post("/seo/keywords", {"website_id": site["id"], "keywords": ["thali near me", "best thali in pune", "how to make thali",
                                                                          "spice garden menu", "thali price"]})
    out = owner.get(f"/seo/keywords?website_id={site['id']}").json()
    assert out["metrics_provider"] is None and "Connect Google Ads" in out["note"]
    by_text = {k["text"]: k for k in out["keywords"]}
    assert all(k["search_volume"] is None and k["difficulty"] is None and k["cpc_minor"] is None for k in out["keywords"])
    assert by_text["thali near me"]["intent"] == "transactional"
    assert by_text["best thali in pune"]["intent"] == "commercial"
    assert by_text["how to make thali"]["intent"] == "informational"
    assert by_text["spice garden menu"]["intent"] == "navigational"
    assert owner.post("/seo/keywords/refresh").status_code == 409


def test_keyword_clustering():
    clusters = keywords.cluster(["thali restaurant", "thali restaurants pune", "best thali restaurant", "biryani delivery",
                                 "biryani home delivery"])
    groups = {frozenset(v) for v in clusters.values()}
    assert frozenset({"biryani delivery", "biryani home delivery"}) in groups
    assert any({"thali restaurant", "thali restaurants pune"} <= g for g in groups)


def test_geo_analysis_mentions_citations_position_sentiment():
    text = ("For coastal food in Pune, Coastal Kitchen is popular. Spice Garden is highly recommended for its excellent thali. "
            "Some reviews of Coastal Kitchen mention slow service.")
    cites = [{"url": "https://www.spicegarden.example/menu"}, {"url": "https://zomato.com/x"}]
    a = geo_analysis.analyze(text, cites, "Spice Garden", ["SpiceGarden"], "spicegarden.example",
                             [{"name": "Coastal Kitchen", "domain": "coastalkitchen.example"}, {"name": "Thali House"}])
    assert a["brand_mentioned"] and a["brand_position"] == 2 and a["brand_cited"]
    assert a["competitor_mentions"] == {"Coastal Kitchen": 2}
    assert a["sentiment"] > 0
    none = geo_analysis.analyze("Try Coastal Kitchen.", [], "Spice Garden", [], None, [{"name": "Coastal Kitchen"}])
    assert not none["brand_mentioned"] and none["sentiment"] is None and none["brand_position"] is None


def _geo_project(api):
    p = api.post("/geo/projects", {"name": "AI visibility", "brand_name": "Spice Garden", "domain": "spicegarden.example",
                                   "competitors": [{"name": "Coastal Kitchen"}]}).json()
    q1 = api.post("/geo/prompts", {"project_id": p["id"], "text": "Best thali in Pune?", "category": "local"}).json()
    q2 = api.post("/geo/prompts", {"project_id": p["id"], "text": "Where to eat coastal food?", "category": "local"}).json()
    return p, q1, q2


def test_geo_monitoring_requires_a_provider_and_supports_manual_import(owner):
    p, q1, _ = _geo_project(owner)
    r = owner.post("/geo/monitoring/run", {"project_id": p["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "integration_required"
    m = owner.post("/geo/results/manual", {"prompt_id": q1["id"], "engine": "google_ai_overview",
                                           "response_text": "Spice Garden and Coastal Kitchen are popular.",
                                           "citations": ["https://spicegarden.example/"]}).json()
    assert m["provider"] == "manual:google_ai_overview" and m["brand_mentioned"] and m["brand_cited"]
    providers = {x["id"]: x for x in owner.get("/geo/providers").json()}
    assert providers["google_ai_overview"]["mode"] == "manual"


def test_geo_monitoring_run_charges_per_successful_query(owner, monkeypatch):
    from app.providers import geo as geo_providers

    monkeypatch.setattr(geo_providers, "available", lambda: {"openai_search": True, "perplexity": True})

    def fake_ask(provider, prompt, location=None):
        if provider == "perplexity" and "coastal" in prompt.lower():
            raise geo_providers.GeoProviderError("boom")
        return f"{'Spice Garden' if provider == 'openai_search' else 'Coastal Kitchen'} is a good pick.", [{"url": "https://zomato.com/a"}]

    monkeypatch.setattr(geo_providers, "ask", fake_ask)
    p, _, _ = _geo_project(owner)
    r = owner.post("/geo/monitoring/run", {"project_id": p["id"]}).json()
    assert r["queries"] == 4 and r["estimated_credits"] == 4
    run_jobs()
    assert owner.get("/billing/credits").json()["balance"] == 100 - 3  # the failed query is free
    v = owner.get(f"/geo/visibility?project_id={p['id']}").json()
    o = v["overall"]
    assert o["results"] == 3 and o["mention_rate"] == round(2 / 3, 3) and o["geo_score"] is not None
    assert v["by_provider"]["openai_search"]["mention_rate"] == 1.0
    comp = owner.get(f"/geo/competitors?project_id={p['id']}").json()
    assert comp["rows"][0]["is_brand"] and comp["top_cited_domains"][0]["domain"] == "zomato.com"
    with SessionLocal() as db:
        assert db.query(GeoResult).filter_by(status="failed").count() == 1


def test_geo_recommendations_flag_content_gaps(owner):
    p, q1, q2 = _geo_project(owner)
    owner.post("/geo/results/manual", {"prompt_id": q1["id"], "engine": "chatgpt", "response_text": "Coastal Kitchen is the top pick."})
    owner.post("/geo/results/manual", {"prompt_id": q2["id"], "engine": "chatgpt", "response_text": "Spice Garden is lovely."})
    recs = owner.get(f"/geo/recommendations?project_id={p['id']}").json()["recommendations"]
    gap = next(r for r in recs if r["type"] == "content_gap")
    assert "Best thali in Pune?" in gap["title"] and gap["content_brief"]["format"] == "answer_article"


def test_geo_prompt_suggestions(owner):
    p, _, _ = _geo_project(owner)
    s = owner.post("/geo/prompts/suggest", {"project_id": p["id"]}).json()["suggestions"]
    cats = {x["category"] for x in s}
    assert {"local", "comparison", "purchase", "informational"} <= cats
    assert any("Coastal Kitchen" in x["text"] for x in s)
    _ = uuid

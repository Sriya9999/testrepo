"""Turn crawl results into categorized issues, an internal SEO score and prioritized
recommendations (each with reason, estimated impact and implementation steps)."""

from collections import Counter, defaultdict

from app.engines.seo_crawler import CrawlResult

SEVERITY_WEIGHT = {"critical": 15, "high": 8, "medium": 4, "low": 1.5}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def issues_from_crawl(result: CrawlResult, performance: dict | None, keywords: list[str] | None = None,
                      target_location: str | None = None) -> list[dict]:
    issues: list[dict] = []

    def add(code, category, severity, message, page=None, **details):
        issues.append({"code": code, "category": category, "severity": severity, "message": message,
                       "page_url": page, "details": details})

    pages = result.pages
    html_pages = [p for p in pages if p.status == 200 and p.is_html]

    # --- site level ---
    if not result.https:
        add("not_https", "technical", "critical", "The site does not redirect to HTTPS.")
    if result.robots.get("status") != 200:
        add("missing_robots", "technical", "medium", "robots.txt is missing.", result.robots["url"])
    elif result.robots.get("disallow_all"):
        add("robots_disallow_all", "technical", "critical", "robots.txt blocks crawlers from the whole site.", result.robots["url"])
    if result.sitemap.get("status") != 200:
        add("missing_sitemap", "technical", "high", "No XML sitemap was found.", result.sitemap["url"])
    elif not result.sitemap.get("urls"):
        add("empty_sitemap", "technical", "medium", "The XML sitemap lists no URLs.", result.sitemap["url"])
    for url in result.blocked[:20]:
        add("blocked_by_robots", "technical", "medium", "Linked page is blocked by robots.txt.", url)
    if html_pages and not any(p.json_ld_types for p in html_pages):
        add("no_structured_data", "content", "medium", "No structured data (JSON-LD) found on any crawled page.")
    if target_location and html_pages and not any(
            t in ("LocalBusiness", "Restaurant", "Store", "MedicalBusiness", "ProfessionalService") or t.endswith("Business")
            for p in html_pages for t in p.json_ld_types):
        add("no_local_business_schema", "content", "medium", "No LocalBusiness structured data for a location-focused business.")

    # --- per page ---
    for p in pages:
        if p.error:
            add("fetch_error", "technical", "high", f"Page could not be fetched: {p.error}", p.url)
            continue
        if p.status and p.status >= 500:
            add("server_error", "technical", "critical", f"Page returns HTTP {p.status}.", p.url)
        elif p.status and p.status >= 400:
            add("client_error", "technical", "high", f"Page returns HTTP {p.status}.", p.url)
        if len(p.redirects) > 1:
            add("redirect_chain", "technical", "medium", f"{len(p.redirects)} redirects before the final page.", p.url,
                chain=p.redirects)
        if p.elapsed_ms and p.elapsed_ms > 1500:
            add("slow_response", "performance", "medium", f"Server took {p.elapsed_ms} ms to respond.", p.url, ms=p.elapsed_ms)

    for p in html_pages:
        if p.noindex:
            add("noindex", "technical", "medium", "Page is set to noindex.", p.url)
        if not p.title:
            add("missing_title", "on_page", "critical", "Missing <title>.", p.url)
        elif len(p.title) > 60:
            add("title_too_long", "on_page", "low", f"Title is {len(p.title)} characters (aim for 30–60).", p.url, title=p.title)
        elif len(p.title) < 30:
            add("title_too_short", "on_page", "low", f"Title is {len(p.title)} characters (aim for 30–60).", p.url, title=p.title)
        if not p.meta_description:
            add("missing_meta_description", "on_page", "medium", "Missing meta description.", p.url)
        elif len(p.meta_description) > 160:
            add("meta_description_too_long", "on_page", "low", f"Meta description is {len(p.meta_description)} characters.", p.url)
        elif len(p.meta_description) < 70:
            add("meta_description_too_short", "on_page", "low", f"Meta description is {len(p.meta_description)} characters.", p.url)
        if not p.h1:
            add("missing_h1", "on_page", "high", "No H1 heading.", p.url)
        elif len(p.h1) > 1:
            add("multiple_h1", "on_page", "low", f"{len(p.h1)} H1 headings.", p.url)
        if p.images_missing_alt:
            add("images_missing_alt", "on_page", "medium", f"{len(p.images_missing_alt)} images without alt text.", p.url,
                images=p.images_missing_alt[:10])
        if not p.viewport:
            add("missing_viewport", "technical", "high", "No mobile viewport meta tag (page is not mobile friendly).", p.url)
        if not p.lang:
            add("missing_lang", "technical", "low", "The <html> tag has no lang attribute.", p.url)
        if not p.canonical:
            add("missing_canonical", "technical", "low", "No canonical tag.", p.url)
        elif p.canonical.rstrip("/") != (p.final_url or p.url).rstrip("/"):
            target_status = result.checked_links.get(p.canonical)
            if target_status and target_status >= 400:
                add("canonical_broken", "technical", "high", f"Canonical points to a page returning {target_status}.", p.url,
                    canonical=p.canonical)
            else:
                add("canonicalized", "technical", "low", "Canonical points to a different URL.", p.url, canonical=p.canonical)
        if p.word_count < 300:
            add("thin_content", "content", "medium", f"Only {p.word_count} words of content.", p.url, words=p.word_count)
        if not p.internal_links:
            add("no_internal_links", "on_page", "low", "Page links to no other pages on the site.", p.url)

    # duplicates
    titles = defaultdict(list)
    descs = defaultdict(list)
    for p in html_pages:
        if p.title:
            titles[p.title.strip().lower()].append(p.url)
        if p.meta_description:
            descs[p.meta_description.strip().lower()].append(p.url)
    for _title, urls in titles.items():
        if len(urls) > 1:
            for u in urls:
                add("duplicate_title", "on_page", "medium", f"Title shared with {len(urls) - 1} other page(s).", u, pages=urls[:10])
    for _desc, urls in descs.items():
        if len(urls) > 1:
            for u in urls:
                add("duplicate_meta_description", "on_page", "low", f"Meta description shared with {len(urls) - 1} other page(s).", u,
                    pages=urls[:10])

    # broken internal links
    sources: dict[str, list[str]] = defaultdict(list)
    for src, links in result.link_graph.items():
        for link in links:
            sources[link].append(src)
    for target, status in result.checked_links.items():
        if status is not None and status >= 400 and sources.get(target):
            add("broken_internal_link", "technical", "high", f"Link to {target} returns HTTP {status}.", sources[target][0],
                target=target, linked_from=sources[target][:10])

    # keyword placement on the home page
    if keywords and html_pages:
        home = html_pages[0]
        haystack = f"{home.title or ''} {' '.join(home.h1)}".lower()
        if not any(k.lower() in haystack for k in keywords[:5]):
            add("keyword_not_in_title", "content", "medium", "None of the top tracked keywords appear in the home page title or H1.",
                home.url, keywords=keywords[:5])

    # performance
    if performance and not performance.get("error"):
        score = performance.get("performance_score")
        lcp = (performance.get("field") or {}).get("lcp_ms") or performance["lab"].get("lcp_ms")
        cls = (performance.get("field") or {}).get("cls") if performance.get("field") else performance["lab"].get("cls")
        inp = (performance.get("field") or {}).get("inp_ms")
        if score is not None and score < 50:
            add("poor_performance_score", "performance", "high", f"Mobile performance score is {score}/100.", result.start_url)
        if lcp and lcp > 2500:
            add("slow_lcp", "performance", "high" if lcp > 4000 else "medium",
                f"Largest Contentful Paint is {lcp / 1000:.1f}s (good is under 2.5s).", result.start_url)
        if cls is not None and cls > 0.1:
            add("high_cls", "performance", "medium", f"Cumulative Layout Shift is {cls:.2f} (good is under 0.1).", result.start_url)
        if inp and inp > 200:
            add("slow_inp", "performance", "medium", f"Interaction to Next Paint is {inp} ms (good is under 200 ms).", result.start_url)
    return issues


def score(issues: list[dict], pages_crawled: int) -> int:
    """Internal 0–100 health indicator (not a search engine metric)."""
    by_code: dict[str, list[dict]] = defaultdict(list)
    for i in issues:
        by_code[i["code"]].append(i)
    penalty = 0.0
    total = max(pages_crawled, 1)
    for code, items in by_code.items():
        severity = items[0]["severity"]
        affected = len({i["page_url"] for i in items if i["page_url"]}) or 1
        site_level = not items[0]["page_url"] or code in ("missing_sitemap", "missing_robots", "not_https", "no_structured_data")
        fraction = 1.0 if site_level else min(1.0, affected / total)
        penalty += SEVERITY_WEIGHT[severity] * (0.4 + 0.6 * fraction)
    return max(0, round(100 - penalty))


def summary(issues: list[dict]) -> dict:
    return {
        "by_severity": dict(Counter(i["severity"] for i in issues)),
        "by_category": dict(Counter(i["category"] for i in issues)),
        "total": len(issues),
    }


PLAYBOOK: dict[str, dict] = {
    "not_https": {"title": "Serve the whole site over HTTPS", "impact": "high",
                  "reason": "Browsers flag HTTP pages as not secure and Google uses HTTPS as a ranking signal.",
                  "steps": ["Install a TLS certificate (most hosts offer free Let's Encrypt).", "301-redirect every http:// URL to https://.",
                            "Update canonical tags, sitemap and internal links to https://."]},
    "robots_disallow_all": {"title": "Unblock the site in robots.txt", "impact": "high",
                            "reason": "Search engines are told not to crawl any page, so nothing new can rank.",
                            "steps": ["Remove 'Disallow: /' for User-agent: *.", "Keep blocks only for admin or private paths.",
                                      "Re-test the file in Search Console."]},
    "missing_sitemap": {"title": "Publish an XML sitemap", "impact": "medium",
                        "reason": "A sitemap helps search engines discover and refresh your important pages.",
                        "steps": ["Generate /sitemap.xml (CMS plugins do this automatically).", "Reference it in robots.txt.",
                                  "Submit it in Search Console."]},
    "missing_robots": {"title": "Add a robots.txt file", "impact": "low",
                       "reason": "Crawlers look for robots.txt first; a missing file is harmless but wastes a chance to point to the sitemap.",
                       "steps": ["Create /robots.txt allowing crawling.", "Add a 'Sitemap:' line with the sitemap URL."]},
    "server_error": {"title": "Fix pages returning server errors", "impact": "high",
                     "reason": "5xx pages are dropped from search results if they persist.",
                     "steps": ["Check server logs for the listed URLs.", "Fix the failing code or restore the content.", "Re-crawl to confirm."]},
    "client_error": {"title": "Fix or redirect missing pages", "impact": "high",
                     "reason": "Visitors and crawlers hit dead ends, and link value is lost.",
                     "steps": ["Restore the page, or 301-redirect it to the closest live page.", "Update links that point to it."]},
    "broken_internal_link": {"title": "Repair broken internal links", "impact": "high",
                             "reason": "Broken links waste crawl budget and frustrate visitors.",
                             "steps": ["Update each link to a working URL.", "Add redirects for removed pages."]},
    "redirect_chain": {"title": "Shorten redirect chains", "impact": "medium",
                       "reason": "Each hop slows the page and can lose ranking signals.",
                       "steps": ["Point links and redirects directly at the final URL."]},
    "missing_title": {"title": "Add unique page titles", "impact": "high",
                      "reason": "The title is the most important on-page signal and the headline in search results.",
                      "steps": ["Write a 30–60 character title per page with its main keyword first.", "Include the brand at the end."]},
    "duplicate_title": {"title": "Make page titles unique", "impact": "medium",
                        "reason": "Duplicate titles make pages compete with each other.",
                        "steps": ["Rewrite titles so each page describes its own topic."]},
    "title_too_long": {"title": "Shorten long titles", "impact": "low", "reason": "Titles over ~60 characters are cut off in results.",
                       "steps": ["Trim to 60 characters, keeping the keyword at the start."]},
    "title_too_short": {"title": "Expand very short titles", "impact": "low",
                        "reason": "Short titles miss a chance to describe the page and include keywords.",
                        "steps": ["Add the main keyword and a benefit; aim for 30–60 characters."]},
    "missing_meta_description": {"title": "Write meta descriptions", "impact": "medium",
                                 "reason": "A good description improves click-through from search results.",
                                 "steps": ["Write 70–160 characters per page that summarise it and end with a call to action.",
                                           "The Content Studio can draft these from the page content."]},
    "duplicate_meta_description": {"title": "Make meta descriptions unique", "impact": "low",
                                   "reason": "Repeated descriptions are often ignored by search engines.",
                                   "steps": ["Write a specific description for each page."]},
    "meta_description_too_long": {"title": "Shorten long meta descriptions", "impact": "low",
                                  "reason": "Descriptions over ~160 characters are truncated.", "steps": ["Trim to 160 characters."]},
    "meta_description_too_short": {"title": "Expand short meta descriptions", "impact": "low",
                                   "reason": "Very short descriptions don't sell the click.", "steps": ["Aim for 70–160 characters."]},
    "missing_h1": {"title": "Add an H1 heading to each page", "impact": "medium",
                   "reason": "The H1 tells visitors and search engines what the page is about.",
                   "steps": ["Add one H1 near the top that matches the page's main topic and keyword."]},
    "multiple_h1": {"title": "Use a single H1 per page", "impact": "low", "reason": "Several H1s blur the page's main topic.",
                    "steps": ["Keep one H1; change the others to H2."]},
    "images_missing_alt": {"title": "Add alt text to images", "impact": "medium",
                           "reason": "Alt text makes images accessible and lets them rank in image search.",
                           "steps": ["Describe each meaningful image in a short phrase.", "Use empty alt=\"\" for decorative images."]},
    "missing_viewport": {"title": "Make pages mobile friendly", "impact": "high",
                         "reason": "Google indexes the mobile version first; pages without a viewport render poorly on phones.",
                         "steps": ["Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", "Check the layout on a phone."]},
    "thin_content": {"title": "Expand thin pages", "impact": "medium",
                     "reason": "Pages with little content rarely rank or answer questions well.",
                     "steps": ["Add useful detail: what, who it's for, pricing, FAQs.", "Merge near-empty pages into stronger ones."]},
    "no_structured_data": {"title": "Add structured data", "impact": "medium",
                           "reason": "Schema markup enables rich results and helps AI answer engines understand the business.",
                           "steps": ["Add Organization (or LocalBusiness) JSON-LD to the home page.",
                                     "Add FAQPage, Product or Article schema where relevant."]},
    "no_local_business_schema": {"title": "Add LocalBusiness schema", "impact": "medium",
                                 "reason": "Local search and AI answers rely on consistent name, address, phone and hours.",
                                 "steps": ["Add LocalBusiness JSON-LD with name, address, phone, hours and geo.",
                                           "Keep the same details on Google Business Profile and directories."]},
    "keyword_not_in_title": {"title": "Put your main keyword on the home page", "impact": "medium",
                             "reason": "The home page title and H1 don't mention any of your priority keywords.",
                             "steps": ["Work the main keyword into the home page title and H1 naturally."]},
    "slow_lcp": {"title": "Speed up the main content", "impact": "medium",
                 "reason": "Slow Largest Contentful Paint hurts Core Web Vitals and conversions.",
                 "steps": ["Compress and resize the hero image (WebP/AVIF).", "Preload the hero image.", "Reduce render-blocking CSS/JS."]},
    "poor_performance_score": {"title": "Improve mobile performance", "impact": "medium",
                               "reason": "The page is slow on mobile, which loses visitors and rankings.",
                               "steps": ["Review the PageSpeed opportunities.", "Defer third-party scripts.", "Enable caching and a CDN."]},
    "high_cls": {"title": "Stop layout shifts", "impact": "low", "reason": "Content jumping while loading frustrates visitors.",
                 "steps": ["Set width/height on images and embeds.", "Reserve space for banners and ads."]},
    "slow_inp": {"title": "Make the page respond faster to taps", "impact": "low",
                 "reason": "Slow interaction response is a Core Web Vital.", "steps": ["Break up long JavaScript tasks.", "Remove unused scripts."]},
    "slow_response": {"title": "Reduce server response time", "impact": "medium", "reason": "Slow servers delay every page view.",
                      "steps": ["Enable page caching.", "Upgrade hosting or use a CDN."]},
    "noindex": {"title": "Review pages set to noindex", "impact": "medium",
                "reason": "These pages are excluded from search. Fine for private pages, harmful for important ones.",
                "steps": ["Remove noindex from pages that should rank."]},
    "blocked_by_robots": {"title": "Review pages blocked by robots.txt", "impact": "medium",
                          "reason": "Linked pages can't be crawled.", "steps": ["Unblock pages that should appear in search."]},
    "canonical_broken": {"title": "Fix canonical tags pointing at errors", "impact": "high",
                         "reason": "Search engines may drop the page.", "steps": ["Point canonicals at the live, preferred URL."]},
    "missing_canonical": {"title": "Add canonical tags", "impact": "low",
                          "reason": "Canonicals prevent duplicate URLs (tracking parameters, http/https) from splitting signals.",
                          "steps": ["Add a self-referencing canonical to each page."]},
    "no_internal_links": {"title": "Link pages to each other", "impact": "low",
                          "reason": "Internal links spread authority and help discovery.", "steps": ["Link to related pages from body content."]},
    "missing_lang": {"title": "Declare the page language", "impact": "low", "reason": "Helps search engines and screen readers.",
                     "steps": ["Add lang=\"en\" (or the right code) to the <html> tag."]},
}


def recommendations(issues: list[dict], keywords: list[dict] | None = None) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for i in issues:
        grouped[i["code"]].append(i)
    recs = []
    for code, items in grouped.items():
        play = PLAYBOOK.get(code)
        if not play:
            continue
        severity = min((i["severity"] for i in items), key=lambda s: SEVERITY_ORDER[s])
        urls = [i["page_url"] for i in items if i["page_url"]]
        recs.append({
            "code": code, "category": items[0]["category"], "priority": severity, "title": play["title"],
            "reason": play["reason"], "estimated_impact": play["impact"], "steps": play["steps"],
            "affected_pages": len(set(urls)), "examples": list(dict.fromkeys(urls))[:5], "kind": "recommendation",
        })
    # Content opportunities from tracked keywords.
    for k in keywords or []:
        if k.get("intent") == "informational" and k.get("position") is None:
            recs.append({"code": "content_opportunity", "category": "content", "priority": "low",
                         "title": f"Write an article answering \"{k['text']}\"",
                         "reason": "An informational keyword you track has no ranking page yet.",
                         "estimated_impact": "medium", "steps": ["Generate an SEO article in the Content Studio.",
                                                                 "Link to it from a related service page."],
                         "affected_pages": 0, "examples": [], "kind": "recommendation"})
        elif k.get("intent") in ("transactional", "commercial") and k.get("position") is None:
            recs.append({"code": "landing_page_opportunity", "category": "content", "priority": "medium",
                         "title": f"Create a landing page for \"{k['text']}\"",
                         "reason": "A buying-intent keyword you track has no ranking page.", "estimated_impact": "high",
                         "steps": ["Generate a landing page draft in the Content Studio.", "Add it to the main navigation or a hub page."],
                         "affected_pages": 0, "examples": [], "kind": "recommendation"})
    impact_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: (SEVERITY_ORDER[r["priority"]], impact_rank[r["estimated_impact"]], -r["affected_pages"]))

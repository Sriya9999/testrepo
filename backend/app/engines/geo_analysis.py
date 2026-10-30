"""Analyse AI answer-engine responses for brand mentions, citations, position and sentiment,
and aggregate them into visibility metrics. The GEO score is a MarketingOS indicator, not a
metric published by any search or AI provider."""

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

POSITIVE = {"best", "recommended", "recommend", "popular", "excellent", "great", "trusted", "top", "favourite", "favorite",
            "quality", "affordable", "loved", "leading", "reliable", "renowned", "award", "authentic", "delicious", "friendly",
            "highly", "well-known", "standout", "reputable"}
NEGATIVE = {"worst", "avoid", "poor", "bad", "overpriced", "complaints", "complaint", "slow", "rude", "closed", "issues",
            "problems", "disappointing", "expensive", "dirty", "scam", "unreliable", "mixed", "negative"}


def domain_of(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.")


def _pattern(names: list[str]) -> re.Pattern | None:
    names = [n.strip() for n in names if n and n.strip()]
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])({alts})(?![\w-])", re.IGNORECASE)


def analyze(text: str, citations: list[dict], brand: str, aliases: list[str], domain: str | None, competitors: list[dict]) -> dict:
    text = text or ""
    entities = [{"name": brand, "names": [brand, *aliases], "domain": domain, "is_brand": True}] + [
        {"name": c["name"], "names": [c["name"], *(c.get("aliases") or [])], "domain": c.get("domain"), "is_brand": False}
        for c in competitors if c.get("name")
    ]
    first_seen: dict[str, int] = {}
    counts: dict[str, int] = {}
    for e in entities:
        pat = _pattern(e["names"])
        matches = list(pat.finditer(text)) if pat else []
        counts[e["name"]] = len(matches)
        if matches:
            first_seen[e["name"]] = matches[0].start()
    order = sorted(first_seen, key=first_seen.get)
    brand_position = order.index(brand) + 1 if brand in first_seen else None

    cited_domains = [domain_of(c.get("url", "")) for c in citations if c.get("url")]
    own = domain_of(domain) if domain else None
    brand_cited = bool(own) and any(d == own or d.endswith("." + own) for d in cited_domains)

    sentiment = None
    if brand in first_seen:
        pat = _pattern([brand, *aliases])
        sentences = [s for s in re.split(r"(?<=[.!?\n])\s+", text) if pat and pat.search(s)]
        words = re.findall(r"[a-z\-]+", " ".join(sentences).lower())
        pos = sum(w in POSITIVE for w in words)
        neg = sum(w in NEGATIVE for w in words)
        sentiment = round((pos - neg) / (pos + neg), 2) if pos + neg else 0.0

    return {
        "brand_mentioned": counts.get(brand, 0) > 0,
        "brand_mentions": counts.get(brand, 0),
        "brand_position": brand_position,
        "brand_cited": brand_cited,
        "competitor_mentions": {e["name"]: counts[e["name"]] for e in entities if not e["is_brand"] and counts.get(e["name"])},
        "competitor_cited": {e["name"]: True for e in entities if not e["is_brand"] and e["domain"] and any(
            d == domain_of(e["domain"]) or d.endswith("." + domain_of(e["domain"])) for d in cited_domains)},
        "sentiment": sentiment,
        "cited_domains": cited_domains,
    }


def visibility(results: list, competitor_names: list[str]) -> dict:
    """results: GeoResult rows (status completed)."""
    done = [r for r in results if r.status == "completed"]
    n = len(done)
    if not n:
        return {"results": 0, "geo_score": None}
    mentioned = [r for r in done if r.brand_mentioned]
    cited = [r for r in done if r.brand_cited]
    positions = [r.brand_position for r in mentioned if r.brand_position]
    sentiments = [r.sentiment for r in mentioned if r.sentiment is not None]
    comp_counts = Counter()
    for r in done:
        for name in (r.competitor_mentions or {}):
            comp_counts[name] += 1
    total_mention_results = len(mentioned) + sum(comp_counts.values())
    sov = len(mentioned) / total_mention_results if total_mention_results else 0.0
    mention_rate = len(mentioned) / n
    citation_rate = len(cited) / n
    avg_position = sum(positions) / len(positions) if positions else None
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None
    prompts = {r.prompt_id for r in done}
    covered = {r.prompt_id for r in mentioned}
    score = 100 * (0.35 * mention_rate + 0.25 * citation_rate + 0.2 * sov
                   + 0.1 * (1 / avg_position if avg_position else 0) + 0.1 * (((avg_sentiment or 0) + 1) / 2 if mentioned else 0))
    domains = Counter(domain_of(c.get("url", "")) for r in done for c in (r.citations or []) if c.get("url"))
    return {
        "results": n,
        "geo_score": round(score),
        "mention_rate": round(mention_rate, 3),
        "citation_rate": round(citation_rate, 3),
        "share_of_voice": round(sov, 3),
        "avg_position": round(avg_position, 2) if avg_position else None,
        "avg_sentiment": round(avg_sentiment, 2) if avg_sentiment is not None else None,
        "prompt_coverage": round(len(covered) / len(prompts), 3) if prompts else 0,
        "prompts": len(prompts),
        "competitors": [{"name": name, "mention_rate": round(comp_counts.get(name, 0) / n, 3),
                         "share_of_voice": round(comp_counts.get(name, 0) / total_mention_results, 3) if total_mention_results else 0}
                        for name in competitor_names],
        "top_cited_domains": [{"domain": d, "count": c} for d, c in domains.most_common(10)],
    }


def recommendations(results: list, prompts: dict, brand: str, has_structured_data: bool | None) -> list[dict]:
    done = [r for r in results if r.status == "completed"]
    if not done:
        return []
    recs = []
    by_prompt: dict = defaultdict(list)
    for r in done:
        by_prompt[r.prompt_id].append(r)
    gaps = []
    for pid, rs in by_prompt.items():
        if not any(r.brand_mentioned for r in rs) and any(r.competitor_mentions for r in rs):
            comps = sorted({c for r in rs for c in (r.competitor_mentions or {})})
            gaps.append((prompts.get(pid, ""), comps))
    for text, comps in gaps[:8]:
        recs.append({"type": "content_gap", "priority": "high", "title": f"Competitors are named for \"{text}\" but {brand} is not",
                     "reason": f"AI answers mention {', '.join(comps[:3])} for this question.",
                     "action": "Publish an answer-focused page or FAQ that directly answers this question, with verifiable facts.",
                     "content_brief": {"platform": "geo", "format": "answer_article", "question": text}, "kind": "recommendation"})
    mentioned = [r for r in done if r.brand_mentioned]
    if mentioned and sum(r.brand_cited for r in done) / len(done) < 0.2:
        recs.append({"type": "citations", "priority": "medium", "title": f"{brand} is mentioned but rarely cited as a source",
                     "reason": "Answer engines cite pages they can quote. Your site is seldom among the sources.",
                     "action": "Add clear, quotable facts (prices, hours, specs), author and date information, and FAQ sections; "
                               "earn listings on the domains that are cited most often.", "kind": "recommendation"})
    if has_structured_data is False:
        recs.append({"type": "structured_data", "priority": "medium", "title": "Add structured data to your site",
                     "reason": "Schema.org markup (Organization/LocalBusiness, FAQPage, Product) helps engines understand your entity.",
                     "action": "Add JSON-LD to the home page and key pages; the SEO audit lists where it is missing.",
                     "kind": "recommendation"})
    negatives = [r for r in mentioned if r.sentiment is not None and r.sentiment < 0]
    if negatives:
        recs.append({"type": "sentiment", "priority": "medium", "title": f"{len(negatives)} answers describe {brand} negatively",
                     "reason": "Answer engines summarise reviews and articles; negative sources shape what they say.",
                     "action": "Review the cited sources in those answers and address the underlying complaints and reviews.",
                     "kind": "recommendation"})
    never = [prompts.get(pid, "") for pid, rs in by_prompt.items() if not any(r.brand_mentioned for r in rs)
             and not any(r.competitor_mentions for r in rs)]
    if never:
        recs.append({"type": "topic_authority", "priority": "low",
                     "title": f"{len(never)} tracked questions mention no brand at all",
                     "reason": "Open questions are the easiest to win with authoritative content.",
                     "action": "Create in-depth guides for: " + "; ".join(never[:3]), "kind": "recommendation"})
    return recs


def suggest_prompts(brand: str, industry: str, products: list[str], location: str | None, competitors: list[str],
                    audience: str = "") -> list[dict]:
    product = products[0] if products else industry
    loc = location or "my city"
    out = [
        ("industry", f"What are the best {industry} brands{f' in {location}' if location else ''}?"),
        ("industry", f"Which {industry} companies are most trusted right now?"),
        ("local", f"Best {product} near {loc}"),
        ("local", f"Where can I get good {product} in {loc}?"),
        ("purchase", f"Where should I buy {product}?"),
        ("purchase", f"Is {brand} worth it?"),
        ("informational", f"How do I choose a good {product}?"),
        ("informational", f"What should I look for in a {industry} provider?"),
    ]
    if audience:
        out.append(("purchase", f"What is the best {product} for {audience}?"))
    for c in competitors[:3]:
        out.append(("comparison", f"{brand} vs {c}: which is better?"))
    if len(competitors) >= 2:
        out.append(("comparison", f"{competitors[0]} or {competitors[1]} for {product}?"))
    return [{"category": cat, "text": text, "location": location} for cat, text in out]

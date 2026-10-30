"""Deterministic, template-based drafting used when no AI provider is configured
(AI_PROVIDER=offline) and in tests. Output follows the same shapes as the LLM provider so
every workflow works end to end; it is clearly labelled as an offline draft in the UI."""

import random
import re

from app.engines.content_formats import LIMITS


def _rng(*parts) -> random.Random:
    return random.Random("|".join(str(p) for p in parts))


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut if cut else text[:limit]


def _tag(word: str) -> str:
    return "#" + re.sub(r"[^0-9a-zA-Z]", "", word.title())


def _ctx(brief: dict, brand: dict) -> dict:
    products = brand.get("products") or []
    product = brief.get("product") or (products[0]["name"] if products and isinstance(products[0], dict) else "") or "our offer"
    ctas = brand.get("approved_ctas") or []
    return {
        "brand": brand.get("name") or brief.get("brand") or "Our brand",
        "industry": brief.get("industry") or brand.get("industry") or "business",
        "product": product,
        "audience": brief.get("audience") or brand.get("target_customers") or "customers like you",
        "objective": (brief.get("objective") or "engagement").lower(),
        "tone": (brief.get("tone") or brand.get("voice") or "friendly").split(",")[0].strip().lower(),
        "keywords": [k for k in (brief.get("keywords") or []) if k],
        "cta": brief.get("cta") or (ctas[0] if ctas else "Learn more"),
        "topic": (brief.get("topic") or "").replace("_", " ").strip(),
        "location": brief.get("location") or ((brand.get("locations") or [None])[0]),
    }


HOOKS = [
    "Stop scrolling: {topic_or_product} just got better.",
    "Here's what {audience} keep asking us about {topic_or_product}.",
    "3 reasons {audience} choose {brand}.",
    "The {topic_or_product} moment you've been waiting for.",
    "New at {brand}: {topic_or_product}.",
    "Small detail, big difference: {topic_or_product}.",
]
BODIES = [
    "At {brand}, {product} is made for {audience}. We focus on the details that matter so you get more out of every visit.",
    "{product} from {brand} brings together quality, care and value, built around what {audience} actually need.",
    "We built {product} for {audience} who want something better. No shortcuts, just {brand} doing what we do best.",
]
TONE_LINES = {
    "premium": "Crafted with care, made to be remembered.",
    "playful": "Warning: may cause sudden happiness.",
    "professional": "Reliable, transparent and built around your goals.",
    "friendly": "We'd love to see you soon.",
    "bold": "Don't settle. Go bigger.",
}


def _fill(template: str, c: dict) -> str:
    topic_or_product = c["topic"] or c["product"]
    return template.format(topic_or_product=topic_or_product, **c)


def _hashtags(c: dict, n: int = 8) -> list[str]:
    words = c["keywords"] + [c["brand"], c["industry"], c["product"]]
    if c["topic"]:
        words.append(c["topic"])
    if c["location"]:
        words.append(c["location"])
    tags: list[str] = []
    for w in words:
        t = _tag(w)
        if len(t) > 2 and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    return tags[:n]


def write(platform: str, fmt: str, brief: dict, brand: dict, variation: int = 0) -> dict:
    c = _ctx(brief, brand)
    r = _rng(platform, fmt, c["brand"], c["product"], c["topic"], variation)
    hook = _fill(r.choice(HOOKS), c)
    body = _fill(r.choice(BODIES), c)
    tone_line = TONE_LINES.get(c["tone"], TONE_LINES["friendly"])

    if fmt == "post":
        caption = f"{hook}\n\n{body} {tone_line}\n\n{c['cta']} 👉"
        return {
            "hook": hook, "caption": caption, "hashtags": _hashtags(c), "cta": c["cta"],
            "image_prompt": f"{c['product']} for {c['brand']}, {c['tone']} style, brand colours, natural light",
            "alt_text": f"{c['product']} by {c['brand']}",
        }
    if fmt == "carousel":
        n = int(brief.get("number_of_slides") or 5)
        n = max(2, min(n, 10))
        points = [
            ("Why it matters", f"{c['audience'].capitalize()} deserve better than average."),
            ("What makes it different", f"{c['product']} is designed around real needs."),
            ("How it works", "Simple from the first step to the last."),
            ("What people say", f"Loved by {c['audience']} who expect quality."),
            ("Made by " + c["brand"], tone_line),
            ("Did you know?", f"{c['brand']} focuses on {c['industry']} done right."),
            ("Behind the scenes", "Every detail is checked by our team."),
            ("Your next step", f"{c['cta']}."),
        ]
        slides = [{"headline": hook if i == 0 else points[(i - 1) % len(points)][0],
                   "body": body if i == 0 else points[(i - 1) % len(points)][1],
                   "image_prompt": f"Slide {i + 1}: {c['product']}, clean layout, brand colours"} for i in range(n - 1)]
        slides.append({"headline": c["cta"], "body": f"Visit {c['brand']} today.", "image_prompt": "Brand logo on solid brand colour"})
        return {"caption": f"{hook} Swipe through ➡️\n\n{c['cta']}.", "hashtags": _hashtags(c), "cta": c["cta"], "slides": slides}
    if fmt == "reel":
        return {
            "hooks": [_fill(h, c) for h in r.sample(HOOKS, 3)],
            "script": [
                {"scene": 1, "duration_seconds": 3, "visual": f"Close-up of {c['product']}", "voiceover": hook, "on_screen_text": hook},
                {"scene": 2, "duration_seconds": 5, "visual": "Team or customer using it", "voiceover": body, "on_screen_text": c["product"]},
                {"scene": 3, "duration_seconds": 4, "visual": "Detail shots, quick cuts", "voiceover": tone_line, "on_screen_text": tone_line},
                {"scene": 4, "duration_seconds": 3, "visual": "Logo and call to action", "voiceover": c["cta"], "on_screen_text": c["cta"]},
            ],
            "shot_suggestions": ["Vertical 9:16, natural light", "Open on motion within the first second", "End on the logo for 1.5s"],
            "music_mood": "upbeat" if c["tone"] in ("playful", "bold") else "warm, modern",
            "caption": f"{hook}\n\n{c['cta']}.", "hashtags": _hashtags(c), "cta": c["cta"],
        }
    if fmt == "story":
        return {
            "frames": [
                {"text": hook, "visual": f"Full-bleed photo of {c['product']}", "sticker": "poll: Have you tried it?"},
                {"text": body, "visual": "Brand colour background with product cut-out", "sticker": None},
                {"text": c["cta"], "visual": "Logo, link sticker", "sticker": "link"},
            ],
            "cta": c["cta"],
        }
    if fmt == "ad":
        return {
            "primary_text": _clip(f"{hook} {tone_line}", LIMITS["facebook_primary_text"]),
            "headline": _clip(f"{c['product']} by {c['brand']}", LIMITS["ad_headline"]),
            "description": _clip(body, 90),
            "cta": c["cta"],
            "image_prompt": f"{c['product']} hero shot, {c['tone']} style, space for headline",
        }
    if fmt == "search_ad":
        return search_ad(c, r)
    if fmt == "article":
        kw = c["keywords"][0] if c["keywords"] else (c["topic"] or c["product"])
        title = f"{kw.capitalize()}: a practical guide from {c['brand']}"
        return {
            "title": title,
            "meta_title": _clip(title, LIMITS["meta_title"]),
            "meta_description": _clip(f"Everything {c['audience']} should know about {kw}. {body}", LIMITS["meta_description"]),
            "slug": re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-"),
            "keywords": c["keywords"],
            "sections": [
                {"heading": f"What is {kw}?", "body": f"{kw.capitalize()} explained in plain language for {c['audience']}. {body}"},
                {"heading": f"Why {kw} matters", "body": "The benefits, the trade-offs and what to look for when choosing."},
                {"heading": f"How {c['brand']} approaches {kw}", "body": f"{c['brand']} focuses on {c['product']} with a {c['tone']} approach. {tone_line}"},
                {"heading": "Next steps", "body": f"{c['cta']}."},
            ],
            "faq": _faq(c, kw),
        }
    if fmt == "landing_page":
        return {
            "hero": {"headline": hook, "subheadline": body, "cta": c["cta"]},
            "sections": [
                {"heading": "Why choose us", "body": f"{c['brand']} is trusted by {c['audience']}. {tone_line}"},
                {"heading": f"About {c['product']}", "body": body},
                {"heading": "How it works", "body": "1. Get in touch. 2. Tell us what you need. 3. We take care of the rest."},
                {"heading": "Questions", "body": "See the FAQ below or contact our team."},
            ],
            "meta_title": _clip(f"{c['product']} | {c['brand']}", LIMITS["meta_title"]),
            "meta_description": _clip(body, LIMITS["meta_description"]),
            "faq": _faq(c, c["product"]),
        }
    if fmt in ("answer_article", "faq"):
        q = brief.get("question") or f"What is the best {c['product']} for {c['audience']}?"
        result = {
            "question": q,
            "short_answer": f"{c['brand']} offers {c['product']} designed for {c['audience']}. {tone_line}",
            "faq": _faq(c, c["product"]),
            "schema_suggestion": {"@type": "FAQPage", "mainEntity_count": 4},
        }
        if fmt == "answer_article":
            result["title"] = q
            result["sections"] = [
                {"heading": "Short answer", "body": result["short_answer"]},
                {"heading": "What to compare", "body": "Quality, price, location, reviews and how well it fits your needs."},
                {"heading": f"Where {c['brand']} fits", "body": body},
                {"heading": "Sources and facts",
                 "body": "Cite opening hours, prices and verifiable facts. Keep them consistent everywhere the brand is listed."},
            ]
        return result
    if fmt == "campaign":
        return {
            "subject_lines": [_clip(hook, LIMITS["email_subject"]), _clip(f"{c['brand']}: {c['product']} for you", LIMITS["email_subject"])],
            "preview_text": _clip(body, 90),
            "body": f"Hi there,\n\n{body}\n\n{tone_line}\n\n{c['cta']}: [link]\n\n— The {c['brand']} team",
            "cta": c["cta"],
        }
    raise ValueError(f"Offline writer does not support {platform}/{fmt}")


def _faq(c: dict, subject: str) -> list[dict]:
    return [
        {"question": f"What is {subject}?", "answer": f"{subject.capitalize()} from {c['brand']} is made for {c['audience']}."},
        {"question": f"Who is {subject} for?", "answer": f"It suits {c['audience']}."},
        {"question": f"Where can I get {subject}?", "answer": f"Directly from {c['brand']}" + (f" in {c['location']}." if c["location"] else ".")},
        {"question": "How do I get started?", "answer": f"{c['cta']}."},
    ]


def search_ad(c: dict, r: random.Random) -> dict:
    lim = LIMITS["google_headline"]
    candidates = [
        c["product"], c["brand"], f"{c['product']} by {c['brand']}", f"Book {c['product']}",
        f"Top {c['industry']}", f"{c['cta']}", "Trusted by locals", "Quality you can see",
        "Simple, fast, friendly", f"Visit {c['brand']}", f"{c['product']} near you",
        "Great value every day", f"Official {c['brand']} site", "See what's new", f"Try {c['product']}",
    ]
    for k in c["keywords"]:
        candidates.insert(2, k.title())
    if c["location"]:
        candidates.insert(3, f"{c['product']} in {c['location']}")
    headlines: list[str] = []
    for h in candidates:
        h = _clip(h, lim)
        if h and h.lower() not in {x.lower() for x in headlines}:
            headlines.append(h)
    headlines = headlines[:15]
    descriptions = [
        _clip(f"{c['product']} from {c['brand']}, made for {c['audience']}. {c['cta']} today.", 90),
        _clip(f"Quality {c['industry']} with a {c['tone']} touch. See why customers choose {c['brand']}.", 90),
        _clip("Clear prices, friendly service and fast responses. Get in touch now.", 90),
        _clip(f"Discover {c['product']} and more. {c['cta']}.", 90),
    ]
    path = re.sub(r"[^A-Za-z0-9-]", "", c["product"].replace(" ", "-"))[:15] or "offers"
    return {"headlines": headlines, "descriptions": descriptions, "paths": [path], "keywords": c["keywords"]}

"""Supported content types, their body shapes, platform limits and rule checks."""

import re

# platform -> format -> billing operation
FORMATS: dict[str, dict[str, str]] = {
    "instagram": {"post": "text_generation", "carousel": "text_generation", "reel": "video_script",
                  "story": "text_generation", "ad": "text_generation"},
    "facebook": {"post": "text_generation", "ad": "text_generation"},
    "linkedin": {"post": "text_generation"},
    "blog": {"article": "long_form_generation"},
    "website": {"landing_page": "long_form_generation"},
    "google_ads": {"search_ad": "text_generation"},
    "geo": {"answer_article": "long_form_generation", "faq": "text_generation"},
    "email": {"campaign": "text_generation"},
}

FORMAT_LABELS = {
    "post": "Post", "carousel": "Carousel", "reel": "Reel script", "story": "Story", "ad": "Ad creative",
    "article": "SEO article", "landing_page": "Landing page", "search_ad": "Responsive search ad",
    "answer_article": "Answer-focused article", "faq": "FAQ", "campaign": "Email campaign",
}

# Sections a user can regenerate individually, per format.
SECTIONS = {
    "post": ["hook", "caption", "hashtags", "cta"],
    "carousel": ["caption", "hashtags", "slides"],
    "reel": ["hooks", "script", "caption", "hashtags"],
    "story": ["frames", "cta"],
    "ad": ["primary_text", "headline", "description"],
    "article": ["title", "meta_description", "sections", "faq"],
    "landing_page": ["hero", "sections"],
    "search_ad": ["headlines", "descriptions"],
    "answer_article": ["short_answer", "sections", "faq"],
    "faq": ["faq"],
    "campaign": ["subject_lines", "body"],
}

LIMITS = {
    "instagram_caption": 2200,
    "instagram_hashtags": 30,
    "facebook_primary_text": 125,  # recommended before truncation
    "ad_headline": 40,
    "google_headline": 30,
    "google_description": 90,
    "google_headlines_min": 3,
    "google_headlines_max": 15,
    "google_descriptions_min": 2,
    "google_descriptions_max": 4,
    "google_path": 15,
    "meta_title": 60,
    "meta_description": 160,
    "linkedin_post": 3000,
    "email_subject": 70,
}

DIMENSIONS = {
    "square": (1080, 1080),
    "portrait": (1080, 1350),
    "story": (1080, 1920),
    "landscape": (1200, 628),
}


def billing_operation(platform: str, fmt: str) -> str:
    try:
        return FORMATS[platform][fmt]
    except KeyError as exc:
        raise ValueError(f"Unsupported content type {platform}/{fmt}") from exc


def _text_of(body) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return " ".join(_text_of(v) for v in body.values())
    if isinstance(body, list):
        return " ".join(_text_of(v) for v in body)
    return ""


def check(platform: str, fmt: str, body: dict, brand=None) -> dict:
    """Rule-based quality and compliance checks. Returns {"ok": bool, "issues": [...]}.
    Errors block approval; warnings are shown to the reviewer."""
    issues: list[dict] = []

    def add(level: str, field: str, message: str):
        issues.append({"level": level, "field": field, "message": message})

    caption = body.get("caption") or ""
    hashtags = body.get("hashtags") or []
    if platform == "instagram":
        if len(caption) > LIMITS["instagram_caption"]:
            add("error", "caption", f"Instagram captions are limited to {LIMITS['instagram_caption']} characters.")
        if len(hashtags) > LIMITS["instagram_hashtags"]:
            add("error", "hashtags", "Instagram allows at most 30 hashtags.")
        if fmt == "carousel":
            slides = body.get("slides") or []
            if not 2 <= len(slides) <= 20:
                add("error", "slides", "Carousels need between 2 and 20 slides.")
    if fmt == "ad":
        if len(body.get("primary_text") or "") > LIMITS["facebook_primary_text"]:
            add("warning", "primary_text", "Primary text over 125 characters is truncated in most placements.")
        if len(body.get("headline") or "") > LIMITS["ad_headline"]:
            add("warning", "headline", "Headlines over 40 characters may be truncated.")
    if platform == "google_ads":
        heads = body.get("headlines") or []
        descs = body.get("descriptions") or []
        for i, h in enumerate(heads):
            if len(h) > LIMITS["google_headline"]:
                add("error", f"headlines.{i}", f"Headline '{h}' is over 30 characters.")
        for i, d in enumerate(descs):
            if len(d) > LIMITS["google_description"]:
                add("error", f"descriptions.{i}", "Description is over 90 characters.")
        if not LIMITS["google_headlines_min"] <= len(heads) <= LIMITS["google_headlines_max"]:
            add("error", "headlines", "Responsive search ads need 3 to 15 headlines.")
        if not LIMITS["google_descriptions_min"] <= len(descs) <= LIMITS["google_descriptions_max"]:
            add("error", "descriptions", "Responsive search ads need 2 to 4 descriptions.")
        if len({h.lower() for h in heads}) != len(heads):
            add("error", "headlines", "Headlines must be unique.")
    if "meta_title" in body and len(body.get("meta_title") or "") > LIMITS["meta_title"]:
        add("warning", "meta_title", "Meta titles over 60 characters are usually truncated in search results.")
    if "meta_description" in body and len(body.get("meta_description") or "") > LIMITS["meta_description"]:
        add("warning", "meta_description", "Meta descriptions over 160 characters are usually truncated.")
    if platform == "linkedin" and len(caption) > LIMITS["linkedin_post"]:
        add("error", "caption", "LinkedIn posts are limited to 3,000 characters.")
    for i, s in enumerate(body.get("subject_lines") or []):
        if len(s) > LIMITS["email_subject"]:
            add("warning", f"subject_lines.{i}", "Subject lines over 70 characters get cut off on mobile.")

    text = _text_of(body).lower()
    if brand is not None:
        for claim in brand.prohibited_claims or []:
            if claim and claim.lower() in text:
                add("error", "compliance", f"Contains a prohibited claim: '{claim}'.")
    for pattern, label in [
        (r"\bguarantee[sd]?\b", "a guarantee"),
        (r"\b100\s?%\s?(safe|effective|results?)\b", "an absolute performance claim"),
        (r"\b(cure|cures|cured)\b", "a medical claim"),
        (r"\b(lose|losing) \d+\s?(kg|kgs|pounds|lbs)\b", "a specific weight-loss claim"),
    ]:
        if re.search(pattern, text):
            add("warning", "compliance", f"Contains {label}; ad platforms often restrict these.")

    return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues}

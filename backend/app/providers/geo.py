"""AI answer-engine providers for GEO monitoring.

Only official APIs are used. Google AI Overviews / AI Mode and Microsoft Copilot have no
public answer API, so they are supported through manual import of observed answers rather
than scraping (PRD 5.7)."""

import httpx

from app.config import get_settings
from app.services.jobs import RetryableError

PROVIDERS = {
    "openai_search": {"name": "ChatGPT Search (OpenAI web search API)", "mode": "api"},
    "perplexity": {"name": "Perplexity (Sonar API)", "mode": "api"},
    "google_ai_overview": {"name": "Google AI Overviews / AI Mode", "mode": "manual",
                           "note": "No public API. Paste observed answers to track them."},
    "copilot": {"name": "Microsoft Copilot", "mode": "manual", "note": "No public answer API. Paste observed answers."},
}


class GeoProviderError(Exception):
    pass


def available() -> dict[str, bool]:
    s = get_settings()
    return {"openai_search": bool(s.openai_api_key), "perplexity": bool(s.perplexity_api_key),
            "google_ai_overview": False, "copilot": False}


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=120)
    except httpx.HTTPError as exc:
        raise RetryableError(f"{url} failed: {exc}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryableError(f"Provider returned {resp.status_code}", delay_seconds=60)
    if resp.status_code >= 400:
        raise GeoProviderError(f"Provider returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def ask(provider: str, prompt: str, location: str | None = None) -> tuple[str, list[dict]]:
    """Return (answer_text, citations[{url, title}])."""
    s = get_settings()
    if provider == "openai_search":
        if not s.openai_api_key:
            raise GeoProviderError("OPENAI_API_KEY is not set")
        tool: dict = {"type": "web_search"}
        if location:
            tool["user_location"] = {"type": "approximate", "city": location}
        data = _post(f"{s.openai_base_url.rstrip('/')}/responses", {"Authorization": f"Bearer {s.openai_api_key}"},
                     {"model": s.openai_search_model, "tools": [tool], "input": prompt})
        text_parts, citations = [], []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text_parts.append(part.get("text", ""))
                    for ann in part.get("annotations", []):
                        if ann.get("type") == "url_citation":
                            citations.append({"url": ann.get("url"), "title": ann.get("title")})
        return "\n".join(text_parts), _dedupe(citations)
    if provider == "perplexity":
        if not s.perplexity_api_key:
            raise GeoProviderError("PERPLEXITY_API_KEY is not set")
        data = _post("https://api.perplexity.ai/chat/completions", {"Authorization": f"Bearer {s.perplexity_api_key}"},
                     {"model": s.perplexity_model, "messages": [{"role": "user", "content": prompt}]})
        text = data["choices"][0]["message"]["content"]
        results = data.get("search_results") or [{"url": u} for u in data.get("citations", [])]
        return text, _dedupe([{"url": r.get("url"), "title": r.get("title")} for r in results if r.get("url")])
    raise GeoProviderError(f"{PROVIDERS.get(provider, {}).get('name', provider)} has no API; use manual import.")


def _dedupe(citations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in citations:
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out

"""AI provider abstraction.

`offline` drafts deterministically from templates (no network, no cost) so every workflow
runs in development and tests. `openai` calls the OpenAI API with JSON-schema structured
outputs. All generated text is validated by app.engines.content_formats afterwards.
"""

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx

from app.config import get_settings
from app.engines import offline_writer
from app.engines.content_formats import FORMAT_LABELS, SECTIONS
from app.services.jobs import RetryableError

SYSTEM_RULES = """You are a senior marketer writing for the brand described in BRAND.
Rules:
- Follow the brand voice and use only approved calls to action when they are given.
- Never use any phrase listed in prohibited_claims, and never promise guaranteed results.
- Do not invent facts (prices, statistics, awards, opening hours) that are not in BRAND or BRIEF.
- Write in the language given by BRIEF.language.
- Return only JSON that matches the requested schema."""


class AIProviderError(Exception):
    pass


class OfflineProvider:
    name = "offline"
    is_offline = True

    def write_content(self, platform: str, fmt: str, brief: dict, brand: dict, variation: int = 0) -> dict:
        return offline_writer.write(platform, fmt, brief, brand, variation)

    def regenerate_section(self, platform: str, fmt: str, body: dict, section: str, brief: dict, brand: dict, seed: int) -> Any:
        fresh = offline_writer.write(platform, fmt, brief, brand, variation=seed)
        return fresh.get(section, body.get(section))

    def json_task(self, task: str, instructions: str, data: dict, schema: dict, offline: Callable[[], dict]) -> dict:
        return offline()

    def image(self, prompt: str, width: int, height: int, brand: dict) -> tuple[bytes, str, str]:
        return placeholder_svg(prompt, width, height, brand), "image/svg+xml", "offline_placeholder"


class OpenAIProvider:
    name = "openai"
    is_offline = False

    def __init__(self):
        s = get_settings()
        if not s.openai_api_key:
            raise AIProviderError("OPENAI_API_KEY is not set")
        self.base = s.openai_base_url.rstrip("/")
        self.text_model = s.openai_text_model
        self.image_model = s.openai_image_model
        self.headers = {"Authorization": f"Bearer {s.openai_api_key}"}

    def _post(self, path: str, body: dict, timeout: float = 90) -> dict:
        try:
            resp = httpx.post(f"{self.base}{path}", json=body, headers=self.headers, timeout=timeout)
        except httpx.HTTPError as exc:
            raise RetryableError(f"OpenAI request failed: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableError(f"OpenAI returned {resp.status_code}", delay_seconds=30)
        if resp.status_code >= 400:
            raise AIProviderError(f"OpenAI returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _json(self, name: str, system: str, user: dict, schema: dict) -> dict:
        data = self._post(
            "/chat/completions",
            {
                "model": self.text_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
                ],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": False}},
            },
        )
        try:
            return json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIProviderError("The model returned malformed JSON") from exc

    def write_content(self, platform: str, fmt: str, brief: dict, brand: dict, variation: int = 0) -> dict:
        example = offline_writer.write(platform, fmt, brief, brand, variation)
        schema = schema_from_example(example)
        task = {
            "TASK": f"Write a {FORMAT_LABELS.get(fmt, fmt)} for {platform}."
            + (f" This is variation #{variation + 1}; make it clearly different from earlier ones." if variation else ""),
            "BRAND": brand,
            "BRIEF": brief,
            "SHAPE_EXAMPLE": example,
        }
        return self._json(f"{platform}_{fmt}", SYSTEM_RULES, task, schema)

    def regenerate_section(self, platform: str, fmt: str, body: dict, section: str, brief: dict, brand: dict, seed: int) -> Any:
        schema = {"type": "object", "properties": {"value": schema_from_example(body.get(section))}, "required": ["value"]}
        out = self._json(
            "regenerate_section",
            SYSTEM_RULES,
            {"TASK": f"Rewrite only the '{section}' part of this {fmt}. Keep everything else consistent.",
             "BRAND": brand, "BRIEF": brief, "CURRENT": body},
            schema,
        )
        return out.get("value")

    def json_task(self, task: str, instructions: str, data: dict, schema: dict, offline: Callable[[], dict]) -> dict:
        return self._json(task, SYSTEM_RULES + "\n" + instructions, data, schema)

    def image(self, prompt: str, width: int, height: int, brand: dict) -> tuple[bytes, str, str]:
        size = "1024x1024" if width == height else ("1024x1536" if height > width else "1536x1024")
        colours = ", ".join(brand.get("colors") or [])
        data = self._post(
            "/images/generations",
            {"model": self.image_model, "prompt": f"{prompt}. Brand colours: {colours}." if colours else prompt, "size": size, "n": 1},
            timeout=180,
        )
        try:
            return base64.b64decode(data["data"][0]["b64_json"]), "image/png", "ai"
        except (KeyError, IndexError) as exc:
            raise AIProviderError("Image response contained no image") from exc


def schema_from_example(value: Any) -> dict:
    """Derive a JSON schema from an example value (keeps prompts and parsers in sync)."""
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: schema_from_example(v) for k, v in value.items()}, "required": list(value)}
    if isinstance(value, list):
        return {"type": "array", "items": schema_from_example(value[0]) if value else {"type": "string"}}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": ["string", "null"]}
    return {"type": "string"}


def placeholder_svg(prompt: str, width: int, height: int, brand: dict) -> bytes:
    from xml.sax.saxutils import escape

    colors = brand.get("colors") or ["#1E293B", "#F97316"]
    bg = colors[0]
    accent = colors[1] if len(colors) > 1 else "#F97316"
    words = escape(prompt)[:120].split()
    lines, line = [], ""
    for w in words:
        if len(line) + len(w) > 28:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    text = "".join(
        f'<text x="50%" y="{45 + i * 7}%" text-anchor="middle" font-family="sans-serif" font-size="{width // 22}" fill="#fff">{t}</text>'
        for i, t in enumerate(lines[:5])
    )
    name = escape(brand.get("name") or "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="{escape(bg)}"/>'
        f'<rect x="0" y="{height - height // 10}" width="100%" height="{height // 10}" fill="{escape(accent)}"/>'
        f'<text x="50%" y="20%" text-anchor="middle" font-family="sans-serif" font-size="{width // 16}" font-weight="700" fill="{escape(accent)}">{name}</text>'
        f"{text}"
        f'<text x="50%" y="97%" text-anchor="middle" font-family="sans-serif" font-size="{width // 40}" fill="#fff">'
        "Offline placeholder: connect an image model to generate artwork</text>"
        "</svg>"
    )
    return svg.encode()


def get_ai() -> OfflineProvider | OpenAIProvider:
    if get_settings().ai_provider == "openai":
        return OpenAIProvider()
    return OfflineProvider()


__all__ = ["AIProviderError", "SECTIONS", "get_ai", "schema_from_example"]

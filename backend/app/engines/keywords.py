"""Keyword helpers that need no external data: intent estimation and clustering.
Search volume, difficulty and CPC are never computed here; they come from a data provider."""

import re
from collections import defaultdict

STOPWORDS = {
    "a", "an", "the", "for", "in", "on", "of", "to", "and", "or", "with", "near", "me", "best", "top", "is",
    "are", "how", "what", "why", "my", "your", "vs", "versus", "at", "by", "from", "can", "do", "i",
}
TRANSACTIONAL = ("buy", "order", "price", "prices", "cost", "deal", "deals", "discount", "coupon", "book", "booking",
                 "hire", "near me", "delivery", "shop", "online", "cheap", "quote", "subscribe")
COMMERCIAL = ("best", "top", "review", "reviews", "vs", "versus", "compare", "comparison", "alternative", "alternatives")
INFORMATIONAL = ("how", "what", "why", "when", "who", "guide", "tips", "ideas", "meaning", "benefits", "examples", "tutorial")

NEGATIVE_SUGGESTIONS = ["free", "jobs", "job", "career", "careers", "salary", "internship", "diy", "how to make",
                        "recipe", "pdf", "download", "wikipedia", "used", "second hand"]


def intent(keyword: str, brand_terms: list[str] | None = None) -> str:
    k = f" {keyword.lower()} "
    if brand_terms and any(b.lower() in k for b in brand_terms if b):
        return "navigational"
    if any(f" {t} " in k for t in TRANSACTIONAL):
        return "transactional"
    if any(f" {t} " in k for t in COMMERCIAL):
        return "commercial"
    if any(f" {t} " in k for t in INFORMATIONAL) or k.strip().endswith("?"):
        return "informational"
    return "commercial" if len(k.split()) <= 2 else "informational"


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(keyword: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", keyword.lower())
    return {_stem(w) for w in words if w not in STOPWORDS}


def cluster(keywords: list[str], threshold: float = 0.5) -> dict[str, list[str]]:
    """Greedy clustering by token overlap (Jaccard). Cluster name = the shortest member."""
    clusters: list[tuple[set[str], list[str]]] = []
    for kw in sorted(set(keywords), key=lambda k: (len(k.split()), k)):
        t = tokens(kw)
        best, best_score = None, 0.0
        for i, (ct, _) in enumerate(clusters):
            if not t or not ct:
                continue
            score = len(t & ct) / len(t | ct)
            contained = t <= ct or ct <= t
            if (score >= threshold or contained) and score > best_score:
                best, best_score = i, score
        if best is None:
            clusters.append((t, [kw]))
        else:
            clusters[best][0].update(t)
            clusters[best][1].append(kw)
    out: dict[str, list[str]] = defaultdict(list)
    for _, members in clusters:
        out[min(members, key=len)] = members
    return dict(out)


def expand_seeds(seeds: list[str], location: str | None = None) -> list[str]:
    """Candidate keyword phrasings to *research* (not metrics): modifiers people commonly search with."""
    out = []
    for s in seeds:
        s = s.strip().lower()
        if not s:
            continue
        out += [s, f"best {s}", f"{s} near me", f"{s} price", f"{s} reviews", f"buy {s}" if len(s.split()) < 3 else f"{s} online"]
        if location:
            out.append(f"{s} in {location.lower()}")
    seen, result = set(), []
    for k in out:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result

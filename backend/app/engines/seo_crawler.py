"""A polite site crawler for SEO audits: respects robots.txt, stays on the site's host,
records redirects, status codes and on-page signals per page."""

import json
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|gz|mp4|mov|mp3|wav|css|js|json|xml|txt|woff2?|ttf|eot)$", re.I)


@dataclass
class Page:
    url: str
    status: int | None = None
    final_url: str | None = None
    redirects: list[dict] = field(default_factory=list)
    elapsed_ms: int | None = None
    content_type: str = ""
    error: str | None = None
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str = ""
    x_robots: str = ""
    canonical: str | None = None
    h1: list[str] = field(default_factory=list)
    h2_count: int = 0
    images_total: int = 0
    images_missing_alt: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_links: int = 0
    word_count: int = 0
    lang: str | None = None
    viewport: bool = False
    json_ld_types: list[str] = field(default_factory=list)
    og_tags: bool = False
    text_sample: str = ""

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type

    @property
    def noindex(self) -> bool:
        return "noindex" in self.meta_robots.lower() or "noindex" in self.x_robots.lower()

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "internal_links"}
        d["internal_links_count"] = len(self.internal_links)
        d["noindex"] = self.noindex
        return d


@dataclass
class CrawlResult:
    start_url: str
    host: str
    pages: list[Page]
    robots: dict
    sitemap: dict
    https: bool
    blocked: list[str]
    link_graph: dict[str, list[str]]
    checked_links: dict[str, int | None]


def normalize_start(domain: str) -> str:
    d = domain.strip()
    if not re.match(r"^https?://", d):
        d = "https://" + d
    p = urlparse(d)
    return f"{p.scheme}://{p.netloc}{p.path or '/'}"


def _norm(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def _parse(page: Page, html: str, base: str, host: str) -> None:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    page.title = title.get_text(strip=True) if title else None
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    page.meta_description = (md.get("content") or "").strip() if md else None
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    page.meta_robots = (mr.get("content") or "") if mr else ""
    can = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    page.canonical = urljoin(base, can.get("href")) if can and can.get("href") else None
    page.h1 = [h.get_text(" ", strip=True)[:200] for h in soup.find_all("h1")]
    page.h2_count = len(soup.find_all("h2"))
    html_tag = soup.find("html")
    page.lang = html_tag.get("lang") if html_tag else None
    page.viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None
    page.og_tags = soup.find("meta", attrs={"property": re.compile("^og:")}) is not None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("@type"):
                t = item["@type"]
                page.json_ld_types.extend(t if isinstance(t, list) else [t])
    imgs = soup.find_all("img")
    page.images_total = len(imgs)
    page.images_missing_alt = [urljoin(base, i.get("src", ""))[:300] for i in imgs if not (i.get("alt") or "").strip()][:20]
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base, href)
        p = urlparse(absolute)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower().removeprefix("www.") == host.removeprefix("www."):
            links.append(_norm(absolute))
        else:
            page.external_links += 1
    page.internal_links = list(dict.fromkeys(links))
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    page.word_count = len(re.findall(r"\w+", text))
    page.text_sample = text[:1500]


def crawl(domain: str, max_pages: int = 50, timeout: float = 10.0, user_agent: str = "MarketingOS-AuditBot/1.0",
          progress: Callable[[int, int], None] | None = None, client: httpx.Client | None = None) -> CrawlResult:
    start = normalize_start(domain)
    host = urlparse(start).netloc.lower()
    own = client is None
    client = client or httpx.Client(timeout=timeout, headers={"User-Agent": user_agent}, follow_redirects=False)
    try:
        root = f"{urlparse(start).scheme}://{host}"
        robots = {"url": f"{root}/robots.txt", "status": None, "disallow_all": False, "sitemaps": []}
        rp = robotparser.RobotFileParser()
        try:
            r = client.get(robots["url"])
            robots["status"] = r.status_code
            if r.status_code == 200:
                lines = r.text.splitlines()
                rp.parse(lines)
                robots["sitemaps"] = [ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")]
                robots["disallow_all"] = not rp.can_fetch(user_agent, f"{root}/") and not rp.can_fetch("*", f"{root}/")
            else:
                rp.parse([])
        except httpx.HTTPError as exc:
            robots["error"] = str(exc)
            rp.parse([])

        sitemap = {"url": (robots["sitemaps"] or [f"{root}/sitemap.xml"])[0], "status": None, "urls": 0}
        sitemap_urls: list[str] = []
        try:
            r = client.get(sitemap["url"], follow_redirects=True)
            sitemap["status"] = r.status_code
            if r.status_code == 200:
                locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)
                sitemap["urls"] = len(locs)
                sitemap["is_index"] = "<sitemapindex" in r.text
                sitemap_urls = [_norm(u) for u in locs if not u.endswith(".xml")][: max_pages]
        except httpx.HTTPError as exc:
            sitemap["error"] = str(exc)

        queue: deque[str] = deque([_norm(start)] + sitemap_urls)
        seen: set[str] = set(queue)
        pages: list[Page] = []
        blocked: list[str] = []
        graph: dict[str, list[str]] = {}
        https = start.startswith("https://")

        while queue and len(pages) < max_pages:
            url = queue.popleft()
            if not (rp.can_fetch(user_agent, url) or rp.can_fetch("*", url)) and robots["status"] == 200:
                blocked.append(url)
                continue
            page = Page(url=url)
            current = url
            t0 = time.monotonic()
            try:
                for _ in range(6):
                    resp = client.get(current)
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        nxt = urljoin(current, resp.headers["location"])
                        page.redirects.append({"from": current, "to": nxt, "status": resp.status_code})
                        current = nxt
                        continue
                    break
                page.elapsed_ms = int((time.monotonic() - t0) * 1000)
                page.status = resp.status_code
                page.final_url = _norm(current)
                page.content_type = resp.headers.get("content-type", "")
                page.x_robots = resp.headers.get("x-robots-tag", "")
                if page.is_html and resp.status_code == 200 and urlparse(current).netloc.lower().removeprefix("www.") == host.removeprefix("www."):
                    _parse(page, resp.text, current, host)
            except httpx.HTTPError as exc:
                page.error = str(exc)[:300]
            if len(pages) == 0 and page.final_url and page.final_url.startswith("https://"):
                https = True
            elif len(pages) == 0 and page.final_url and page.final_url.startswith("http://"):
                https = False
            pages.append(page)
            graph[url] = page.internal_links
            for link in page.internal_links:
                if link not in seen and not SKIP_EXT.search(urlparse(link).path):
                    seen.add(link)
                    queue.append(link)
            if progress:
                progress(len(pages), max_pages)

        # Check a sample of linked-but-uncrawled internal URLs for broken links.
        crawled = {p.url for p in pages}
        checked: dict[str, int | None] = {p.url: p.status for p in pages}
        targets = [u for links in graph.values() for u in links if u not in crawled and not SKIP_EXT.search(urlparse(u).path)]
        for url in list(dict.fromkeys(targets))[:30]:
            try:
                r = client.head(url, follow_redirects=True)
                if r.status_code in (405, 501):
                    r = client.get(url, follow_redirects=True)
                checked[url] = r.status_code
            except httpx.HTTPError:
                checked[url] = None
        return CrawlResult(start, host, pages, robots, sitemap, https, blocked, graph, checked)
    finally:
        if own:
            client.close()


def pagespeed(url: str, api_key: str | None, timeout: float = 90) -> dict | None:
    """Google PageSpeed Insights (Lighthouse lab data + Chrome UX Report field data if available)."""
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key
    try:
        r = httpx.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params, timeout=timeout)
        if r.status_code != 200:
            return {"error": f"PageSpeed returned {r.status_code}"}
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": str(exc)[:200]}
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    field = data.get("loadingExperience", {}).get("metrics", {})

    def num(key):
        return audits.get(key, {}).get("numericValue")

    return {
        "performance_score": round((lh.get("categories", {}).get("performance", {}).get("score") or 0) * 100),
        "lab": {"lcp_ms": num("largest-contentful-paint"), "cls": num("cumulative-layout-shift"),
                "tbt_ms": num("total-blocking-time"), "fcp_ms": num("first-contentful-paint")},
        "field": {
            "lcp_ms": field.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile"),
            "inp_ms": field.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile"),
            "cls": (field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile") or 0) / 100 if field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") else None,
        } if field else None,
        "source": "pagespeed_insights",
    }

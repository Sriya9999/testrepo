"""The Orchestrator Agent.

Turns an instruction into a reviewable plan, then runs specialised agents step by step.
Agents only take "automatic" actions (drafting, analysing, recommending). Everything that
publishes or spends is turned into approval requests grouped under the run, and executes
only after a human approves it (see app.services.policy.ACTION_POLICIES)."""

import re
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.brands import brand_context
from app.db import utcnow
from app.engines import seo_rules
from app.errors import AppError, PaymentRequired
from app.models import (
    AdAccount,
    AiExecutionLog,
    AiRun,
    AiTask,
    Approval,
    Brand,
    ConnectedAccount,
    ContentAsset,
    GeoProject,
    GeoPrompt,
    SeoAudit,
    SeoIssue,
    SocialPost,
    Website,
    Workspace,
)
from app.providers.ai import get_ai
from app.services import credits, policy
from app.services.accounts import default_brand

AGENTS = {
    "orchestrator": {"name": "Orchestrator Agent", "function": "Coordinates all agents", "actions": ["create_content_draft"]},
    "strategy": {"name": "Strategy Agent", "function": "Marketing strategy and planning", "actions": ["generate_recommendations"]},
    "seo": {"name": "SEO Agent", "function": "Website and keyword optimisation", "actions": ["analyze_keywords", "generate_recommendations"]},
    "sem": {"name": "SEM Agent", "function": "Google Ads recommendations", "actions": ["create_campaign_draft", "launch_campaign", "increase_budget"],
            "requires": "google_ads"},
    "geo": {"name": "GEO Agent", "function": "AI search visibility", "actions": ["generate_recommendations"]},
    "content": {"name": "Content Agent", "function": "Text and content generation", "actions": ["generate_caption", "generate_content", "approve_content"]},
    "creative": {"name": "Creative Agent", "function": "Image and visual generation", "actions": ["generate_image"]},
    "social": {"name": "Social Agent", "function": "Publishing and calendar management", "actions": ["schedule_post", "publish_post"],
               "requires": "instagram"},
    "meta_ads": {"name": "Meta Ads Agent", "function": "Advertising recommendations",
                 "actions": ["create_campaign_draft", "launch_campaign", "increase_budget"],
                 "requires": "meta"},
    "analytics": {"name": "Analytics Agent", "function": "Reports and insights", "actions": ["generate_recommendations"]},
}

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                      "october", "november", "december"], 1)}
MAX = {"posts": 30, "carousels": 10, "reels": 10, "stories": 10}


def _num(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def parse_instruction(text: str, today: date | None = None) -> dict:
    """Rule-based intent parsing (the offline path; an LLM refines this when configured)."""
    t = text.lower()
    today = today or date.today()
    plan = {
        "posts": _num(r"(\d+)\s*(?:instagram\s+|ig\s+|feed\s+|social\s+)?posts?", t),
        "carousels": _num(r"(\d+)\s*carousels?", t),
        "reels": _num(r"(\d+)\s*reels?", t),
        "stories": _num(r"(\d+)\s*stor(?:y|ies)", t),
        "meta_campaign": bool(re.search(r"meta ads?|facebook ads?|instagram ads?|meta campaign|ads? campaign|run advertising|run ads|paid social|advertis", t)),
        "google_campaign": bool(re.search(r"google ads?|search ads?|\bsem\b|\bppc\b|search campaign", t)),
        "seo": bool(re.search(r"\bseo\b|google visibility|rank|organic|search visibility|website", t)),
        "geo": bool(re.search(r"\bgeo\b|ai search|chatgpt|perplexity|ai visibility|mentioned in ai|answer engine|ai overview", t)),
        "duration_days": _num(r"(\d+)[- ]?days?", t) or (7 * _num(r"(\d+)[- ]?weeks?", t) if _num(r"(\d+)[- ]?weeks?", t) else None),
        "start_date": None,
        "daily_budget_minor": None,
    }
    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            year = today.year if month >= today.month else today.year + 1
            start = date(year, month, 1)
            plan["start_date"] = max(start, today + timedelta(days=1)).isoformat()
            if not plan["duration_days"]:
                nxt = date(year + (month == 12), month % 12 + 1, 1)
                plan["duration_days"] = (nxt - start).days
            break
    money = re.search(r"(?:₹|rs\.?|inr)\s?([\d,]+)|([\d,]+)\s?(?:rupees|inr)", t)
    if money:
        amount = int((money.group(1) or money.group(2)).replace(",", ""))
        per_day = bool(re.search(r"per day|/day|a day|daily", t))
        days = plan["duration_days"] or 30
        plan["daily_budget_minor"] = amount * 100 if per_day else max(1, amount // days) * 100
    vague = not any([plan["posts"], plan["carousels"], plan["reels"], plan["stories"], plan["meta_campaign"], plan["google_campaign"]])
    if vague and re.search(r"grow|marketing|campaign|plan|customers|visibility|everything", t):
        plan.update({"posts": plan["posts"] or 12, "reels": plan["reels"] or 4, "meta_campaign": True, "seo": True, "geo": True})
        if "google" in t:
            plan["google_campaign"] = True
    if re.search(r"instagram|content|posts?", t) and not any(plan[k] for k in ("posts", "carousels", "reels", "stories")):
        plan["posts"] = 8
    for k, cap in MAX.items():
        plan[k] = min(plan[k] or 0, cap)
    plan["duration_days"] = min(plan["duration_days"] or 30, 92)
    plan["start_date"] = plan["start_date"] or (today + timedelta(days=1)).isoformat()
    return plan


def estimate_plan(db: Session, plan: dict) -> dict:
    items = [("agent_orchestration", 1), ("strategy_generation", 1)]
    if plan["posts"]:
        items.append(("text_generation", plan["posts"]))
    if plan["carousels"]:
        items.append(("text_generation", plan["carousels"]))
    if plan["stories"]:
        items.append(("text_generation", plan["stories"]))
    if plan["reels"]:
        items.append(("video_script", plan["reels"]))
    visuals = plan["posts"] + plan["carousels"] + (1 if plan["meta_campaign"] else 0)
    if visuals:
        items.append(("image_generation", visuals))
    campaigns = int(plan["meta_campaign"]) + int(plan["google_campaign"])
    if campaigns:
        items.append(("campaign_draft", campaigns))
    if plan["seo"] or plan["geo"]:
        items.append(("recommendations", int(plan["seo"]) + int(plan["geo"])))
    return {"items": [{"operation": op, "quantity": q, "credits": credits.cost_of(db, op) * q} for op, q in items],
            "total": credits.estimate(db, items), "visuals": visuals}


def describe_plan(plan: dict, connected: dict) -> list[dict]:
    """Human-readable task list shown before the run starts."""
    steps = [{"agent": "orchestrator", "title": "Read the brand profile and connected data"},
             {"agent": "strategy", "title": f"Build a {plan['duration_days']}-day strategy starting {plan['start_date']}"}]
    if plan["seo"]:
        steps.append({"agent": "seo", "title": "Prepare an SEO plan from the latest audit and tracked keywords"})
    if plan["geo"]:
        steps.append({"agent": "geo", "title": "Prepare a GEO plan and AI-search prompts to track"})
    parts = [f"{plan[k]} {k}" for k in ("posts", "carousels", "reels", "stories") if plan[k]]
    if parts:
        steps.append({"agent": "content", "title": "Draft " + ", ".join(parts)})
        steps.append({"agent": "creative", "title": "Generate visuals for feed posts"})
        steps.append({"agent": "social", "title": "Prepare the Instagram calendar" + ("" if connected.get("instagram") else
                                                                                       " (connect Instagram to schedule)"),
                      "requires_approval": True})
    if plan["meta_campaign"]:
        steps.append({"agent": "meta_ads", "title": "Prepare a Meta Ads campaign" + (
            f" at {plan['daily_budget_minor'] / 100:,.0f}/day" if plan["daily_budget_minor"] else ""), "requires_approval": True})
    if plan["google_campaign"]:
        steps.append({"agent": "sem", "title": "Prepare a Google search campaign", "requires_approval": True})
    steps.append({"agent": "orchestrator", "title": "Bundle everything that publishes or spends into approval requests"})
    return steps


def connected_platforms(db: Session, workspace_id: uuid.UUID) -> dict:
    accounts = db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id == workspace_id,
                                                         ConnectedAccount.status == "connected")).all()
    return {p: any(a.provider == p for a in accounts) for p in ("instagram", "meta", "google_ads", "search_console", "google_analytics")}


class Runner:
    def __init__(self, db: Session, run: AiRun):
        self.db, self.run = db, run
        self.ws = db.get(Workspace, run.workspace_id)
        self.seq = 0
        self.output: dict = {"content_ids": [], "post_ids": [], "campaign_ids": [], "approval_ids": [], "media_ids": []}
        disabled = set(policy.workspace_settings(self.ws).get("agents", {}).get("disabled", []))
        self.disabled = disabled

    # -- helpers --
    def log(self, agent: str, message: str, task: AiTask | None = None, level: str = "info", **data) -> None:
        self.db.add(AiExecutionLog(workspace_id=self.run.workspace_id, run_id=self.run.id, task_id=task.id if task else None,
                                   agent=agent, level=level, message=message, data=data))
        self.db.commit()

    def task(self, agent: str, title: str) -> AiTask:
        self.seq += 1
        t = AiTask(workspace_id=self.run.workspace_id, run_id=self.run.id, agent=agent, title=title, sequence=self.seq,
                   status="running", started_at=utcnow())
        self.db.add(t)
        self.db.commit()
        return t

    def done(self, t: AiTask, output: dict | None = None, credits_used: int = 0, status: str = "done") -> None:
        t.status, t.finished_at, t.output, t.credits_used = status, utcnow(), output or {}, credits_used
        self.run.credits_used += credits_used
        self.db.commit()

    def cancelled(self) -> bool:
        self.db.refresh(self.run)
        return self.run.status == "cancelled"

    def charge(self, op: str, qty: int = 1) -> int:
        return credits.charge(self.db, self.run.workspace_id, op, qty, reference=str(self.run.id), actor_id=self.run.requested_by,
                              description=f"Agent run: {op}")

    # -- run --
    def execute(self) -> dict:
        db, run = self.db, self.run
        plan = run.plan["parsed"]
        brand = db.get(Brand, uuid.UUID(run.plan["brand_id"])) if run.plan.get("brand_id") else default_brand(db, run.workspace_id)
        bctx = brand_context(brand)
        connected = connected_platforms(db, run.workspace_id)

        t = self.task("orchestrator", "Read the brand profile and connected data")
        if not brand:
            self.log("orchestrator", "No brand profile found: drafts will be generic. Add one under Settings → Brand.", t, "warning")
        self.log("orchestrator", f"Connected: {', '.join(k for k, v in connected.items() if v) or 'nothing yet'}", t)
        self.charge("agent_orchestration")
        self.done(t, {"brand": bctx.get("name"), "connected": connected}, credits.cost_of(db, "agent_orchestration"))

        if self.cancelled():
            return self.output
        strategy = self.strategy(plan, bctx, connected)
        for step in (lambda: plan["seo"] and self.seo(),
                     lambda: plan["geo"] and self.geo(bctx, brand),
                     lambda: self.content(plan, brand, strategy),
                     lambda: self.social(plan, connected),
                     lambda: plan["meta_campaign"] and self.ads("meta", plan, bctx),
                     lambda: plan["google_campaign"] and self.ads("google", plan, bctx)):
            if self.cancelled():
                return self.output
            step()
        t = self.task("orchestrator", "Bundle approvals")
        n = len(self.output["approval_ids"])
        self.log("orchestrator", f"{n} item(s) are waiting for approval. Nothing is published or spent until you approve." if n
                 else "Nothing needs approval: all outputs are drafts.", t)
        self.done(t, {"approvals": n})
        return self.output

    def strategy(self, plan: dict, bctx: dict, connected: dict) -> dict:
        if "strategy" in self.disabled:
            return {}
        t = self.task("strategy", f"Build a {plan['duration_days']}-day strategy")
        products = [p.get("name") for p in bctx.get("products", []) if isinstance(p, dict)] or [bctx.get("name", "our offer")]
        weeks = max(1, plan["duration_days"] // 7)
        themes = ["Introduce the brand and what makes it different", "Show the product or service in action",
                  "Social proof: customers, reviews, behind the scenes", "Offer and urgency", "Education: tips and FAQs",
                  "Community and local moments"]

        def offline():
            return {
                "objective": "Grow awareness and enquiries with consistent content, paid reach and search visibility.",
                "pillars": [f"{p}: benefits and use cases" for p in products[:3]] + ["Behind the scenes", "Customer stories"],
                "weekly_themes": [{"week": i + 1, "theme": themes[i % len(themes)]} for i in range(weeks)],
                "channel_mix": [c for c, on in (("Instagram", plan["posts"] or plan["reels"]), ("Meta Ads", plan["meta_campaign"]),
                                                ("Google Ads", plan["google_campaign"]), ("SEO", plan["seo"]), ("GEO", plan["geo"])) if on],
                "kpis_to_watch": ["Reach and engagement rate", "Cost per lead / result", "Website visits from search",
                                  "Brand mentions in AI answers"],
                "posting_cadence": f"{round((plan['posts'] + plan['reels'] + plan['carousels']) / weeks, 1)} feed posts per week",
                "note": "No targets are set from estimates; baselines come from the first 2 weeks of measured data.",
            }
        out = get_ai().json_task("strategy", "Create a concise marketing strategy for the period. Do not invent numeric targets.",
                                 {"BRAND": bctx, "PLAN": plan, "CONNECTED": connected},
                                 {"type": "object", "properties": {"objective": {"type": "string"}, "pillars": {"type": "array"},
                                                                   "weekly_themes": {"type": "array"}, "channel_mix": {"type": "array"},
                                                                   "kpis_to_watch": {"type": "array"}, "posting_cadence": {"type": "string"}}},
                                 offline)
        used = self.charge("strategy_generation")
        self.output["strategy"] = out
        self.log("strategy", f"Strategy ready: {len(out.get('weekly_themes', []))} weekly themes, pillars: "
                 + ", ".join(out.get("pillars", [])[:3]), t)
        self.done(t, out, used)
        return out

    def seo(self) -> None:
        if "seo" in self.disabled:
            return
        db = self.db
        t = self.task("seo", "SEO plan")
        site = db.scalar(select(Website).where(Website.workspace_id == self.run.workspace_id).order_by(Website.created_at))
        if site is None:
            self.log("seo", "No website added yet. Add it under SEO to get an audit and recommendations.", t, "warning")
            self.done(t, {"recommendations": []}, status="skipped")
            return
        audit = db.scalar(select(SeoAudit).where(SeoAudit.website_id == site.id, SeoAudit.status == "completed")
                          .order_by(SeoAudit.created_at.desc()))
        if audit is None:
            from app.services import jobs

            a = SeoAudit(workspace_id=site.workspace_id, website_id=site.id, config={"max_pages": 30, "include_pagespeed": True,
                                                                                      "domain": site.domain})
            db.add(a)
            db.flush()
            jobs.enqueue(db, "seo.audit", {"audit_id": a.id}, workspace_id=site.workspace_id, max_attempts=1)
            self.log("seo", f"Started a first audit of {site.domain}; recommendations will appear under SEO when it finishes.", t)
            self.done(t, {"audit_id": str(a.id)})
            return
        issues = [{"code": i.code, "category": i.category, "severity": i.severity, "page_url": i.page_url}
                  for i in db.scalars(select(SeoIssue).where(SeoIssue.audit_id == audit.id))]
        recs = seo_rules.recommendations(issues)[:6]
        used = self.charge("recommendations")
        self.output["seo_recommendations"] = recs
        self.log("seo", f"Top SEO priorities for {site.domain} (score {audit.score}/100): " + "; ".join(r["title"] for r in recs[:3]), t)
        self.done(t, {"recommendations": recs, "audit_id": str(audit.id)}, used)

    def geo(self, bctx: dict, brand: Brand | None) -> None:
        if "geo" in self.disabled:
            return
        from app.engines import geo_analysis

        db = self.db
        t = self.task("geo", "GEO plan")
        project = db.scalar(select(GeoProject).where(GeoProject.workspace_id == self.run.workspace_id))
        if project is None:
            site = db.scalar(select(Website).where(Website.workspace_id == self.run.workspace_id))
            project = GeoProject(workspace_id=self.run.workspace_id, name=f"{bctx.get('name', 'Brand')} AI visibility",
                                 brand_name=bctx.get("name") or self.ws.name, domain=site.domain if site else None,
                                 competitors=[{"name": c, "domain": None, "aliases": []} for c in bctx.get("competitor_references", [])])
            db.add(project)
            db.flush()
            products = [p.get("name", "") for p in bctx.get("products", []) if isinstance(p, dict)]
            for s in geo_analysis.suggest_prompts(project.brand_name, bctx.get("industry") or "business", products,
                                                  (bctx.get("locations") or [None])[0], [c["name"] for c in project.competitors],
                                                  bctx.get("target_customers", ""))[:10]:
                db.add(GeoPrompt(workspace_id=project.workspace_id, project_id=project.id, text=s["text"], category=s["category"],
                                 location=s["location"], source="ai_suggested"))
            self.log("geo", "Created a GEO project with 10 suggested AI-search questions to track. Run monitoring from the GEO page.", t)
        recs = [
            {"title": "Publish answer-focused FAQ content for your top questions", "kind": "recommendation"},
            {"title": "Add Organization/LocalBusiness and FAQPage structured data", "kind": "recommendation"},
            {"title": "Keep name, address, hours and prices identical across your site and listings", "kind": "recommendation"},
        ]
        used = self.charge("recommendations")
        self.output["geo_recommendations"] = recs
        self.done(t, {"project_id": str(project.id), "recommendations": recs}, used)

    def content(self, plan: dict, brand: Brand | None, strategy: dict) -> None:
        if "content" in self.disabled:
            return
        from app.api.content import create_images, generate_into

        db = self.db
        jobs_ = [("instagram", "post", plan["posts"]), ("instagram", "carousel", plan["carousels"]),
                 ("instagram", "reel", plan["reels"]), ("instagram", "story", plan["stories"])]
        if not any(n for *_, n in jobs_):
            return
        t = self.task("content", "Draft content")
        themes = [w.get("theme", "") for w in strategy.get("weekly_themes", [])] or [""]
        products = [p.get("name") for p in (brand.products if brand else []) if isinstance(p, dict)] or [""]
        used = 0
        i = 0
        for platform, fmt, count in jobs_:
            for n in range(count):
                brief = {"objective": "engagement", "topic": themes[i % len(themes)], "product": products[i % len(products)],
                         "tone": (brand.voice if brand else "") or "friendly", "language": "en"}
                asset = ContentAsset(workspace_id=self.run.workspace_id, brand_id=brand.id if brand else None, platform=platform,
                                     format=fmt, objective="engagement", brief=brief,
                                     title=f"{fmt.title()} {n + 1}: {brief['topic'] or brief['product']}"[:300],
                                     created_by=self.run.requested_by, ai_run_id=self.run.id, generation_status="pending")
                db.add(asset)
                db.flush()
                try:
                    used += generate_into(db, asset, 1, self.run.requested_by, str(self.run.id))
                except PaymentRequired:
                    db.rollback()
                    self.log("content", "Stopped drafting: out of credits.", t, "warning")
                    self.done(t, {"content_ids": self.output["content_ids"]}, used)
                    return
                db.commit()
                self.output["content_ids"].append(str(asset.id))
                i += 1
        self.log("content", f"Drafted {len(self.output['content_ids'])} pieces of content.", t)
        self.done(t, {"content_ids": self.output["content_ids"]}, used)

        if "creative" in self.disabled:
            return
        t = self.task("creative", "Generate visuals")
        used = 0
        made = 0
        for cid in self.output["content_ids"]:
            asset = db.get(ContentAsset, uuid.UUID(cid))
            if asset.format not in ("post", "carousel"):
                continue
            prompt = (asset.body or {}).get("image_prompt") or ((asset.body or {}).get("slides") or [{}])[0].get("image_prompt") or asset.title
            try:
                media = create_images(db, asset.workspace_id, prompt, brand, "portrait", 1, self.run.requested_by, str(self.run.id))
            except PaymentRequired:
                db.rollback()
                self.log("creative", f"Generated {made} visuals, then ran out of credits. Remaining posts need images.", t, "warning")
                break
            from app.services import storage

            body = dict(asset.body)
            body["media"] = [{"media_asset_id": str(m.id), "url": storage.public_url(m.storage_key), "kind": "image",
                              "mime_type": m.mime_type} for m in media]
            asset.body = body
            used += credits.cost_of(db, "image_generation")
            self.output["media_ids"] += [str(m.id) for m in media]
            made += 1
            db.commit()
        self.log("creative", f"Generated {made} visual(s)" + (" (offline placeholders: connect an image model for artwork)"
                                                               if get_ai().is_offline else "") + ".", t)
        self.done(t, {"media_ids": self.output["media_ids"]}, used)

    def social(self, plan: dict, connected: dict) -> None:
        if "social" in self.disabled or not self.output["content_ids"]:
            return
        from app.api.social import caption_from_content, request_post_approval

        db = self.db
        t = self.task("social", "Prepare the Instagram calendar")
        account = db.scalar(select(ConnectedAccount).where(ConnectedAccount.workspace_id == self.run.workspace_id,
                                                           ConnectedAccount.provider == "instagram",
                                                           ConnectedAccount.status == "connected"))
        start = date.fromisoformat(plan["start_date"])
        n = len(self.output["content_ids"])
        spacing = max(plan["duration_days"] / max(n, 1), 1)
        pending_media = 0
        fmt_map = {"post": "image", "carousel": "carousel", "reel": "reel", "story": "story"}
        for i, cid in enumerate(self.output["content_ids"]):
            asset = db.get(ContentAsset, uuid.UUID(cid))
            when = datetime.combine(start + timedelta(days=int(i * spacing)), time(13, 30), tzinfo=UTC)  # 19:00 IST
            media = (asset.body or {}).get("media", [])
            post = SocialPost(workspace_id=self.run.workspace_id, connected_account_id=account.id if account else None,
                              content_asset_id=asset.id, format=fmt_map[asset.format], caption=caption_from_content(asset),
                              media=media, scheduled_at=when, created_by=self.run.requested_by)
            db.add(post)
            db.flush()
            self.output["post_ids"].append(str(post.id))
            if account and media and asset.format in ("post", "carousel") and (asset.format != "carousel" or len(media) >= 2):
                try:
                    a = request_post_approval(db, post, when, self.run.requested_by, agent="social", group_id=self.run.id,
                                              reasoning=f"Scheduled per the {plan['duration_days']}-day plan, evenly spaced at 7 pm IST.")
                    self.output["approval_ids"].append(str(a.id))
                except AppError as exc:
                    self.log("social", f"Post {i + 1} kept as draft: {exc.message}", t, "warning")
            else:
                pending_media += 1
            db.commit()
        msg = f"Planned {n} posts between {start} and {start + timedelta(days=plan['duration_days'])}."
        if not account:
            msg += " Connect an Instagram account to send them for scheduling approval."
        elif pending_media:
            msg += f" {pending_media} need media (Reels/Stories need video, carousels need 2+ images) before they can be scheduled."
        self.log("social", msg, t)
        self.done(t, {"post_ids": self.output["post_ids"]})

    def ads(self, platform: str, plan: dict, bctx: dict) -> None:
        agent = "meta_ads" if platform == "meta" else "sem"
        if agent in self.disabled:
            return
        from app.api.ads import GenerateIn, build_ai_draft, request_launch, validate

        db = self.db
        t = self.task(agent, f"Prepare a {'Meta Ads' if platform == 'meta' else 'Google search'} campaign")
        acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == self.run.workspace_id, AdAccount.platform == platform,
                                                 AdAccount.status == "active"))
        budget = plan["daily_budget_minor"] or 50_000  # ₹500/day default proposal
        body = GenerateIn(objective="traffic" if platform == "google" else "traffic", daily_budget_minor=budget,
                          start_date=date.fromisoformat(plan["start_date"]),
                          end_date=date.fromisoformat(plan["start_date"]) + timedelta(days=plan["duration_days"]),
                          website=bctx.get("website_url") or "")
        c = build_ai_draft(db, self.run.workspace_id, platform, body, self.run.requested_by, self.run.id)
        used = self.charge("campaign_draft")
        if platform == "meta" and self.output["media_ids"]:
            cfg = dict(c.config)
            cfg["media_asset_ids"] = [self.output["media_ids"][0]]
            c.config = cfg
        db.commit()
        self.output["campaign_ids"].append(str(c.id))
        errors = validate(db, c)
        if acct is None:
            self.log(agent, f"Draft saved. Connect a {'Meta' if platform == 'meta' else 'Google Ads'} ad account to request launch.", t, "warning")
        elif errors:
            self.log(agent, "Draft saved but not ready to launch: " + "; ".join(errors), t, "warning")
        else:
            a = request_launch(db, c, True, self.run.requested_by, agent=agent, group_id=self.run.id,
                               reasoning=c.config.get("ai_reasoning"))
            self.output["approval_ids"].append(str(a.id))
            db.commit()
            self.log(agent, f"Campaign ready for approval at {budget / 100:,.0f} {c.currency}/day.", t)
        self.done(t, {"campaign_id": str(c.id), "validation_errors": errors}, used)


def run(db: Session, run_id: uuid.UUID) -> dict:
    r = db.get(AiRun, run_id)
    if r.status == "cancelled":
        return {"cancelled": True}
    r.status, r.started_at = "running", utcnow()
    db.commit()
    runner = Runner(db, r)
    try:
        output = runner.execute()
    except Exception as exc:
        db.rollback()
        r = db.get(AiRun, run_id)
        r.status, r.error, r.finished_at = "failed", str(exc)[:1000], utcnow()
        r.output = runner.output
        db.add(AiExecutionLog(workspace_id=r.workspace_id, run_id=r.id, agent="orchestrator", level="error", message=f"Run failed: {exc}"))
        db.commit()
        raise
    db.refresh(r)
    if r.status != "cancelled":
        pending = db.scalars(select(Approval).where(Approval.group_id == r.id, Approval.status == "pending")).all()
        r.status = "awaiting_approval" if pending else "completed"
    r.output, r.finished_at = output, utcnow()
    db.commit()
    return {"status": r.status, "approvals": len(output["approval_ids"])}

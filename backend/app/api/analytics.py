import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines import ads_optimizer, analytics, geo_analysis
from app.engines import reports as report_engine
from app.errors import AppError, NotFound
from app.models import AdInsight, Campaign, Client, GeoProject, GeoResult, Job, Report, Website, Workspace, WorkspaceMember
from app.permissions import Role
from app.providers.ai import get_ai
from app.services import credits, jobs, storage
from app.services.email import send_email

router = APIRouter(tags=["analytics"])


def scope(db: Session, ctx, client_ids: list[uuid.UUID] | None = None, all_clients: bool = False) -> list[uuid.UUID]:
    """Workspaces a report covers. Agencies can roll up the clients the user may see."""
    if ctx.workspace.kind != "agency" or not (client_ids or all_clients):
        return [ctx.workspace_id]
    clients = db.scalars(select(Client).where(Client.agency_workspace_id == ctx.workspace_id)).all()
    if ctx.role not in (Role.AGENCY_OWNER, Role.ADMINISTRATOR):
        assigned = {m.workspace_id for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == ctx.user.id))}
        clients = [c for c in clients if c.client_workspace_id in assigned]
    if client_ids:
        wanted = {str(c) for c in client_ids}
        clients = [c for c in clients if str(c.id) in wanted]
    return [c.client_workspace_id for c in clients] + ([ctx.workspace_id] if all_clients else [])


def _range(start: date | None, end: date | None, days: int = 30) -> tuple[date, date]:
    end = end or date.today()
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise AppError("start must be before end")
    if (end - start).days > 730:
        raise AppError("Choose a range of two years or less.")
    return start, end


@router.get("/analytics/overview")
def overview(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None, client_ids: str | None = None,
             all_clients: bool = False):
    ctx.require("analytics:read")
    start, end = _range(start, end)
    ids = scope(db, ctx, [uuid.UUID(c) for c in client_ids.split(",")] if client_ids else None, all_clients)
    ov = analytics.overview(db, ids, start, end, ctx.workspace.currency)
    return {**ov, "summary": analytics.summary_text(ov, ctx.workspace.currency), "series": analytics.series(db, ids, start, end),
            "channels": analytics.channels(db, ids, start, end), "top_campaigns": analytics.top_campaigns(db, ids, start, end),
            "top_posts": analytics.top_posts(db, ids, start, end), "workspaces": len(ids)}


@router.get("/analytics/seo")
def seo_report(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    start, end = _range(start, end)
    s = analytics.series(db, [ctx.workspace_id], start, end)
    sites = [{"domain": w.domain, "score": w.latest_score} for w in db.scalars(select(Website).where(Website.workspace_id == ctx.workspace_id))]
    return {"websites": sites, "organic": [{"date": d["date"], "clicks": d["organic_clicks"], "sessions": d["organic_sessions"]} for d in s["days"]]}


def _ads_report(db, ctx, platform, start, end):
    rows = db.scalars(select(AdInsight).where(AdInsight.workspace_id == ctx.workspace_id, AdInsight.platform == platform,
                                              AdInsight.entity_level == "campaign", AdInsight.date >= start, AdInsight.date <= end)).all()
    campaigns = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id == ctx.workspace_id))}
    return {"totals": ads_optimizer.totals(rows), "daily": ads_optimizer.daily_series(rows),
            "top_campaigns": analytics.top_campaigns(db, [ctx.workspace_id], start, end),
            "recommendations": ads_optimizer.analyze(rows, campaigns, ctx.workspace.currency),
            "sources": sorted({r.source for r in rows})}


@router.get("/analytics/sem")
def sem_report(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    return _ads_report(db, ctx, "google", *_range(start, end))


@router.get("/analytics/meta-ads")
def meta_report(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    return _ads_report(db, ctx, "meta", *_range(start, end))


@router.get("/analytics/geo")
def geo_report(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    start, end = _range(start, end)
    out = []
    for p in db.scalars(select(GeoProject).where(GeoProject.workspace_id == ctx.workspace_id)):
        rows = db.scalars(select(GeoResult).where(GeoResult.project_id == p.id, GeoResult.observed_at >= start,
                                                  GeoResult.observed_at < end + timedelta(days=1))).all()
        out.append({"project": p.name, **geo_analysis.visibility(rows, [c["name"] for c in p.competitors])})
    return {"projects": out}


@router.get("/analytics/social")
def social_report(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    start, end = _range(start, end)
    t = analytics.period_totals(db, [ctx.workspace_id], start, end)
    return {"engagement": t["engagement"], "reach": t["reach"], "posts_published": t["posts_published"],
            "top_posts": analytics.top_posts(db, [ctx.workspace_id], start, end, 10), "sources": sorted(set(t["social_sources"]))}


@router.get("/analytics/roi")
def roi(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None, all_clients: bool = False):
    ctx.require("analytics:read")
    start, end = _range(start, end)
    ids = scope(db, ctx, None, all_clients)
    ch = analytics.channels(db, ids, start, end)
    spend = sum(c["spend_minor"] or 0 for c in ch)
    revenue = sum(c["revenue_minor"] or 0 for c in ch)
    return {"spend_minor": spend, "platform_reported_revenue_minor": revenue, "roas": round(revenue / spend, 2) if spend else None,
            "channels": ch, "attribution_note": "Conversions and revenue are as reported by each ad platform (their own attribution "
            "windows). Totals can double count when a customer interacted with more than one channel."}


# ---- clients performance (agency) ------------------------------------------------------

@router.get("/analytics/clients")
def clients_performance(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:read")
    if ctx.workspace.kind != "agency":
        raise AppError("Client comparison is available in agency workspaces.")
    start, end = _range(start, end)
    out = []
    for ws_id in scope(db, ctx, None, True):
        if ws_id == ctx.workspace_id:
            continue
        ws = db.get(Workspace, ws_id)
        ov = analytics.overview(db, [ws_id], start, end, ws.currency)
        k = ov["kpis"]
        flags = []
        if k["cpa"]["change_pct"] and k["cpa"]["change_pct"] > 20:
            flags.append("CPA up more than 20%")
        if k["conversions"]["change_pct"] and k["conversions"]["change_pct"] < -20:
            flags.append("Conversions down more than 20%")
        if k["organic_traffic"]["change_pct"] and k["organic_traffic"]["change_pct"] < -15:
            flags.append("Organic traffic down more than 15%")
        shown = ("spend", "conversions", "cpa", "organic_traffic", "engagement")
        out.append({"workspace_id": str(ws_id), "name": ws.name, "kpis": {key: k[key] for key in shown},
                    "underperforming": bool(flags), "flags": flags})
    return sorted(out, key=lambda r: (not r["underperforming"], r["name"]))


# ---- AI reporting assistant ------------------------------------------------------------

class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    start: date | None = None
    end: date | None = None


def _facts(db, ctx, start, end) -> tuple[dict, list[dict]]:
    ids = scope(db, ctx, None, ctx.workspace.kind == "agency")
    ov = analytics.overview(db, ids, start, end, ctx.workspace.currency)
    facts = []
    for key, k in ov["kpis"].items():
        if k["value"] is not None:
            facts.append({"label": report_engine.LABELS.get(key, key), "value": report_engine.fmt(k["value"], k["unit"], ov["currency"]),
                          "previous": report_engine.fmt(k["previous"], k["unit"], ov["currency"]), "change_pct": k["change_pct"],
                          "kind": k["kind"], "sources": k["sources"]})
    data = {"overview": ov, "top_campaigns": analytics.top_campaigns(db, ids, start, end, "results"),
            "top_campaigns_by_spend": analytics.top_campaigns(db, ids, start, end, "spend_minor"),
            "top_posts": analytics.top_posts(db, ids, start, end), "channels": analytics.channels(db, ids, start, end)}
    if ctx.workspace.kind == "agency":
        data["clients"] = clients_performance(ctx, db, start, end)
    return data, facts


def _offline_answer(q: str, data: dict, currency: str) -> dict:
    ql = q.lower()
    k = data["overview"]["kpis"]

    def money(v):
        return f"{currency} {v / 100:,.0f}" if v is not None else "not measured"

    recs: list[str] = []
    if "cost" in ql or "cpc" in ql or "expensive" in ql or "increase" in ql and "ad" in ql:
        cpc = k["cpc"]
        ans = (f"Cost per click is {money(cpc['value'])} vs {money(cpc['previous'])} in the previous period"
               + (f" ({cpc['change_pct']:+.0f}%)." if cpc["change_pct"] is not None else "."))
        spenders = data["top_campaigns_by_spend"][:3]
        if spenders:
            ans += " Biggest spenders: " + ", ".join(f"{c['name']} ({money(c['spend_minor'])}, CPC {money(c['cpc_minor'])})" for c in spenders) + "."
        recs.append("Check the campaigns with the largest CPC increase for audience overlap or creative fatigue.")
    elif "engagement" in ql or "content" in ql or "post" in ql:
        posts = data["top_posts"]
        ans = ("Top posts by engagement: " + "; ".join(f"\"{p['caption'][:60]}\" ({p['engagement']} interactions)" for p in posts[:3]) + "."
               if posts else "No published posts with engagement data in this period.")
        if posts:
            recs.append("Create more variations in the style of the top post.")
    elif "lead" in ql or "conversion" in ql:
        camps = data["top_campaigns"]
        listed = "; ".join(f"{c['name']} ({c['results']} results, CPA {money(c['cpa_minor'])})" for c in camps[:3])
        ans = (f"Campaigns with the most tracked results: {listed}."
               if camps and camps[0]["results"] else "No campaign recorded conversions in this period.")
    elif "organic" in ql or "seo" in ql or "traffic" in ql:
        t = k["organic_traffic"]
        ans = (f"Organic traffic was {t['value']:,}" + (f" ({t['change_pct']:+.0f}% vs previous period)." if t["change_pct"] is not None else ".")
               if t["value"] is not None else "No organic traffic data: connect Search Console or Google Analytics.")
    elif "client" in ql and data.get("clients") is not None:
        under = [c for c in data["clients"] if c["underperforming"]]
        ans = ("Underperforming clients: " + "; ".join(f"{c['name']} ({', '.join(c['flags'])})" for c in under) + "."
               if under else "No client crossed the underperformance thresholds in this period.")
    elif "budget" in ql or "allocate" in ql:
        ch = [c for c in data["channels"] if c.get("cpa_minor")]
        if ch:
            best = min(ch, key=lambda c: c["cpa_minor"])
            ans = f"{best['channel'].replace('_', ' ').title()} has the lowest cost per result ({money(best['cpa_minor'])})."
            recs.append(f"Consider moving budget gradually toward {best['channel'].replace('_', ' ')}; any increase needs approval.")
        else:
            ans = "There isn't enough conversion data to compare channels yet."
    else:
        ans = " ".join(analytics.summary_text(data["overview"], currency))
    return {"answer": ans, "recommendations": [{"text": r, "kind": "recommendation"} for r in recs]}


@router.post("/analytics/ask")
def ask(body: AskIn, db: DB, ctx: WorkspaceContext = require("analytics:read")):
    credits.ensure_affordable(db, ctx.workspace_id, [("analytics_question", 1)])
    start, end = _range(body.start, body.end)
    data, facts = _facts(db, ctx, start, end)
    currency = ctx.workspace.currency
    out = get_ai().json_task(
        "analytics_answer",
        "Answer the marketer's question using ONLY the DATA provided. Quote numbers from DATA. Label anything that is a "
        "recommendation as such. If DATA does not contain the answer, say what is missing.",
        {"QUESTION": body.question, "DATA": data, "CURRENCY": currency},
        {"type": "object", "properties": {"answer": {"type": "string"},
                                          "recommendations": {"type": "array", "items": {"type": "object"}}}},
        lambda: _offline_answer(body.question, data, currency))
    credits.charge(db, ctx.workspace_id, "analytics_question", actor_id=ctx.user.id, description="Reporting assistant question")
    db.commit()
    return {"question": body.question, "answer": out.get("answer"), "facts": facts,
            "recommendations": [{**r, "kind": "recommendation"} for r in out.get("recommendations", []) if isinstance(r, dict)],
            "range": {"start": start, "end": end}, "provider": get_ai().name,
            "legend": {"measured": "reported by the platform", "calculated": "derived from measured values",
                       "internal": "MarketingOS indicator", "recommendation": "AI suggestion, not a measurement"}}


# ---- reports ---------------------------------------------------------------------------

class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: Literal["pdf", "csv"] = "pdf"
    start: date | None = None
    end: date | None = None
    client_ids: list[uuid.UUID] = []
    all_clients: bool = False
    white_label: bool = False
    schedule: Literal["once", "weekly", "monthly"] = "once"
    recipients: list[EmailStr] = []


def report_out(r: Report) -> dict:
    return {"id": str(r.id), "name": r.name, "format": r.format, "filters": r.filters, "white_label": r.white_label,
            "schedule": r.schedule, "recipients": r.recipients, "status": r.status, "error": r.error,
            "generated_at": r.generated_at, "next_run_at": r.next_run_at, "created_at": r.created_at,
            "download_path": f"/analytics/reports/{r.id}/download" if r.status == "ready" else None}


@router.post("/analytics/reports", status_code=202)
def create_report(body: ReportIn, db: DB, ctx: WorkspaceContext = require("analytics:export")):
    start, end = _range(body.start, body.end)
    r = Report(workspace_id=ctx.workspace_id, name=body.name, format=body.format, white_label=body.white_label,
               schedule=body.schedule, recipients=[str(e) for e in body.recipients], created_by=ctx.user.id,
               filters={"start": start.isoformat(), "end": end.isoformat(), "client_ids": [str(c) for c in body.client_ids],
                        "all_clients": body.all_clients, "days": (end - start).days + 1})
    db.add(r)
    db.flush()
    job = jobs.enqueue(db, "analytics.report", {"report_id": r.id}, workspace_id=ctx.workspace_id, created_by=ctx.user.id)
    db.commit()
    return {**report_out(r), "job_id": str(job.id)}


@router.get("/analytics/reports")
def list_reports(ctx: Ctx, db: DB):
    ctx.require("analytics:read")
    return [report_out(r) for r in db.scalars(select(Report).where(Report.workspace_id == ctx.workspace_id).order_by(Report.created_at.desc()))]


@router.get("/analytics/reports/{report_id}")
def get_report(report_id: str, ctx: Ctx, db: DB):
    ctx.require("analytics:read")
    return report_out(get_or_404(db, Report, report_id, ctx, "Report"))


@router.get("/analytics/reports/{report_id}/download")
def download_report(report_id: str, ctx: Ctx, db: DB):
    ctx.require("analytics:read")
    r = get_or_404(db, Report, report_id, ctx, "Report")
    if r.status != "ready" or not r.storage_key:
        raise NotFound("The report is not ready yet.")
    mime = "application/pdf" if r.format == "pdf" else "text/csv"
    return Response(storage.read_bytes(r.storage_key), media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{r.name.replace(" ", "_")}.{r.format}"'})


@router.delete("/analytics/reports/{report_id}", status_code=204)
def delete_report(report_id: str, db: DB, ctx: WorkspaceContext = require("analytics:export")):
    db.delete(get_or_404(db, Report, report_id, ctx, "Report"))
    db.commit()


@router.get("/analytics/export.csv")
def export_csv(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None):
    ctx.require("analytics:export")
    start, end = _range(start, end)
    ids = [ctx.workspace_id]
    data = report_engine.to_csv(analytics.overview(db, ids, start, end, ctx.workspace.currency), analytics.series(db, ids, start, end),
                                analytics.channels(db, ids, start, end))
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="marketingos_{start}_{end}.csv"'})


@jobs.handler("analytics.report")
def _job_report(db: Session, job: Job) -> dict:
    from app.deps import WorkspaceContext as Wc
    from app.models import User

    r = db.get(Report, uuid.UUID(job.payload["report_id"]))
    ws = db.get(Workspace, r.workspace_id)
    f = r.filters
    if r.schedule == "once":
        start, end = date.fromisoformat(f["start"]), date.fromisoformat(f["end"])
    else:
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=int(f.get("days", 30)) - 1)
    creator = db.get(User, r.created_by) if r.created_by else None
    ids = [r.workspace_id]
    if ws.kind == "agency" and creator is not None and (f.get("client_ids") or f.get("all_clients")):
        from app.deps import resolve_role
        from app.permissions import permissions_for

        role = resolve_role(db, creator, ws)
        ids = scope(db, Wc(user=creator, workspace=ws, role=role, permissions=permissions_for(role)),
                    [uuid.UUID(c) for c in f.get("client_ids", [])] or None, bool(f.get("all_clients")))
    ov = analytics.overview(db, ids, start, end, ws.currency)
    ch = analytics.channels(db, ids, start, end)
    if r.format == "csv":
        data, ext = report_engine.to_csv(ov, analytics.series(db, ids, start, end), ch), ".csv"
    else:
        rows = db.scalars(select(AdInsight).where(AdInsight.workspace_id.in_(ids), AdInsight.entity_level == "campaign",
                                                  AdInsight.date >= start, AdInsight.date <= end)).all()
        camps = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id.in_(ids)))}
        wl = None
        if r.white_label:
            org = ws.organization
            wl = {**(org.white_label or {}), "agency_name": (org.white_label or {}).get("agency_name") or org.name}
        data = report_engine.to_pdf(r.name, ws.name, ov, ch, analytics.summary_text(ov, ws.currency),
                                    ads_optimizer.analyze(rows, camps, ws.currency), wl)
        ext = ".pdf"
    r.storage_key = storage.save_bytes(data, ext, prefix=f"reports/{ws.id}")
    r.status, r.generated_at, r.error = "ready", utcnow(), None
    if r.schedule != "once":
        r.next_run_at = utcnow() + timedelta(days=7 if r.schedule == "weekly" else 30)
    for to in r.recipients:
        send_email(to, f"{r.name} is ready", f"Your report for {ws.name} ({start} to {end}) is ready in MarketingOS.")
    db.commit()
    return {"report_id": str(r.id), "bytes": len(data)}


@jobs.on_failure("analytics.report")
def _job_report_failed(db: Session, job: Job, message: str) -> None:
    r = db.get(Report, uuid.UUID(job.payload["report_id"]))
    if r is not None:
        r.status, r.error = "failed", message.split("\n")[0][:500]


def enqueue_scheduled_reports(db: Session) -> int:
    due = db.scalars(select(Report).where(Report.schedule != "once", Report.next_run_at <= utcnow())).all()
    for r in due:
        r.next_run_at = utcnow() + timedelta(days=7 if r.schedule == "weekly" else 30)
        jobs.enqueue(db, "analytics.report", {"report_id": r.id}, workspace_id=r.workspace_id)
    db.commit()
    return len(due)

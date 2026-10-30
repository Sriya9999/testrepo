import json
import uuid
from datetime import timedelta

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.deps import DB, Ctx, WorkspaceContext, require
from app.errors import AppError, NotFound, ServiceUnavailable, Unauthorized
from app.models import (
    Client,
    ConnectedAccount,
    CreditCost,
    CreditTransaction,
    GeoPrompt,
    Invoice,
    Organization,
    PaymentEvent,
    PaymentOrder,
    Plan,
    SeoAudit,
    Subscription,
    Workspace,
    WorkspaceMember,
)
from app.security import constant_time_equals, hmac_sha256_hex
from app.services import audit, credits

router = APIRouter(tags=["billing"])

CREDIT_PACKS = {"starter_pack": (500, 49_900), "growth_pack": (2000, 179_900), "pro_pack": (5000, 399_900)}


def plan_out(p: Plan) -> dict:
    return {"code": p.code, "name": p.name, "audience": p.audience, "price_minor": p.price_minor, "currency": p.currency,
            "monthly_credits": p.monthly_credits, "limits": p.limits, "credit_expiry_days": p.credit_expiry_days,
            "credit_policy": "Credits do not expire while the subscription is active." if p.credit_expiry_days is None
            else f"Monthly credits expire {p.credit_expiry_days} days after they are granted."}


@router.get("/billing/plans")
def plans(db: DB):
    return [plan_out(p) for p in db.scalars(select(Plan).where(Plan.is_public.is_(True)).order_by(Plan.price_minor.is_(None), Plan.price_minor))]


def _subscription(db: Session, org_id) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.organization_id == org_id))


def _invoice(db: Session, org_id, amount: int, description: str, payment_id: str | None) -> Invoice:
    inv = Invoice(organization_id=org_id, number=f"INV-{utcnow():%Y%m}-{uuid.uuid4().hex[:6].upper()}", amount_minor=amount,
                  description=description, provider_payment_id=payment_id, issued_at=utcnow())
    db.add(inv)
    return inv


def _billing_workspace(db: Session, org: Organization) -> Workspace:
    """Plan credits go to the organization's primary (non-client) workspace."""
    return db.scalar(select(Workspace).where(Workspace.organization_id == org.id, Workspace.kind != "client").order_by(Workspace.created_at))


def activate_plan(db: Session, org: Organization, plan: Plan, provider: str, provider_sub_id: str | None, payment_id: str | None) -> Subscription:
    sub = _subscription(db, org.id)
    now = utcnow()
    if sub is None:
        sub = Subscription(organization_id=org.id, plan_id=plan.id)
        db.add(sub)
    sub.plan_id, sub.status, sub.provider = plan.id, "active", provider
    sub.provider_subscription_id = provider_sub_id or sub.provider_subscription_id
    sub.current_period_start, sub.current_period_end = now, now + timedelta(days=30)
    ws = _billing_workspace(db, org)
    if plan.monthly_credits:
        credits.grant(db, ws.id, plan.monthly_credits, reference=payment_id, description=f"{plan.name} plan monthly credits")
    if plan.price_minor:
        _invoice(db, org.id, plan.price_minor, f"{plan.name} plan, monthly", payment_id)
    return sub


class SubscribeIn(BaseModel):
    plan_code: str


class PurchaseIn(BaseModel):
    pack: str


def _razorpay(path: str, body: dict) -> dict:
    s = get_settings()
    if not (s.razorpay_key_id and s.razorpay_key_secret):
        raise ServiceUnavailable("Payments are not configured.")
    try:
        resp = httpx.post(f"https://api.razorpay.com/v1{path}", json=body, auth=(s.razorpay_key_id, s.razorpay_key_secret), timeout=30)
    except httpx.HTTPError as exc:
        raise ServiceUnavailable(f"Payment provider unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise AppError(f"Payment provider error: {resp.text[:300]}")
    return resp.json()


@router.post("/billing/subscribe")
def subscribe(body: SubscribeIn, db: DB, ctx: WorkspaceContext = require("billing:manage")):
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    if plan is None:
        raise NotFound("Plan not found")
    if plan.price_minor is None:
        return {"status": "contact_sales", "message": "Enterprise plans are set up by our team. We'll be in touch."}
    org = ctx.workspace.organization
    mode = get_settings().payments_mode
    if mode == "test":
        sub = activate_plan(db, org, plan, "test", None, f"test_{uuid.uuid4().hex[:10]}")
        audit.record(db, "billing.subscribed", ctx=ctx, data={"plan": plan.code, "mode": "test"})
        db.commit()
        return {"status": "active", "mode": "test", "plan": plan_out(plan), "current_period_end": sub.current_period_end}
    if not plan.razorpay_plan_id:
        raise AppError("This plan is not linked to a payment plan yet.")
    rp = _razorpay("/subscriptions", {"plan_id": plan.razorpay_plan_id, "total_count": 120, "customer_notify": 1,
                                      "notes": {"organization_id": str(org.id), "plan_code": plan.code}})
    db.add(PaymentOrder(organization_id=org.id, workspace_id=ctx.workspace_id, kind="subscription", plan_code=plan.code,
                        amount_minor=plan.price_minor, provider="razorpay", provider_order_id=rp["id"], created_by=ctx.user.id))
    db.commit()
    return {"status": "pending_payment", "mode": "razorpay", "subscription_id": rp["id"], "key_id": get_settings().razorpay_key_id,
            "short_url": rp.get("short_url")}


@router.post("/billing/credits/purchase")
def purchase_credits(body: PurchaseIn, db: DB, ctx: WorkspaceContext = require("billing:manage")):
    if body.pack not in CREDIT_PACKS:
        raise AppError(f"Unknown pack. Choose one of {', '.join(CREDIT_PACKS)}.")
    amount_credits, price = CREDIT_PACKS[body.pack]
    org = ctx.workspace.organization
    if get_settings().payments_mode == "test":
        ref = f"test_{uuid.uuid4().hex[:10]}"
        credits.grant(db, ctx.workspace_id, amount_credits, "purchase", reference=ref, actor_id=ctx.user.id,
                      description=f"Purchased {amount_credits} credits (test mode)")
        _invoice(db, org.id, price, f"{amount_credits} AI credits", ref)
        audit.record(db, "billing.credits_purchased", ctx=ctx, data={"credits": amount_credits, "mode": "test"})
        db.commit()
        return {"status": "paid", "mode": "test", "balance": credits.get_wallet(db, ctx.workspace_id).balance}
    order = PaymentOrder(organization_id=org.id, workspace_id=ctx.workspace_id, kind="credits", credits=amount_credits,
                         amount_minor=price, provider="razorpay", created_by=ctx.user.id)
    db.add(order)
    db.flush()
    rp = _razorpay("/orders", {"amount": price, "currency": "INR", "receipt": str(order.id),
                               "notes": {"payment_order_id": str(order.id), "workspace_id": str(ctx.workspace_id)}})
    order.provider_order_id = rp["id"]
    db.commit()
    return {"status": "pending_payment", "mode": "razorpay", "order_id": rp["id"], "amount": price, "currency": "INR",
            "key_id": get_settings().razorpay_key_id}


@router.get("/billing/credits")
def credit_balance(ctx: Ctx, db: DB):
    ctx.require("billing:read")
    return {"balance": credits.get_wallet(db, ctx.workspace_id).balance,
            "packs": [{"code": k, "credits": v[0], "price_minor": v[1], "currency": "INR"} for k, v in CREDIT_PACKS.items()],
            "costs": costs(db)}


@router.get("/billing/costs")
def costs(db: DB):
    rows = {c.operation: c for c in db.scalars(select(CreditCost))}
    return [{"operation": op, "credits": rows[op].credits if op in rows else default, "description": rows[op].description if op in rows else desc}
            for op, (default, desc) in credits.DEFAULT_COSTS.items()]


@router.get("/billing/estimate")
def estimate(ctx: Ctx, db: DB, operation: str, quantity: int = 1):
    total = credits.estimate(db, [(operation, quantity)])
    return {"operation": operation, "quantity": quantity, "credits": total, "balance": credits.get_wallet(db, ctx.workspace_id).balance}


@router.get("/billing/usage")
def usage(ctx: Ctx, db: DB):
    ctx.require("billing:read")
    org = ctx.workspace.organization
    sub = _subscription(db, org.id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    since = utcnow() - timedelta(days=30)
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_op = db.execute(select(CreditTransaction.operation, func.sum(CreditTransaction.amount)).where(
        CreditTransaction.workspace_id == ctx.workspace_id, CreditTransaction.kind == "debit",
        CreditTransaction.created_at >= since).group_by(CreditTransaction.operation)).all()
    ws_ids = [w.id for w in db.scalars(select(Workspace).where(Workspace.organization_id == org.id))]
    return {
        "subscription": {"plan": plan_out(plan) if plan else None, "status": sub.status if sub else None,
                         "current_period_end": sub.current_period_end if sub else None, "provider": sub.provider if sub else None},
        "usage": {
            "client_workspaces": db.scalar(select(func.count()).select_from(Client).where(Client.agency_workspace_id == ctx.workspace_id)) or 0,
            "members": db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.workspace_id)) or 0,
            "seo_audits_per_month": db.scalar(select(func.count()).select_from(SeoAudit).where(SeoAudit.workspace_id == ctx.workspace_id,
                                                                                               SeoAudit.created_at >= month_start)) or 0,
            "geo_prompts": db.scalar(select(func.count()).select_from(GeoPrompt).where(GeoPrompt.workspace_id == ctx.workspace_id)) or 0,
            "social_accounts": db.scalar(select(func.count()).select_from(ConnectedAccount).where(
                ConnectedAccount.workspace_id.in_(ws_ids), ConnectedAccount.provider == "instagram",
                ConnectedAccount.status != "disconnected")) or 0,
        },
        "limits": plan.limits if plan else {},
        "credits": {"balance": credits.get_wallet(db, ctx.workspace_id).balance,
                    "used_last_30_days": -sum(int(v or 0) for _, v in by_op),
                    "by_operation": [{"operation": op or "other", "credits": -int(v or 0)} for op, v in by_op]},
    }


@router.get("/billing/transactions")
def transactions(ctx: Ctx, db: DB, limit: int = 100):
    ctx.require("billing:read")
    rows = db.scalars(select(CreditTransaction).where(CreditTransaction.workspace_id == ctx.workspace_id)
                      .order_by(CreditTransaction.created_at.desc()).limit(min(limit, 500)))
    return [{"id": str(t.id), "amount": t.amount, "balance_after": t.balance_after, "kind": t.kind, "operation": t.operation,
             "reference": t.reference, "description": t.description, "created_at": t.created_at} for t in rows]


@router.get("/billing/invoices")
def invoices(ctx: Ctx, db: DB):
    ctx.require("billing:read")
    rows = db.scalars(select(Invoice).where(Invoice.organization_id == ctx.workspace.organization_id).order_by(Invoice.issued_at.desc()))
    return [{"id": str(i.id), "number": i.number, "amount_minor": i.amount_minor, "currency": i.currency, "description": i.description,
             "status": i.status, "issued_at": i.issued_at} for i in rows]


@router.post("/billing/webhooks")
async def webhook(request: Request, db: DB):
    """Razorpay webhook. The signature is an HMAC-SHA256 of the raw body with the webhook secret."""
    secret = get_settings().razorpay_webhook_secret
    if not secret:
        raise ServiceUnavailable("Webhooks are not configured.")
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not signature or not constant_time_equals(hmac_sha256_hex(secret, raw), signature):
        raise Unauthorized("Invalid webhook signature")
    event = json.loads(raw)
    event_id = request.headers.get("x-razorpay-event-id") or event.get("id") or hmac_sha256_hex(secret, raw)
    if db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == event_id)):
        return {"ok": True, "duplicate": True}
    kind = event.get("event", "")
    payload = event.get("payload", {})
    note = None
    if kind in ("order.paid", "payment.captured"):
        payment = payload.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id") or payload.get("order", {}).get("entity", {}).get("id")
        order = db.scalar(select(PaymentOrder).where(PaymentOrder.provider_order_id == order_id)) if order_id else None
        if order is not None and order.status != "paid" and order.kind == "credits":
            if int(payment.get("amount", order.amount_minor)) < order.amount_minor:
                note = "amount mismatch"
            else:
                order.status = "paid"
                credits.grant(db, order.workspace_id, order.credits, "purchase", reference=payment.get("id"),
                              description=f"Purchased {order.credits} credits")
                _invoice(db, order.organization_id, order.amount_minor, f"{order.credits} AI credits", payment.get("id"))
        else:
            note = "no matching unpaid order"
    elif kind in ("subscription.activated", "subscription.charged"):
        sub_entity = payload.get("subscription", {}).get("entity", {})
        order = db.scalar(select(PaymentOrder).where(PaymentOrder.provider_order_id == sub_entity.get("id")))
        if order is not None:
            org = db.get(Organization, order.organization_id)
            plan = db.scalar(select(Plan).where(Plan.code == order.plan_code))
            activate_plan(db, org, plan, "razorpay", sub_entity.get("id"), payload.get("payment", {}).get("entity", {}).get("id"))
            order.status = "paid"
    elif kind in ("subscription.halted", "subscription.cancelled", "subscription.pending"):
        sub_entity = payload.get("subscription", {}).get("entity", {})
        sub = db.scalar(select(Subscription).where(Subscription.provider_subscription_id == sub_entity.get("id")))
        if sub is not None:
            sub.status = {"subscription.halted": "past_due", "subscription.pending": "past_due"}.get(kind, "cancelled")
    db.add(PaymentEvent(provider="razorpay", event_id=event_id, event_type=kind, payload=event, note=note))
    db.commit()
    return {"ok": True}

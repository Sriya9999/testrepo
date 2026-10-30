import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin


class Plan(IdMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    audience: Mapped[str] = mapped_column(String(100), default="")
    price_minor: Mapped[int | None] = mapped_column(BigInteger)  # null = custom pricing
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    monthly_credits: Mapped[int] = mapped_column(Integer, default=0)
    limits: Mapped[dict] = mapped_column(default=dict)
    credit_expiry_days: Mapped[int | None] = mapped_column(Integer)
    is_public: Mapped[bool] = mapped_column(default=True)
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(64))


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="trialing")  # trialing | active | past_due | cancelled
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(20), default="none")  # none | razorpay | test
    provider_subscription_id: Mapped[str | None] = mapped_column(String(64))


class CreditWallet(IdMixin, TimestampMixin, Base):
    """One wallet per workspace. Agency wallets can allocate credits to client wallets."""

    __tablename__ = "credit_wallets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)


class CreditTransaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "credit_transactions"

    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_wallets.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    amount: Mapped[int] = mapped_column(BigInteger)  # positive = credit, negative = debit
    balance_after: Mapped[int] = mapped_column(BigInteger)
    # grant | purchase | debit | refund | allocation_in | allocation_out | expiry | adjustment
    kind: Mapped[str] = mapped_column(String(20))
    operation: Mapped[str | None] = mapped_column(String(60))
    reference: Mapped[str | None] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditCost(IdMixin, TimestampMixin, Base):
    """Configurable price list: how many credits each AI operation costs."""

    __tablename__ = "credit_costs"

    operation: Mapped[str] = mapped_column(String(60), unique=True)
    credits: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300), default="")


class Invoice(IdMixin, TimestampMixin, Base):
    __tablename__ = "invoices"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="paid")
    provider_payment_id: Mapped[str | None] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "payment_orders"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # credits | subscription
    credits: Mapped[int | None] = mapped_column(Integer)
    plan_code: Mapped[str | None] = mapped_column(String(30))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    provider: Mapped[str] = mapped_column(String(20))
    provider_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="created")  # created | paid | failed
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PaymentEvent(IdMixin, TimestampMixin, Base):
    """Processed webhook events, for idempotency."""

    __tablename__ = "payment_events"

    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(Text)

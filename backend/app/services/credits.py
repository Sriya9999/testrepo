"""AI credit wallets.

Rules (PRD section 10): every AI operation has a configurable cost; users see the estimate
before running it; credits are charged only after the operation succeeds, in the same
transaction that stores its output; every movement is an auditable transaction.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError, PaymentRequired
from app.models import CreditCost, CreditTransaction, CreditWallet

DEFAULT_COSTS: dict[str, tuple[int, str]] = {
    "text_generation": (2, "Caption, post, ad copy or short-form text"),
    "long_form_generation": (6, "Blog article, landing page or long email"),
    "content_variation": (2, "One additional variation of a piece of content"),
    "section_regeneration": (1, "Regenerate one section of existing content"),
    "image_generation": (10, "One generated image"),
    "video_script": (3, "Reel script, hooks and storyboard"),
    "video_generation": (60, "One generated video clip through a video integration"),
    "strategy_generation": (15, "Marketing strategy and campaign plan"),
    "campaign_draft": (5, "AI-generated Meta or Google Ads campaign draft"),
    "geo_prompt_query": (1, "One AI search query on one provider"),
    "geo_prompt_discovery": (2, "Suggested GEO prompts for a brand"),
    "recommendations": (3, "AI recommendations from SEO, GEO or ads data"),
    "analytics_question": (2, "One question to the AI reporting assistant"),
    "agent_orchestration": (5, "Orchestrator planning for an agent workflow"),
}


def get_wallet(db: Session, workspace_id: uuid.UUID, *, lock: bool = False) -> CreditWallet:
    stmt = select(CreditWallet).where(CreditWallet.workspace_id == workspace_id)
    if lock:
        stmt = stmt.with_for_update()
    wallet = db.scalar(stmt)
    if wallet is None:
        wallet = CreditWallet(workspace_id=workspace_id, balance=0)
        db.add(wallet)
        db.flush()
    return wallet


def cost_of(db: Session, operation: str) -> int:
    row = db.scalar(select(CreditCost).where(CreditCost.operation == operation))
    if row is not None:
        return row.credits
    if operation in DEFAULT_COSTS:
        return DEFAULT_COSTS[operation][0]
    raise AppError(f"Unknown billable operation '{operation}'")


def estimate(db: Session, items: list[tuple[str, int]]) -> int:
    return sum(cost_of(db, op) * qty for op, qty in items)


def ensure_affordable(db: Session, workspace_id: uuid.UUID, items: list[tuple[str, int]]) -> int:
    """Pre-flight check before queueing work. Returns the estimate."""
    total = estimate(db, items)
    balance = get_wallet(db, workspace_id).balance
    if total > balance:
        raise PaymentRequired(
            f"This needs {total} credits but the workspace has {balance}.",
            details={"required": total, "balance": balance},
        )
    return total


def _post(
    db: Session,
    wallet: CreditWallet,
    amount: int,
    kind: str,
    *,
    operation: str | None = None,
    reference: str | None = None,
    description: str = "",
    actor_id: uuid.UUID | None = None,
) -> CreditTransaction:
    wallet.balance += amount
    txn = CreditTransaction(
        wallet_id=wallet.id,
        workspace_id=wallet.workspace_id,
        amount=amount,
        balance_after=wallet.balance,
        kind=kind,
        operation=operation,
        reference=reference,
        description=description,
        actor_id=actor_id,
    )
    db.add(txn)
    return txn


def charge(
    db: Session,
    workspace_id: uuid.UUID,
    operation: str,
    quantity: int = 1,
    *,
    reference: str | None = None,
    description: str = "",
    actor_id: uuid.UUID | None = None,
) -> int:
    """Debit credits for a completed operation. Raises PaymentRequired (caller rolls back)."""
    amount = cost_of(db, operation) * quantity
    if amount <= 0:
        return 0
    wallet = get_wallet(db, workspace_id, lock=True)
    if wallet.balance < amount:
        raise PaymentRequired(
            f"Not enough credits: {operation} costs {amount}, balance is {wallet.balance}.",
            details={"required": amount, "balance": wallet.balance},
        )
    _post(
        db, wallet, -amount, "debit", operation=operation, reference=reference,
        description=description or f"{operation} x{quantity}", actor_id=actor_id,
    )
    return amount


def grant(
    db: Session,
    workspace_id: uuid.UUID,
    amount: int,
    kind: str = "grant",
    *,
    reference: str | None = None,
    description: str = "",
    actor_id: uuid.UUID | None = None,
) -> CreditTransaction:
    if amount <= 0:
        raise AppError("Amount must be positive")
    wallet = get_wallet(db, workspace_id, lock=True)
    return _post(db, wallet, amount, kind, reference=reference, description=description, actor_id=actor_id)


def allocate(
    db: Session, from_workspace: uuid.UUID, to_workspace: uuid.UUID, amount: int, actor_id: uuid.UUID
) -> None:
    """Move credits from an agency wallet to one of its client wallets (or back)."""
    if amount <= 0:
        raise AppError("Amount must be positive")
    # Lock in a stable order to avoid deadlocks between concurrent transfers.
    first, second = sorted([from_workspace, to_workspace], key=str)
    wallets = {first: get_wallet(db, first, lock=True), second: get_wallet(db, second, lock=True)}
    source, target = wallets[from_workspace], wallets[to_workspace]
    if source.balance < amount:
        raise PaymentRequired(
            f"Only {source.balance} credits are available to allocate.",
            details={"required": amount, "balance": source.balance},
        )
    ref = uuid.uuid4().hex
    _post(db, source, -amount, "allocation_out", reference=ref, description="Allocated to client", actor_id=actor_id)
    _post(db, target, amount, "allocation_in", reference=ref, description="Allocated by agency", actor_id=actor_id)

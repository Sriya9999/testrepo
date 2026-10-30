import asyncio
import uuid
from datetime import timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, load_workspace_context, require, user_from_token
from app.engines import orchestrator
from app.errors import AppError, Conflict
from app.models import AiExecutionLog, AiRun, AiTask, Approval, Brand, Job
from app.providers.ai import get_ai
from app.services import audit, credits, jobs
from app.services.policy import ACTION_POLICIES, workspace_settings

router = APIRouter(tags=["agents"])


class RunIn(BaseModel):
    instruction: str = Field(min_length=5, max_length=4000)
    brand_id: uuid.UUID | None = None


class AgentPatch(BaseModel):
    enabled: bool


def _plan(db: Session, ctx, instruction: str) -> dict:
    parsed = orchestrator.parse_instruction(instruction)
    ai = get_ai()
    if not ai.is_offline:
        refined = ai.json_task(
            "plan", "Extract the deliverables from the instruction. Keep numbers the user gave; use 0/false for anything not asked.",
            {"INSTRUCTION": instruction, "DEFAULTS": parsed},
            {"type": "object", "properties": {k: {"type": ["integer", "boolean", "string", "null"]} for k in parsed}},
            lambda: parsed)
        for k, default in parsed.items():
            value = refined.get(k)
            if value is None:
                continue
            if isinstance(default, bool):
                parsed[k] = bool(value)
            elif isinstance(default, int):
                try:
                    parsed[k] = int(value)
                except (TypeError, ValueError):
                    pass
            elif isinstance(value, (str, int)):
                parsed[k] = value
        for k, cap in orchestrator.MAX.items():
            parsed[k] = min(int(parsed[k] or 0), cap)
    connected = orchestrator.connected_platforms(db, ctx.workspace_id)
    est = orchestrator.estimate_plan(db, parsed)
    return {"parsed": parsed, "steps": orchestrator.describe_plan(parsed, connected), "estimate": est, "connected": connected,
            "balance": credits.get_wallet(db, ctx.workspace_id).balance}


def run_out(db: Session, r: AiRun, detail: bool = False) -> dict:
    if r.status == "awaiting_approval":
        pending = db.scalar(select(func.count()).select_from(Approval).where(Approval.group_id == r.id, Approval.status == "pending"))
        if not pending:
            r.status = "completed"
            db.commit()
    out = {"id": str(r.id), "instruction": r.instruction, "status": r.status, "plan": r.plan, "credits_used": r.credits_used,
           "error": r.error, "started_at": r.started_at, "finished_at": r.finished_at, "created_at": r.created_at}
    if detail:
        out["output"] = r.output
        out["tasks"] = [{"id": str(t.id), "agent": t.agent, "title": t.title, "status": t.status, "credits_used": t.credits_used,
                         "output": t.output, "started_at": t.started_at, "finished_at": t.finished_at}
                        for t in db.scalars(select(AiTask).where(AiTask.run_id == r.id).order_by(AiTask.sequence))]
        out["approvals"] = [{"id": str(a.id), "title": a.title, "action_type": a.action_type, "status": a.status,
                             "budget_impact_minor": a.budget_impact_minor, "currency": a.currency}
                            for a in db.scalars(select(Approval).where(Approval.group_id == r.id).order_by(Approval.created_at))]
    return out


@router.get("/agents")
def list_agents(ctx: Ctx, db: DB):
    ctx.require("agents:read")
    connected = orchestrator.connected_platforms(db, ctx.workspace_id)
    disabled = set(workspace_settings(ctx.workspace).get("agents", {}).get("disabled", []))
    since = utcnow() - timedelta(days=30)
    usage = dict(db.execute(select(AiTask.agent, func.sum(AiTask.credits_used)).where(
        AiTask.workspace_id == ctx.workspace_id, AiTask.created_at >= since).group_by(AiTask.agent)).all())
    runs = dict(db.execute(select(AiTask.agent, func.count()).where(AiTask.workspace_id == ctx.workspace_id).group_by(AiTask.agent)).all())
    out = []
    for key, a in orchestrator.AGENTS.items():
        needs = a.get("requires")
        status = "disabled" if key in disabled else ("needs_integration" if needs and not connected.get(needs) else "ready")
        out.append({"id": key, "name": a["name"], "function": a["function"], "status": status, "requires": needs,
                    "enabled": key not in disabled, "credits_last_30_days": int(usage.get(key) or 0), "tasks_run": int(runs.get(key) or 0),
                    "actions": [{"action": act, "policy": ACTION_POLICIES.get(act, "requires_approval")} for act in a["actions"]]})
    return {"agents": out, "provider": get_ai().name}


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentPatch, db: DB, ctx: WorkspaceContext = require("workspace:manage")):
    if agent_id not in orchestrator.AGENTS or agent_id == "orchestrator":
        raise AppError("Unknown agent (the orchestrator can't be disabled).")
    settings = dict(ctx.workspace.settings or {})
    agents = dict(settings.get("agents", {}))
    disabled = set(agents.get("disabled", []))
    (disabled.discard if body.enabled else disabled.add)(agent_id)
    agents["disabled"] = sorted(disabled)
    settings["agents"] = agents
    ctx.workspace.settings = settings
    audit.record(db, "agent.toggled", ctx=ctx, data={"agent": agent_id, "enabled": body.enabled})
    db.commit()
    return {"id": agent_id, "enabled": body.enabled}


@router.post("/agents/plan")
def preview_plan(body: RunIn, db: DB, ctx: WorkspaceContext = require("agents:run")):
    """Break the instruction into a reviewable plan with a credit estimate. Runs nothing."""
    return _plan(db, ctx, body.instruction)


@router.post("/agents/run", status_code=202)
def start_run(body: RunIn, db: DB, ctx: WorkspaceContext = require("agents:run")):
    plan = _plan(db, ctx, body.instruction)
    if body.brand_id:
        get_or_404(db, Brand, body.brand_id, ctx, "Brand")
    # The workflow must at least afford planning + strategy; content stops cleanly if credits run out.
    credits.ensure_affordable(db, ctx.workspace_id, [("agent_orchestration", 1), ("strategy_generation", 1)])
    r = AiRun(workspace_id=ctx.workspace_id, instruction=body.instruction, requested_by=ctx.user.id,
              plan={**plan, "brand_id": str(body.brand_id) if body.brand_id else None})
    db.add(r)
    db.flush()
    job = jobs.enqueue(db, "agents.run", {"run_id": r.id}, workspace_id=ctx.workspace_id, created_by=ctx.user.id, max_attempts=1)
    audit.record(db, "agents.run_started", ctx=ctx, resource_type="ai_run", resource_id=r.id, data={"instruction": body.instruction[:500]})
    db.commit()
    return {**run_out(db, r), "job_id": str(job.id)}


@jobs.handler("agents.run")
def _job_run(db: Session, job: Job) -> dict:
    return orchestrator.run(db, uuid.UUID(job.payload["run_id"]))


@router.get("/agents/runs")
def list_runs(ctx: Ctx, db: DB, limit: int = 50):
    ctx.require("agents:read")
    rows = db.scalars(select(AiRun).where(AiRun.workspace_id == ctx.workspace_id).order_by(AiRun.created_at.desc()).limit(min(limit, 200)))
    return [run_out(db, r) for r in rows]


@router.get("/agents/runs/{run_id}")
def get_run(run_id: str, ctx: Ctx, db: DB):
    ctx.require("agents:read")
    return run_out(db, get_or_404(db, AiRun, run_id, ctx, "Run"), detail=True)


@router.post("/agents/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: DB, ctx: WorkspaceContext = require("agents:run")):
    r = get_or_404(db, AiRun, run_id, ctx, "Run")
    if r.status in ("completed", "failed", "cancelled"):
        raise Conflict(f"This run is already {r.status}.")
    r.status = "cancelled"
    r.finished_at = utcnow()
    for a in db.scalars(select(Approval).where(Approval.group_id == r.id, Approval.status == "pending")):
        a.status = "superseded"
    db.add(AiExecutionLog(workspace_id=r.workspace_id, run_id=r.id, agent="orchestrator", level="warning",
                          message=f"Cancelled by {ctx.user.email}. Pending approvals were withdrawn."))
    audit.record(db, "agents.run_cancelled", ctx=ctx, resource_type="ai_run", resource_id=r.id)
    db.commit()
    return run_out(db, r, detail=True)


def logs_out(rows) -> list[dict]:
    return [{"id": str(entry.id), "agent": entry.agent, "level": entry.level, "message": entry.message, "data": entry.data,
             "created_at": entry.created_at} for entry in rows]


@router.get("/agents/runs/{run_id}/logs")
def run_logs(run_id: str, ctx: Ctx, db: DB):
    ctx.require("agents:read")
    r = get_or_404(db, AiRun, run_id, ctx, "Run")
    return logs_out(db.scalars(select(AiExecutionLog).where(AiExecutionLog.run_id == r.id).order_by(AiExecutionLog.created_at)))


@router.websocket("/ws/agents/runs/{run_id}")
async def run_stream(websocket: WebSocket, run_id: str, token: str, workspace_id: str):
    """Live workflow updates: pushes new log lines and the run status until it finishes."""
    with SessionLocal() as db:
        try:
            user = user_from_token(db, token)
            ctx = load_workspace_context(db, user, workspace_id)
            ctx.require("agents:read")
            r = get_or_404(db, AiRun, run_id, ctx, "Run")
        except AppError:
            await websocket.close(code=4403)
            return
        run_uuid = r.id
    await websocket.accept()
    sent = 0
    try:
        while True:
            with SessionLocal() as db:
                r = db.get(AiRun, run_uuid)
                logs = db.scalars(select(AiExecutionLog).where(AiExecutionLog.run_id == run_uuid).order_by(AiExecutionLog.created_at)).all()
                new = logs[sent:]
                sent = len(logs)
                await websocket.send_json(jsonable_encoder({"status": r.status, "credits_used": r.credits_used, "logs": logs_out(new)}))
                if r.status in ("completed", "failed", "cancelled", "awaiting_approval"):
                    await websocket.close()
                    return
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return

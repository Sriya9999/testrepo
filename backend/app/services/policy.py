"""The AI autonomy model (PRD 5.10) and per-workspace approval/spend policies."""

import copy

AUTOMATIC = "automatic"
REQUIRES_APPROVAL = "requires_approval"

# What the AI (and agents acting for a user) may do on its own.
ACTION_POLICIES: dict[str, str] = {
    "generate_caption": AUTOMATIC,
    "generate_content": AUTOMATIC,
    "generate_image": AUTOMATIC,
    "analyze_keywords": AUTOMATIC,
    "generate_recommendations": AUTOMATIC,
    "create_campaign_draft": AUTOMATIC,
    "create_content_draft": AUTOMATIC,
    "approve_content": REQUIRES_APPROVAL,
    "schedule_post": REQUIRES_APPROVAL,
    "publish_post": REQUIRES_APPROVAL,
    "launch_campaign": REQUIRES_APPROVAL,
    "activate_campaign": REQUIRES_APPROVAL,
    "increase_budget": REQUIRES_APPROVAL,
    "modify_campaign": REQUIRES_APPROVAL,
    "pause_campaign": "configurable",  # see approvals.require_approval_for_pause
}

DEFAULT_WORKSPACE_SETTINGS: dict = {
    "approvals": {
        # Single-person businesses must be able to approve their own work.
        "allow_self_approval": True,
        "require_approval_for_pause": False,
        "require_approval_for_budget_decrease": False,
    },
    "spend_limits": {
        # Hard caps in minor units (paise). Drafts above the cap are refused.
        "meta_max_daily_budget_minor": 2_000_000,  # ₹20,000 / day
        "google_max_daily_budget_minor": 2_000_000,
    },
    "notifications": {"email_on_approval_request": True},
    "agents": {"disabled": []},
}


def workspace_settings(workspace) -> dict:
    merged = copy.deepcopy(DEFAULT_WORKSPACE_SETTINGS)
    for section, values in (workspace.settings or {}).items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def requires_approval(action: str, workspace=None) -> bool:
    policy = ACTION_POLICIES.get(action, REQUIRES_APPROVAL)  # unknown actions are gated
    if policy == "configurable":
        if action == "pause_campaign" and workspace is not None:
            return bool(workspace_settings(workspace)["approvals"]["require_approval_for_pause"])
        return True
    return policy == REQUIRES_APPROVAL


def max_daily_budget(workspace, platform: str) -> int:
    return int(workspace_settings(workspace)["spend_limits"][f"{platform}_max_daily_budget_minor"])

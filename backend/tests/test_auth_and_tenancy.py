import re

import pyotp

from app.services.email import OUTBOX
from tests.conftest import login, register


def _token_from_outbox(kind: str) -> str:
    msg = next(m for m in reversed(OUTBOX) if kind in m["text"] or kind in m["subject"].lower())
    return re.search(r"token=([\w\-]+)", msg["text"]).group(1)


def test_register_creates_workspace_wallet_and_trial(client):
    api = register(client, "a@biz.in")
    me = api.get("/users/me").json()
    assert me["email"] == "a@biz.in"
    assert me["email_verified"] is False
    assert len(me["workspaces"]) == 1 and me["workspaces"][0]["role"] == "agency_owner"
    ws = api.get(f"/workspaces/{api.workspace_id}").json()
    assert ws["credit_balance"] == 100
    assert ws["plan"]["code"] == "starter"
    assert "content:write" in ws["permissions"]


def test_duplicate_and_weak_passwords_rejected(client):
    register(client, "dup@biz.in")
    r = client.post("/api/v1/auth/register", json={"email": "dup@biz.in", "password": "Str0ngPassword!", "full_name": "x",
                                                    "account_type": "business", "organization_name": "x"})
    assert r.status_code == 409
    r = client.post("/api/v1/auth/register", json={"email": "weak@biz.in", "password": "alllowercase", "full_name": "x",
                                                    "account_type": "business", "organization_name": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "weak_password"


def test_login_refresh_rotation_and_reuse_detection(client):
    register(client, "r@biz.in")
    assert client.post("/api/v1/auth/login", json={"email": "r@biz.in", "password": "wrong-Passw0rd"}).status_code == 401
    api = login(client, "r@biz.in")
    first = api.session["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.json()["refresh_token"]
    # Reusing the rotated token is treated as theft: every session is revoked.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_email_verification_and_password_reset(client):
    api = register(client, "v@biz.in")
    token = _token_from_outbox("verify")
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert api.get("/users/me").json()["email_verified"] is True
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400  # single use

    assert client.post("/api/v1/auth/forgot-password", json={"email": "nobody@biz.in"}).status_code == 200
    assert client.post("/api/v1/auth/forgot-password", json={"email": "v@biz.in"}).status_code == 200
    token = _token_from_outbox("reset")
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": "N3wPassword!!"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "v@biz.in", "password": "N3wPassword!!"}).status_code == 200


def test_mfa_challenge(client):
    api = register(client, "m@biz.in")
    secret = api.post("/users/me/mfa/setup").json()["secret"]
    assert api.post("/users/me/mfa/enable", {"code": "000000"}).status_code == 400
    assert api.post("/users/me/mfa/enable", {"code": pyotp.TOTP(secret).now()}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": "m@biz.in", "password": "Str0ngPassword!"}).json()
    assert r["mfa_required"] and "access_token" not in r
    bad = client.post("/api/v1/auth/login/mfa", json={"mfa_token": r["mfa_token"], "code": "123456"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/login/mfa", json={"mfa_token": r["mfa_token"], "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_requests_need_a_valid_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/users/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_tenant_isolation_between_businesses(client, owner):
    other = register(client, "other@rival.in", org="Rival")
    brand_id = owner.get("/brands").json()[0]["id"]
    # Another tenant cannot select the workspace...
    assert other.in_workspace(owner.workspace_id).get("/brands").status_code == 404
    assert other.get(f"/workspaces/{owner.workspace_id}").status_code == 404
    # ...nor read a record by id through its own workspace.
    assert other.get(f"/brands/{brand_id}").status_code == 404
    assert other.get("/brands").json() == []
    r = owner.post("/content/generate", {"platform": "instagram", "format": "post", "topic": "weekend"})
    cid = r.json()["content_id"]
    assert other.get(f"/content/{cid}").status_code == 404
    assert other.patch(f"/content/{cid}", {"title": "hijack"}).status_code == 404


def test_agency_client_isolation_and_roles(client):
    agency = register(client, "boss@agency.in", "agency", "Pixel Agency")
    c1 = agency.post("/agency/clients", {"name": "Cafe One", "industry": "cafe"}).json()
    c2 = agency.post("/agency/clients", {"name": "Gym Two", "industry": "fitness"}).json()
    assert len(agency.get("/agency/clients").json()) == 2

    # An account manager is assigned to one client only.
    register(client, "am@agency.in", org="x")
    assert agency.post(f"/workspaces/{agency.workspace_id}/members", {"email": "am@agency.in", "role": "account_manager"}).status_code == 201
    agency.patch(f"/agency/clients/{c1['id']}", {"account_manager_id": login(client, "am@agency.in").user["id"]})
    am = login(client, "am@agency.in")
    visible = am.get("/users/me").json()["workspaces"]
    ids = {w["id"] for w in visible}
    assert c1["workspace_id"] in ids and c2["workspace_id"] not in ids
    assert am.in_workspace(c2["workspace_id"]).get("/brands").status_code == 404
    assert [c["name"] for c in am.get("/agency/clients").json()] == ["Cafe One"]

    # A client approver can review but not run campaigns or manage members.
    client_ws = agency.in_workspace(c1["workspace_id"])
    assert client_ws.post(f"/workspaces/{c1['workspace_id']}/members", {"email": "approver@cafe.in", "role": "client_approver"}).json()["status"] == "invited"
    approver = register(client, "approver@cafe.in", org="Cafe One staff").in_workspace(c1["workspace_id"])
    assert approver.get("/brands").status_code == 200
    assert approver.post("/ads/meta/campaigns/drafts", {"name": "x"}).status_code == 403
    assert approver.post(f"/workspaces/{c1['workspace_id']}/members", {"email": "z@z.in", "role": "viewer"}).status_code == 403
    # Nobody can grant a role above their own.
    assert am.in_workspace(c1["workspace_id"]).post(f"/workspaces/{c1['workspace_id']}/members",
                                                    {"email": "y@y.in", "role": "administrator"}).status_code == 403


def test_credits_allocation_from_agency_to_client(client):
    agency = register(client, "alloc@agency.in", "agency", "Alloc Agency")
    c = agency.post("/agency/clients", {"name": "Bakery"}).json()
    r = agency.post(f"/agency/clients/{c['id']}/credits", {"amount": 40})
    assert r.json() == {"agency_balance": 60, "client_balance": 40}
    assert agency.post(f"/agency/clients/{c['id']}/credits", {"amount": 1000}).status_code == 402
    txns = agency.get("/billing/transactions").json()
    assert txns[0]["kind"] == "allocation_out" and txns[0]["amount"] == -40


def test_audit_log_records_sensitive_actions(client, owner):
    owner.post(f"/workspaces/{owner.workspace_id}/members", {"email": "new@biz.in", "role": "viewer"})
    actions = [e["action"] for e in owner.get("/audit-logs").json()]
    assert "member.added" in actions and "brand.created" in actions

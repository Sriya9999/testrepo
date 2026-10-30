import uuid
from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.db import SessionLocal
from app.models import ConnectedAccount, SocialPost
from app.providers import ai as ai_module
from app.services import integrations
from tests.conftest import JPEG, run_jobs


def _generate(api, **extra):
    body = {"platform": "instagram", "format": "post", "topic": "weekend thali", "keywords": ["coastal food"], **extra}
    r = api.post("/content/generate", body)
    assert r.status_code == 202, r.text
    run_jobs()
    return api.get(f"/content/{r.json()['content_id']}").json()


def test_generation_uses_brand_and_charges_after_success(owner):
    content = _generate(owner, variations=3)
    assert content["generation_status"] == "ready"
    assert "Spice Garden" in content["body"]["caption"]
    assert content["body"]["cta"] == "Book a table"  # approved CTA from brand memory
    assert len(content["versions"]) == 3
    # 2 credits for the post + 2 x 2 for the extra variations
    assert owner.get("/billing/credits").json()["balance"] == 100 - 6


def test_failed_generation_is_not_charged(owner, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ai_module.OfflineProvider, "write_content", boom)
    r = owner.post("/content/generate", {"platform": "instagram", "format": "post", "topic": "x"})
    run_jobs()
    content = owner.get(f"/content/{r.json()['content_id']}").json()
    assert content["generation_status"] == "failed"
    assert owner.get("/billing/credits").json()["balance"] == 100


def test_insufficient_credits_are_refused_up_front(owner):
    from app.services import credits

    with SessionLocal() as db:
        credits.charge(db, uuid.UUID(owner.workspace_id), "text_generation", 46)  # 92 credits, 8 left
        db.commit()
    r = owner.post("/content/images/generate", {"prompt": "thali on a banana leaf"})
    assert r.status_code == 402 and r.json()["error"]["details"]["required"] == 10


def test_versions_edit_regenerate_and_approval(owner):
    c = _generate(owner)
    cid = c["id"]
    edited = owner.patch(f"/content/{cid}", {"body": {**c["body"], "caption": "Hand-written caption"}}).json()
    assert edited["current_version"] == 2 and edited["versions"][-1]["source"] == "user"
    regen = owner.post(f"/content/{cid}/regenerate", {"section": "hashtags"}).json()
    assert regen["current_version"] == 3
    assert owner.post(f"/content/{cid}/regenerate", {"section": "nonsense"}).status_code == 400
    back = owner.post(f"/content/{cid}/versions/1/select").json()
    assert back["body"] == c["body"]

    sub = owner.post(f"/content/{cid}/submit").json()
    assert owner.get(f"/content/{cid}").json()["status"] == "in_review"
    assert owner.post(f"/approvals/{sub['approval_id']}/approve", {}).json()["status"] == "executed"
    assert owner.get(f"/content/{cid}").json()["status"] == "approved"
    # Editing approved content sends it back to draft.
    owner.patch(f"/content/{cid}", {"body": {**c["body"], "caption": "changed"}})
    assert owner.get(f"/content/{cid}").json()["status"] == "draft"


def test_prohibited_claims_block_approval(owner):
    c = _generate(owner)
    body = {**c["body"], "caption": "The best in the world thali!"}
    out = owner.patch(f"/content/{c['id']}", {"body": body}).json()
    assert out["quality"]["ok"] is False
    assert owner.post(f"/content/{c['id']}/submit").status_code == 400


def test_stale_approval_is_refused(owner):
    c = _generate(owner)
    approval_id = owner.post(f"/content/{c['id']}/submit").json()["approval_id"]
    # Content changes after the request (directly in the DB, bypassing the API's invalidation).
    from app.models import ContentAsset

    with SessionLocal() as db:
        asset = db.get(ContentAsset, uuid.UUID(c["id"]))
        asset.body = {**asset.body, "caption": "sneaky change"}
        db.commit()
    r = owner.post(f"/approvals/{approval_id}/approve", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_stale"


def test_export_formats(owner):
    c = _generate(owner, platform="blog", format="article", keywords=["thali in pune"])
    md = owner.post(f"/content/{c['id']}/export?format=md")
    assert md.status_code == 200 and md.text.startswith("# ")
    assert owner.post(f"/content/{c['id']}/export?format=json").json()["title"]


def _sandbox_instagram(api, **details):
    acct = api.post("/integrations/instagram/connect", {"mode": "sandbox"}).json()["accounts"][0]
    if details:
        with SessionLocal() as db:
            a = db.get(ConnectedAccount, uuid.UUID(acct["id"]))
            a.details = {**a.details, **details}
            db.commit()
    return acct


def test_instagram_schedule_requires_approval_then_publishes(owner):
    acct = _sandbox_instagram(owner)
    media = owner.upload()
    post = owner.post("/social/posts", {"connected_account_id": acct["id"], "caption": "Weekend thali is back",
                                        "media_asset_ids": [media["id"]]}).json()
    # Publishing an unapproved post only creates an approval request.
    r = owner.post(f"/social/posts/{post['id']}/publish").json()
    assert r["requires_approval"] and r["status"] == "in_review"
    run_jobs()
    assert owner.get(f"/social/posts/{post['id']}").json()["status"] == "in_review"

    when = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    sub = owner.post(f"/social/posts/{post['id']}/schedule", {"scheduled_at": when}).json()
    approvals = owner.get("/approvals").json()
    assert [a["id"] for a in approvals] == [sub["approval_id"]]  # the earlier publish-now request was superseded
    owner.post(f"/approvals/{sub['approval_id']}/approve", {})
    assert owner.get(f"/social/posts/{post['id']}").json()["status"] == "scheduled"

    # Time passes: the scheduler picks the post up and the worker publishes it.
    with SessionLocal() as db:
        db.get(SocialPost, uuid.UUID(post["id"])).scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        from app.api.social import enqueue_due_posts

        assert enqueue_due_posts(db) == 1
    run_jobs()
    status = owner.get(f"/social/posts/{post['id']}/status").json()
    assert status["status"] == "published" and status["external_id"].startswith("sandbox_")
    assert any(e["event"] == "sandbox_publish" for e in status["publish_log"])


def test_scheduling_validation(owner):
    acct = _sandbox_instagram(owner)
    post = owner.post("/social/posts", {"connected_account_id": acct["id"], "caption": "no media"}).json()
    assert owner.post(f"/social/posts/{post['id']}/submit", {}).status_code == 400
    media = owner.upload()
    owner.patch(f"/social/posts/{post['id']}", {"media_asset_ids": [media["id"]]})
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert owner.post(f"/social/posts/{post['id']}/schedule", {"scheduled_at": past}).status_code == 400


def test_editing_approved_post_requires_reapproval_and_cancel(owner):
    acct = _sandbox_instagram(owner)
    media = owner.upload()
    post = owner.post("/social/posts", {"connected_account_id": acct["id"], "caption": "v1", "media_asset_ids": [media["id"]]}).json()
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    a = owner.post(f"/social/posts/{post['id']}/schedule", {"scheduled_at": when}).json()["approval_id"]
    owner.post(f"/approvals/{a}/approve", {})
    assert owner.patch(f"/social/posts/{post['id']}", {"caption": "v2"}).json()["status"] == "draft"
    a2 = owner.post(f"/social/posts/{post['id']}/schedule", {"scheduled_at": when}).json()["approval_id"]
    assert owner.post(f"/social/posts/{post['id']}/cancel").json()["status"] == "cancelled"
    assert owner.get(f"/approvals/{a2}").json()["status"] == "superseded"


def test_temporary_failures_are_retried(owner):
    acct = _sandbox_instagram(owner, simulate_failures=1)
    media = owner.upload()
    post = owner.post("/social/posts", {"connected_account_id": acct["id"], "caption": "retry me", "media_asset_ids": [media["id"]]}).json()
    a = owner.post(f"/social/posts/{post['id']}/publish").json()["approval_id"]
    owner.post(f"/approvals/{a}/approve", {})
    run_jobs()
    status = owner.get(f"/social/posts/{post['id']}/status").json()
    assert status["status"] == "published" and status["attempts"] == 2
    assert owner.get(f"/approvals/{a}").json()["status"] == "executed"


def test_live_instagram_publishing_flow(owner):
    """The real Graph API sequence: create container, poll status, publish, read permalink."""
    with SessionLocal() as db:
        acct = ConnectedAccount(workspace_id=uuid.UUID(owner.workspace_id), provider="instagram", external_id="17841400000000001",
                                display_name="@spicegarden", mode="live", details={"ig_user_id": "17841400000000001"})
        db.add(acct)
        db.flush()
        integrations.store_token(db, acct, "EAAtoken", None, 5_000_000)
        db.commit()
        acct_id = str(acct.id)
    png = owner.upload()
    post = owner.post("/social/posts", {"connected_account_id": acct_id, "caption": "Live!", "media_asset_ids": [png["id"]]}).json()
    assert owner.post(f"/social/posts/{post['id']}/publish").status_code == 400  # live accounts need JPEG
    jpg = owner.upload(JPEG, "image/jpeg", "photo.jpg")
    owner.patch(f"/social/posts/{post['id']}", {"media_asset_ids": [jpg["id"]]})
    a = owner.post(f"/social/posts/{post['id']}/publish").json()["approval_id"]
    base = "https://graph.facebook.com/v21.0"
    with respx.mock(assert_all_called=True) as mock:
        create = mock.post(f"{base}/17841400000000001/media").mock(return_value=httpx.Response(200, json={"id": "C1"}))
        mock.get(f"{base}/C1").mock(return_value=httpx.Response(200, json={"status_code": "FINISHED"}))
        mock.post(f"{base}/17841400000000001/media_publish").mock(return_value=httpx.Response(200, json={"id": "M1"}))
        mock.get(f"{base}/M1").mock(return_value=httpx.Response(200, json={"id": "M1", "permalink": "https://instagram.com/p/x"}))
        owner.post(f"/approvals/{a}/approve", {})
        run_jobs()
        sent = dict(httpx.QueryParams(create.calls[0].request.content.decode()))
        assert sent["caption"] == "Live!" and sent["image_url"].endswith(".jpg")
        assert "access_token=EAAtoken" in str(create.calls[0].request.url)
    status = owner.get(f"/social/posts/{post['id']}/status").json()
    assert status["status"] == "published" and status["permalink"] == "https://instagram.com/p/x"


def test_tokens_are_never_returned(owner):
    with SessionLocal() as db:
        acct = ConnectedAccount(workspace_id=uuid.UUID(owner.workspace_id), provider="meta", external_id="99",
                                display_name="Meta", mode="live", details={})
        db.add(acct)
        db.flush()
        integrations.store_token(db, acct, "EAAsupersecret", "refresh-secret", 3600)
        db.commit()
    for path in ("/integrations", "/integrations/accounts", "/integrations/health"):
        body = owner.get(path).text
        assert "EAAsupersecret" not in body and "refresh-secret" not in body

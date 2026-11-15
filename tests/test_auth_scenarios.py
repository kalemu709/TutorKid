"""Integration tests for authentication-and-user-state design scenarios."""

from __future__ import annotations

import uuid


def test_config_reports_dev_mode(api):
    response = api.get("/api/auth/config")
    assert response.status_code == 200
    assert response.json()["dev_mode"] is True


def test_anonymous_me(api):
    response = api.me()
    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_csrf_required_for_session(api):
    api.session.headers.pop("X-Requested-With", None)
    response = api.post(
        "/api/auth/session",
        json={"id_token": api.token("a@example.com"), "role": "kid"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf"


def test_signup_requires_role(api):
    response = api.create_session("kid@example.com")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "role_required"
    assert body["email"] == "kid@example.com"
    assert body["unclaimed_kid"] is None


def test_kid_free_email_signup_and_login(api):
    uid = f"kid-{uuid.uuid4()}"
    first = api.create_session("kid@example.com", role="kid", name="Kid One", uid=uid)
    assert first.status_code == 200
    body = first.json()
    assert body["authenticated"] is True
    assert body["user"]["role"] == "kid"
    assert body["account"]["owner_user_id"] == body["user"]["user_id"]
    assert "tk_session" in api.session.cookies
    assert api.me().json()["user"]["email"] == "kid@example.com"

    api.logout()
    assert api.me().json()["authenticated"] is False

    logged_in = api.create_session("kid@example.com", uid=uid)
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["role"] == "kid"
    assert logged_in.json()["account"] is not None


def test_parent_free_email_signup_needs_kid_selection(api):
    response = api.create_session("parent@example.com", role="parent", name="Parent")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "parent"
    assert body["account"] is None
    assert body["kids"] == []


def test_parent_adds_new_kid_and_selects(api):
    parent = api.create_session("parent@example.com", role="parent", name="Parent")
    assert parent.status_code == 200

    added = api.add_kid("Alex", "alex@example.com")
    assert added.status_code == 200
    assert added.json()["status"] == "created"
    account_id = added.json()["account"]["account_id"]

    me = api.me().json()
    assert me["account"]["account_id"] == account_id
    kids = api.kids().json()["kids"]
    assert len(kids) == 1
    assert kids[0]["selectable"] is True
    assert kids[0]["kid_email"] == "alex@example.com"


def test_parent_cannot_add_parent_email(api):
    from tests.conftest import ApiClient

    api.create_session("parent@example.com", role="parent")
    other_api = ApiClient(api.base_url, api.identity)
    assert other_api.create_session("other@example.com", role="parent").status_code == 200

    refused = api.add_kid("Nope", "other@example.com")
    assert refused.status_code == 409
    assert refused.json()["code"] == "email_is_parent"


def test_second_parent_needs_approval(api):
    from tests.conftest import ApiClient

    parent1 = api
    assert parent1.create_session("p1@example.com", role="parent", name="P1").status_code == 200
    created = parent1.add_kid("Alex", "alex@example.com")
    assert created.json()["status"] == "created"
    account_id = created.json()["account"]["account_id"]

    parent2 = ApiClient(api.base_url, api.identity)
    assert parent2.create_session("p2@example.com", role="parent", name="P2").status_code == 200
    pending = parent2.add_kid("Alex", "alex@example.com")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_approval"
    request_id = pending.json()["request"]["request_id"]

    kids2 = parent2.kids().json()["kids"]
    assert any(item["status"] == "waiting_for_approval" for item in kids2)
    select = parent2.select_kid(account_id)
    assert select.status_code == 403

    # Parent1 still on the account; approve the request.
    assert parent1.select_kid(account_id).status_code == 200
    requests = parent1.guardian_requests().json()["requests"]
    assert len(requests) == 1
    assert requests[0]["requester_email"] == "p2@example.com"

    decided = parent1.decide(request_id, True)
    assert decided.status_code == 200
    assert decided.json()["request"]["approved"] is True

    assert parent2.select_kid(account_id).status_code == 200
    assert parent2.me().json()["account"]["account_id"] == account_id


def test_decline_guardian_request(api):
    from tests.conftest import ApiClient

    parent1 = api
    parent1.create_session("p1@example.com", role="parent")
    account_id = parent1.add_kid("Alex", "alex@example.com").json()["account"]["account_id"]

    parent2 = ApiClient(api.base_url, api.identity)
    parent2.create_session("p2@example.com", role="parent")
    request_id = parent2.add_kid("Alex", "alex@example.com").json()["request"]["request_id"]

    parent1.select_kid(account_id)
    parent1.decide(request_id, False)

    kids2 = parent2.kids().json()["kids"]
    assert any(item["status"] == "declined" for item in kids2)
    assert parent2.select_kid(account_id).status_code == 403


def test_kid_accepts_parent_created_account(api):
    from tests.conftest import ApiClient

    parent = api
    parent.create_session("parent@example.com", role="parent", name="Parent")
    created = parent.add_kid("Alex", "alex@example.com").json()
    account_id = created["account"]["account_id"]
    kid_user_id = created["kid"]["user_id"]

    kid = ApiClient(api.base_url, api.identity)
    preview = kid.create_session("alex@example.com", role="kid", name="Alex Real")
    assert preview.status_code == 409
    assert preview.json()["code"] == "claim_required"
    assert preview.json()["unclaimed_kid"]["guardians"][0]["email"] == "parent@example.com"

    accepted = kid.create_session(
        "alex@example.com",
        role="kid",
        decision="accept",
        name="Alex Real",
        uid="alex-uid",
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["user"]["user_id"] == kid_user_id
    assert body["account"]["account_id"] == account_id
    assert body["user"]["firebase_uid"] == "alex-uid"


def test_kid_declines_parent_created_account_creates_new(api):
    from tests.conftest import ApiClient

    parent = api
    parent.create_session("parent@example.com", role="parent")
    created = parent.add_kid("Alex", "alex@example.com").json()
    ghost_user_id = created["kid"]["user_id"]
    ghost_account_id = created["account"]["account_id"]

    kid = ApiClient(api.base_url, api.identity)
    declined = kid.create_session(
        "alex@example.com",
        role="kid",
        decision="decline",
        name="Alex Real",
        uid="alex-uid",
    )
    assert declined.status_code == 200
    body = declined.json()
    assert body["user"]["user_id"] != ghost_user_id
    assert body["account"]["account_id"] != ghost_account_id
    assert body["account"]["guardian_user_ids"] == []

    # Parent still has the ghost account selectable.
    kids = parent.kids().json()["kids"]
    ghost = next(item for item in kids if item["account_id"] == ghost_account_id)
    assert ghost["selectable"] is True
    assert ghost["status"] == "declined_by_kid"
    assert ghost["ghost"] is True


def test_parent_signup_releases_unclaimed_kid_email(api):
    from tests.conftest import ApiClient

    parent = api
    parent.create_session("parent@example.com", role="parent")
    created = parent.add_kid("Alex", "alex@example.com").json()
    ghost_account_id = created["account"]["account_id"]

    claiming_parent = ApiClient(api.base_url, api.identity)
    response = claiming_parent.create_session("alex@example.com", role="parent", name="Alex Adult")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "parent"
    assert response.json()["account"] is None

    kids = parent.kids().json()["kids"]
    ghost = next(item for item in kids if item["account_id"] == ghost_account_id)
    assert ghost["kid_email"] is None
    assert ghost["selectable"] is True


def test_email_conflict_for_signed_in_user(api):
    from tests.conftest import ApiClient

    api.create_session("taken@example.com", role="kid", uid="kid-1")
    other = ApiClient(api.base_url, api.identity)
    conflict = other.create_session("taken@example.com", role="parent", uid="parent-1")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "email_taken"


def test_requester_cannot_decide_own_request(api):
    from tests.conftest import ApiClient

    parent1 = api
    parent1.create_session("p1@example.com", role="parent")
    # Create kid who signs up alone, then parent2 requests; kid decides.
    kid = ApiClient(api.base_url, api.identity)
    kid_body = kid.create_session("kid@example.com", role="kid", uid="kid-alone").json()
    account_id = kid_body["account"]["account_id"]

    parent2 = ApiClient(api.base_url, api.identity)
    parent2.create_session("p2@example.com", role="parent")
    request_id = parent2.add_kid("Kid", "kid@example.com").json()["request"]["request_id"]

    # Parent2 somehow on no account; cannot decide.
    denied = parent2.decide(request_id, True)
    assert denied.status_code in {403, 404, 400}

    # Kid can approve.
    assert kid.decide(request_id, True).status_code == 200
    assert parent2.select_kid(account_id).status_code == 200


def test_logout_revokes_session(api):
    api.create_session("kid@example.com", role="kid")
    assert api.me().json()["authenticated"] is True
    assert api.logout().status_code == 200
    assert api.me().json()["authenticated"] is False


def test_parent_relogin_clears_selected_account(api):
    uid = f"parent-{uuid.uuid4()}"
    api.create_session("parent@example.com", role="parent", uid=uid)
    account_id = api.add_kid("Alex", "alex@example.com").json()["account"]["account_id"]
    assert api.me().json()["account"]["account_id"] == account_id
    api.logout()

    again = api.create_session("parent@example.com", uid=uid)
    assert again.status_code == 200
    assert again.json()["account"] is None

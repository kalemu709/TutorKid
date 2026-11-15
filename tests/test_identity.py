"""Unit tests for FirebaseIdentityVerifier: only verified emails are accepted."""

from __future__ import annotations

import pytest

from auth.identity import FirebaseIdentityVerifier, IdentityError


class _FakeFirebaseAuth:
    def __init__(self, claims):
        self.claims = claims

    def verify_id_token(self, id_token, app=None):
        return self.claims


def _verifier(claims) -> FirebaseIdentityVerifier:
    verifier = FirebaseIdentityVerifier.__new__(FirebaseIdentityVerifier)
    verifier._auth = _FakeFirebaseAuth(claims)
    verifier._app = None
    return verifier


def _claims(provider: str, verified):
    claims = {
        "uid": "uid-1",
        "email": "Kid@Example.com",
        "name": "Kid",
        "firebase": {"sign_in_provider": provider},
    }
    if verified is not None:
        claims["email_verified"] = verified
    return claims


@pytest.mark.parametrize("provider", ["password", "google.com"])
@pytest.mark.parametrize("verified", [False, None])
def test_unverified_email_is_rejected(provider, verified):
    with pytest.raises(IdentityError, match="not verified"):
        _verifier(_claims(provider, verified)).verify("token")


@pytest.mark.parametrize("provider", ["password", "google.com"])
def test_verified_email_is_accepted(provider):
    identity = _verifier(_claims(provider, True)).verify("token")
    assert identity.uid == "uid-1"
    assert identity.email == "kid@example.com"
    assert identity.name == "Kid"

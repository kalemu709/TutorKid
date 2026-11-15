"""Firebase (or local-dev) identity verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    uid: str
    email: str
    name: str


class IdentityVerifier(Protocol):
    def verify(self, id_token: str) -> Identity: ...


class DevIdentityVerifier:
    """Accepts HMAC-signed local tokens when AUTH_DEV_MODE=1.

    Token format: ``dev.<payload_b64url>.<sig_b64url>``
    payload JSON: ``{"uid","email","name"}``
    """

    PREFIX = "dev."

    def __init__(self, secret: str):
        if not secret:
            raise IdentityError("AUTH_DEV_SECRET is required when AUTH_DEV_MODE=1.")
        self.secret = secret.encode("utf-8")

    def sign(self, uid: str, email: str, name: str = "") -> str:
        payload = {
            "uid": uid,
            "email": email.strip().lower(),
            "name": (name or "").strip() or email.split("@")[0],
        }
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        sig = base64.urlsafe_b64encode(
            hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        return f"{self.PREFIX}{body}.{sig}"

    def verify(self, id_token: str) -> Identity:
        if not isinstance(id_token, str) or not id_token.startswith(self.PREFIX):
            raise IdentityError("Invalid development identity token.")
        try:
            body, sig = id_token[len(self.PREFIX) :].split(".", 1)
        except ValueError as exc:
            raise IdentityError("Invalid development identity token.") from exc
        expected = base64.urlsafe_b64encode(
            hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        if not hmac.compare_digest(sig, expected):
            raise IdentityError("Invalid development identity token signature.")
        pad = "=" * (-len(body) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
        except Exception as exc:
            raise IdentityError("Invalid development identity token payload.") from exc
        uid = str(payload.get("uid") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        name = str(payload.get("name") or "").strip() or (email.split("@")[0] if email else "")
        if not uid or not email or "@" not in email:
            raise IdentityError("Development identity must include uid and email.")
        return Identity(uid=uid, email=email, name=name)


class FirebaseIdentityVerifier:
    def __init__(self, app):
        self._auth = __import__("firebase_admin.auth", fromlist=["auth"])
        self._app = app

    def verify(self, id_token: str) -> Identity:
        if not isinstance(id_token, str) or not id_token.strip():
            raise IdentityError("Missing identity token.")
        try:
            decoded = self._auth.verify_id_token(id_token, app=self._app)
        except Exception as exc:
            raise IdentityError("Could not verify the sign-in token.") from exc
        uid = str(decoded.get("uid") or "").strip()
        email = str(decoded.get("email") or "").strip().lower()
        name = str(decoded.get("name") or "").strip()
        if not uid or not email:
            raise IdentityError("Sign-in did not provide a verified email.")
        # Account matching (claiming a parent-created kid, releasing an email)
        # trusts the email, so it must be proven for every provider. Google
        # accounts arrive verified; email/password needs the verification link.
        if decoded.get("email_verified") is not True:
            raise IdentityError("Email is not verified yet. Open the verification link we sent, then sign in.")
        if not name:
            name = email.split("@")[0]
        return Identity(uid=uid, email=email, name=name)


def create_identity_verifier() -> IdentityVerifier:
    if os.environ.get("AUTH_DEV_MODE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        return DevIdentityVerifier(os.environ.get("AUTH_DEV_SECRET", "").strip())

    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        app = firebase_admin.get_app()
    else:
        creds_file = os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
        creds_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
        if creds_file:
            path = Path(creds_file)
            if not path.is_absolute():
                path = Path(__file__).resolve().parent.parent / path
            if not path.is_file():
                raise IdentityError(f"FIREBASE_CREDENTIALS_FILE not found: {path}")
            cred = credentials.Certificate(str(path))
        elif creds_json:
            cred = credentials.Certificate(json.loads(creds_json))
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
            cred = credentials.ApplicationDefault()
        else:
            raise IdentityError(
                "Configure FIREBASE_CREDENTIALS_FILE or FIREBASE_CREDENTIALS_JSON, "
                "or set AUTH_DEV_MODE=1 for local development."
            )
        options = {}
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
        if project_id:
            options["projectId"] = project_id
        app = firebase_admin.initialize_app(cred, options or None)
    return FirebaseIdentityVerifier(app)


def public_auth_config() -> dict:
    """Browser-safe Firebase web config and whether local-dev sign-in is available."""
    dev_mode = os.environ.get("AUTH_DEV_MODE", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }
    return {
        "dev_mode": dev_mode,
        "firebase": {
            "apiKey": os.environ.get("FIREBASE_WEB_API_KEY", "").strip() or None,
            "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", "").strip() or None,
            "projectId": os.environ.get("FIREBASE_PROJECT_ID", "").strip() or None,
            "appId": os.environ.get("FIREBASE_WEB_APP_ID", "").strip() or None,
        },
    }

"""HTTP helpers for authentication endpoints."""

from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from .identity import (
    DevIdentityVerifier,
    IdentityError,
    create_identity_verifier,
    public_auth_config,
)
from .service import CSRF_HEADER, CSRF_VALUE, COOKIE_NAME, AuthError, AuthService


JsonSender = Callable[[int, dict], None]


class AuthApi:
    def __init__(self, service: AuthService, identity_verifier=None):
        self.service = service
        self.identity = identity_verifier or create_identity_verifier()
        self.cookie_secure = _cookie_secure()

    def handle_get(self, handler) -> bool:
        path = urlsplit(handler.path).path
        if path == "/api/auth/config":
            handler.send_json(200, public_auth_config())
            return True
        if path == "/api/auth/me":
            return self._me(handler)
        if path == "/api/auth/kids":
            return self._kids(handler)
        if path == "/api/auth/guardian-requests":
            return self._guardian_requests(handler)
        return False

    def handle_post(self, handler) -> bool:
        path = urlsplit(handler.path).path
        if path == "/api/auth/session":
            return self._create_session(handler)
        if path == "/api/auth/dev-token":
            return self._dev_token(handler)
        if path == "/api/auth/logout":
            return self._logout(handler)
        if path == "/api/auth/kids":
            return self._add_kid(handler)
        if path == "/api/auth/kids/select":
            return self._select_kid(handler)
        if path.startswith("/api/auth/guardian-requests/") and path.endswith("/decide"):
            request_id = path[len("/api/auth/guardian-requests/") : -len("/decide")]
            return self._decide_request(handler, request_id)
        return False

    # ---- handlers ----------------------------------------------------------

    def _me(self, handler) -> bool:
        try:
            payload = self.service.current_status(self._cookie_token(handler))
            handler.send_json(200, payload)
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    def _kids(self, handler) -> bool:
        try:
            handler.send_json(200, self.service.list_kids_for_parent(self._cookie_token(handler)))
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    def _guardian_requests(self, handler) -> bool:
        try:
            handler.send_json(200, self.service.pending_guardian_requests(self._cookie_token(handler)))
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    def _create_session(self, handler) -> bool:
        if not self._csrf_ok(handler):
            return True
        try:
            body = self._json_body(handler, 8192)
            id_token = body.get("id_token")
            role = body.get("role")
            decision = body.get("decision")
            identity = self.identity.verify(id_token)
            result = self.service.create_session_from_identity(
                identity,
                role=role,
                decision=decision,
                user_agent=handler.headers.get("User-Agent"),
                ip_address=handler.client_ip(),
            )
            token = result.pop("token")
            self._set_session_cookie(handler, token)
            # Enrich like /me for parents.
            enriched = self.service.current_status(token)
            handler.send_json(200, enriched)
        except IdentityError as exc:
            handler.send_json(401, {"error": str(exc), "code": "invalid_token"})
        except AuthError as exc:
            self._send_error(handler, exc)
        except Exception as exc:
            handler.send_json(500, {"error": "Could not create session: " + str(exc)[:300]})
        return True

    def _dev_token(self, handler) -> bool:
        if not self._csrf_ok(handler):
            return True
        if not isinstance(self.identity, DevIdentityVerifier):
            handler.send_json(404, {"error": "Development sign-in is disabled."})
            return True
        try:
            body = self._json_body(handler, 4096)
            email = str(body.get("email") or "").strip().lower()
            name = str(body.get("name") or "").strip()
            uid = str(body.get("uid") or "").strip() or f"dev-{email}"
            if not email or "@" not in email:
                raise AuthError("Enter a valid email.")
            token = self.identity.sign(uid=uid, email=email, name=name)
            handler.send_json(200, {"id_token": token})
        except AuthError as exc:
            self._send_error(handler, exc)
        except IdentityError as exc:
            handler.send_json(400, {"error": str(exc)})
        return True

    def _logout(self, handler) -> bool:
        if not self._csrf_ok(handler):
            return True
        token = self._cookie_token(handler)
        self.service.logout(token)
        self._clear_session_cookie(handler)
        handler.send_json(200, {"ok": True})
        return True

    def _add_kid(self, handler) -> bool:
        if not self._csrf_ok(handler):
            return True
        try:
            body = self._json_body(handler, 4096)
            result = self.service.add_kid(
                self._cookie_token(handler),
                name=body.get("name", ""),
                email=body.get("email", ""),
            )
            handler.send_json(200, result)
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    def _select_kid(self, handler) -> bool:
        if not self._csrf_ok(handler):
            return True
        try:
            body = self._json_body(handler, 2048)
            result = self.service.select_kid(
                self._cookie_token(handler),
                account_id=str(body.get("account_id") or ""),
            )
            handler.send_json(200, result)
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    def _decide_request(self, handler, request_id: str) -> bool:
        if not self._csrf_ok(handler):
            return True
        try:
            body = self._json_body(handler, 2048)
            approved = body.get("approved")
            if not isinstance(approved, bool):
                raise AuthError("approved must be true or false.")
            result = self.service.decide_guardian_request(
                self._cookie_token(handler),
                request_id=request_id,
                approved=approved,
            )
            handler.send_json(200, result)
        except AuthError as exc:
            self._send_error(handler, exc)
        return True

    # ---- helpers -----------------------------------------------------------

    def _csrf_ok(self, handler) -> bool:
        if handler.headers.get(CSRF_HEADER) != CSRF_VALUE:
            handler.send_json(
                403,
                {
                    "error": f"Missing or invalid {CSRF_HEADER} header.",
                    "code": "csrf",
                },
            )
            return False
        return True

    def _cookie_token(self, handler) -> Optional[str]:
        raw = handler.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _json_body(self, handler, maximum: int) -> dict:
        data = handler.read_body(maximum)
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise AuthError("JSON object required.")
        return payload

    def _set_session_cookie(self, handler, token: str) -> None:
        parts = [
            f"{COOKIE_NAME}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={14 * 24 * 60 * 60}",
        ]
        if self.cookie_secure:
            parts.append("Secure")
        handler.queue_header("Set-Cookie", "; ".join(parts))

    def _clear_session_cookie(self, handler) -> None:
        parts = [
            f"{COOKIE_NAME}=",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0",
        ]
        if self.cookie_secure:
            parts.append("Secure")
        handler.queue_header("Set-Cookie", "; ".join(parts))

    def _send_error(self, handler, exc: AuthError) -> None:
        payload: dict[str, Any] = {"error": exc.message}
        if exc.code:
            payload["code"] = exc.code
        payload.update(exc.extra)
        # AuthError responses may also need Set-Cookie clearance in future; none today.
        handler.send_json(exc.status, payload)


def _cookie_secure() -> bool:
    value = os.environ.get("SESSION_COOKIE_SECURE", "auto").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return os.environ.get("K_SERVICE") is not None  # Cloud Run

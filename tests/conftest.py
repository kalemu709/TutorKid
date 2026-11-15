"""Shared fixtures for auth integration tests."""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AUTH_DEV_MODE", "1")
os.environ.setdefault("AUTH_DEV_SECRET", "test-secret-for-integration")
os.environ.setdefault("SESSION_COOKIE_SECURE", "0")

from auth.api import AuthApi
from auth.db import Database, apply_migrations
from auth.identity import DevIdentityVerifier
from auth.service import CSRF_HEADER, CSRF_VALUE, AuthService
import server as app_server


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://tutorkid:tutorkid@127.0.0.1:54329/tutorkid",
    )


def _wait_for_db(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with psycopg.connect(url) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Postgres was not ready: {last_error}")


@pytest.fixture(scope="session")
def database_url():
    url = _database_url()
    _wait_for_db(url)
    apply_migrations(url)
    return url


@pytest.fixture(autouse=True)
def clean_db(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("TRUNCATE guardian_request, session, account, \"user\" RESTART IDENTITY CASCADE")
        conn.commit()
    yield


@pytest.fixture(scope="session")
def identity():
    return DevIdentityVerifier(os.environ["AUTH_DEV_SECRET"])


@pytest.fixture(scope="session")
def server_url(database_url, identity):
    db = Database(database_url, min_size=1, max_size=4)
    service = AuthService(db)
    app_server.AUTH_API = AuthApi(service, identity)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app_server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    # Wait until the handler answers.
    for _ in range(50):
        try:
            requests.get(f"{base}/api/auth/config", timeout=0.5)
            break
        except Exception:
            time.sleep(0.05)
    yield base
    httpd.shutdown()
    db.close()


@pytest.fixture
def api(server_url, identity):
    return ApiClient(server_url, identity)


class ApiClient:
    def __init__(self, base_url: str, identity: DevIdentityVerifier):
        self.base_url = base_url
        self.identity = identity
        self.session = requests.Session()
        self.session.headers[CSRF_HEADER] = CSRF_VALUE

    def token(self, email: str, *, uid: str | None = None, name: str | None = None) -> str:
        return self.identity.sign(
            uid=uid or f"uid-{uuid.uuid4()}",
            email=email,
            name=name or email.split("@")[0],
        )

    def get(self, path: str, **kwargs):
        return self.session.get(self.base_url + path, timeout=10, **kwargs)

    def post(self, path: str, json=None, **kwargs):
        return self.session.post(self.base_url + path, json=json, timeout=10, **kwargs)

    def create_session(self, email: str, *, role=None, decision=None, uid=None, name=None):
        return self.post(
            "/api/auth/session",
            json={
                "id_token": self.token(email, uid=uid, name=name),
                "role": role,
                "decision": decision,
            },
        )

    def me(self):
        return self.get("/api/auth/me")

    def logout(self):
        return self.post("/api/auth/logout", json={})

    def add_kid(self, name: str, email: str):
        return self.post("/api/auth/kids", json={"name": name, "email": email})

    def kids(self):
        return self.get("/api/auth/kids")

    def select_kid(self, account_id: str):
        return self.post("/api/auth/kids/select", json={"account_id": account_id})

    def guardian_requests(self):
        return self.get("/api/auth/guardian-requests")

    def decide(self, request_id: str, approved: bool):
        return self.post(
            f"/api/auth/guardian-requests/{request_id}/decide",
            json={"approved": approved},
        )

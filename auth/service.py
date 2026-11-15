"""Auth business logic for the authentication-and-user-state design."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg

from .db import Database
from .identity import Identity

SESSION_DAYS = int(os.environ.get("SESSION_LIFETIME_DAYS", "14"))
LAST_SEEN_MINUTES = 5
COOKIE_NAME = "tk_session"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "TutorKid"


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400, code: Optional[str] = None, extra: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra or {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _serialize_user(row: dict) -> dict:
    return {
        "user_id": str(row["user_id"]),
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "firebase_uid": row["firebase_uid"],
    }


def _serialize_account(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    guardians = row.get("guardian_user_ids") or []
    return {
        "account_id": str(row["account_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "guardian_user_ids": [str(item) for item in guardians],
    }


class AuthService:
    def __init__(self, db: Database):
        self.db = db

    # ---- low-level lookups -------------------------------------------------

    def find_user_by_firebase_uid(self, conn: psycopg.Connection, uid: str) -> Optional[dict]:
        return conn.execute(
            'SELECT * FROM "user" WHERE firebase_uid = %s',
            (uid,),
        ).fetchone()

    def find_user_by_email(self, conn: psycopg.Connection, email: str) -> Optional[dict]:
        return conn.execute(
            'SELECT * FROM "user" WHERE lower(email) = lower(%s)',
            (email,),
        ).fetchone()

    def find_account_by_owner(self, conn: psycopg.Connection, owner_user_id: UUID | str) -> Optional[dict]:
        return conn.execute(
            "SELECT * FROM account WHERE owner_user_id = %s",
            (owner_user_id,),
        ).fetchone()

    def find_account(self, conn: psycopg.Connection, account_id: UUID | str) -> Optional[dict]:
        return conn.execute(
            "SELECT * FROM account WHERE account_id = %s",
            (account_id,),
        ).fetchone()

    def release_unclaimed_kid_email(self, conn: psycopg.Connection, email: str) -> Optional[dict]:
        return conn.execute(
            """
            UPDATE "user"
            SET email = NULL
            WHERE lower(email) = lower(%s) AND role = 'kid' AND firebase_uid IS NULL
            RETURNING *
            """,
            (email,),
        ).fetchone()

    def create_session_row(
        self,
        conn: psycopg.Connection,
        *,
        user_id: UUID | str,
        account_id: Optional[UUID | str],
        user_agent: Optional[str],
        ip_address: Optional[str],
    ) -> tuple[str, dict]:
        token = secrets.token_urlsafe(32)
        expires = _utcnow() + timedelta(days=SESSION_DAYS)
        row = conn.execute(
            """
            INSERT INTO session (user_id, account_id, token_hash, expires_at, user_agent, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, account_id, _hash_token(token), expires, user_agent, ip_address),
        ).fetchone()
        return token, row

    def load_session(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT s.*,
                       u.user_id AS u_user_id, u.email AS u_email, u.name AS u_name,
                       u.role AS u_role, u.firebase_uid AS u_firebase_uid,
                       a.account_id AS a_account_id, a.owner_user_id AS a_owner_user_id,
                       a.guardian_user_ids AS a_guardian_user_ids
                FROM session s
                JOIN "user" u ON u.user_id = s.user_id
                LEFT JOIN account a ON a.account_id = s.account_id
                WHERE s.token_hash = %s
                """,
                (_hash_token(token),),
            ).fetchone()
            if not row:
                return None
            if row["revoked_at"] is not None or row["expires_at"] <= _utcnow():
                return None

            # Drop account if user is no longer owner/guardian.
            account = None
            if row["a_account_id"]:
                guardians = row["a_guardian_user_ids"] or []
                is_owner = row["a_owner_user_id"] == row["u_user_id"]
                is_guardian = row["u_user_id"] in guardians
                if is_owner or is_guardian:
                    account = {
                        "account_id": row["a_account_id"],
                        "owner_user_id": row["a_owner_user_id"],
                        "guardian_user_ids": guardians,
                    }
                else:
                    conn.execute(
                        "UPDATE session SET account_id = NULL WHERE session_id = %s",
                        (row["session_id"],),
                    )

            if row["last_seen_at"] <= _utcnow() - timedelta(minutes=LAST_SEEN_MINUTES):
                conn.execute(
                    "UPDATE session SET last_seen_at = now() WHERE session_id = %s",
                    (row["session_id"],),
                )

            return {
                "session": {
                    "session_id": str(row["session_id"]),
                    "expires_at": row["expires_at"].isoformat(),
                },
                "user": {
                    "user_id": str(row["u_user_id"]),
                    "email": row["u_email"],
                    "name": row["u_name"],
                    "role": row["u_role"],
                    "firebase_uid": row["u_firebase_uid"],
                },
                "account": _serialize_account(account),
            }

    # ---- signup / login ----------------------------------------------------

    def create_session_from_identity(
        self,
        identity: Identity,
        *,
        role: Optional[str] = None,
        decision: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        with self.db.connection() as conn:
            existing = self.find_user_by_firebase_uid(conn, identity.uid)
            if existing:
                account_id = None
                if existing["role"] == "kid":
                    account = self.find_account_by_owner(conn, existing["user_id"])
                    if not account:
                        raise AuthError("Kid account is missing.", status=500)
                    account_id = account["account_id"]
                token, _ = self.create_session_row(
                    conn,
                    user_id=existing["user_id"],
                    account_id=account_id,
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
                return self._session_response(conn, token)

            email_owner = self.find_user_by_email(conn, identity.email)
            unclaimed = (
                email_owner
                if email_owner
                and email_owner["role"] == "kid"
                and email_owner["firebase_uid"] is None
                else None
            )
            conflict = email_owner is not None and unclaimed is None

            if role is None:
                payload = {
                    "email": identity.email,
                    "name": identity.name,
                    "unclaimed_kid": self._unclaimed_kid_payload(conn, unclaimed) if unclaimed else None,
                }
                raise AuthError(
                    "Choose whether you are signing up as a parent or a kid.",
                    status=409,
                    code="role_required",
                    extra=payload,
                )

            if role not in {"parent", "kid"}:
                raise AuthError("Role must be parent or kid.")

            if conflict:
                raise AuthError(
                    "This email already belongs to a signed-in user.",
                    status=409,
                    code="email_taken",
                )

            if role == "parent":
                if unclaimed:
                    self.release_unclaimed_kid_email(conn, identity.email)
                parent = conn.execute(
                    """
                    INSERT INTO "user" (email, name, role, firebase_uid)
                    VALUES (%s, %s, 'parent', %s)
                    RETURNING *
                    """,
                    (identity.email, identity.name, identity.uid),
                ).fetchone()
                token, _ = self.create_session_row(
                    conn,
                    user_id=parent["user_id"],
                    account_id=None,
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
                return self._session_response(conn, token)

            # role == kid
            if unclaimed:
                if decision not in {"accept", "decline"}:
                    raise AuthError(
                        "Accept or decline the account waiting for this email.",
                        status=409,
                        code="claim_required",
                        extra={
                            "email": identity.email,
                            "name": identity.name,
                            "unclaimed_kid": self._unclaimed_kid_payload(conn, unclaimed),
                        },
                    )
                if decision == "accept":
                    kid = conn.execute(
                        """
                        UPDATE "user"
                        SET firebase_uid = %s, name = COALESCE(NULLIF(%s, ''), name)
                        WHERE user_id = %s AND firebase_uid IS NULL
                        RETURNING *
                        """,
                        (identity.uid, identity.name, unclaimed["user_id"]),
                    ).fetchone()
                    if not kid:
                        raise AuthError("That kid account was claimed by someone else.", status=409)
                    account = self.find_account_by_owner(conn, kid["user_id"])
                    token, _ = self.create_session_row(
                        conn,
                        user_id=kid["user_id"],
                        account_id=account["account_id"],
                        user_agent=user_agent,
                        ip_address=ip_address,
                    )
                    return self._session_response(conn, token)

                # decline
                self.release_unclaimed_kid_email(conn, identity.email)
                kid = conn.execute(
                    """
                    INSERT INTO "user" (email, name, role, firebase_uid)
                    VALUES (%s, %s, 'kid', %s)
                    RETURNING *
                    """,
                    (identity.email, identity.name, identity.uid),
                ).fetchone()
                account = conn.execute(
                    """
                    INSERT INTO account (owner_user_id, guardian_user_ids)
                    VALUES (%s, '{}')
                    RETURNING *
                    """,
                    (kid["user_id"],),
                ).fetchone()
                token, _ = self.create_session_row(
                    conn,
                    user_id=kid["user_id"],
                    account_id=account["account_id"],
                    user_agent=user_agent,
                    ip_address=ip_address,
                )
                return self._session_response(conn, token)

            # free email kid signup
            kid = conn.execute(
                """
                INSERT INTO "user" (email, name, role, firebase_uid)
                VALUES (%s, %s, 'kid', %s)
                RETURNING *
                """,
                (identity.email, identity.name, identity.uid),
            ).fetchone()
            account = conn.execute(
                """
                INSERT INTO account (owner_user_id, guardian_user_ids)
                VALUES (%s, '{}')
                RETURNING *
                """,
                (kid["user_id"],),
            ).fetchone()
            token, _ = self.create_session_row(
                conn,
                user_id=kid["user_id"],
                account_id=account["account_id"],
                user_agent=user_agent,
                ip_address=ip_address,
            )
            return self._session_response(conn, token)

    def _unclaimed_kid_payload(self, conn: psycopg.Connection, kid: dict) -> dict:
        account = self.find_account_by_owner(conn, kid["user_id"])
        guardians = []
        if account:
            ids = account["guardian_user_ids"] or []
            if ids:
                rows = conn.execute(
                    'SELECT user_id, name, email FROM "user" WHERE user_id = ANY(%s)',
                    (list(ids),),
                ).fetchall()
                by_id = {row["user_id"]: row for row in rows}
                for gid in ids:
                    row = by_id.get(gid)
                    if row:
                        guardians.append(
                            {
                                "user_id": str(row["user_id"]),
                                "name": row["name"],
                                "email": row["email"],
                            }
                        )
        return {
            "user_id": str(kid["user_id"]),
            "name": kid["name"],
            "email": kid["email"],
            "account_id": str(account["account_id"]) if account else None,
            "guardians": guardians,
        }

    def _session_response(self, conn: psycopg.Connection, token: str) -> dict:
        # Re-load through same connection so callers get consistent data before commit.
        row = conn.execute(
            """
            SELECT s.session_id, s.expires_at, s.account_id,
                   u.user_id, u.email, u.name, u.role, u.firebase_uid,
                   a.account_id AS a_account_id, a.owner_user_id, a.guardian_user_ids
            FROM session s
            JOIN "user" u ON u.user_id = s.user_id
            LEFT JOIN account a ON a.account_id = s.account_id
            WHERE s.token_hash = %s
            """,
            (_hash_token(token),),
        ).fetchone()
        account = None
        if row["a_account_id"]:
            account = {
                "account_id": row["a_account_id"],
                "owner_user_id": row["owner_user_id"],
                "guardian_user_ids": row["guardian_user_ids"] or [],
            }
        return {
            "token": token,
            "session": {
                "session_id": str(row["session_id"]),
                "expires_at": row["expires_at"].isoformat(),
            },
            "user": {
                "user_id": str(row["user_id"]),
                "email": row["email"],
                "name": row["name"],
                "role": row["role"],
                "firebase_uid": row["firebase_uid"],
            },
            "account": _serialize_account(account),
        }

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE session
                SET revoked_at = now()
                WHERE token_hash = %s AND revoked_at IS NULL
                """,
                (_hash_token(token),),
            )

    # ---- parent kid management ---------------------------------------------

    def require_user(self, token: Optional[str]) -> dict:
        state = self.load_session(token)
        if not state:
            raise AuthError("Sign in required.", status=401, code="unauthenticated")
        return state

    def add_kid(self, token: Optional[str], name: str, email: str) -> dict:
        state = self.require_user(token)
        if state["user"]["role"] != "parent":
            raise AuthError("Only parents can add kids.", status=403)
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not name:
            raise AuthError("Enter the kid's name.")
        if not email or "@" not in email:
            raise AuthError("Enter a valid kid email.")

        parent_id = state["user"]["user_id"]
        with self.db.connection() as conn:
            existing = self.find_user_by_email(conn, email)
            if existing and existing["role"] == "parent":
                raise AuthError("That email belongs to a parent account.", status=409, code="email_is_parent")

            if existing and existing["role"] == "kid":
                account = self.find_account_by_owner(conn, existing["user_id"])
                if not account:
                    raise AuthError("Kid account is missing.", status=500)
                guardians = account["guardian_user_ids"] or []
                parent_uuid = UUID(parent_id)
                if parent_uuid in guardians:
                    conn.execute(
                        "UPDATE session SET account_id = %s WHERE session_id = %s",
                        (account["account_id"], state["session"]["session_id"]),
                    )
                    return {
                        "status": "already_guardian",
                        "account": _serialize_account(account),
                        "kid": _serialize_user(existing),
                    }

                pending = conn.execute(
                    """
                    SELECT * FROM guardian_request
                    WHERE account_id = %s AND requester_user_id = %s AND decided_at IS NULL
                    """,
                    (account["account_id"], parent_id),
                ).fetchone()
                if not pending:
                    pending = conn.execute(
                        """
                        INSERT INTO guardian_request (account_id, requester_user_id)
                        VALUES (%s, %s)
                        RETURNING *
                        """,
                        (account["account_id"], parent_id),
                    ).fetchone()
                return {
                    "status": "pending_approval",
                    "request": {
                        "request_id": str(pending["request_id"]),
                        "account_id": str(pending["account_id"]),
                        "approved": pending["approved"],
                        "decided_at": pending["decided_at"].isoformat() if pending["decided_at"] else None,
                    },
                    "kid": _serialize_user(existing),
                }

            kid = conn.execute(
                """
                INSERT INTO "user" (email, name, role, firebase_uid)
                VALUES (%s, %s, 'kid', NULL)
                RETURNING *
                """,
                (email, name),
            ).fetchone()
            account = conn.execute(
                """
                INSERT INTO account (owner_user_id, guardian_user_ids)
                VALUES (%s, ARRAY[%s]::uuid[])
                RETURNING *
                """,
                (kid["user_id"], parent_id),
            ).fetchone()
            conn.execute(
                "UPDATE session SET account_id = %s WHERE session_id = %s",
                (account["account_id"], state["session"]["session_id"]),
            )
            return {
                "status": "created",
                "account": _serialize_account(account),
                "kid": _serialize_user(kid),
            }

    def list_kids_for_parent(self, token: Optional[str]) -> dict:
        state = self.require_user(token)
        if state["user"]["role"] != "parent":
            raise AuthError("Only parents have a kid list.", status=403)
        parent_id = UUID(state["user"]["user_id"])
        with self.db.connection() as conn:
            accounts = conn.execute(
                """
                SELECT a.*, u.name AS kid_name, u.email AS kid_email, u.firebase_uid AS kid_firebase_uid
                FROM account a
                JOIN "user" u ON u.user_id = a.owner_user_id
                WHERE %s = ANY (a.guardian_user_ids)
                ORDER BY u.name NULLS LAST, u.created_at
                """,
                (parent_id,),
            ).fetchall()
            requests = conn.execute(
                """
                SELECT gr.*, u.name AS kid_name, u.email AS kid_email
                FROM guardian_request gr
                JOIN account a ON a.account_id = gr.account_id
                JOIN "user" u ON u.user_id = a.owner_user_id
                WHERE gr.requester_user_id = %s
                ORDER BY gr.created_at DESC
                """,
                (parent_id,),
            ).fetchall()

        selectable = []
        for row in accounts:
            selectable.append(
                {
                    "account_id": str(row["account_id"]),
                    "kid_name": row["kid_name"],
                    "kid_email": row["kid_email"],
                    "ghost": row["kid_email"] is None and row["kid_firebase_uid"] is None,
                    "selectable": True,
                    "status": "declined_by_kid" if row["kid_email"] is None else "guardian",
                }
            )

        pending_or_declined = []
        seen_accounts = {item["account_id"] for item in selectable}
        for row in requests:
            account_id = str(row["account_id"])
            if account_id in seen_accounts and row["approved"] is True:
                continue
            if row["decided_at"] is None:
                status = "waiting_for_approval"
                selectable_flag = False
            elif row["approved"]:
                continue
            else:
                status = "declined"
                selectable_flag = False
            pending_or_declined.append(
                {
                    "account_id": account_id,
                    "request_id": str(row["request_id"]),
                    "kid_name": row["kid_name"],
                    "kid_email": row["kid_email"],
                    "selectable": selectable_flag,
                    "status": status,
                }
            )

        return {
            "selected_account_id": state["account"]["account_id"] if state["account"] else None,
            "kids": selectable + pending_or_declined,
        }

    def select_kid(self, token: Optional[str], account_id: str) -> dict:
        state = self.require_user(token)
        if state["user"]["role"] != "parent":
            raise AuthError("Only parents select a kid account.", status=403)
        with self.db.connection() as conn:
            account = self.find_account(conn, account_id)
            if not account:
                raise AuthError("Account not found.", status=404)
            guardians = account["guardian_user_ids"] or []
            if UUID(state["user"]["user_id"]) not in guardians:
                raise AuthError("You are not a guardian of that kid.", status=403)
            conn.execute(
                "UPDATE session SET account_id = %s WHERE session_id = %s",
                (account_id, state["session"]["session_id"]),
            )
            return {"account": _serialize_account(account)}

    def pending_guardian_requests(self, token: Optional[str]) -> dict:
        state = self.require_user(token)
        if not state["account"]:
            return {"requests": []}
        account_id = state["account"]["account_id"]
        user_id = UUID(state["user"]["user_id"])
        account = state["account"]
        is_owner = account["owner_user_id"] == state["user"]["user_id"]
        is_guardian = user_id in [UUID(item) for item in account["guardian_user_ids"]]
        if not (is_owner or is_guardian):
            return {"requests": []}

        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT gr.*, u.name AS requester_name, u.email AS requester_email
                FROM guardian_request gr
                JOIN "user" u ON u.user_id = gr.requester_user_id
                WHERE gr.account_id = %s AND gr.decided_at IS NULL
                ORDER BY gr.created_at
                """,
                (account_id,),
            ).fetchall()
        return {
            "requests": [
                {
                    "request_id": str(row["request_id"]),
                    "requester_user_id": str(row["requester_user_id"]),
                    "requester_name": row["requester_name"],
                    "requester_email": row["requester_email"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
                if str(row["requester_user_id"]) != state["user"]["user_id"]
            ]
        }

    def decide_guardian_request(self, token: Optional[str], request_id: str, approved: bool) -> dict:
        state = self.require_user(token)
        if not state["account"]:
            raise AuthError("Select a kid account first.", status=403, code="account_required")
        decider_id = state["user"]["user_id"]
        with self.db.connection() as conn:
            request = conn.execute(
                "SELECT * FROM guardian_request WHERE request_id = %s",
                (request_id,),
            ).fetchone()
            if not request:
                raise AuthError("Request not found.", status=404)
            if str(request["account_id"]) != state["account"]["account_id"]:
                raise AuthError("Request is for a different account.", status=403)
            if str(request["requester_user_id"]) == decider_id:
                raise AuthError("You cannot decide your own guardian request.", status=403)
            account = self.find_account(conn, request["account_id"])
            guardians = account["guardian_user_ids"] or []
            is_owner = str(account["owner_user_id"]) == decider_id
            is_guardian = UUID(decider_id) in guardians
            if not (is_owner or is_guardian):
                raise AuthError("Only the kid or an existing guardian can decide.", status=403)

            updated = conn.execute(
                """
                UPDATE guardian_request
                SET decided_at = now(), decided_by_user_id = %s, approved = %s
                WHERE request_id = %s AND decided_at IS NULL
                RETURNING *
                """,
                (decider_id, approved, request_id),
            ).fetchone()
            if not updated:
                raise AuthError("This request was already decided.", status=409)

            if approved:
                conn.execute(
                    """
                    UPDATE account
                    SET guardian_user_ids = array_append(guardian_user_ids, %s)
                    WHERE account_id = %s AND NOT (%s = ANY (guardian_user_ids))
                    """,
                    (updated["requester_user_id"], updated["account_id"], updated["requester_user_id"]),
                )
            return {
                "request": {
                    "request_id": str(updated["request_id"]),
                    "approved": updated["approved"],
                    "decided_at": updated["decided_at"].isoformat(),
                }
            }

    def current_status(self, token: Optional[str]) -> dict:
        state = self.load_session(token)
        if not state:
            return {"authenticated": False, "user": None, "account": None}
        payload = {
            "authenticated": True,
            "user": state["user"],
            "account": state["account"],
            "session": state["session"],
        }
        if state["user"]["role"] == "parent":
            payload["kids"] = self.list_kids_for_parent(token)["kids"]
            payload["selected_account_id"] = state["account"]["account_id"] if state["account"] else None
        if state["account"]:
            payload["pending_guardian_requests"] = self.pending_guardian_requests(token)["requests"]
        else:
            payload["pending_guardian_requests"] = []
        return payload

    def cleanup_sessions(self) -> int:
        with self.db.connection() as conn:
            result = conn.execute(
                """
                DELETE FROM session
                WHERE (expires_at < now() - interval '30 days')
                   OR (revoked_at IS NOT NULL AND revoked_at < now() - interval '30 days')
                """
            )
            return result.rowcount or 0

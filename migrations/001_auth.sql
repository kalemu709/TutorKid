-- Authentication and user state (docs/features/authentication-and-user-state/design.md)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE "user" (
  user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text,
  name          text,
  role          text NOT NULL,
  firebase_uid  text UNIQUE,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (email IS NOT NULL OR (role = 'kid' AND firebase_uid IS NULL)),
  CHECK (role IN ('parent', 'kid'))
);

CREATE UNIQUE INDEX user_email_unique ON "user" (lower(email));

CREATE TABLE account (
  account_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id      uuid NOT NULL UNIQUE REFERENCES "user" (user_id),
  guardian_user_ids  uuid[] NOT NULL DEFAULT '{}'
);

CREATE INDEX account_guardians ON account USING gin (guardian_user_ids);

CREATE TABLE guardian_request (
  request_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id          uuid NOT NULL REFERENCES account (account_id) ON DELETE CASCADE,
  requester_user_id   uuid NOT NULL REFERENCES "user" (user_id) ON DELETE CASCADE,
  created_at          timestamptz NOT NULL DEFAULT now(),
  decided_at          timestamptz,
  decided_by_user_id  uuid REFERENCES "user" (user_id),
  approved            boolean
);

CREATE UNIQUE INDEX guardian_request_pending
  ON guardian_request (account_id, requester_user_id)
  WHERE decided_at IS NULL;

CREATE TABLE session (
  session_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES "user" (user_id) ON DELETE CASCADE,
  account_id    uuid REFERENCES account (account_id) ON DELETE SET NULL,
  token_hash    bytea NOT NULL UNIQUE,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at    timestamptz,
  user_agent    text,
  ip_address    inet
);

CREATE INDEX session_user_id ON session (user_id);
CREATE INDEX session_expires ON session (expires_at);

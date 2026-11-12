---
status: draft
code: not implemented yet
depends_on: ../../architecture.md
updated: 2026-11-12
---

# Authentication and user state

## Objective

The website stays usable anonymously, in a stateless way. This feature adds authentication, so a user who signs in can use the website statefully: what they do is saved to an account and is there when they come back.

## Scenarios

### 1. Sign up

A first-time user signs up with Google (Gmail) or an email link. The browser always asks their role: **parent** or **kid**. The server then applies the matching branch below. (Firebase does not distinguish sign-up from log-in; see [Sign in with Firebase](#sign-in-with-firebase).)

- **Parent, email free** (no user has this email): create the parent `user`, sign them in with `session.account_id` unset. Their first page is select-or-add a kid; they cannot use account data until a kid is selected (scenarios 2 and 4).
- **Parent, email only on an unclaimed kid** (a `user` with this email, `role = 'kid'`, `firebase_uid` still `NULL` — someone else created a kid with this email): [release that email](#releasing-an-unclaimed-kid-email), then create the parent as above. The parent is never forced into the kid role. The old kid row and its account stay for whoever created them.
- **Parent, email already a signed-in user or a parent user:** refuse sign-up; each email is one user.
- **Kid, email matches an unclaimed kid** (`role = 'kid'`, `firebase_uid` still `NULL`): show that account and each guardian's name and email; ask accept or decline.
  - **Accept:** set `firebase_uid` on that kid row; the kid takes over that user and account. Sign them in with `session.account_id` set to that account.
  - **Decline:** [release the email](#releasing-an-unclaimed-kid-email) from the unclaimed kid row, create a **new** kid `user` and account (owner, no guardians), sign them in on the new account. The parent's old kid row stays (email cleared) with its progress; the parent can still select that ghost account, and can later ask to join the kid's real account (scenario 2).
- **Kid, email free:** create the kid `user` and account (owner, no guardians); sign them in with `session.account_id` set to that account.
- **Kid, email already a signed-in user or a parent user:** refuse sign-up.

### 2. Parent adds a kid

A signed-in parent enters a kid's **name** and **email**. The server looks up `user` by that email:

- **No user with that email:** in one transaction, create a kid `user` (`role = 'kid'`, `firebase_uid` `NULL`, name and email as entered) and an `account` with that kid as `owner_user_id` and this parent in `guardian_user_ids`. Set `session.account_id` to the new account. No approval step — nobody else can reach this kid yet.
- **A kid user with that email exists** (signed in already, or still unclaimed from another parent): that kid already has an account (`owner_user_id` points at them).
  - If this parent is already a guardian: no change; they may select that kid (scenario 4).
  - Otherwise: create a pending `guardian_request` (reuse if one is already pending). Do **not** add the parent to `guardian_user_ids` yet. The parent sees "waiting for approval" and cannot select that kid until scenario 3 approves.
- **A parent user with that email:** refuse; each email is one user.

### 3. Approve a new guardian

When an account has pending `guardian_request` rows, the next time the **owner (kid)** or an **existing guardian** works in that account, they see each request (requester name and email) and approve or decline.

- **Approved:** add the requester to `guardian_user_ids`; that parent may select the kid (scenario 4).
- **Declined:** account unchanged; the requester sees the request as declined and still cannot select that kid.

The requester cannot decide their own request. Until decided, they keep working with other kids.

### 4. Parent selects a kid

The parent sees:

| Listed how | Selectable? |
|---|---|
| Accounts where they are in `guardian_user_ids` | Yes |
| Pending `guardian_request` they made | No — "waiting for approval" |
| Declined `guardian_request` they made | No — "declined" |
| Ghost kid they still guardian (`email` `NULL` after the real kid declined takeover) | Yes — "declined by the kid"; progress on that account remains |

Picking a selectable kid sets `session.account_id` to that account after checking the parent is still a guardian.

### 5. Log in

A returning user (matched by `firebase_uid`) signs in with the same method as before. A new `session` is created:

- **Kid:** `session.account_id` is set to the account they own.
- **Parent:** `session.account_id` starts `NULL`; they must select or add a kid again before using account data (scenarios 2 and 4).

They stay signed in until the session expires or they log out. Parents and kids each use their own login ([decision 0002](decisions/0002-kids-are-users.md)); there is no profile switching under one sign-in.

### 6. Log out

Set `revoked_at` on the session, clear the cookie, and sign out of Firebase. The next visit is anonymous until sign-in again.

## Data

Columns marked *operational* are for reliability only. Tables are in creation order so every foreign key targets an existing table.

### Tables

#### user

One row per person: every parent, every kid who signed up, and every kid a parent added who has not signed in yet (and ghost kid rows left after a declined takeover).

```sql
CREATE TABLE "user" (
  user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text,                                 -- NULL only on an unclaimed kid after email release
  name          text,                                 -- sign-in profile, or name a parent entered when adding the kid
  role          text NOT NULL,                        -- 'parent' or 'kid' today; open for new roles
  firebase_uid  text UNIQUE,                          -- operational: NULL until this person has signed in
  created_at    timestamptz NOT NULL DEFAULT now(),   -- operational
  CHECK (email IS NOT NULL OR (role = 'kid' AND firebase_uid IS NULL))
);
CREATE UNIQUE INDEX user_email_unique ON "user" (lower(email));
```

- **`email`:** unique case-insensitively. Required for every parent and every signed-in user. May be `NULL` only for a kid with `firebase_uid IS NULL` after [email release](#releasing-an-unclaimed-kid-email) (kid declined takeover, or real owner signed up as parent). Matching "parent added this kid" always uses email.
- **`name`:** from the sign-in profile on sign-up, or from the parent when adding a kid. Shown on accept-account and guardian-request screens.
- **`firebase_uid`:** `NULL` for parent-created kids who have never signed in; set on first successful sign-in (accept path or normal kid/parent sign-up).
- **`role`:** string validated by the server (`parent`, `kid`). Picked at sign-up; parent-created kids get `kid`.
- **Role vs permissions:** inside a selected account, parent and kid can do the same things. Role only decides ownership/guardian shape and that parents must select a kid before account work.

#### account

One account per **kid user row**. The kid is `owner_user_id`; parents who may use it are `guardian_user_ids` ([decision 0003](decisions/0003-account-owned-by-kid.md)).

```sql
CREATE TABLE account (
  account_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id      uuid NOT NULL UNIQUE REFERENCES "user" (user_id),
  guardian_user_ids  uuid[] NOT NULL DEFAULT '{}'
);
CREATE INDEX account_guardians ON account USING gin (guardian_user_ids);
```

- `owner_user_id` unique ⇒ each kid **user** has exactly one account. After a declined takeover there can be two kid users (ghost + real), each with their own account.
- Every id in `guardian_user_ids` must be a `user` with `role = 'parent'` (server-checked; no FK on array elements).
- Users reach accounts only as owner or guardian — there is no `account_id` on `user`.
- GIN index supports listing a parent's kids: `WHERE $parent_id = ANY (guardian_user_ids)`.

#### guardian_request

Pending (or decided) request for a parent to join an **existing** account's guardians ([decision 0005](decisions/0005-new-guardians-need-approval.md)).

```sql
CREATE TABLE guardian_request (
  request_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id          uuid NOT NULL REFERENCES account (account_id) ON DELETE CASCADE,
  requester_user_id   uuid NOT NULL REFERENCES "user" (user_id) ON DELETE CASCADE,
  created_at          timestamptz NOT NULL DEFAULT now(),
  decided_at          timestamptz,
  decided_by_user_id  uuid REFERENCES "user" (user_id),
  approved            boolean
);
CREATE UNIQUE INDEX guardian_request_pending ON guardian_request (account_id, requester_user_id)
  WHERE decided_at IS NULL;
```

- At most one **pending** request per parent per account. Decided rows are kept for history and for the parent's list UI.

#### session

One row per signed-in browser, plus which account that browser is working in.

```sql
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
```

- **Kid sessions:** `account_id` set at sign-in to the account they own.
- **Parent sessions:** `account_id` starts `NULL` at sign-in; set when they add or select a kid. Stored per session so one parent can use different kids on different devices.

## Behaviour

### Sign in with Firebase

1. Browser signs in with Firebase (Google or email link) → Firebase ID token.
2. Browser sends the token once. Server verifies with Firebase Admin SDK → Firebase uid + verified email.
3. **`user` with this `firebase_uid` exists → log in** (scenario 5): create session as in step 5; do not ask role.
4. **Otherwise → sign up** (scenario 1): browser sends chosen role; server branches:
   - **Kid + unclaimed kid email:** show accept/decline UI (guardians' names and emails).
     - **Accept:** `UPDATE` set `firebase_uid` on that row.
     - **Decline:** one transaction: [release email](#releasing-an-unclaimed-kid-email), then insert new kid `user` + `account` (owner, no guardians).
   - **Kid + free email:** one transaction: insert kid `user` + `account` (owner, no guardians).
   - **Parent + unclaimed kid email only:** one transaction: [release email](#releasing-an-unclaimed-kid-email), then insert parent `user`.
   - **Parent + free email:** insert parent `user`.
   - **Email owned by signed-in user or parent user:** refuse.
5. Create `session`, set cookie (`HttpOnly`, `Secure`, `SameSite=Lax`); store only SHA-256 of the token.
   - Kid → `session.account_id` = their owned account.
   - Parent → `session.account_id` = `NULL` → select-or-add-kid page.

### Releasing an unclaimed kid email

When the verified owner of an email signs up and that email still sits only on a never-signed-in kid (`role = 'kid'`, `firebase_uid IS NULL`). The kid row keeps name, account, guardians, and saved work; only email is cleared:

```sql
UPDATE "user"
SET email = NULL
WHERE lower(email) = lower($email) AND role = 'kid' AND firebase_uid IS NULL;
```

Used by: kid **decline** (scenario 1), and parent sign-up against an unclaimed kid email (scenario 1).

### Parent adds a kid

Implements scenario 2.

1. Parent submits name + email.
2. Lookup `user` by `lower(email)`:
   - **Kid found:** if parent already in that account's `guardian_user_ids`, no-op. Else insert pending `guardian_request` (or reuse pending). Do not change `guardian_user_ids`.
   - **No user:** one transaction — insert kid `user` (`firebase_uid` `NULL`) + `account` (owner = kid, guardians = `{parent}`); set `session.account_id` to that account.
   - **Parent found:** refuse.

### Approve or decline a guardian request

Implements scenario 3.

1. Owner or existing guardian opens an account that has pending requests → show requester name/email first.
2. Only owner or current `guardian_user_ids` may decide; requester may not.
3. **Approve** (one transaction; first decision wins):

   ```sql
   UPDATE guardian_request
   SET decided_at = now(), decided_by_user_id = $decider_id, approved = true
   WHERE request_id = $request_id AND decided_at IS NULL
   RETURNING account_id, requester_user_id;

   -- only if a row was returned:
   UPDATE account
   SET guardian_user_ids = array_append(guardian_user_ids, $requester_user_id)
   WHERE account_id = $account_id AND NOT ($requester_user_id = ANY (guardian_user_ids));
   ```

4. **Decline:** same first `UPDATE` with `approved = false`; leave `guardian_user_ids` unchanged.
5. Someone can always decide: a parent-created kid already has that parent as guardian; a kid who signed up alone is the owner with no guardians and decides themselves.

### Parent selects a kid

Implements scenario 4: list as in the scenario table; on pick, verify guardian membership, then `UPDATE session SET account_id = $account_id`.

### The account a request works in

Every read/write of account data uses `session.account_id`. Before use, verify the session user is still owner or guardian; otherwise clear `session.account_id` and, for a parent, return them to select-or-add. Parent requests with `account_id` null are refused until a kid is selected.

### Stay signed in

- Hash cookie → load session; missing / expired / revoked ⇒ treat as anonymous.
- Update `last_seen_at` at most every few minutes.
- Fixed lifetime (for example 14 days), then sign in again.
- Mutations also require a custom header (for example `X-Requested-With`) with `SameSite=Lax` against CSRF.

### Log out

Implements scenario 6: set `revoked_at`, clear cookie, Firebase sign-out.

## Operations

- **Session cleanup:** delete sessions expired or revoked more than 30 days ago.

## Decisions

- [0001](decisions/0001-firebase-auth-own-sessions.md): Firebase Auth for identity, our own session table
- [0002](decisions/0002-kids-are-users.md): Kids use their own login, as users with role `kid`
- [0003](decisions/0003-account-owned-by-kid.md): Each account is owned by one kid and lists the kid's guardians
- [0004](decisions/0004-parents-add-kids.md): Parents add kids by name and email; a kid claims their account by signing in with that email
- [0005](decisions/0005-new-guardians-need-approval.md): A parent joining a kid's existing account needs approval from the kid or an existing guardian
- [0006](decisions/0006-kid-accepts-parent-created-account.md): A kid accepts or declines an account a parent created for them

---
status: accepted
date: 2026-11-11
---

# 0002: Kids use their own login, as users with role `kid`

## Context

Kids use the site alongside parents in the same account. A common alternative is for only the parent to sign in and for kids to be profiles under the account, without their own login.

## Options considered

- Kids as profiles under the parent's account, with an optional PIN
- Kids as users with their own login, as in the requested data model

## Decision

Kids use their own login. Each kid is a row in `user` with `role = 'kid'` and the shared account's `account_id`, and signs in, stays signed in, and logs out exactly like a parent. This keeps the requested data model unchanged and lets each kid sign in as themselves. Profiles were considered and rejected.

## Consequences

- Parents and kids sign in the same way and share one `user` and `session` design.
- A kid needs their own sign-in identity (for example their own Google account), because `email` is required and unique per user.
- How kids and parents share an account is settled in [0003](0003-account-owned-by-kid.md): the kid owns the account and parents are its guardians.

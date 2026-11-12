---
status: accepted
date: 2026-11-12
---

# 0003: Each account is owned by one kid and lists the kid's guardians

## Context

Kids use their own login ([0002](0002-kids-are-users.md)), and sign-up created a new account for every user, so a kid had no way to share an account with their parents.

## Decision

Kids and parents have separate user IDs. The `account` table has:

- an owner, `owner_user_id`: the kid the account belongs to;
- a list of guardians, `guardian_user_ids`: the user IDs of the kid's mother, father, and so on.

When a kid signs up, their account is created with them as the owner.

## Consequences

- Each kid **user** has exactly one account (`owner_user_id` unique). After a declined takeover ([0006](0006-kid-accepts-parent-created-account.md)) a ghost kid user and a real kid user can each own an account.
- Guardian IDs are an array, which Postgres cannot check with a foreign key; the server validates them.
- How a parent is linked as a guardian, and which account a parent works in, are settled in [0004](0004-parents-add-kids.md).

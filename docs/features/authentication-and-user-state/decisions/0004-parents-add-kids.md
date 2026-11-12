---
status: accepted
date: 2026-11-12
---

# 0004: Parents add kids by name and email; a kid claims their account by signing in with that email

## Context

Each account is owned by one kid and lists the kid's guardians ([0003](0003-account-owned-by-kid.md)). It was open how a parent gets linked to a kid's account, and which account a parent belongs to when they have several kids. Many kids will not sign in themselves at first, so the site must work with only a parent signed in.

## Decision

- On first sign-up, a user picks their role: parent or kid.
- After signing up or logging in, a parent first selects a kid or adds a kid, before doing anything else.
- A parent adds a kid by giving the kid's name and email. If the kid already has an account (they signed up on their own, or another parent added them), the parent asks to become a guardian of it. Otherwise this creates the kid's user (not yet signed in) and the kid's account, with the kid as owner and the parent as guardian.
- When a kid signs up and their verified email matches a kid added by a parent, the kid can take over that user and account, after accepting it ([0006](0006-kid-accepts-parent-created-account.md)). If no parent added them, a new account is created for them.
- The account a parent works in is the kid they selected, stored on their session. A user has no `account_id`; they reach an account by being its owner or a guardian.

## Consequences

- A kid's progress is kept in their own account from the start, even before they ever sign in, so the site can be adopted with only the parent signed in.
- `user.firebase_uid` is empty for kids added by a parent until they sign in.
- `user.account_id` from the original data model is removed; `account.owner_user_id`, `account.guardian_user_ids`, and `session.account_id` replace it.
- Claiming a kid relies on Firebase verifying the email, so only the real owner of the email can take over the kid's account.
- Each kid user has exactly one account. If the kid declines a parent-created account ([0006](0006-kid-accepts-parent-created-account.md)), the ghost kid user and the real kid user each keep their own account.
- A parent joining a kid's existing account needs approval from the kid or an existing guardian; see [0005](0005-new-guardians-need-approval.md).

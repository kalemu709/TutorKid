---
status: accepted
date: 2026-11-12
---

# 0006: A kid accepts or declines an account a parent created for them

## Context

A parent can create a kid's account with the kid's email before the kid ever signs in ([0004](0004-parents-add-kids.md)). When the kid then signed up, they took over that account automatically, even if it was created by someone they do not know or want as a guardian.

## Decision

When a kid signs up and a parent already created an account for their email, the kid is first shown that account with the name and email of each guardian, and asked whether to accept it.

- **Accept:** the kid takes over the existing user and account.
- **Decline:** the kid gets their own new account. The parent-created kid record gives up the email, so the kid's own user can have it, and keeps its name, account, and everything saved in it.

## Consequences

- A kid is never placed under guardians without agreeing to it, either here or through guardian approval ([0005](0005-new-guardians-need-approval.md)).
- Nothing is lost on decline: the parent keeps their record of the kid and its progress, and can ask to join the kid's own account, which the kid then approves or declines.
- `user.email` may be `NULL`, but only for a kid record that has never signed in; a check constraint enforces this.
- A declined kid record can no longer be claimed by signing in, because it has no email.
- The same email release is used when the real owner signs up as a **parent** and the email is only on an unclaimed kid: the kid record releases the email, the parent is created, and the owner is never forced into the kid role (see [Sign in with Firebase](../design.md#sign-in-with-firebase)).

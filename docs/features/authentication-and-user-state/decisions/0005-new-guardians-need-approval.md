---
status: accepted
date: 2026-11-12
---

# 0005: A parent joining a kid's existing account needs approval from the kid or an existing guardian

## Context

A parent adds a kid by entering the kid's email ([0004](0004-parents-add-kids.md)). If that kid already had an account, the parent became a guardian at once, so anyone who knew a kid's email could see and change that kid's account.

## Decision

When a parent adds a kid who already has an account, the parent's request to become a guardian waits for approval. The kid or any existing guardian of the account can approve or decline it. Only once it is approved is the parent added to the account's guardians.

Adding a kid who has no account yet still needs no approval, because nobody else has access to that kid.

## Consequences

- Knowing a kid's email is no longer enough to reach their account.
- A second parent cannot work with the kid until the kid or the first parent approves them.
- Requests are stored in a `guardian_request` table, with one pending request per parent per account, and the first decision wins.
- Every account always has someone who can decide: either a guardian, or a kid who signed up on their own.

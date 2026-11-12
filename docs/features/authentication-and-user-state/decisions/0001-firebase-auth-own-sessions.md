---
status: accepted
date: 2026-11-11
---

# 0001: Firebase Auth for identity, our own session table

## Context

Users must log in to an account, and the requested data model includes a session table per user.

## Options considered

- A managed sign-in service such as Firebase Auth, with Google sign-in and email links
- Our own email and password sign-in, with the session table
- Our own passwordless email-link sign-in, with the session table

## Decision

Firebase Auth verifies who the user is. After that, the app creates its own `session` row and cookie, as in the requested model. `user.firebase_uid` links the two.

## Consequences

- The site never stores passwords.
- Sessions, expiry, and revocation are under the app's control and live in the same database as everything else.
- Each login needs one call to verify the Firebase ID token with the Firebase Admin SDK.

Details: [Sign in with Firebase](../design.md#sign-in-with-firebase).

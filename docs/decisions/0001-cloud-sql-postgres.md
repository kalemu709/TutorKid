---
status: accepted
date: 2026-11-11
---

# 0001: Cloud SQL for PostgreSQL as the database

## Context

The site needs to store accounts, users, sessions, task lists, and tasks whose character metadata and exam results are JSON. Several tables reference each other, and some changes must touch two tables at once (for example creating a task and adding it to the task list).

## Options considered

- Cloud SQL for PostgreSQL
- Supabase (hosted Postgres that also includes sign-in and file storage)
- Firestore (Google's document database, no SQL)
- SQLite, to keep local development simple

## Decision

Cloud SQL for PostgreSQL. JSON fields use `jsonb`. Local development uses Postgres in Docker.

## Consequences

- Foreign keys, unique constraints, and multi-table transactions are enforced by the database, which the design relies on so that work is never lost or corrupted.
- `jsonb` allows updating a single character or appending an exam attempt atomically in one statement.
- It runs alongside the existing Cloud Run service, connected through the Cloud SQL connector.
- Schema changes need versioned migrations.

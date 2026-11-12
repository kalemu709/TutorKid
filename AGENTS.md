# Agent instructions

The user says which kind of work a task is and which feature it concerns. Follow the matching work order below. Do not skip a step or start the next one before the current one is done.

## General

- **Source of truth:** the design docs. Feature designs are in `docs/features/<feature>/design.md`; the service, code, and data layout is in [docs/architecture.md](docs/architecture.md).
- **Approval** means the user explicitly says so. Never mark a design `accepted` or treat a proposal as approved on your own.
- If a change would conflict with a feature's objectives, say so and ask before going ahead.
- Keep each design doc's `code:` and `updated:` header fields current.
- Ignore docs marked `status: superseded`.

## Type 1: feature development

1. **Design, approved.**
   - For an existing feature, locate its approved design (`status: accepted`) in `docs/features/<feature>/design.md`.
   - For a new feature or a change to a design, write or update the design doc (`status: draft`) in `docs/features/<feature>/design.md`, following the structure of the existing feature docs, and ask the user for approval. When the user approves, set `status: accepted`.
2. **Update the architecture** if the design is new or changed: bring `docs/architecture.md` in line with any services, code locations, or data stores the feature adds or changes.
3. **Write the code** according to the approved design. If the code needs to differ from the design, stop, update the design and get it approved again (step 1) before continuing.

## Type 2: bug fix

1. **Propose a one-pager** based on the existing docs and get the user's approval before writing code. Keep it short and clean.:

   ```text
   <One-line summary of the fix>

   Problem: what goes wrong, and how to reproduce it.
   Cause:   why it happens, with the files involved.
   Fix:     what changes, and why this is the right place to fix it.
   Design:  which design docs are affected, or "none".
   Testing: how the fix will be verified.
   ```

2. **Code the fix** as approved, and use the one-pager as the commit message.

## Before pushing (both types)

When the user says a commit is ready to push:

1. Compare the commit with the related design docs and `docs/architecture.md`.
2. If they differ, update the docs to match the code being submitted, and include the doc changes in the commit.
3. Tell the user which docs were changed, or that they were already in sync, before pushing.

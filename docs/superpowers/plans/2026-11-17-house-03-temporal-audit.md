# HOUSE-03 Temporal Audit Implementation Plan

> **For agentic workers:** Execute task-by-task using the supplied HOUSE-03 audit request.

**Goal:** Preserve correct, non-retroactive appliance context for P1/P4 across temporal changes and enforce authorization/isolation at the API and SQLite boundaries.

**Architecture:** Keep the relational temporal catalogue and F0 contracts. Enforce non-overlapping `[valid_from, valid_to)` intervals in SQLite, perform updates in existing `BEGIN IMMEDIATE` transactions, and expose consumption context only when the full event has one unambiguous snapshot; provide temporal segments when it crosses a boundary.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, Ruff.

**Spec:** `docs/architecture/house-03-appliance-catalog.md`, `docs/modules/energy.md`, `docs/modules/billing.md`, `docs/architecture/contracts.md`.

## Global Constraints

- Preserve F0 contract models and authorization dependencies.
- Never equate owner, user, or payer; P4 remains responsible for attribution.
- Keep physical MCP identifiers private and prevent tenant-supplied physical device IDs.
- Preserve closed historical rows and use half-open UTC intervals.
- Do not implement NILM, billing, MCP controls, or HOUSE-04.

## Review Focus

- Closed temporal rows can overlap after direct SQL writes; reject overlap at SQL level.
- A consumption ending after a context transition cannot inherit its start-time owner for the whole event; return explicit segments and no single context.
- Failed interval changes must roll back the old-row closure and new-row insert together.
- Replay and concurrent same-time writes must not corrupt history or rewrite the past.
- Ex-member history and cross-house identifiers must remain readable only through authorized scoped queries.

---

### Task 1: Temporal invariants and atomic writes

**Files:**
- Modify: `app/backend/src/homemind/core/migrations/0101_house_appliance_catalog.sql` (or add a forward correction migration if the migration is already released)
- Modify: `app/backend/src/homemind/features/appliances/repo.py`
- Test: `app/backend/src/homemind/features/appliances/tests/test_catalog.py`

**Interfaces:** Keep existing public commands. SQLite must reject any overlapping state or meter-link intervals for one appliance.

- [x] Add tests for overlap, exact boundaries, same-timestamp concurrent transitions, rollback, idempotent replay, and interval stability after reopen.
- [x] Run focused tests and confirm the new invariants fail on the existing implementation.
- [x] Add SQLite overlap guards and make context changes atomic/idempotent where the command is replayed.
- [x] Run focused tests and the backend checks.

### Task 2: P1/P4 historical query semantics

**Files:**
- Modify: `app/backend/src/homemind/features/appliances/repo.py`
- Modify: `docs/architecture/house-03-appliance-catalog.md`
- Modify: `docs/modules/energy.md`
- Modify: `docs/modules/billing.md`
- Test: `app/backend/src/homemind/features/appliances/tests/test_catalog.py`

**Interfaces:** Add a segment query for identified consumption events. Each segment contains `[start, end)` and ownership context or no context. `context_for_consumption` returns one ownership only if the full event has one stable context; unknown, retired, missing, or cross-transition context yields no single owner.

- [x] Add tests for unknown matches, retirement, historical owner transfer, location/scope transitions, and an event crossing a transition.
- [x] Run focused tests and confirm crossing events cannot return one unique owner.
- [x] Implement segment/context queries with batched SQL and no attribution decision.
- [x] Document P1 matching/meter semantics and P4 consumption context, ambiguity, and no-retroactivity.

### Task 3: Authorization, integration, and delivery

**Files:**
- Modify as needed: `app/backend/src/homemind/features/appliances/{repo.py,router.py,schemas.py}`
- Test: `app/backend/src/homemind/features/appliances/tests/test_catalog.py`
- Modify: `docs/architecture/house-03-appliance-catalog.md`
- Update: PR #142 description and review requests

- [x] Add tests for two-house device/room/owner isolation, tenant physical-device restrictions, demo-only device creation, and departed-member history.
- [x] Run focused tests, `make check`, and inspect the full diff against the current `origin/main`.
- [ ] Record the invariant/protection/test matrix, HOUSE-02/HOUSE-04 impact, and any pending decisions in the PR.
- [ ] Request P1 and P4 validation on PR #142; do not merge or close #86.

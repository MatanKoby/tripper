# Claims

Execution-state ledger, managed by coding agents. Records who is working on what and the recent
completion log. The user does not normally edit this. Procedures:
`specflow/procedures/claim-batch.md` and `specflow/procedures/finish-batch.md`.

Entry format:

```
### Batch N — <short title>
- Owner: <agent>
- Started: YYYY-MM-DD HH:MM        (UTC)
- Finished: YYYY-MM-DD HH:MM       (only in Completed)
- Commit: <short SHA>              (only in Completed)
- Handoff note: ...                (only when a mid-batch handoff occurred)
```

## In progress

<!-- One entry per actively claimed batch. -->

### Batch 6 — Firestore security rules + config seed
- Owner: claude
- Started: 2026-07-12 19:12

## Completed

### Batch 1 [MANUAL] — Provision GCP/Firebase, Vercel, GitHub
- Owner: Matan (user)
- Started: 2026-07-12
- Finished: 2026-07-12
- Commit: n/a (external console/CLI setup, no in-repo files)

**What shipped.** The external infrastructure M1 runs on, provisioned by the user in the GCP/Firebase,
Vercel, and GitHub consoles (no code — `spec/architecture.md`, region `us-central1`). Per the batch
checklist: GCP project with Firebase enabled; Firestore in Native mode at `us-central1`; Firebase Auth
with the Google provider + OAuth consent screen; the `config/access` doc seeded with the owner allowlist
(`spec/access.md`); GitHub repo secrets (`NEBIUS_API_KEY`, `NEBIUS_ENDPOINT_URL`, `NEBIUS_ENDPOINT_ID`,
plus GCP deploy auth); and a Vercel project linked to `web/` with the Firebase web config exposed as
`VITE_FIREBASE_*` env vars. These values feed Batch 7 (frontend Firebase config) and Batch 8 (deploy
auth, which finalizes the GCP deploy mechanism). Marked done by the user; not agent-verified.

### Batch 5 — Sweeper (scheduled) + index
- Owner: claude
- Started: 2026-07-12 16:07
- Finished: 2026-07-12 16:39
- Commit: 5ce5384

**What shipped.** The scheduled sweeper that recovers jobs stranded in `running` after a hard crash
(`spec/flows.md` under *Sweeper*). `tripper/sweeper.py`'s `sweep(db, *, clock, max_attempts)` queries
`collection_group("trips")` for `status == "running"` AND `leaseExpiresAt < now` (via `FieldFilter`),
materializes the hits, and per doc runs `_reap_one`: a `@firestore.transactional` mutation that
**re-applies the guard** (still `running` AND lease still expired) before acting, then re-queues to
`pending` when `attempts < maxAttempts`, else writes a terminal `error` (`TripError` kind
`"LeaseExpired"`, `lastError` set). The re-check means a job the orchestrator reclaims between the
query and the write is left alone, not clobbered back to `pending`. The sweeper does not bump
`attempts` (the next `claim_job` does) and reuses `tripper.jobs` vocabulary (`_lease_expired`,
`DEFAULT_MAX_ATTEMPTS`, `Clock`, `utcnow`) plus the `TripError` contract type; it never touches the
orchestrator internals or `jobs.py`. `sweep` returns a `SweepReport(scanned, requeued, failed,
skipped)` and never raises for one bad doc (logged + counted `skipped`). `main.py` registers
`sweep_stuck_jobs` via `@scheduler_fn.on_schedule(schedule="every 5 minutes")` (region defaults to
`us-central1`; the Cloud Scheduler job is created at deploy time in Batch 8). `firestore.indexes.json`
defines the required composite index (`trips`, `COLLECTION_GROUP`, `status` + `leaseExpiresAt` ascending).

**Tests / verification.** `tests/test_sweeper.py` (8 tests) drives it against the Firestore emulator
(reuses `tests/conftest.py`): stale `running` → `pending` (attempts not bumped); exhausted attempts →
terminal `LeaseExpired` error; missing `maxAttempts` → `DEFAULT_MAX_ATTEMPTS` fallback; live-lease
`running` untouched; `done`/`error`/`pending` docs ignored; `running` with no lease not reaped;
collection-group scope spans users and partitions outcomes; empty sweep is a zero `SweepReport`.
Full suite: `pytest` 40 passed (5 config + 17 contract + 10 orchestrator + 8 sweeper), `ruff check`
clean, `python -m compileall` OK, and `main.py` imports with `sweep_stuck_jobs` registered. Requires
the `functions` extra + firebase CLI/Java for the emulator tests (no manual prereqs). Note: the
emulator does not enforce composite indexes, so the query runs in tests without the deployed index.
Follow-ups: deploying the index and creating the scheduler job are Batch 8. A re-queued `pending` job
is not re-triggered by `onCreate` (which fires on create only); how M1 re-invokes the orchestrator on
a swept-back job is not wired in this batch and is left to a later batch/spec decision.

### Batch 4 — Orchestrator + Firestore onCreate trigger
- Owner: claude
- Started: 2026-07-12 13:51
- Finished: 2026-07-12 14:40
- Commit: 583b20d

**What shipped.** The Firestore-triggered orchestrator with the M1 reliability machinery
(`spec/flows.md`). `tripper/agents/base.py` defines the `Agent` adapter interface (the orchestrator
sees only this + the contract; `name` is the transport slot, e.g. `"hotel"`). `tripper/jobs.py`
holds the doc-state primitives: `claim_job` (a `@firestore.transactional` claim that proceeds only
if `pending` OR `running` with an expired lease, then sets `running`/`startedAt`/`attempts += 1`/
`leaseExpiresAt` and seeds `maxAttempts`), `lease_heartbeat` (a daemon-thread context manager that
bumps `leaseExpiresAt` every 45s; Firestore write only, never pings the agent), and
`write_done`/`write_error`. `tripper/orchestrator.py`'s `run_job` strings them together: claim →
(skip if not claimed) → run agents under the heartbeat → validate output against the contract
(`HotelPayload` + `TripSuggestions`) → `write_done`, with a catch-all that persists `error` +
`lastError` and never lets the handler crash (so no redelivery storm; hard crashes fall to the
lease + sweeper). `main.py` is the composition root: `initialize_app()`, the
`on_document_created("users/{userId}/trips/{tripId}")` entrypoint, and a `build_active_agents(settings)`
seam that returns `[]` until Batch 10 registers the hotel adapter (kept out of the reliability core).
Tuning constants: `LEASE_BUDGET` 15 min, `HEARTBEAT_INTERVAL` 45s, `DEFAULT_MAX_ATTEMPTS` 3.

**Tests / verification.** `tests/test_orchestrator.py` (10 tests) runs against the Firestore emulator
via an in-test fake agent (not a shipped mock). `tests/conftest.py` self-starts a firestore-only
emulator on a `demo-tripper` project (reuses `FIRESTORE_EMULATOR_HOST` / an already-listening port;
skips cleanly if the CLI/emulator is unavailable) and resets data per test. Covers: pending→done,
duplicate delivery does not double-run, live-lease running is skipped, expired-lease running is
reclaimed (attempts→2), agent exception → `error`, invalid agent output → `error` (contract
validation), malformed input → `error` before any agent runs, claim seeds reliability fields, missing
doc not claimed, heartbeat bumps the lease. Full suite: `pytest` 32 passed (5 config + 17 contract +
10 orchestrator), `ruff check` clean, `python -m compileall` OK, and `main.py` imports with the
trigger endpoint registered. Requires the `functions` extra (`pip install -e '.[functions]'`) plus
the firebase CLI + Java for the emulator tests. No manual prereqs. Follow-ups: `requirements.txt` /
`.gcloudignore` are Batch 8 (deploy); the real hotel adapter + agent registration is Batch 10; the
sweeper reuses these `jobs.py` helpers in Batch 5.

### Batch 3 — Agent contract types
- Owner: claude
- Started: 2026-07-12 11:06
- Finished: 2026-07-12 12:22
- Commit: 302b280

**What shipped.** The tripper/agent contract in `tripper/contract.py` (`spec/schema.md`): request
types (`TripInput` + `Place`/`Stay`/`Guests`/`Filters`), the agent response payload (`HotelPayload`
+ `Pick`/`Offer`/`Resolved`/`Diagnostics`), the transport wrapper (`TripSuggestions` + `TripError`),
and shared types (`Room`, `GeoPoint`) + enums (`Amenity`, `LensName`, `AgentStatus`,
`TransportStatus`). All models are strict (`extra="forbid"`) pydantic v2 and share a `_Model` base
with `from_dict` / `to_dict` Firestore round-trip helpers (dates as ISO strings, enums as values,
`GeoPoint` as a `{lat, lon}` dict). Validation: `place` requires a locator (text | city+country_code
| center), `stay.check_out > check_in`, filter range bounds (`min_star` 1..5, `min_guest_rating`
0..10), `Pick.score` 0..1, and `TripSuggestions` status/error/hotel consistency. `tests/test_contract.py`
(17 tests) round-trips full docs and asserts the rejection cases. Verified: `pytest` 22 passed
(5 config + 17 contract), `ruff check` clean. No manual prereqs. Unblocks Batches 4, 6, 10.

<!-- Recent finishes, newest first. Older entries archived to specflow/history/CLAIMS_DONE.md. -->

### Batch 2 — Repo skeleton & tooling
- Owner: claude
- Started: 2026-07-11 21:01
- Finished: 2026-07-12 05:46
- Commit: 2352813

**What shipped.** Backend Python package skeleton and tooling. `pyproject.toml` (hatchling build,
ruff + pytest; pydantic/pydantic-settings core, firebase-admin/firebase-functions as a `functions`
extra). `tripper/config.py` provides `Settings`: loads agent + Firebase config from env, splits
`ENABLED_PROVIDERS`, validates that `liteapi`/`llm` selections have the config they need (raising
`ConfigError`), and exposes `agent_env()` for the future hotel adapter. `tests/test_config.py`
(5 tests, green). `firebase.json` + `.firebaserc` set up the Firestore + Auth emulators.
`.env.example` documents the backend vars. Verified: `ruff check` clean, `pytest` 5 passed,
editable install works. No manual prereqs. Deploy files (`main.py`, `requirements.txt`,
`.gcloudignore`) deferred to Batch 4/8.

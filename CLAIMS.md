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

### Batch 7 — Frontend wireframe (Vite + React)
- Owner: claude
- Started: 2026-07-13 16:35

## Completed

### Batch 10 — Hotel adapter + vendor submodule
- Owner: claude
- Started: 2026-07-13 12:58
- Finished: 2026-07-13 13:54
- Commit: d32235b

**What shipped.** The real hotel agent wired as the Accommodation agent (`spec/schema.md`,
`spec/agents.md`). `vendor/agents/hotel-finder-agent` added as an HTTPS git submodule
(`https://github.com/MatanKoby/hotel-finder-agent.git`, tracking `dev`, pinned at `c739d64`); its
package is `hotel_finder` (src layout). `tripper/agents/hotel_adapter.py`'s `HotelAdapter(Agent)`
(transport slot `"hotel"`) is the one place that knows the agent's API: `_to_request` maps
`TripInput` to the agent's `HotelSearchRequest` field-by-field (expanding `guests` into a single room
when `stay.rooms` is null; a set `stay.rooms` overrides `guests`; `guest_nationality` is trip-level on
both sides, mapped request-level → request-level; amenities list → set, lenses/filters/place/center
carried across), `_agent_settings` builds the agent's `Settings` from tripper's config via
`Settings.agent_env()` (lower-cased keys as init kwargs; empty values dropped so the agent keeps its
keyless `mock`+`heuristic` defaults), `run` calls the agent's `search_sync`, and `_to_payload` maps
`HotelSearchResponse` back by dumping to JSON, dropping the `request_id` echo, and re-validating
against tripper's `HotelPayload` (so upstream drift fails loudly at the boundary). Registered in
`main.build_active_agents` via a **function-local** import of `HotelAdapter`, so importing `main`
never requires the submodule (resolved at trigger time, where the deploy has vendored it).

**Tests / verification.** `tests/test_hotel_adapter.py` (10 tests) is non-e2e (agent on `mock`
provider + `heuristic` scorer, no keys/LLM); the module `pytest.importorskip`s `hotel_finder` so it
skips cleanly where the submodule is not installed (prereq: `pip install -e
vendor/agents/hotel-finder-agent`, which pulls `openai`+`httpx`). Covers both mapping directions
(guests→room expansion, rooms-override, request-level `guest_nationality`, place/filters/lenses,
lenses-None passthrough, response→payload with `request_id` dropped), `_agent_settings` from tripper
config, a full `HotelAdapter.run` yielding a populated `HotelPayload`, and an emulator-backed
`run_job([HotelAdapter])` round-trip driving a pending doc to `done` with `results.hotel` populated
(the batch's "orchestrator produces `TripSuggestions.hotel`" check). Full suite: `pytest` 50 passed
(40 prior + 10), `ruff check` clean, `compileall` OK, `main` imports with both triggers registered
and `build_active_agents` returning `[HotelAdapter("hotel")]`. Prereqs: the submodule installed
editable (as above) + the firebase CLI/Java for the emulator-backed test (skips without them).
Follow-ups: **spec/schema.md is inaccurate** — its prose says the adapter maps `guest_nationality`
to the agent's `stay.guest_nationality`, but the agent's `Stay` has no such field; it is request-level
on both sides (the code is correct). Left for the user to confirm before a `spec:` fix (surfaced, not
freelanced). Deploy packaging of the submodule into the Cloud Function is Batch 8; the submodule-bump
gate (Batch 9) now has real test targets.

### Batch 9 — vendor/agents read-only guardrails + bump gate
- Owner: claude
- Started: 2026-07-12 19:30
- Finished: 2026-07-13 12:31
- Commit: 6a3db30

**What shipped.** The read-only guardrails for vendored agents and the submodule-bump verification
gate (`spec/agents.md`). `.claude/settings.json` (new, project-level, team-wide) adds a
`permissions.deny` for `Edit`/`Write`/`NotebookEdit` under `vendor/agents/**` and a `PreToolUse` hook
(matcher `Edit|Write|NotebookEdit|MultiEdit|Bash`) that runs `scripts/vendor_agents_guard.sh`. The
guard reads the hook payload on stdin and emits a PreToolUse `deny` decision (never a hook error) when
a call would edit a file inside `vendor/agents/**` or run a mutation there via Bash: shell redirects
(`>`/`>>`), `sed -i`, destructive file utils (`rm rmdir mv cp tee dd truncate chmod chown touch ln`),
or a git write-command operating with the submodule as its repo (`git -C vendor/agents/… <write>` or
`cd vendor/agents/… && git <write>`). It deliberately allows pointer advances (`git submodule update
--remote`, `git add` of the gitlink from the superproject) and all read-only inspection (cat/ls/grep/
`git log`/`git diff`/`compileall`), so the legitimate bump flow is never blocked. Path matching handles
absolute, relative, and `./`-prefixed forms; jq-missing fails open (the deny rule still applies).
`scripts/submodule_bump_gate.sh` implements the gate: compile-check (`python -m compileall`) + the
submodule's non-e2e tests (`pytest -m "not e2e"`, `cd` into the submodule) + tripper's adapter/contract
tests (`pytest -k "adapter or contract"` from root). Default (local) mode rolls the pointer back
(`restore --staged` + `git submodule update --init --checkout`) and commits nothing on failure, and
commits the validated bump on its own on green (`meta: bump … to <short>`); `--check-only` (CI) validates
only, no git mutation. Env knobs: `PYTHON`, `SUBMODULE_TEST_CMD`, `TRIPPER_TEST_ARGS`, `BUMP_COMMIT_PREFIX`.
Absent/unchecked-out submodule → `--check-only` skips cleanly (exit 0). `.github/workflows/submodule-gate.yml`
runs the gate `--check-only` on any push/PR touching `.gitmodules` or `vendor/agents/**` (also the gate
script / workflow itself), with `submodules: recursive`, `setup-python@v5` (3.12), `pip install -e '.[dev]'`,
and a best-effort editable install of the submodule.

**Tests / verification.** The guard was pipe-tested against a 20+ case block/allow matrix (all green):
blocks Edit/Write/NotebookEdit under `vendor/agents/**`, shell redirect/`sed -i`/`rm`/`mv`/`touch` into
the path, and `git -C`/`cd &&` git-writes inside the submodule; allows the pointer bump, `git add` of the
gitlink, `git log/diff`, `compileall`, `pip install -e`, and unrelated commands. **Live proof:** a `Write`
to `vendor/agents/hotel-finder-agent/__guard_probe__.txt` in-session was denied ("File is in a directory
that is denied by your permission settings"), with no file/dir created. The gate was exercised against
throwaway fixtures: a syntax-error module → `GATE FAILED` (rc 1); a clean module with an `e2e`-marked test
→ `GATE PASSED` (rc 0) with the e2e test deselected; absent submodule → clean skip; `--help` renders;
unknown option → rc 2. Full repo unchanged and green: `pytest` 40 passed, `ruff check` clean, both scripts
`bash -n` OK, workflow YAML parses. Prereqs: `jq` (guard) and, for the gate, a Python with `pytest`
(the repo `.venv`, or the deps the CI workflow installs). Notes/follow-ups: the guard's Bash heuristics are
conservative (e.g. `cp` out of the submodule is blocked); this batch adds a 4th file beyond the three the
queue listed — `scripts/vendor_agents_guard.sh` — because embedding the hook logic inline in JSON would be
unmaintainable. The real submodule + adapter arrive in Batch 10, at which point the gate's check 2/3 run
against actual tests; the workflow triggers only once `.gitmodules`/`vendor/agents/**` exist.

### Batch 6 — Firestore security rules + config seed
- Owner: claude
- Started: 2026-07-12 19:12
- Finished: 2026-07-12 19:20
- Commit: 7c7c73b

**What shipped.** The client-side Firestore security rules enforcing ownership + the access allowlist
at the DB layer (`spec/access.md`). `firestore.rules` ports the spec's rules verbatim: `accessOk()`
reads `config/access` via `get()` and returns true only for a verified email that the config admits
(`mode == 'open'`, or the lowercased email is in `allowedEmails`) — a missing `config/access` makes the
`get()` fail, so it denies (fail closed); `match /config/{doc}` denies all client read/write (admin/
console only); `match /users/{uid}/trips/{tripId}` allows `read` only to the owner (`request.auth.uid
== uid`), `create` only for a clean `pending` doc (own path, `status == "pending"`, no `results`,
`accessOk()`), and denies `update`/`delete` (the backend transitions docs via the Admin SDK, which
bypasses rules). `firebase.json` gains a `firestore` block pointing at `firestore.rules` +
`firestore.indexes.json` (loads real rules into the emulator; Batch 8's CI does the actual deploy).

**Tests / verification.** `tests/rules/` is a JS harness using Firebase's official
`@firebase/rules-unit-testing` (v4) + `firebase` (v11) — the only supported way to unit-test rules; the
Python Admin SDK bypasses them. `npm test` wraps `node --test` in `firebase emulators:exec --only
firestore --project demo-tripper` (fake project, fully offline; the firebase CLI walks up to the
repo-root `firebase.json`). 15 cases, all green: allowlisted create allowed; non-allowlisted denied;
`open` mode admits any verified user; unverified email denied; unauthenticated denied; missing config
fails closed; non-`pending` status denied; `results` present denied; create under another user's path
denied; owner read allowed; cross-user read denied; client update denied; client delete denied;
client read + write of `config/access` denied. Full check: 15 rules tests + 40 pytest (unchanged) pass,
`ruff check` clean. Prereqs: Node/npm (`cd tests/rules && npm install`) plus the firebase CLI + Java
(already needed by the pytest emulator suite); `node_modules/` is gitignored, `package-lock.json`
committed. Note: the emulator does not enforce composite indexes, and `accessOk()`'s `get()` is not
metered in tests. Follow-ups: deploying the rules + creating the allowlist doc live are Batch 1
(seeded) / Batch 8 (deploy); the backend's defense-in-depth re-check of allowlist membership
(`spec/access.md`) lives with the orchestrator, not these client rules.

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

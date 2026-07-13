# Build Queue — Completed History

One-paragraph summaries of every shipped batch, newest at the top. Skim this for context when
picking a new claim. The full implementation history is in `git log` + `specflow/history/CLAIMS_DONE.md`.

<!-- Append a summary here when you finish a batch (see specflow/procedures/finish-batch.md).
     Format, e.g.:

## Batch 1 — <title>
Shipped <what> in <where>. Key commit `<sha>`. <One line on any follow-up deferred.>
-->

## Batch 7 — Frontend wireframe (Vite + React)
Shipped the client-side wireframe end to end in `web/` (`spec/ui.md`), an unstyled Vite + React (TS)
SPA that talks only to Firebase. `firebase.ts` inits Auth/Firestore from `VITE_FIREBASE_*` (with a
`VITE_USE_EMULATOR` local-dev path to the emulators); `types.ts` mirrors `tripper/contract.py`;
`buildTripInput.ts` maps the form to a clean `TripInput` enforcing the contract's client-side
invariants; `useAuth` (Google sign-in) + `useJob` do the flow (`spec/flows.md`): auto-id ref under
`users/{uid}/trips`, listen, then write `{ input, status:"pending" }`. `TripForm`/`Accommodation`/`App`
are the three-column frame — only Accommodation populated, rendering `results.hotel.lenses` on `done`
(the queue's `results.hotel.items` was drift; the contract has no `items`), the message on `error`, and
a warming-up state while `pending`/`running`. Verified: `npm run build`/`typecheck` green; the TS
builder's `TripInput`s cross-validated against Python `tripper.contract`; an emulator round-trip against
the real `firestore.rules` confirmed the exact `useJob` write shape is allowed for an allowlisted user,
denied otherwise, and the `done`/`error` transitions propagate to the listener. Key commit `e46891b`.
Live Vercel deploy + the web config as Vercel env vars is Batch 8 (+ Batch 1).

## Batch 10 — Hotel adapter + vendor submodule
Wired the real hotel agent as the Accommodation agent (`spec/schema.md`, `spec/agents.md`). Added
`vendor/agents/hotel-finder-agent` as an HTTPS git submodule (tracking `dev`, pinned `c739d64`; package
`hotel_finder`) and `tripper/agents/hotel_adapter.py`: `HotelAdapter` (slot `"hotel"`) maps `TripInput`
→ the agent's `HotelSearchRequest` (guests expand into one room when `stay.rooms` is null; a set
`stay.rooms` overrides; `guest_nationality` is request-level on both sides), builds the agent's
`Settings` from tripper config via `agent_env()`, calls `search_sync`, and maps `HotelSearchResponse`
→ `HotelPayload` (drops the `request_id` echo, re-validates against tripper's contract). Registered in
`main.build_active_agents` via a function-local import so `main` imports without the submodule.
`tests/test_hotel_adapter.py` (10 tests, `importorskip`s `hotel_finder`) covers both mapping
directions, settings, a full mock+heuristic run, and an emulator-backed `run_job` round-trip to `done`
with `results.hotel`. 50 pytest passed, ruff clean. Key commit `d32235b`. Note: `spec/schema.md` prose
still says `guest_nationality` maps to the agent's `stay.guest_nationality`, but that field does not
exist on the agent's `Stay` (it is request-level); flagged for a user-confirmed `spec:` fix. Submodule
deploy packaging is Batch 8.

## Batch 1 [MANUAL] — Provision GCP/Firebase, Vercel, GitHub
Provisioned by the user (no in-repo code) the external infrastructure M1 runs on (`spec/architecture.md`,
region `us-central1`): a GCP project with Firebase enabled, Firestore in Native mode at `us-central1`,
Firebase Auth with the Google provider, the `config/access` allowlist doc (`spec/access.md`), GitHub
repo secrets (`NEBIUS_*` + GCP deploy auth), and a Vercel project linked to `web/` with `VITE_FIREBASE_*`
env vars. Values feed Batch 7 (frontend Firebase config) and Batch 8 (deploy auth). No commit
(external console/CLI setup); marked done by the user, not agent-verified.

## Batch 9 — vendor/agents read-only guardrails + bump gate
Shipped the read-only guardrails for vendored agents and the submodule-bump verification gate
(`spec/agents.md`). `.claude/settings.json` (new) denies `Edit`/`Write`/`NotebookEdit` under
`vendor/agents/**` and adds a `PreToolUse` hook running `scripts/vendor_agents_guard.sh`, which emits a
`deny` decision for edits or git/file mutations inside the submodule (redirects, `sed -i`, `rm`/`mv`/…,
`git -C`/`cd &&` git-writes) while allowing pointer advances (`git submodule update --remote`, `git add`
of the gitlink) and read-only inspection. `scripts/submodule_bump_gate.sh` compile-checks the submodule,
runs its non-e2e tests + tripper's adapter/contract tests, rolls the pointer back on failure and commits
the bump on green; `--check-only` validates without mutating (CI). `.github/workflows/submodule-gate.yml`
runs the gate `--check-only` on any push/PR touching `.gitmodules` or `vendor/agents/**`. Verified by a
20+ case guard pipe-test, a live-denied `Write` under `vendor/agents/`, and gate runs against broken/clean
fixtures (fail rc 1 / pass rc 0 with e2e deselected); 40 pytest + ruff still green. Key commit `6a3db30`.
Adds a 4th file beyond the three the queue listed (`scripts/vendor_agents_guard.sh`, the hook helper).
The real submodule + adapter (and thus the gate's live test targets) arrive in Batch 10.

## Batch 6 — Firestore security rules + config seed
Shipped the client-side Firestore security rules enforcing ownership + the access allowlist at the DB
layer (`spec/access.md`). `firestore.rules` ports the spec verbatim: `accessOk()` reads `config/access`
via `get()` (fail-closed if missing) and admits only a verified email under `open` mode or on the
lowercased `allowedEmails`; `config/**` is locked from all clients; `users/{uid}/trips/{tripId}` allows
owner-only `read` and a create-only clean `pending` doc (own path, no `results`, `accessOk()`), denying
`update`/`delete` (the Admin SDK backend bypasses rules). `firebase.json` gains a `firestore` block
(rules + `firestore.indexes.json`). `tests/rules/` is a JS harness using Firebase's official
`@firebase/rules-unit-testing` (the only supported rules-test tool; Python's Admin SDK bypasses rules),
run via `firebase emulators:exec ... node --test` — 15 cases green (allowlist gate, open mode, unverified/
unauthenticated/fail-closed denials, shape guards, cross-user read, update/delete, config lockout);
40 pytest unchanged, ruff clean. Key commit `7c7c73b`. Live deploy of rules + seeding the allowlist doc
are Batch 1 (seeded) / Batch 8 (deploy); the backend's defense-in-depth allowlist re-check lives with
the orchestrator, not these client rules.

## Batch 5 — Sweeper (scheduled) + index
Shipped the scheduled sweeper that recovers jobs stranded in `running` after a hard crash
(`spec/flows.md`): `tripper/sweeper.py`'s `sweep()` queries `collection_group("trips")` for
`status == "running"` AND `leaseExpiresAt < now` and, per doc, runs a transactional `_reap_one` that
re-applies the guard then re-queues to `pending` (attempts remain) or writes a terminal `LeaseExpired`
error (attempts exhausted), returning a `SweepReport`. Reuses `tripper.jobs` (`_lease_expired`,
`DEFAULT_MAX_ATTEMPTS`) and the `TripError` contract; never touches the orchestrator or `jobs.py`.
`main.py` registers `sweep_stuck_jobs` via `@scheduler_fn.on_schedule("every 5 minutes")` (default
region `us-central1`); `firestore.indexes.json` defines the composite index the query needs.
`tests/test_sweeper.py` (8 tests) drives it against the emulator; full suite 40 passed, ruff clean.
Key commit `5ce5384`. Index deploy + Cloud Scheduler job are Batch 8; re-invoking the orchestrator on
a swept-back `pending` job (onCreate fires on create only) is left to a later batch.

## Batch 4 — Orchestrator + Firestore onCreate trigger
Shipped the Firestore-triggered orchestrator with the M1 reliability machinery (`spec/flows.md`):
`tripper/agents/base.py` (the `Agent` adapter seam), `tripper/jobs.py` (`claim_job` transactional
idempotent claim on pending-or-expired-lease, `lease_heartbeat` daemon bump, `write_done`/
`write_error`), `tripper/orchestrator.py` (`run_job`: claim → run agents under the heartbeat →
validate against the contract → terminal write, with a non-crashing catch-all), and `main.py`
(`on_document_created` entrypoint + a `build_active_agents` seam that is empty until Batch 10).
`tests/test_orchestrator.py` (10 tests) drives it against a self-started Firestore emulator with an
in-test fake agent; full suite 32 passed, ruff clean. Key commit `583b20d`. `requirements.txt`/
`.gcloudignore` deferred to Batch 8; hotel adapter registration is Batch 10; the sweeper (Batch 5)
reuses `jobs.py`.

## Batch 3 — Agent contract types
Shipped the tripper/agent contract in `tripper/contract.py` (`spec/schema.md`): request types
(`TripInput` + `Place`/`Stay`/`Guests`/`Filters`), the agent response payload (`HotelPayload` +
`Pick`/`Offer`/`Resolved`/`Diagnostics`), the `TripSuggestions` transport wrapper (+ `TripError`),
and shared types/enums (`Room`, `GeoPoint`, `Amenity`, `LensName`, `AgentStatus`, `TransportStatus`).
Strict (`extra="forbid"`) pydantic v2 models on a `_Model` base with `from_dict`/`to_dict` Firestore
round-trip helpers; validators enforce a required place locator, date ordering, filter/score range
bounds, and transport status/error/hotel consistency. `tests/test_contract.py` (17 tests) covers
round-trips and rejections. Key commit `302b280`. Unblocks Batches 4, 6, 10.

## Batch 2 — Repo skeleton & tooling
Shipped the backend Python package skeleton and tooling: `pyproject.toml` (hatchling, ruff +
pytest, pydantic/pydantic-settings core with a `functions` extra), `tripper/config.py` (`Settings`
with env loading, `ENABLED_PROVIDERS` split, `liteapi`/`llm` validation via `ConfigError`, and
`agent_env()` for the hotel adapter), `tests/test_config.py` (5 green), and the Firestore + Auth
emulator config (`firebase.json`, `.firebaserc`, `.env.example`). Key commit `2352813`. Deploy files
(`main.py`, `requirements.txt`, `.gcloudignore`) deferred to Batch 4/8.

# Build Queue

Reference spec: [`spec/`](spec/README.md)
Agent work tracking: `CLAIMS.md` (managed by coding agents)
Completed history: [`specflow/history/BUILD_QUEUE_DONE.md`](specflow/history/BUILD_QUEUE_DONE.md) — one-paragraph summaries of shipped batches.

## How this works

- This file lists only **un-done batches**, in full. Completed batches collapse to summaries
  in `specflow/history/BUILD_QUEUE_DONE.md` (git log + `specflow/history/CLAIMS_DONE.md` hold the implementation history).
- Dependencies are listed where they exist — the agent decides execution order.
- Agents claim and track completion in `CLAIMS.md`. **No Owner / Started / Status ever goes in
  this file** — that's execution state, and it lives in `CLAIMS.md` only.
- Batches are designed so two agents can work different batches at once without file conflicts.
- See `specflow/procedures/claim-batch.md` before claiming.

---

## Un-done batches

> **Pick-order pointer for "continue".** Milestone goal: a vertical slice where the UI submits a
> trip, the hotel agent runs, and results render (live on Vercel). Critical path:
> 10 (needs 9 first) → 7, with Batch 1 (`[MANUAL]`, user-run) and Batch 8 (deploy) making it live.
> Batches 2, 3, 4, 5 are done. Batches 6, 9 are claimable now; 10 (hotel adapter) is unblocked
> (needs 9); then 7; then 8. When the user says "continue" after a context clear, ask which batch to
> claim.

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

---

## Batch 1 [MANUAL] — Provision GCP/Firebase, Vercel, GitHub

**Depends on:** none. Runs alongside the code batches; only the deploy batch (8) and a live FE need it.

**Goal.** Stand up the external infra M1 runs on. The user performs these in the consoles/CLI; no
code. Region is `us-central1` throughout (`spec/architecture.md`).

### Deliverables (checklist)
- **GCP project** created, with **Firebase enabled** on it.
- **Firestore** in **Native mode**, location **`us-central1`** (regional, permanent).
- **Firebase Auth** enabled with the **Google** provider; OAuth consent screen configured.
- **`config/access`** doc seeded: `{ "mode": "allowlist", "allowedEmails": ["<your-email-lowercased>"] }`
  (`spec/access.md`).
- **GitHub repo secrets**: `NEBIUS_API_KEY`, `NEBIUS_ENDPOINT_URL`, `NEBIUS_ENDPOINT_ID`, plus GCP
  deploy auth (Workload Identity Federation preferred, or a service-account key) — auth mechanism
  finalized in Batch 8.
- **Vercel project** linked to this repo, root set to `web/`, with the Firebase web config exposed
  as `VITE_FIREBASE_*` env vars.

### Files this batch creates/edits
- None in-repo (external console/CLI setup). Values feed Batches 7 and 8.

### Verification
- Google sign-in works in a scratch test; `config/access` visible in the Firestore console; all
  GitHub secrets present; Vercel project builds a placeholder.

---

## Batch 6 — Firestore security rules + config seed

**Depends on:** Batch 3 (doc shape).

**Goal.** Enforce ownership + the access allowlist at the DB layer (`spec/access.md`).

### Deliverables
- `firestore.rules` matching `access.md`: `accessOk()` (verified email + allowlist/open),
  `config/**` locked from clients, `trips` create/read only, no client update/delete.
- Rules unit tests on the emulator.

### Files this batch creates/edits
- `firestore.rules`, `tests/rules/` (rules tests).

### Does NOT touch
- Python backend, `web/`.

### Verification
- Rules tests: non-allowlisted create denied; allowlisted allowed; `open` mode allows any verified
  user; cross-user read denied; client update/delete denied.

---

## Batch 7 — Frontend wireframe (Vite + React)

**Depends on:** Batch 3 (shapes); Batch 1 (Firebase web config).

**Goal.** The client-side wireframe end to end (`spec/ui.md`).

### Deliverables
- Vite + React (TS) SPA; Google sign-in (`spec/access.md`).
- Three-column layout: left tab scroll-nav (Flights / Accommodation / Activities), center a container
  per section (only Accommodation populated; the others "coming soon"), right the trip-input form +
  submit + job-status indicator.
- On submit, writes the job doc and listens; renders `results.hotel.items` on `done`, the message on
  `error`, and a "thinking / warming up" state while `pending`/`running`.

### Files this batch creates/edits
- `web/` (the whole Vite app).

### Does NOT touch
- Python backend, `firestore.rules`.

### Verification
- Against the emulator or the real project: sign in, submit, a seeded `done` doc renders; an `error`
  doc shows its message.

---

## Batch 8 — CI/CD (GitHub Actions)

**Depends on:** Batches 4, 5, 6, 7, and Batch 1.

**Goal.** Automated deploys for backend and frontend.

### Deliverables
- Backend workflow deploys the orchestrator + sweeper to Cloud Functions Gen2 (`us-central1`) with
  `submodules: recursive` and `--set-env-vars` from GitHub Secrets; deploys `firestore.rules` +
  indexes; creates/updates the Cloud Scheduler job for the sweeper.
- Frontend deploy to Vercel.
- GCP deploy auth finalized here (Workload Identity Federation recommended; SA key acceptable).

### Files this batch creates/edits
- `.github/workflows/backend.yml`, `.github/workflows/frontend.yml` (or Vercel git integration),
  any deploy scripts.

### Does NOT touch
- Application logic.

### Verification
- A push to `dev` deploys; functions live in `us-central1`; rules active; the scheduler job exists.

---

## Batch 9 — vendor/agents read-only guardrails + bump gate

**Depends on:** none. (The actual submodule add is in Batch 10.)

**Goal.** Enforce the read-only rule and the submodule-bump verification gate (`spec/agents.md`).

### Deliverables
- `.claude/settings.json` deny for `Edit`/`Write` under `vendor/agents/**`, plus a `PreToolUse` hook
  blocking edits and git-mutations there.
- A bump-gate script: compile-check + the submodule's non-e2e tests + tripper's adapter/contract
  tests, rolling the pointer back on failure.
- A CI job running the gate on any submodule-pointer change.

### Files this batch creates/edits
- `.claude/settings.json`, `scripts/submodule_bump_gate.sh`,
  `.github/workflows/submodule-gate.yml`.

### Does NOT touch
- Application logic.

### Verification
- The hook blocks a write under `vendor/agents/`; the gate script fails a deliberately broken bump.

---

## Batch 10 — Hotel adapter + vendor submodule

**Depends on:** Batches 3, 4, 9. (The hotel agent's clean API and the request/response contract are
ready: `spec/schema.md`.)

**Goal.** Wire the real hotel agent as the Accommodation agent.

### Deliverables
- Add `vendor/agents/hotel-finder-agent` as a git submodule (HTTPS).
- `tripper/agents/hotel_adapter.py` maps `TripInput` to the agent's `HotelSearchRequest` (expanding
  `guests` into one room when `stay.rooms` is null), calls `search` / `search_sync` with a `Settings`
  built from tripper's config, and maps `HotelSearchResponse` to the hotel payload in
  `spec/schema.md`; register it in the orchestrator as the Accommodation agent.
- Adapter/contract tests (non-e2e; `mock` provider + `heuristic` scorer, so no keys or LLM needed).

### Files this batch creates/edits
- `.gitmodules`, `vendor/agents/hotel-finder-agent` (submodule), `tripper/agents/hotel_adapter.py`,
  `tests/test_hotel_adapter.py`, orchestrator agent-registration.

### Does NOT touch
- Reliability machinery (Batch 4), `web/`, `firestore.rules`.

### Verification
- The adapter maps a sample hotel-agent response to `AgentResult`; the orchestrator produces
  `TripSuggestions.hotel`.

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
> trip, the hotel agent runs, and results render (live on Vercel). Critical path now: Batch 7
> (frontend) → Batch 8 (deploy), which makes it live.
> Batches 1, 2, 3, 4, 5, 6, 9, 10 are done. Batch 7 (frontend) is claimable now (deps 1, 3 complete);
> Batch 8 (deploy) depends on 4, 5, 6, 7, 1 — claimable once 7 lands.
> When the user says "continue" after a context clear, ask which batch to claim.

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

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

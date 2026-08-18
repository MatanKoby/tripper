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

> **Milestone M2 (shipped).** The per-domain data model + backend fan-out to all three domains, the
> raw-JSON-per-container FE, and the **feedback / refine loop** are all done (`roadmap.md`,
> `schema.md`, `flows.md`, `agents.md`, `ui.md`; history in `specflow/history/BUILD_QUEUE_DONE.md`).
> The next milestone (the **orchestration agent**, an interactive, multi-turn planner,
> `roadmap.md`) is not yet broken into batches; the one open upstream gate is the hotel agent's
> `refine_sync` + stable `Pick.id`, which unblocks *hotel* refine only. **Batch 16** is a standalone
> operational batch, independent of that milestone work.

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

---

### Batch 16 — Sweeper recovery redesign + free-tier cost guardrails  (dep: none)

Context: the scheduled sweeper was ~98% of all backend activity and ~100% of billed Firestore reads,
while its recovery path never completed: it re-queues a stranded run to `pending`, but `main.py`
registers only `on_document_created` triggers and `FirestoreOptions` (firebase-functions 0.6.0)
exposes no `retry`, so nothing re-fires it. It also holds one of the **three** Cloud Scheduler jobs
free per billing account, a quota shared across the user's other GCP projects.

- **Drop the schedule.** Remove `sweep_stuck_jobs` / `@scheduler_fn.on_schedule` from `main.py`; the
  deploy tears the Cloud Scheduler job down and returns the slot. Idle cost → zero.
- **Sweep opportunistically** instead: call `sweep()` at the top of `orchestrate` (trip `onCreate`),
  where stale state is the only place it matters.
- **Terminal-only reap.** `_reap_one` drops the re-queue branch: a `running` run past its lease goes
  straight to terminal `error`, so a dead run stops spinning instead of parking at `pending`
  forever. `SweepReport.requeued` and the sweeper's `max_attempts` plumbing go with it; a
  refinement's terminal error still resets its parent domain to `idle`.
- **Cap every function**: explicit `memory`, `timeout_sec`, `max_instances`, `region` on all three
  `on_document_created` triggers. Never set `min_instances` (0 is the default and the discipline).
- **Quieten logs**: `main.py`'s `logging.basicConfig` drops to `WARNING` (Logging's free allotment is
  account-wide, not per project).
- **Deploy hygiene** (`DEPLOY.md`): document the Artifact Registry cleanup policy
  (`firebase functions:artifacts:setpolicy --days 1`), since four function images accumulate
  against 0.5 GB free, and drop the Cloud Scheduler job from the deploy description.
- **Fix `.firebaserc`**: its default project is `tripper`; the real project id is `tripper-af0fc`.
- Spec: rewrite `flows.md` → *Sweeper* (and the "sweeper may re-queue" line under *Idempotent
  claim*), and correct `architecture.md`'s "All within free tier for M1" with the named-database
  finding plus the cost guardrails.

Files: `main.py`, `tripper/sweeper.py`, `tests/test_sweeper.py`, `.firebaserc`, `DEPLOY.md`,
`spec/flows.md`, `spec/architecture.md`.

Deferred (not this batch): Firestore TTL policies on `suggested` / `refinements` (needs an
`expiresAt` written at creation → `spec/schema.md` change; storage sits at 0 GiB of 1 GiB free, so
there is no pressure). A per-domain **retry control** in the FE: with terminal-only reap, an
`error` domain is a dead end until the user resubmits the trip, since Refine is `idle`-gated
(`spec/ui.md`).

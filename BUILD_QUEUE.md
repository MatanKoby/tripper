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

> **Pick-order pointer for "continue".** When the user types "continue" after a context clear,
> **ask** which un-done batch to claim rather than guessing. (Keep a rough priority order here
> as the queue fills.)

---

## Batch 1 — <short title> (example — replace or delete)

> This is a worked example showing the batch shape. Delete it once you have real batches.

**Depends on:** none.

**Goal.** One or two sentences: what this batch delivers and why.

### Deliverables
- Concrete, checkable outcomes — not "work on X" but "X does Y, verified by Z".

### Files this batch creates/edits
- `path/to/file` — what changes. (This list is what the parallelism check reads — keep it honest.)

### Does NOT touch
- Files deliberately out of scope, so a parallel batch knows it's safe.

### Verification
- How to confirm it works (test, manual step, query).

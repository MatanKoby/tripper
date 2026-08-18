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
> `refine_sync` + stable `Pick.id`, which unblocks *hotel* refine only. **No un-done batches
> remain.**

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

---

_(none)_

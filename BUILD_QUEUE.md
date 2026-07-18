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

> **Milestone M2 (current):** the per-domain data model + backend fan-out, with **all three domains
> integrated** — accommodations rebuilt on the new model, and **flights** + **activities** vendored
> and wired in (`roadmap.md`, `schema.md`, `flows.md`, `agents.md`). The FE renders each domain as
> **raw JSON per container**; the **feedback / refine loop** lands last. Supersedes the M1 single-doc
> `results` model (`archive.md`). **Batch 13 is the only batch left**: 11 + 12 + 15 built the
> backend fan-out to all three agents, and 14 shipped the per-domain FE read model + raw-JSON render
> + extended form. 13's *hotel* refine is gated on upstream `refine_sync` while flights/activities
> refine is not, so build the flights/activities + FE path first and guard the hotel branch.

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

---

### Batch 13 — Feedback / refine loop (all domains)  (dep: 12, 15)

- Refinement-doc `onCreate` → **refine run**: claim/lease it, set the domain `running`, read the
  `feedback` marks off `suggested`, call the domain adapter's refine, **append** round-N `suggested`
  tagged with `round`, mark the refinement `done`, domain back to `idle` (`flows.md`).
- **Flights / activities refine** = re-run search with the feedback folded into the request; **no
  upstream dependency** (`agents.md`). **Hotel refine** = the agent's `refine_sync` — `[NOT READY]`
  until upstream ships `refine_sync` + stable `Pick.id` and the submodule bump lands (`agents.md`);
  build the flights/activities + FE path first and guard the hotel branch until then.
- FE: like / dislike controls write `feedback`; a per-section **Refine** button (enabled only when the
  domain is `idle`) creates a `refinements` doc; selection writes a `selected` doc (`ui.md`).
- Sweeper: extend the `collectionGroup` sweep to refinement docs.

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

> **Milestone M2 (current):** the per-domain data model + the hotel **feedback / refine loop**, built
> accommodations-first (`roadmap.md`, `schema.md`, `flows.md`). It **supersedes** the M1 single-doc
> `results` model (`archive.md`), so Batches 12 and 14 rebuild the accommodations vertical on the new
> schema. Activities / flights integration comes *after* this milestone (`roadmap.md`), not yet
> queued. Suggested order: **11 → (12, 14 in parallel) → 13** (13 gated on upstream).

Tags: `[MANUAL]` = the user executes it (agents skip). `[NOT READY]` = blocked, do not claim.

---

### Batch 11 — Data model & Firestore config (foundation)

Tripper-owned storage shapes + rules + indexes for the new tree (`schema.md`, `access.md`). No agent
behavior yet; Batches 12 and 14 build on it.

- `tripper/contract.py`: the neutral `ResultItem` (+ `price`), and the domain / suggested / selected /
  refinement doc models (`schema.md` → Firestore data model). Retire the M1 `TripSuggestions` wrapper
  (moved to `archive.md`).
- Firestore **security rules** for the subtree (`access.md`): backend-owned `domains` + `suggested`
  (except the client `feedback` field via `affectedKeys().hasOnly(["feedback"])`), client-owned
  `selected`, `accessOk()`-gated `refinements` create.
- **Indexes**: collection-group indexes for the sweeper (`domains` + `refinements` in `running` with
  `leaseExpiresAt < now`) and the ordered `suggested` query (by `lens` / `score` / `round`, excluding
  `dismissed`).
- `[MANUAL]` reminder: rules + indexes deploy from a workstation, not CI (`DEPLOY.md`).

### Batch 12 — Backend fan-out & per-domain search run  (dep: 11)

- Trip `onCreate` → **fan-out**: set trip `active`, create a `domains/{domain}` doc per active agent
  (M2: accommodations only). (`flows.md`)
- Domain-doc `onCreate` → **search run**: claim/lease the domain doc (reuse the `jobs.py` claim on the
  new doc), run the hotel adapter, write round-1 `ResultItem` `suggested` docs, set `agentStatus:
  idle`.
- Hotel adapter emits `ResultItem` + `detail` and uses `Pick.id` as the suggestion id (`schema.md`,
  `agents.md`).
- Sweeper: `collectionGroup` over domain docs (`flows.md`). Replaces the M1 single-orchestrator path.

### Batch 13 — Hotel feedback / refine loop (backend)  `[NOT READY]`  (dep: 11, 12)

Gated on the **upstream** hotel agent shipping `refine_sync` + stable `Pick.id`, and the submodule
bump landing (bump gate, `agents.md`). Do not claim until the vendored agent exposes refine.

- Refinement-doc `onCreate` → **refine run**: claim/lease it, set the domain `running`, read the
  `feedback` marks off `suggested`, call the hotel adapter's `refine`, **append** round-N `suggested`
  tagged with `round`, mark the refinement `done`, domain back to `idle`. (`flows.md`)
- Sweeper: extend the `collectionGroup` sweep to refinement docs.

### Batch 14 — Frontend: per-domain read model, renderers, feedback, refine, selection  (dep: 11; renders 12's output)

- Replace `web/src/useJob.ts`'s single-doc listener with a trip listener + per-domain `suggested`
  listeners (`flows.md`).
- Accommodation renderer over `ResultItem` + `detail`: group by `lens`, hide `dismissed` (`ui.md`).
- Like / dislike controls write `feedback`; a per-section **Refine** button (enabled only when the
  domain is `idle`) creates a `refinements` doc (the refine only *runs* once Batch 13 + upstream land).
- Selection writes a `selected` doc (accommodations single-select) and shows the chosen hotel.
- Flights / Activities keep "coming soon" (`ui.md`).

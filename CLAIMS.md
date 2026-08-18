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

### Batch 16 — Sweeper recovery redesign + free-tier cost guardrails
- Owner: claude
- Started: 2026-08-18 06:04

## Completed

### Batch 13 — Feedback / refine loop (all domains)
- Owner: claude
- Started: 2026-07-18 12:23
- Finished: 2026-07-18 13:49
- Commit: 1f478a9

**What shipped.** The wanted/unwanted feedback + refine loop across all domains (`spec/flows.md`,
`spec/agents.md`, `spec/schema.md`, `spec/ui.md`), closing milestone **M2**. A create on a
`refinements/{id}` doc fires a **refine run** that re-runs the domain's agent with the user's
feedback folded in and appends the next round of `suggested`.

- **`tripper/agents/base.py`** — the refine seam: `PriorCandidate` (a prior candidate + its
  `feedback` mark + `lens`/`round`, read off `suggested`), `RefineNotSupported`, an
  `Agent.supports_refine` flag (default `False`), and a default `Agent.refine(trip, prior)` that
  raises the guard. So a domain with no refine path fails cleanly rather than crashing.
- **`flight_adapter.py` / `activities_adapter.py`** — `supports_refine = True` + `refine()`.
  Flights folds the marks into the **fare budget** (disliked prices cap it below the cheapest
  disliked, liked prices floor it) and re-runs `run` (`_run` shared with search). Activities does a
  **fresh stateless run** whose `interests` gains liked categories / drops disliked ones (mapped to
  `InterestGroup`) and whose `notes` name the liked/disliked activities (`_drive` shared with
  search). **Hotel stays guarded** (inherits the default `refine`) until upstream `refine_sync`
  ships (`spec/roadmap.md`).
- **`tripper/orchestrator.py`** — `run_refine`: claim the **refinement** doc (lifecycle field
  `status`, vs the domain's `agentStatus`), read the current feedback off `suggested`, set the
  domain `running` **with a fresh lease** and heartbeat **both** the refinement and the domain doc
  (so the domains-sweep leaves a refine-busy domain alone), call `adapter.refine`, append the round,
  dismiss the disliked prior candidates, then settle the domain → `idle` (round N+1) + the
  refinement → `done`. On any failure it errors the refinement and **resets the domain to `idle`**
  so a dead refine never strands it as "thinking". Helpers: `_load_prior_candidates`
  (reconstructs the neutral `ResultItem` out of each stored doc, dropping run/sort extras),
  `_next_round`, `_mark_domain_running`, `_fail_refine_safely`.
- **`tripper/jobs.py`** — `write_refine_result`: append the round, dismiss the disliked, drive the
  domain idle, mark the refinement done. Refine candidate doc ids are **round-qualified**
  (`{agentId}::r{round}`) so an appended round never clobbers a prior one — necessary because both
  the flight and activities agents reuse ids across runs (surfaced below).
- **`tripper/sweeper.py`** — generalized to reap **two** collection groups: `domains` (on
  `agentStatus`, as before) and `refinements` (on `status`), via `_sweep_group`. A terminally-failed
  refinement also resets its still-`running` parent domain to `idle` (one transaction). `SweepReport`
  gained `__add__` to sum the two group tallies. The `refinements` composite index already existed
  (Batch 11).
- **`main.py`** — a third create trigger, `refine` on
  `users/{userId}/trips/{tripId}/domains/{domain}/refinements/{refineId}` → `run_refine`.
- **Frontend** (`useJob.ts`, `DomainSection.tsx`, `types.ts`, `App.tsx`) — per-domain `selected` +
  `refinements` listeners added to the existing trip/domain/suggested ones; three write actions:
  `setFeedback` (patch **only** `feedback`, toggles off on re-click), `refine` (create a `pending`
  refinements doc), `select`/`deselect` (write/remove a `selected` doc — single-select overwrites a
  fixed `choice` slot, multi keys by suggestion id; the snapshot copies only the neutral
  `ResultItem`). `DomainSection` renders, in the idle state, per-candidate Like/Dislike + Select
  controls, a per-section **Refine** button (only reachable when the domain is idle), a selected
  slot, and a refine-failed banner; **dismissed candidates are filtered out**; the raw-JSON dump is
  kept alongside (M2 first pass). New `types.ts`: `RefinementStatus`, `Feedback`, `SelectedDoc`,
  `RefinementDoc`.

**No changes to `firestore.rules` / `firestore.indexes.json`** — Batch 11 already added the
feedback-only `suggested` update rule, the `accessOk()`-gated `refinements` create, client-owned
`selected` CRUD, and the `refinements` sweep index. The 30 rules unit tests still pass, confirming
the FE writes exactly what the rules permit.

**Verification.** `ruff check` clean; `pytest` **112 passed** (was 91) against the Firestore emulator
+ all three mock agents: +6 orchestrator `run_refine` (append/round-qualify/dismiss, feedback read,
hotel-guard errors + domain reset, duplicate-delivery skip, unknown-domain error, two-round
increment), +5 flight refine (budget fold cap/floor/noop + a tighter-budget re-run), +5 activities
refine (interests/notes fold + drop-all + noop + a completed refined run), +5 sweeper refinements
(requeue, terminal-error-resets-domain, idle-domain-untouched, live-lease-skip, mixed domain+refine
pass), +1 hotel refine guard, and **+1 full emulator-backed end-to-end refine** with the real
activities agent (search → dislike the culture picks → refine → round 2 appended under `::r2` ids,
culture dismissed and absent from round 2, refinement `done`, domain `idle` at round 2). Frontend:
`tsc --noEmit` + `vite build` clean. A true browser end-to-end (Google popup + live Firestore) is
the documented manual step and was not run.

**Decisions surfaced (not freelanced into a spec edit).** (1) **Round-qualified `suggested` doc
ids** (`::r{round}` for refine rounds; round 1 keeps the plain agent id): `spec/schema.md` says the
`suggestionId` *is* the agent's stable item id, but both new agents reuse ids across runs, so an
appended round must not clobber the prior one; feedback still round-trips because the refine reads
the actual stored doc ids. Worth a one-line schema note. (2) **Refine sets the domain `running` with
a refreshed lease + a second heartbeat on the domain doc**, so the domains-sweep never reaps a
refine-busy domain; on failure the domain is reset to `idle`. (3) **The sweeper resets a still-
running parent domain to `idle`** when it terminally-errors a refinement — beyond the literal
`flows.md` sweeper text, to avoid a stranded "thinking" domain. (4) **Single-select uses a fixed
`choice` doc id** (multi keys by suggestion id) — one realization of `schema.md`'s "one doc for
accommodations now; the shape already supports many". None conflict with the specs; all realize
documented intent. Note the pre-existing limitation (Batch 5): a sweeper **re-queue** to `pending`
resets state but does not re-fire the run (`onCreate` fires on create only) — unchanged here.

### Batch 14 — Frontend: per-domain read model, raw-JSON render & form
- Owner: claude
- Started: 2026-07-18 11:56
- Finished: 2026-07-18 12:16
- Commit: d73ee13

**What shipped.** The frontend now reads the M2 **per-domain** Firestore model and renders each
domain independently (`spec/flows.md`, `spec/schema.md`, `spec/ui.md`), replacing the M1 single-doc
`results` render.

- **`web/src/useJob.ts`** — the single trip-doc listener is replaced by a trip listener **plus**,
  for each of the three domains, a `domains/{domain}` state-doc listener and a `suggested/*`
  collection listener (all torn down together on resubmit/unmount). New `JobState` exposes
  `{ submitting, tripId, trip, domains, submitError }` where `domains` is a per-domain
  `{ doc, suggested }` record; suggestions are sorted by `round` then `rank`. The client listens to
  all three domains and never enumerates agents (an inactive one just stays empty).
- **`web/src/DomainSection.tsx`** (new, replaces `Accommodation.tsx`) — generic section driven by
  its own `domains/{domain}.agentStatus`: before fan-out / `pending` / `running` → "thinking /
  warming up"; `idle` → the domain's `suggested` docs dumped as **raw JSON** (`<pre>`); `error` →
  the message; plus trip-level `status: "error"` (fan-out failure) and `submitError` banners. A
  styled per-domain renderer is deferred (`spec/roadmap.md`).
- **`web/src/App.tsx`** — center column maps `DOMAIN_SECTIONS` (Flights / Accommodation /
  Activities) to a `DomainSection` each; section ids are the `Domain` values so the left-nav
  anchors match.
- **Form** (`TripForm.tsx`, `buildTripInput.ts`, `types.ts`) — adds the flights + activities
  `TripInput` fields: `origin`, `flight_budget_usd`, `activities_budget_usd`, `interests` (the 8
  `InterestGroup`s), `travel_style` (`TravelStyle`), with new "Flights (optional)" and "Activities
  (optional)" fieldsets. `types.ts` gains the read-model types (`Domain`, `DomainAgentStatus`,
  `ResultItem`, `Price`, `SuggestedDoc`, `DomainDoc`, updated `TripDoc`) and the `InterestGroup` /
  `TravelStyle` / `Domain` enum arrays; the M1 hotel read types (`Pick`/`HotelPayload`/
  `TripSuggestions`/lens labels) are dropped. Empty optionals are omitted so the adapters apply
  their defaults. All three `presets.ts` quick-fills now populate the new fields.

**Deferred (Batch 13):** feedback (like/dislike), the per-section Refine button, and selection
controls. `SuggestedDoc.feedback` is typed but never written yet.

**Verification.** `tsc --noEmit` and `vite build` both clean; the dev server transforms the full
module graph (App → DomainSection/TripForm/useJob) without error. A true end-to-end submit
(create trip → fan-out → per-domain `suggested` render) needs the Firebase emulator + backend
triggers running and was **not** exercised here.

### Batch 15 — Vendor flights + activities agents, adapters & TripInput extension
- Owner: claude
- Started: 2026-07-18 10:32
- Finished: 2026-07-18 11:20
- Commit: d1d3540

**What shipped.** Flights and activities are now integrated, so the M2 fan-out activates all three
domains (`spec/agents.md`, `spec/schema.md`). **Two submodules vendored** under `vendor/agents/`:
`flight-finder-agent` (`rosenn88`, package `flight_finder`, sync entry `flight_finder.run`, pinned
`main` @`97502f9`) and `travel-agent` (`hadar-grimberg`, package `travel_agent`, entry
`travel_agent.ActivitiesAgent().handle`, pinned `master` @`73edce5`); both pass the submodule-bump
gate (`compileall` + non-e2e tests + tripper adapter/contract tests). **`tripper/contract.py`**:
`TripInput` gains `origin`, `flight_budget_usd`, `activities_budget_usd`, `interests`,
`travel_style`, plus the `InterestGroup` (8 group names) and `TravelStyle` (relaxed/balanced/packed)
enums. **`tripper/config.py`**: adds the Nebius fields the new agents read that tripper lacked
(`nebius_endpoint_id`, `nebius_api_key`, `nebius_base_url`) and per-agent env builders
`flight_agent_env()` / `activities_agent_env()` (the existing `agent_env()` stays the hotel one);
a shared `_drop_empty` keeps blanks out so each agent falls back to its keyless default;
`.env.example` documents the new vars.

**`tripper/agents/flight_adapter.py`** (`FlightAdapter`, domain `flights`, `selection_mode: single`):
maps `TripInput` + shared context to the flight agent's request dict (destination = `place.city`
else `place.text`; origin = `trip.origin`; the stay dates become a **round trip**, out on `check_in`
back on `check_out`; `flight_budget_usd` in USD), calls `run`, and maps each market `Offer` (cheapest
first) to a neutral `ResultItem` (`price` per-`total` USD, within/over-budget badge, google/skyscanner
link, offer+query in `detail`), the offer's **market code** as the stable suggestion id;
`summary`/`within_budget_count`/`pricing_source`/`query` go on `diagnostics`. Because tripper always
passes a structured origin+destination the agent's free-text LLM path never runs (fully
deterministic); with no `TRAVELPAYOUTS_TOKEN` it uses offline **simulated** pricing. A missing origin
or center-only destination is a clean empty outcome (warning), and the agent's `BadRequest`
(unresolvable place) is caught as empty+warning, not a transport error.

**`tripper/agents/activities_adapter.py`** (`ActivitiesAdapter`, domain `activities`,
`selection_mode: multi`): builds the agent's `start` trip (destination, stay dates,
`budget_usd` = `activities_budget_usd` or the `1500.0` default, `travelers` = adults+children clamped
1..20, `interests` omitted when null so the agent defaults, `travel_style`), then **drives the
multi-turn LangGraph conversation statelessly within the one run** — `start`, then per awaiting round
relay `{selected: <all names>, approve: true}` to accept the category and advance, bounded by a
25-turn cap — until `completed`, and **discards the instance** (no `session_id` persisted,
`spec/agents.md`). Each `RecommendedActivity` across rounds becomes a `ResultItem` (title=name,
subtitle=category, `price` per-`person` USD when a cost is present, description as rationale,
reservation badge; id `"{category}-{index}"`); the completed `itinerary` + `reservation_checklist` +
`user_preferences` go on `diagnostics`. `RecommendedActivity` carries no booking link, so `url` is
`None`. A reported agent `status: "error"` raises (transport failure → domain `error`); no
destination or no recommendations is an empty outcome with a warning.

**`main.build_active_agents`** now returns `[HotelAdapter, FlightAdapter, ActivitiesAdapter]`
(function-local imports, so importing `main` still needs no submodule). **`requirements.txt`**
installs both new local-path submodules (travel-agent brings the heavy `langgraph`/`langchain` stack
— the largest contributor to the Function image, `spec/agents.md`). `.gitmodules` pins the tracking
branches (`main` / `master`).

**Verification.** `ruff check` clean; `pytest` **91 passed** against the Firestore emulator + both
mock agents (was 66): +14 flight-adapter, +14 activities-adapter (request/result/collection mapping,
empty/unroutable outcomes, `_require_ok` raise, and per-domain emulator-backed
`fan_out`→`run_search`→`suggested/*` round-trips), +3 contract (new-field defaults, unknown
interest/style rejection), and the `FULL_TRIP_INPUT` round-trip fixture extended. Both submodule-bump
gates pass in `--check-only`. A full three-domain `fan_out` under `firebase emulators:exec` drives
all three domains to `idle` with candidates (accommodations 8, flights 10, activities 6) — exactly
the deployed trigger behavior.

**Manual prereqs / follow-ups for the user.**
- **Editable installs for local dev / tests:** `pip install -e vendor/agents/flight-finder-agent -e
  vendor/agents/travel-agent` (the adapter tests `importorskip` their agent, so they skip cleanly
  without it). CI already checks out submodules recursively.
- **Deploy secrets (Batch 8 / DEPLOY.md, not updated here):** to run activities against a real LLM,
  set `NEBIUS_API_KEY` + `NEBIUS_BASE_URL` (per-token) or `NEBIUS_ENDPOINT_URL` + `NEBIUS_ENDPOINT_ID`
  (serverless); for live flight fares set `TRAVELPAYOUTS_TOKEN` (the flight agent reads it straight
  from the process env). Without them both agents run keyless (simulated / mock). Consider adding
  these to `DEPLOY.md`'s secret list and confirming the Function image size stays within limits given
  the langgraph stack.
- **Spec drift to confirm (surfaced, not freelanced):** (1) `spec/architecture.md` line ~41 says
  "There is no `NEBIUS_ENDPOINT_ID`" — true for the hotel agent, but the flight/activities agents do
  read it; the line may want a note. (2) `spec/schema.md` says activities map a booking-link `url`,
  but `RecommendedActivity` has no such field (url is `None`); the booking links live on the
  itinerary's reservation items instead. (3) activities selection is `multi` and flights `single`
  (spec states only accommodations=single) — chosen here, worth confirming. (4) The langgraph
  `MemorySaver` emits harmless "Deserializing unregistered type" warnings to stderr per run; cosmetic.

### Batch 12 — Backend fan-out & per-domain search run (domain-general)
- Owner: claude
- Started: 2026-07-17 06:24
- Finished: 2026-07-17 07:30
- Commit: fb2e68e

**What shipped.** The M1 single-doc orchestrator is replaced by the M2 fan-out (`spec/flows.md`).
The `Agent` seam (`tripper/agents/base.py`) is now domain-general: an adapter declares its `domain`
+ `selection_mode` and returns a neutral `DomainSearchResult` (a list of `Suggestion` = stable id +
`ResultItem` + optional lens, plus `diagnostics` / `warnings` / `counts`), never `HotelPayload`.
`tripper/orchestrator.py` gained `fan_out` (trip `onCreate` → mark the trip `active`, idempotently
create one `domains/{domain}` doc per active agent) and `run_search` (domain `onCreate` → claim/lease
the domain doc on `agentStatus`, run the adapter, write `suggested/*`, drive to `idle`; a failure
errors only that domain). `tripper/jobs.py`: `claim_job` is parametrized by `status_field`,
`write_search_result` writes the candidates then flips the domain to `idle`, `write_run_error`
replaces the single-doc terminal write (`write_done`/`write_error` removed). The hotel adapter now
maps picks → `ResultItem` + `detail` (id = `"{lens}-{index}"` until the agent exposes a stable
`Pick.id`, `spec/agents.md`). The sweeper reaps the `domains` collection group on `agentStatus`.
`main.py` wires two create triggers (trip fan-out, domain search) + the sweeper.

**Verification.** 66 tests pass against the Firestore emulator + the vendored hotel mock agent,
including a full `fan_out` → `run_search` → `suggested/*` round-trip with the real `HotelAdapter`.
`ruff check` clean.

**Scope / follow-ups.** Only the hotel agent is active (this batch stays green with one domain);
Batch 15 vendors flights + activities and activates all three. `TripSuggestions` remains in
`contract.py` as documented M1 legacy (`spec/archive.md`). No Firestore rules change: search runs
write via the Admin SDK, which bypasses rules.

### Batch 11 — Data model & Firestore config
- Owner: claude
- Started: 2026-07-16 19:01
- Finished: 2026-07-17 05:16
- Commit: b22578a

**What shipped.** The tripper-owned storage shapes + Firestore config for the M2 per-domain tree
(`spec/schema.md`, `spec/access.md`), a pure foundation: no agent behavior, Batches 12 (backend
fan-out/search) and 14 (FE) build on it. **`tripper/contract.py`** gains the neutral, rendering-ready
`ResultItem` (+ nested `Price`) that all domains share, and the four per-domain Firestore doc models
`DomainDoc` / `SuggestedDoc` / `SelectedDoc` / `RefinementDoc`, plus the enums `Domain`,
`DomainAgentStatus` (the domain run lifecycle pending/running/idle/error, distinct from the existing
`AgentStatus` data-outcome enum), `SelectionMode`, `SelectionStatus`, `RefinementStatus`, `Feedback`,
`SelectedStatus`, `PricePer`. `SuggestedDoc` subclasses `ResultItem` (schema.md: "all ResultItem
fields" flat) and adds `lens`/`rank`/`round`/`dismissed`/`feedback`. **Design decisions:** (1) field
names are the *exact* Firestore keys, camelCase where the doc is camelCase (`agentStatus`,
`selectionMode`, `selectionStatus`, `suggestionId`), so `_Model.to_dict`/`from_dict` round-trip the
stored shape with no alias machinery (ruff selects E/F/I/UP/B, no pep8-naming, so camelCase fields
are lint-clean). (2) Following the M1 precedent (`jobs.py` writes lease/timestamp fields
imperatively, the pydantic contract models only the payload), the doc models capture durable
*content*; the reliability/lease fields (`startedAt`/`leaseExpiresAt`/`attempts`/`maxAttempts`/
`lastError`) and server timestamps (`createdAt`/`updatedAt`) are left to the run machinery in Batch
12, documented in each model's docstring. **`firestore.rules`** ports `access.md`'s subtree verbatim:
backend-only `domains` + `suggested` (client may patch **only** `feedback` via
`diff(...).affectedKeys().hasOnly(["feedback"])`), client-owned `selected`, `accessOk()`-gated
`refinements` create; the trip-create rule drops the M1 `!("results")` guard (M2 trips carry no
`results`). **`firestore.indexes.json`** adds three indexes: collection-group sweeper indexes for
`domains` (`agentStatus` + `leaseExpiresAt`) and `refinements` (`status` + `leaseExpiresAt`), and the
per-domain ordered `suggested` query index (`dismissed`, `lens`, `score` DESC, `round` DESC,
COLLECTION scope).

**Scoping decision (why `TripSuggestions` was not deleted).** The queue bullet says "retire the M1
`TripSuggestions` wrapper". Its *spec* is already archived (`spec/archive.md`, done in `eef5bd0`), but
the *code* is still consumed by the live M1 orchestrator (`orchestrator.py`, `jobs.py`,
`hotel_adapter.py`, `base.py`, `sweeper.py`), and `archive.md` states the M1 code "runs this model
until the DB batch rebuilds it" — that rebuild is **Batch 12** ("Replaces the M1 single-orchestrator
path"), not 11. Deleting the wrapper here would break the still-live M1 path and leave the tree red
between batches, contradicting Batch 11's "No agent behavior yet". So the wrapper is **marked legacy**
(module docstring + a section banner pointing to `archive.md`) and kept importable; **Batch 12 does
the physical removal** when it replaces the orchestrator that depends on it. Same reasoning kept the
M1 `trips` sweeper index in `firestore.indexes.json` (the M1 sweeper still queries it until 12).

**Tests / verification.** `tests/test_contract.py` +12 (round-trips of `ResultItem`, `SuggestedDoc`,
`SelectedDoc`, `DomainDoc` fan-out defaults, `RefinementDoc` default; score-bound, unknown-`per`,
unknown-`feedback`, and unknown-field rejections). The rules suite was reworked from 15 to **30**:
dropped the obsolete "create carrying results is denied" case (M2 rule no longer guards it) and added
the subtree cases — domain read-only vs client write denied; suggested feedback-only patch allowed
while any non-feedback field or feedback+other is denied, create/delete denied; selected create+delete
by owner, cross-user denied; refinement `accessOk()`-gated pending create, non-pending denied,
non-allowlisted denied, client update denied, owner read. All green: `ruff check` clean, `pytest` 62
passed (was 50), rules `npm test` 30 passed against the emulator loading the real `firestore.rules`,
`python -m compileall` OK, and `import main` succeeds with both triggers (M1 path intact — no
orchestrator/`main.py`/`jobs.py` changes).

**`[MANUAL]` prereq for the user.** This batch changed `firestore.rules` **and**
`firestore.indexes.json`. CI deploys **functions only**; Firestore config deploys from a workstation
(`DEPLOY.md`). Run `firebase deploy --only firestore --project <GCP_PROJECT>` from an owner
workstation so the new subtree rules + M2 indexes take effect (the emulator does not enforce composite
indexes, so the `suggested` and sweeper indexes are unverified until deployed). **Follow-up for Batch
14:** the `suggested` index fixes the query order — Batch 14's listener must use
`where('dismissed','==',false).orderBy('lens').orderBy('score','desc').orderBy('round','desc')` to
match it (adjust the index if the FE needs a different order).

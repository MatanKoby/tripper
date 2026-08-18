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

### Batch 17 — Structured destination (city + country) in the trip form  (dep: none)

Context: the flight agent returns zero candidates for a normal search because it cannot resolve the
destination it is handed. `buildTripInput.ts` hardcodes `place = { text: destination }` from one
free-text field, so `place.city` is never set, and `_destination()` in `tripper/agents/flight_adapter.py`
falls back to that raw text. The agent then reports `couldn't match destination 'Barcelona, Spain'
to any city or airport`. The shipped presets seed exactly that broken shape, and the field
placeholder ("e.g. Paris, France") teaches it. Splitting on the comma would only be a guess, so the
fix is to collect the data structurally at the form.

- **`web/src/countries.ts`** (new): the ISO-3166-1 alpha-2 code list. Names render through
  `Intl.DisplayNames`, so only the codes are stored.
- **`FormState`**: replace `destination` with `destinationCity` + `destinationCountry` (alpha-2).
- **`TripForm.tsx`**: a City text input plus a Country select, replacing the single Destination field.
- **`buildTripInput.ts`**: build `place = { city, country_code }` when both are present, keeping the
  `{ text }` form as the fallback so `Place._require_locator` is still satisfied either way.
- **`presets.ts`**: re-express the three presets as city + country code.
- Backend stays unchanged: `_destination()` already prefers `place.city`. Add a `test_flight_adapter`
  case pinning that a structured place yields the bare city.

Files: `web/src/countries.ts` (new), `web/src/TripForm.tsx`, `web/src/buildTripInput.ts`,
`web/src/presets.ts`, `tests/test_flight_adapter.py`.

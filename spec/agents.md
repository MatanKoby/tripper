# Agents (vendoring & integration)

## Layout

- Agents are public repos vendored as **git submodules under `vendor/agents/`**. One repo per
  domain:
  - **accommodations** — `hotel-finder-agent`: <https://github.com/MatanKoby/hotel-finder-agent>
    (vendored at `vendor/agents/hotel-finder-agent`, M1).
  - **flights** — `flight-finder-agent`: <https://github.com/rosenn88/flight-finder-agent>
    (import `flight_finder`, sync entry `flight_finder.run`).
  - **activities** — `travel-agent`: <https://github.com/hadar-grimberg/travel-agent>
    (import `travel_agent`, sync entry `travel_agent.ActivitiesAgent().handle`).
- Tripper reaches each agent only through its adapter (`architecture.md` under Agent contract +
  adapters). Agents expose a clean API; tripper does not wrap any CLI.

## Integration contract

For an agent's repo to be vendored here it must meet the following. The reference implementation is
`hotel-finder-agent`; new agents mirror it. Tripper never patches the submodule (see Read-only
rule), so all of this lives in the agent's own repo.

1. **Installable package.** A `pyproject.toml` (runtime deps declared) with a `src/<package>/`
   layout; `pip install -e .` from a clean venv succeeds and makes it importable. Tripper installs
   the submodule this way into the Cloud Function at deploy (`architecture.md`). A flat pile of
   scripts is not installable.
2. **One or more synchronous, machine-facing entry points.** Each a single callable, dict/JSON in
   and dict/JSON out; no HTTP, CLI, or subprocess on the call path (an async core provides a sync
   wrapper). Stable import path + name — tripper pins a ref and imports exactly it. A **search**
   entry point is required (reference: `hotel_finder.search_sync`). An agent that supports the
   wanted/unwanted **feedback loop** also exports a **refine** entry point: it takes the prior
   request + candidates + the user's wanted/unwanted marks and returns the *same* response shape,
   biasing toward wanted and away from unwanted (reference target: `hotel_finder.refine_sync`; the
   hotel agent's refine is upstream WIP, `roadmap.md`). Tripper drives the loop through the adapter
   and the refine flow in `flows.md`.
3. **Stable request/response schema.** Input fields and output structure documented and versioned;
   Pydantic v2 models exported from the package preferred (hotel: `HotelSearchRequest` /
   `HotelSearchResponse`), a JSON schema is the minimum. The adapter maps tripper's contract
   (`schema.md`) to and from this. Each response item carries a **stable id**, unique within a
   request, so the consumer can mark it and echo it back for refine; tripper uses it as the
   `suggested` doc id (`schema.md`). Hotel: `Pick` promotes the record's `id` + `source`.
4. **Config by injection.** LLM endpoint / keys / providers / tokens read from env vars or an
   injectable settings object; no hardcoded secrets, no reading a private `.env`. Tripper holds the
   credentials and passes them (`architecture.md` under Deployment & secrets). Reference:
   `hotel_finder.config.Settings`.
5. **Keyless / offline default.** With no secrets set, the entry point still imports and returns a
   valid (mock) response, for CI and local runs. Hotel: `mock` provider + `heuristic` scorer.
6. **Import-safe.** `import <package>` triggers no key checks, network calls, or servers; those
   happen when the entry point runs.
7. **Deps in package metadata**, not only a loose `requirements.txt`, so the editable install pulls
   them.
8. **Offline tests**, with any live test marked so `pytest -m "not e2e"` excludes it — these are
   what the Submodule-bump gate runs.

**Done** = from a clean env with no secrets set, `pip install -e .` then
`python -c "from <package> import <entry>; print(<entry>({<minimal input>}))"` imports and returns a
structured result.

## Read-only rule

`vendor/agents/**` is owned upstream and **never edited by tripper**. Interface gaps are fixed
either in tripper's adapter or upstream in the agent repo, never by an inline edit to the
submodule. Enforcement (deferred): a `.claude/settings.json` deny rule plus a `PreToolUse` hook
that blocks edits and git-mutations inside these paths.

## Submodule-bump gate

Tripper may advance a submodule pointer (`git submodule update --remote`), but before committing
the bump it must:

1. Compile-check the submodule (`python -m compileall`).
2. Run the submodule's non-e2e tests (no live LLM round-trip).
3. Run tripper's adapter/contract tests for that agent.

On any failure, roll the pointer back and report; do not commit. On green, commit the bump on its
own. This is also a CI job on any submodule-pointer change.

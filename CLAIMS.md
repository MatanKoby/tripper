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

## Completed

### Batch 3 — Agent contract types
- Owner: claude
- Started: 2026-07-12 11:06
- Finished: 2026-07-12 12:22
- Commit: 302b280

**What shipped.** The tripper/agent contract in `tripper/contract.py` (`spec/schema.md`): request
types (`TripInput` + `Place`/`Stay`/`Guests`/`Filters`), the agent response payload (`HotelPayload`
+ `Pick`/`Offer`/`Resolved`/`Diagnostics`), the transport wrapper (`TripSuggestions` + `TripError`),
and shared types (`Room`, `GeoPoint`) + enums (`Amenity`, `LensName`, `AgentStatus`,
`TransportStatus`). All models are strict (`extra="forbid"`) pydantic v2 and share a `_Model` base
with `from_dict` / `to_dict` Firestore round-trip helpers (dates as ISO strings, enums as values,
`GeoPoint` as a `{lat, lon}` dict). Validation: `place` requires a locator (text | city+country_code
| center), `stay.check_out > check_in`, filter range bounds (`min_star` 1..5, `min_guest_rating`
0..10), `Pick.score` 0..1, and `TripSuggestions` status/error/hotel consistency. `tests/test_contract.py`
(17 tests) round-trips full docs and asserts the rejection cases. Verified: `pytest` 22 passed
(5 config + 17 contract), `ruff check` clean. No manual prereqs. Unblocks Batches 4, 6, 10.

<!-- Recent finishes, newest first. Older entries archived to specflow/history/CLAIMS_DONE.md. -->

### Batch 2 — Repo skeleton & tooling
- Owner: claude
- Started: 2026-07-11 21:01
- Finished: 2026-07-12 05:46
- Commit: 2352813

**What shipped.** Backend Python package skeleton and tooling. `pyproject.toml` (hatchling build,
ruff + pytest; pydantic/pydantic-settings core, firebase-admin/firebase-functions as a `functions`
extra). `tripper/config.py` provides `Settings`: loads agent + Firebase config from env, splits
`ENABLED_PROVIDERS`, validates that `liteapi`/`llm` selections have the config they need (raising
`ConfigError`), and exposes `agent_env()` for the future hotel adapter. `tests/test_config.py`
(5 tests, green). `firebase.json` + `.firebaserc` set up the Firestore + Auth emulators.
`.env.example` documents the backend vars. Verified: `ruff check` clean, `pytest` 5 passed,
editable install works. No manual prereqs. Deploy files (`main.py`, `requirements.txt`,
`.gcloudignore`) deferred to Batch 4/8.

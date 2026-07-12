# Build Queue — Completed History

One-paragraph summaries of every shipped batch, newest at the top. Skim this for context when
picking a new claim. The full implementation history is in `git log` + `specflow/history/CLAIMS_DONE.md`.

<!-- Append a summary here when you finish a batch (see specflow/procedures/finish-batch.md).
     Format, e.g.:

## Batch 1 — <title>
Shipped <what> in <where>. Key commit `<sha>`. <One line on any follow-up deferred.>
-->

## Batch 3 — Agent contract types
Shipped the tripper/agent contract in `tripper/contract.py` (`spec/schema.md`): request types
(`TripInput` + `Place`/`Stay`/`Guests`/`Filters`), the agent response payload (`HotelPayload` +
`Pick`/`Offer`/`Resolved`/`Diagnostics`), the `TripSuggestions` transport wrapper (+ `TripError`),
and shared types/enums (`Room`, `GeoPoint`, `Amenity`, `LensName`, `AgentStatus`, `TransportStatus`).
Strict (`extra="forbid"`) pydantic v2 models on a `_Model` base with `from_dict`/`to_dict` Firestore
round-trip helpers; validators enforce a required place locator, date ordering, filter/score range
bounds, and transport status/error/hotel consistency. `tests/test_contract.py` (17 tests) covers
round-trips and rejections. Key commit `302b280`. Unblocks Batches 4, 6, 10.

## Batch 2 — Repo skeleton & tooling
Shipped the backend Python package skeleton and tooling: `pyproject.toml` (hatchling, ruff +
pytest, pydantic/pydantic-settings core with a `functions` extra), `tripper/config.py` (`Settings`
with env loading, `ENABLED_PROVIDERS` split, `liteapi`/`llm` validation via `ConfigError`, and
`agent_env()` for the hotel adapter), `tests/test_config.py` (5 green), and the Firestore + Auth
emulator config (`firebase.json`, `.firebaserc`, `.env.example`). Key commit `2352813`. Deploy files
(`main.py`, `requirements.txt`, `.gcloudignore`) deferred to Batch 4/8.

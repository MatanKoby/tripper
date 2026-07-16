# Archive

Superseded designs, kept for institutional memory. These describe what was true when shipped; they
are **not** the current intended design. The live design is in the other `spec/**` files.

## M1 single-document job model (superseded by the per-domain model in `schema.md`)

M1 shipped one Firestore document per request that held the whole run: the trip `input`, a single
lifecycle `status`, and one `results` blob carrying every agent's output. The multi-domain
data model (`schema.md` → Firestore data model) replaces it: per-domain subcollections of
`suggested` / `selected` docs, a per-domain agent lifecycle, and a client feedback + refine loop.
The M1 code (`tripper/orchestrator.py`, `tripper/jobs.py`, `web/src/useJob.ts`) runs this model
until the DB batch (`BUILD_QUEUE.md`) rebuilds it.

### Transport wrapper: TripSuggestions (orchestrator-owned; job `results`)

```jsonc
{
  "status": "ok|error",                // transport: error = the call/import/timeout failed
  "error":  "{ message, kind }|null",  // only when status == "error"
  "hotel":  "<agent payload>|null"     // present when status == "ok"
}
```

`agent_status` `empty`|`degraded` both mapped to transport `status` `"ok"`. The transport `status` /
`error` mirrored the job doc's lifecycle `status` / `error`: a failed call marked the job `error`,
and this object was written as the job's `results` on success.

### Firestore job document

One document per request. Path: `users/{uid}/trips/{tripId}`

- `input`: the `TripInput` (`schema.md`). Written by the client on create.
- `status`: `"pending" | "running" | "done" | "error"`.
- `results`: `TripSuggestions`. Written by the backend when `status == "done"`.
- `error`: `{ message, kind }`. Written by the backend when `status == "error"`.
- `createdAt`, `updatedAt`: server timestamps.
- Reliability fields: `startedAt`, `leaseExpiresAt`, `attempts`, `maxAttempts`, `lastError`.

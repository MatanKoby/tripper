# Schema

Data shapes for the UI input, the tripper/agent contract, and the Firestore job document. Types
are described in language-neutral terms; the Python implementation lives in `tripper/contract.py`.

## Trip input

The user-entered parameters, stored as the `input` field of the job document (below).

- `destination`: string (city or area). Required.
- `check_in`, `check_out`: dates (ISO `YYYY-MM-DD`). Required.
- `guests`: `{ adults: int >= 1, children: int >= 0 }`. Required.
- `budget`: `{ amount: number, currency: string, basis: "per_night" | "total" }`. Optional.
- `preferences`: `{ text: string, min_stars?: int, amenities?: string[] }`. Optional.
- `origin`: string. Optional in M1 (used by the flight agent later: `roadmap.md`).

## Agent contract

One shape for every agent, so the orchestrator stays agent-agnostic.

**Request** (`AgentRequest`): the subset of trip input relevant to the agent's domain plus shared
context. For M1 the hotel agent receives `destination`, `check_in`, `check_out`, `guests`,
`budget`, and `preferences`.

**Response** (`AgentResult`):

- `status`: `"ok" | "error"`.
- `items`: list of options. A hotel item: `{ name, price, currency, rating?, location?, url?,
  details? }`.
- `summary`: short natural-language summary from the agent.
- `error`: `{ message, kind }`, present when `status == "error"`.
- `diagnostics`: optional `{ latency_ms?, tokens? }`.

Nebius config is not part of the request; the adapter supplies it (`architecture.md` under Nebius
config).

**Aggregated result** (`TripSuggestions`): `{ hotel: AgentResult }` in M1. Later gains `flight`
and `activities` keys (`roadmap.md`). Stored as the `results` field of the job document.

## Firestore job document

One document per request. Its path, ownership, and access rules are in `access.md`; the meaning
and transitions of the lifecycle fields are in `flows.md`.

Path: `users/{uid}/trips/{tripId}`

- `input`: the trip input above. Written by the client on create.
- `status`: `"pending" | "running" | "done" | "error"`.
- `results`: `TripSuggestions`. Written by the backend when `status == "done"`.
- `error`: `{ message, kind }`. Written by the backend when `status == "error"`.
- `createdAt`, `updatedAt`: server timestamps.
- Reliability fields (`flows.md`): `startedAt`, `leaseExpiresAt`, `attempts`, `maxAttempts`,
  `lastError`.

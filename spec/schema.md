# Schema

Data shapes for the UI form, the tripper/agent contract, and the Firestore data model. The hotel
agent owns its request/response shapes (Pydantic `HotelSearchRequest` / `HotelSearchResponse`);
tripper's orchestrator owns the neutral, per-domain **storage** shapes it writes to Firestore
(`ResultItem`, the domain/suggested/selected/refinement docs below). Tripper's implementation lives
in `tripper/contract.py`. The agent contract is agreed with the hotel agent (`agents.md`).

The Firestore data model is **per domain**: one trip fans out to a `domains/{domain}` subtree
(accommodations, activities, flights), each holding its own `suggested` candidates, `selected`
choices, and `refinements` (the wanted/unwanted feedback loop). Lifecycle and triggers are in
`flows.md`; ownership and rules in `access.md`. The M1 single-document `results` model this replaces
is in `archive.md`.

`place` / `stay` / `guests` are shared trip context that later agents (flight, activities) reuse;
`filters` / `lenses` / `picks_per_lens` are hotel-specific. The hotel adapter maps `TripInput` to
the agent's `HotelSearchRequest`, expanding `guests` into a single room when `stay.rooms` is null,
and mapping trip-level `guest_nationality` into the agent's `stay.guest_nationality`.

## Request: TripInput (UI form and job `input`; tripper to hotel agent)

```jsonc
{
  "place": {
    "text":         "string|null",     // free text, geocoded when structured fields absent
    "country_code": "string|null",     // ISO-3166-1 alpha-2
    "city":         "string|null",
    "center":       "GeoPoint|null",   // precise "near this point"; resolved.center echoes it
    "radius_km":    "number = 5.0",    // only meaningful with center
    "desired_area": "string|null"      // soft neighborhood bias
    // require at least one of: text | city (+country_code) | center
  },
  "stay": {
    "check_in":  "date",              // required (past dates produce a warning, not an error)
    "check_out": "date",              // required, > check_in
    "currency":  "string = \"EUR\"",
    "rooms":     "Room[]|null"        // null = derive 1 room from guests; if set, OVERRIDES guests
  },
  "guests": {                          // trip-level; used only when stay.rooms is null
    "adults":        "int >=1 = 2",
    "children_ages": "int[] = []"
  },
  "guest_nationality": "string = \"US\"",  // trip-level; adapter maps it to the agent's stay.guest_nationality
  "filters": {                         // every field optional
    "price_min":           "number|null",   // per night
    "price_max":           "number|null",
    "min_star":            "int 1..5|null",
    "min_guest_rating":    "number 0..10|null",
    "refundable":          "bool|null",      // null = a cheapest-refundable AND a cheapest-non-refundable offer
    "must_have_amenities": "Amenity[] = []",
    "property_types":      "string[] = []"   // empty = all lodging types; wired to LiteAPI hotelTypeId
  },
  "lenses":         "LensName[]|null = null", // null = all three
  "picks_per_lens": "int >=1 = 3"             // N per lens (also caps the budget-too-low fallback)
  // intent / anchor_hotel dropped for M1 (ZONE-only)
}
```

## Response: hotel agent payload (agent to tripper, before wrapping)

The agent never raises for a data outcome; problems are `agent_status` + `warnings`.

```jsonc
{
  "agent_status": "ok|empty|degraded",   // data outcome, NOT transport
  "warnings":     "string[]",
  "resolved": {
    "city": "string|null", "area": "string|null", "center": "GeoPoint|null",
    "check_in": "date|null", "check_out": "date|null", "currency": "string|null"
  },
  "lenses": { "<LensName>": "Pick[]" },  // up to all three keys
  "diagnostics": {
    "scorer": "string", "providers_used": "string[]",
    "candidates_found": "int", "candidates_after_filter": "int",
    "shortlisted": "int", "widened": "bool"
  }
}

// Pick (flat, rendering-ready)
{
  "id":                     "string",               // stable per-hotel identity (agents.md): tripper's suggestion doc id + the refine feedback ref
  "source":                 "string",               // provider that produced it; unique together with id
  "name":                   "string",
  "score":                  "number 0..1",          // normalized, comparable across lenses
  "rationale":              "string",
  "why":                    "object<string,number>", // free-form subscores; keys scorer-dependent
  "area":                   "string|null",
  "distance_to_desired_km": "number|null",           // null when no desired_area/center
  "price_per_night":        "number|null", "currency": "string|null",
  "rating":                 "number 0..10|null", "review_count": "int|null", "star_rating": "int 1..5|null",
  "description":            "string|null",
  "amenities":              "Amenity[] = []",
  "coordinates":            "GeoPoint|null",
  "image_url":              "string|null",           // provider-supplied; not on the agent's Hotel model yet
  "url":                    "string|null",
  "offers":                 "Offer[] = []"
}

// Offer
{ "total": "number", "per_night": "number|null", "currency": "string",
  "board": "string|null", "refundable": "bool", "over_budget": "bool = false" }
```

## Storage item: ResultItem (neutral) + detail

Each agent payload is mapped, in that agent's adapter, to a list of **neutral `ResultItem`** docs
that all domains share, so one save seam writes them and the FE list/skeleton is domain-agnostic.
Domain-specific fields the neutral shape doesn't cover live in an opaque `detail` blob that the
domain's own renderer reads (`ui.md`). The adapter maps, e.g., hotel `Pick` → `ResultItem`
(`name`→`title`, `area`→`subtitle`, best `offer`→`price`, `amenities`→`badges`), dropping the rest
into `detail` (offers, `star_rating`, `why` subscores, `distance_to_desired_km`, coordinates, …).

```jsonc
// ResultItem — the neutral, rendering-ready suggestion shape (all domains)
{
  "title":     "string",
  "subtitle":  "string|null",
  "score":     "number 0..1|null",              // comparable within a domain
  "price":     "{ amount: number, per: \"night\"|\"total\"|\"person\", currency: string }|null",
  "rating":    "number|null",
  "image_url": "string|null",
  "url":       "string|null",
  "badges":    "string[] = []",                 // short chips (amenities, refundable, …)
  "rationale": "string|null",
  "detail":    "object = {}"                    // domain-specific passthrough; the domain renderer reads it
}
```

The same neutral shape is what `selected.snapshot` copies (below), so a selection renders with the
same renderer as a suggestion.

## Shared types

- `Room` = `{ adults: int >= 1, children_ages: int[] }`
- `GeoPoint` = `{ lat: number, lon: number }`
- `Amenity` in: `wifi, pool, gym, breakfast, parking, ac, spa, pet_friendly, kitchen, bar, restaurant, airport_shuttle`
- `LensName` in: `stratified_best, overall_standouts, hidden_gems`
- `Domain` in: `accommodations, activities, flights`

## Firestore data model

One trip fans out to a per-domain subtree. Paths, ownership, and rules: `access.md`. Lifecycle,
triggers, and the refine loop: `flows.md`. `{domain}` is a `Domain` value; the single collection
plus the `{domain}` wildcard keeps rules and `collectionGroup` queries uniform.

```
users/{uid}/trips/{tripId}                     # trip: input + status rollup
  /domains/{domain}                            # one per active agent (accommodations | activities | flights)
      /suggested/{suggestionId}                # candidates (backend), + client feedback mark
      /selected/{itemId}                       # the user's choices (client)
      /refinements/{refineId}                  # a wanted/unwanted refine request (client) -> a refine run
```

**Trip** `users/{uid}/trips/{tripId}`
- `input`: the `TripInput` above. Written by the client on create.
- `status`: `"pending" | "active" | "error"`. `pending` on create; `active` once the backend has
  fanned out to the domain docs; `error` only if fan-out itself fails. A trip is **never terminal**
  (the user can always refine): overall progress is read from the domain docs, not this field.
- `createdAt`, `updatedAt`: server timestamps.

**Domain** `.../domains/{domain}` — durable per-domain state **and** the round-1 search job (its
`onCreate` is the search trigger; `flows.md`).
- `domain`: `Domain`.
- `agentStatus`: `"pending" | "running" | "idle" | "error"` — claim state of the current run;
  `idle` = a round completed, ready to view / refine. Cycles `idle`→`running`→`idle` each round.
- `selectionMode`: `"single" | "multi"` (accommodations: `single`).
- `selectionStatus`: `"none" | "partial" | "confirmed"`.
- `round`: highest completed round (1 = initial search).
- `warnings`: `string[]`; `diagnostics`: `object` (latest run, from the agent); `counts`: `object`.
- Reliability fields for the round-1 job (`flows.md`): `startedAt`, `leaseExpiresAt`, `attempts`,
  `maxAttempts`, `lastError`.

**Suggested** `.../suggested/{suggestionId}` — one candidate; `suggestionId` is the agent's stable
item id (hotel: `Pick.id`, identity per `agents.md`). Backend-written except `feedback`.
- All `ResultItem` fields above (`title`, `score`, `price`, `detail`, …).
- `lens`: `LensName|null` (hotel grouping); `rank`: `int`; `round`: `int` — sort/group keys, since
  subcollection docs are unordered.
- `dismissed`: `bool = false` — superseded / removed from view without deleting.
- `feedback`: `"liked" | "disliked" | null` — **client-written**, the only client-writable field
  (`access.md`); the wanted/unwanted input a refine reads.
- `createdAt`.

**Selected** `.../selected/{itemId}` — a chosen item. **Client-written.** One doc for accommodations
now (`selectionMode: single`); the shape already supports many.
- `suggestionId`: the `suggested` doc it came from (back-reference).
- `snapshot`: a copy of that suggestion's `ResultItem` at selection time, so the choice survives the
  agent re-running.
- `meta`: `object` — per-agent selection metadata (accommodations: nights; activities: day / time /
  order; flights: leg / cabin).
- `status`: `"selected" | "confirmed"`; `createdAt`.

**Refinement** `.../refinements/{refineId}` — one refine request + its run. **Client-creates**
`{ round, status: "pending" }`; its `onCreate` triggers the refine run, which reads the current
`feedback` marks off `suggested`, calls the agent's refine entry point (`agents.md`), and **appends**
new picks to `suggested` tagged with this `round` (`flows.md`). Backend transitions it.
- `round`: `int`; `status`: `"pending" | "running" | "done" | "error"`.
- Reliability fields (`flows.md`): `startedAt`, `leaseExpiresAt`, `attempts`, `maxAttempts`,
  `lastError`; `createdAt`.

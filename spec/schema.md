# Schema

Data shapes for the UI form, the tripper/hotel-agent contract, and the Firestore job document.
The hotel agent owns the request/response shapes (Pydantic `HotelSearchRequest` /
`HotelSearchResponse`); tripper's orchestrator owns the transport wrapper. Tripper's
implementation lives in `tripper/contract.py`. This contract is agreed with the hotel agent.

`place` / `stay` / `guests` are shared trip context that later agents (flight, activities) reuse;
`filters` / `lenses` / `picks_per_lens` are hotel-specific. The hotel adapter maps `TripInput` to
the agent's `HotelSearchRequest`, expanding `guests` into a single room when `stay.rooms` is null.

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
    "check_in":          "date",              // required (past dates produce a warning, not an error)
    "check_out":         "date",              // required, > check_in
    "currency":          "string = \"EUR\"",
    "guest_nationality": "string = \"US\"",   // affects rates upstream (LiteAPI)
    "rooms":             "Room[]|null"        // null = derive 1 room from guests; if set, OVERRIDES guests
  },
  "guests": {                          // trip-level; used only when stay.rooms is null
    "adults":        "int >=1 = 2",
    "children_ages": "int[] = []"
  },
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

## Transport wrapper: TripSuggestions (orchestrator-owned; job `results`)

```jsonc
{
  "status": "ok|error",                // transport: error = the call/import/timeout failed
  "error":  "{ message, kind }|null",  // only when status == "error"
  "hotel":  "<agent payload>|null"     // present when status == "ok"
}
```

`agent_status` `empty`|`degraded` both map to transport `status` `"ok"`. The transport `status` /
`error` mirror the job doc's lifecycle `status` / `error` (`flows.md`): a failed call marks the job
`error`, and this object is written as the job's `results` on success. M1 has only `hotel`; `flight`
and `activities` arrive later (`roadmap.md`).

## Shared types

- `Room` = `{ adults: int >= 1, children_ages: int[] }`
- `GeoPoint` = `{ lat: number, lon: number }`
- `Amenity` in: `wifi, pool, gym, breakfast, parking, ac, spa, pet_friendly, kitchen, bar, restaurant, airport_shuttle`
- `LensName` in: `stratified_best, overall_standouts, hidden_gems`

## Firestore job document

One document per request. Its path, ownership, and access rules are in `access.md`; the meaning
and transitions of the lifecycle fields are in `flows.md`.

Path: `users/{uid}/trips/{tripId}`

- `input`: the `TripInput` above. Written by the client on create.
- `status`: `"pending" | "running" | "done" | "error"`.
- `results`: `TripSuggestions`. Written by the backend when `status == "done"`.
- `error`: `{ message, kind }`. Written by the backend when `status == "error"`.
- `createdAt`, `updatedAt`: server timestamps.
- Reliability fields (`flows.md`): `startedAt`, `leaseExpiresAt`, `attempts`, `maxAttempts`,
  `lastError`.

// TypeScript mirror of the tripper/agent contract (spec/schema.md, tripper/contract.py).
// The UI produces `TripInput` (the trip `input`) and reads the per-domain Firestore model:
// the trip doc's lifecycle plus each `domains/{domain}` doc and its `suggested/*` candidates.
// Field names and shapes match the Pydantic models so the backend's strict (extra="forbid")
// validation accepts what we write; the M1 single-doc `results` model is superseded (spec/archive.md).

// --- enumerations -----------------------------------------------------------------------------

export const AMENITIES = [
  "wifi",
  "pool",
  "gym",
  "breakfast",
  "parking",
  "ac",
  "spa",
  "pet_friendly",
  "kitchen",
  "bar",
  "restaurant",
  "airport_shuttle",
] as const;
export type Amenity = (typeof AMENITIES)[number];

export const LENS_NAMES = [
  "stratified_best",
  "overall_standouts",
  "hidden_gems",
] as const;
export type LensName = (typeof LENS_NAMES)[number];

// The activities agent's 8 category groups (spec/schema.md); each selects the whole group.
export const INTEREST_GROUPS = [
  "nature",
  "food",
  "culture",
  "adventure",
  "nightlife",
  "family",
  "shopping",
  "beach",
] as const;
export type InterestGroup = (typeof INTEREST_GROUPS)[number];

// Activities pace (spec/schema.md).
export const TRAVEL_STYLES = ["relaxed", "balanced", "packed"] as const;
export type TravelStyle = (typeof TRAVEL_STYLES)[number];

// The three per-domain slots a trip fans out to (spec/schema.md; the domain doc id is the value).
export const DOMAINS = ["accommodations", "activities", "flights"] as const;
export type Domain = (typeof DOMAINS)[number];

export type TripStatus = "pending" | "active" | "error";
export type DomainAgentStatus = "pending" | "running" | "idle" | "error";
export type SelectionMode = "single" | "multi";
export type SelectionStatus = "none" | "partial" | "confirmed";

// --- shared value types -----------------------------------------------------------------------

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface Room {
  adults: number; // >= 1
  children_ages: number[];
}

// --- request: TripInput -----------------------------------------------------------------------

export interface Place {
  text?: string | null;
  country_code?: string | null; // ISO-3166-1 alpha-2
  city?: string | null;
  center?: GeoPoint | null;
  radius_km?: number; // default 5.0; only meaningful with center
  desired_area?: string | null;
}

export interface Stay {
  check_in: string; // ISO date "YYYY-MM-DD"
  check_out: string; // ISO date, > check_in
  currency?: string; // default "EUR"
  rooms?: Room[] | null; // null = derive 1 room from guests; if set, OVERRIDES guests
}

export interface Guests {
  adults: number; // >= 1, default 2
  children_ages: number[];
}

export interface Filters {
  price_min?: number | null; // per night
  price_max?: number | null;
  min_star?: number | null; // 1..5
  min_guest_rating?: number | null; // 0..10
  refundable?: boolean | null; // null = both a refundable and a non-refundable offer
  must_have_amenities?: Amenity[];
  property_types?: string[];
}

export interface TripInput {
  place: Place;
  stay: Stay;
  guests?: Guests; // used only when stay.rooms is null
  guest_nationality?: string; // default "US"
  filters?: Filters;
  lenses?: LensName[] | null; // null = all three (hotel)
  picks_per_lens?: number; // >= 1, default 3
  // --- flights (spec/agents.md) ---
  origin?: string | null; // departure point: city name or 3-letter IATA
  flight_budget_usd?: number | null; // max airfare in USD (flight offers are USD-only)
  // --- activities (spec/agents.md) ---
  activities_budget_usd?: number | null; // USD budget (ex-lodging); adapter defaults if null
  interests?: InterestGroup[] | null; // null = the agent's default (culture, food)
  travel_style?: TravelStyle; // default "balanced"
}

// --- read model: per-domain Firestore docs (spec/schema.md) ------------------------------------

export interface Price {
  amount: number;
  per: "night" | "total" | "person";
  currency: string;
}

/** The neutral, rendering-ready suggestion shape shared by all domains (spec/schema.md). */
export interface ResultItem {
  title: string;
  subtitle?: string | null;
  score?: number | null; // 0..1, comparable within a domain
  price?: Price | null;
  rating?: number | null;
  image_url?: string | null;
  url?: string | null;
  badges?: string[];
  rationale?: string | null;
  detail?: Record<string, unknown>; // domain-specific passthrough
}

/** A `.../suggested/{suggestionId}` candidate: a ResultItem plus sort/group keys (spec/schema.md). */
export interface SuggestedDoc extends ResultItem {
  id: string; // the Firestore doc id (the agent's stable item id)
  lens?: LensName | null; // hotel grouping; null for domains without lenses
  rank?: number;
  round?: number;
  dismissed?: boolean;
  feedback?: "liked" | "disliked" | null; // client-written (deferred to Batch 13)
}

/** A `.../domains/{domain}` durable per-domain state doc (backend-owned; spec/schema.md). */
export interface DomainDoc {
  domain: Domain;
  agentStatus: DomainAgentStatus;
  selectionMode?: SelectionMode;
  selectionStatus?: SelectionStatus;
  round?: number;
  warnings?: string[];
  diagnostics?: Record<string, unknown>;
  counts?: Record<string, unknown>;
  error?: TripError | null; // set alongside agentStatus "error"
  lastError?: string | null;
}

export interface TripError {
  message: string;
  kind: string;
}

/** The trip doc at users/{uid}/trips/{tripId} (fields the UI reads; spec/schema.md). */
export interface TripDoc {
  input?: TripInput;
  status: TripStatus;
  error?: TripError | null; // only if fan-out itself fails
}

// --- display order + labels -------------------------------------------------------------------

// Section order matches the left nav (spec/ui.md): Flights, Accommodation, Activities.
export const DOMAIN_SECTIONS: { domain: Domain; label: string }[] = [
  { domain: "flights", label: "Flights" },
  { domain: "accommodations", label: "Accommodation" },
  { domain: "activities", label: "Activities" },
];

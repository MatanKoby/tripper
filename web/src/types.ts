// TypeScript mirror of the tripper/agent contract (spec/schema.md, tripper/contract.py).
// The UI produces `TripInput` (the job `input`) and renders `TripSuggestions` (the job `results`)
// plus the job doc's lifecycle fields. Field names and shapes match the Pydantic models so the
// backend's strict (extra="forbid") validation accepts what we write.

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

export type AgentStatus = "ok" | "empty" | "degraded";
export type TransportStatus = "ok" | "error";
export type JobStatus = "pending" | "running" | "done" | "error";

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
  lenses?: LensName[] | null; // null = all three
  picks_per_lens?: number; // >= 1, default 3
}

// --- response: hotel agent payload ------------------------------------------------------------

export interface Offer {
  total: number;
  per_night?: number | null;
  currency: string;
  board?: string | null;
  refundable: boolean;
  over_budget?: boolean;
}

export interface Pick {
  name: string;
  score: number; // 0..1, comparable across lenses
  rationale: string;
  why?: Record<string, number>;
  area?: string | null;
  distance_to_desired_km?: number | null;
  price_per_night?: number | null;
  currency?: string | null;
  rating?: number | null; // 0..10
  review_count?: number | null;
  star_rating?: number | null; // 1..5
  description?: string | null;
  amenities?: Amenity[];
  coordinates?: GeoPoint | null;
  image_url?: string | null;
  url?: string | null;
  offers?: Offer[];
}

export interface Resolved {
  city?: string | null;
  area?: string | null;
  center?: GeoPoint | null;
  check_in?: string | null;
  check_out?: string | null;
  currency?: string | null;
}

export interface Diagnostics {
  scorer: string;
  providers_used?: string[];
  candidates_found?: number;
  candidates_after_filter?: number;
  shortlisted?: number;
  widened?: boolean;
}

export interface HotelPayload {
  agent_status: AgentStatus;
  warnings?: string[];
  resolved: Resolved;
  lenses?: Partial<Record<LensName, Pick[]>>; // up to all three keys
  diagnostics: Diagnostics;
}

// --- transport wrapper + job doc --------------------------------------------------------------

export interface TripError {
  message: string;
  kind: string;
}

export interface TripSuggestions {
  status: TransportStatus;
  error?: TripError | null;
  hotel?: HotelPayload | null;
}

/** The Firestore job doc at users/{uid}/trips/{tripId} (fields the UI reads; spec/schema.md). */
export interface TripDoc {
  input?: TripInput;
  status: JobStatus;
  results?: TripSuggestions | null;
  error?: TripError | null;
}

// --- lens display order + labels (for the flattened wireframe list) ---------------------------

export const LENS_LABELS: Record<LensName, string> = {
  stratified_best: "Stratified best",
  overall_standouts: "Overall standouts",
  hidden_gems: "Hidden gems",
};

// Turn the wireframe form state into a clean TripInput, mirroring the client-side invariants the
// backend's Pydantic contract enforces (spec/schema.md): a place locator, check_out > check_in,
// adults >= 1, picks_per_lens >= 1. Empty optionals are omitted so the backend applies its defaults.
import type { Amenity, InterestGroup, TravelStyle, TripInput } from "./types";

export type RefundablePref = "either" | "refundable" | "nonrefundable";

export interface FormState {
  destination: string; // place.text (the locator we expose in M1)
  desiredArea: string;
  checkIn: string; // "YYYY-MM-DD"
  checkOut: string;
  currency: string;
  adults: string;
  childrenAges: string; // comma/space separated ints
  guestNationality: string;
  priceMin: string;
  priceMax: string;
  minStar: string; // "" | "1".."5"
  minGuestRating: string;
  refundable: RefundablePref;
  amenities: Amenity[];
  picksPerLens: string;
  // --- flights ---
  origin: string; // departure point: city name or 3-letter IATA
  flightBudgetUsd: string;
  // --- activities ---
  activitiesBudgetUsd: string;
  interests: InterestGroup[];
  travelStyle: TravelStyle;
}

export const EMPTY_FORM: FormState = {
  destination: "",
  desiredArea: "",
  checkIn: "",
  checkOut: "",
  currency: "EUR",
  adults: "2",
  childrenAges: "",
  guestNationality: "US",
  priceMin: "",
  priceMax: "",
  minStar: "",
  minGuestRating: "",
  refundable: "either",
  amenities: [],
  picksPerLens: "3",
  origin: "",
  flightBudgetUsd: "",
  activitiesBudgetUsd: "",
  interests: [],
  travelStyle: "balanced",
};

/** Parse "6, 9 11" -> [6, 9, 11]; ignores blanks, rejects non-integers. */
function parseAges(raw: string): number[] | null {
  const parts = raw
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const ages: number[] = [];
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 0) return null;
    ages.push(n);
  }
  return ages;
}

function optionalNumber(raw: string): number | undefined {
  const t = raw.trim();
  if (!t) return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}

export type BuildResult =
  | { ok: true; input: TripInput }
  | { ok: false; error: string };

export function buildTripInput(form: FormState): BuildResult {
  const destination = form.destination.trim();
  if (!destination) return { ok: false, error: "Enter a destination." };

  if (!form.checkIn || !form.checkOut) {
    return { ok: false, error: "Pick both a check-in and a check-out date." };
  }
  if (form.checkOut <= form.checkIn) {
    return { ok: false, error: "Check-out must be after check-in." };
  }

  const adults = Number(form.adults);
  if (!Number.isInteger(adults) || adults < 1) {
    return { ok: false, error: "Adults must be a whole number of at least 1." };
  }

  const childrenAges = parseAges(form.childrenAges);
  if (childrenAges === null) {
    return { ok: false, error: "Children ages must be whole numbers (e.g. 6, 9)." };
  }

  const picksPerLens = Number(form.picksPerLens);
  if (!Number.isInteger(picksPerLens) || picksPerLens < 1) {
    return { ok: false, error: "Picks per lens must be a whole number of at least 1." };
  }

  const desiredArea = form.desiredArea.trim();
  const place: TripInput["place"] = { text: destination };
  if (desiredArea) place.desired_area = desiredArea;

  const filters: NonNullable<TripInput["filters"]> = {};
  const priceMin = optionalNumber(form.priceMin);
  const priceMax = optionalNumber(form.priceMax);
  if (priceMin !== undefined) filters.price_min = priceMin;
  if (priceMax !== undefined) filters.price_max = priceMax;
  if (form.minStar) filters.min_star = Number(form.minStar);
  const minGuestRating = optionalNumber(form.minGuestRating);
  if (minGuestRating !== undefined) filters.min_guest_rating = minGuestRating;
  if (form.refundable === "refundable") filters.refundable = true;
  else if (form.refundable === "nonrefundable") filters.refundable = false;
  if (form.amenities.length) filters.must_have_amenities = [...form.amenities];

  const input: TripInput = {
    place,
    stay: {
      check_in: form.checkIn,
      check_out: form.checkOut,
      currency: form.currency.trim() || "EUR",
    },
    guests: { adults, children_ages: childrenAges },
    guest_nationality: form.guestNationality.trim() || "US",
    picks_per_lens: picksPerLens,
    travel_style: form.travelStyle,
  };
  if (Object.keys(filters).length) input.filters = filters;

  // Flights + activities fields: send only what the user set, so the adapters apply their
  // own defaults for the rest (spec/schema.md; empty optionals omitted).
  const origin = form.origin.trim();
  if (origin) input.origin = origin;
  const flightBudget = optionalNumber(form.flightBudgetUsd);
  if (flightBudget !== undefined) input.flight_budget_usd = flightBudget;
  const activitiesBudget = optionalNumber(form.activitiesBudgetUsd);
  if (activitiesBudget !== undefined) input.activities_budget_usd = activitiesBudget;
  if (form.interests.length) input.interests = [...form.interests];

  return { ok: true, input };
}

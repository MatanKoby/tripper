// Premade trip parameters for one-click "quick fill" of the form (a dev/demo convenience, not part
// of the M1 spec). Each preset returns a full FormState built from EMPTY_FORM, with dates computed
// fresh at click time from today's date so the query is always in the future and passes the same
// client-side invariants as a hand-typed one (buildTripInput: check_out > check_in, adults >= 1).
import { EMPTY_FORM, type FormState } from "./buildTripInput";

/** Local-date "YYYY-MM-DD" (avoids the UTC shift a toISOString() slice would introduce). */
function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** The next occurrence of `weekday` (0=Sun .. 6=Sat) strictly after today. */
function nextWeekday(weekday: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const delta = (weekday - d.getDay() + 7) % 7 || 7; // 1..7, never today
  d.setDate(d.getDate() + delta);
  return d;
}

function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

export interface Preset {
  id: string;
  label: string;
  build: () => FormState;
}

export const PRESETS: Preset[] = [
  {
    id: "barcelona-weekend",
    label: "Barcelona · next weekend · 2 adults",
    build: () => {
      const checkIn = nextWeekday(6); // Saturday
      return {
        ...EMPTY_FORM,
        destination: "Barcelona, Spain",
        checkIn: iso(checkIn),
        checkOut: iso(addDays(checkIn, 2)), // Sat -> Mon, 2 nights
        currency: "EUR",
        adults: "2",
        childrenAges: "",
        guestNationality: "US",
        origin: "New York, NY",
        flightBudgetUsd: "900",
        activitiesBudgetUsd: "400",
        interests: ["food", "beach"],
        travelStyle: "balanced",
      };
    },
  },
  {
    id: "paris-friday",
    label: "Paris · next Fri, 3 nights · 2 adults",
    build: () => {
      const checkIn = nextWeekday(5); // Friday
      return {
        ...EMPTY_FORM,
        destination: "Paris, France",
        desiredArea: "Le Marais",
        checkIn: iso(checkIn),
        checkOut: iso(addDays(checkIn, 3)),
        currency: "EUR",
        adults: "2",
        guestNationality: "US",
        origin: "London, UK",
        flightBudgetUsd: "400",
        activitiesBudgetUsd: "600",
        interests: ["culture", "food"],
        travelStyle: "packed",
      };
    },
  },
  {
    id: "rome-family",
    label: "Rome · next weekend · 2 adults + 1 kid",
    build: () => {
      const checkIn = nextWeekday(6); // Saturday
      return {
        ...EMPTY_FORM,
        destination: "Rome, Italy",
        checkIn: iso(checkIn),
        checkOut: iso(addDays(checkIn, 2)),
        currency: "EUR",
        adults: "2",
        childrenAges: "8",
        minStar: "4",
        guestNationality: "US",
        origin: "Berlin, Germany",
        flightBudgetUsd: "500",
        activitiesBudgetUsd: "500",
        interests: ["family", "culture"],
        travelStyle: "relaxed",
      };
    },
  },
];

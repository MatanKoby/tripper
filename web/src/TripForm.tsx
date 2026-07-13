// The trip-input form (right column; spec/ui.md, shape from spec/schema.md). Wireframe only: plain
// inputs, no styling beyond layout. Builds a validated TripInput and hands it to the parent to write.
import { useState } from "react";
import {
  buildTripInput,
  EMPTY_FORM,
  type FormState,
  type RefundablePref,
} from "./buildTripInput";
import { AMENITIES, type Amenity, type TripInput } from "./types";

interface Props {
  onSubmit: (input: TripInput) => void;
  submitting: boolean;
  disabled: boolean; // e.g. not signed in
}

export default function TripForm({ onSubmit, submitting, disabled }: Props) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [validationError, setValidationError] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleAmenity(a: Amenity) {
    setForm((f) => ({
      ...f,
      amenities: f.amenities.includes(a)
        ? f.amenities.filter((x) => x !== a)
        : [...f.amenities, a],
    }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = buildTripInput(form);
    if (!result.ok) {
      setValidationError(result.error);
      return;
    }
    setValidationError(null);
    onSubmit(result.input);
  }

  return (
    <form className="trip-form" onSubmit={handleSubmit}>
      <label>
        Destination
        <input
          type="text"
          value={form.destination}
          placeholder="e.g. Paris, France"
          onChange={(e) => set("destination", e.target.value)}
        />
      </label>

      <label>
        Desired area <span className="hint">(optional)</span>
        <input
          type="text"
          value={form.desiredArea}
          placeholder="e.g. Le Marais"
          onChange={(e) => set("desiredArea", e.target.value)}
        />
      </label>

      <div className="row">
        <label>
          Check-in
          <input
            type="date"
            value={form.checkIn}
            onChange={(e) => set("checkIn", e.target.value)}
          />
        </label>
        <label>
          Check-out
          <input
            type="date"
            value={form.checkOut}
            onChange={(e) => set("checkOut", e.target.value)}
          />
        </label>
      </div>

      <div className="row">
        <label>
          Adults
          <input
            type="number"
            min={1}
            value={form.adults}
            onChange={(e) => set("adults", e.target.value)}
          />
        </label>
        <label>
          Children ages <span className="hint">(e.g. 6, 9)</span>
          <input
            type="text"
            value={form.childrenAges}
            onChange={(e) => set("childrenAges", e.target.value)}
          />
        </label>
      </div>

      <div className="row">
        <label>
          Currency
          <input
            type="text"
            value={form.currency}
            onChange={(e) => set("currency", e.target.value)}
          />
        </label>
        <label>
          Guest nationality
          <input
            type="text"
            value={form.guestNationality}
            onChange={(e) => set("guestNationality", e.target.value)}
          />
        </label>
      </div>

      <fieldset>
        <legend>Filters (optional)</legend>
        <div className="row">
          <label>
            Min price / night
            <input
              type="number"
              min={0}
              value={form.priceMin}
              onChange={(e) => set("priceMin", e.target.value)}
            />
          </label>
          <label>
            Max price / night
            <input
              type="number"
              min={0}
              value={form.priceMax}
              onChange={(e) => set("priceMax", e.target.value)}
            />
          </label>
        </div>
        <div className="row">
          <label>
            Min stars
            <select value={form.minStar} onChange={(e) => set("minStar", e.target.value)}>
              <option value="">Any</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={String(n)}>
                  {n}+
                </option>
              ))}
            </select>
          </label>
          <label>
            Min guest rating
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              value={form.minGuestRating}
              onChange={(e) => set("minGuestRating", e.target.value)}
            />
          </label>
        </div>
        <label>
          Refundable
          <select
            value={form.refundable}
            onChange={(e) => set("refundable", e.target.value as RefundablePref)}
          >
            <option value="either">Either</option>
            <option value="refundable">Refundable only</option>
            <option value="nonrefundable">Non-refundable only</option>
          </select>
        </label>
        <div className="amenities">
          <span>Must-have amenities</span>
          <div className="amenity-grid">
            {AMENITIES.map((a) => (
              <label key={a} className="checkbox">
                <input
                  type="checkbox"
                  checked={form.amenities.includes(a)}
                  onChange={() => toggleAmenity(a)}
                />
                {a}
              </label>
            ))}
          </div>
        </div>
        <label>
          Picks per lens
          <input
            type="number"
            min={1}
            value={form.picksPerLens}
            onChange={(e) => set("picksPerLens", e.target.value)}
          />
        </label>
      </fieldset>

      {validationError && <p className="form-error">{validationError}</p>}

      <button type="submit" disabled={submitting || disabled}>
        {submitting ? "Submitting..." : "Plan trip"}
      </button>
      {disabled && <p className="hint">Sign in to plan a trip.</p>}
    </form>
  );
}

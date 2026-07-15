// The trip-input form (right column; spec/ui.md, shape from spec/schema.md). A Quick fill chip card
// above one white form card. Builds a validated TripInput and hands it to the parent to write; the
// parent passes the job-status pill in via statusSlot so it renders under the submit button.
import { useState, type ReactNode } from "react";
import {
  buildTripInput,
  EMPTY_FORM,
  type FormState,
  type RefundablePref,
} from "./buildTripInput";
import { PRESETS } from "./presets";
import { AMENITIES, type Amenity, type TripInput } from "./types";

interface Props {
  onSubmit: (input: TripInput) => void;
  submitting: boolean; // true until the job resolves; keeps the submit button disabled
  disabled: boolean; // e.g. not signed in
  statusSlot?: ReactNode; // the job-status pill, rendered under the submit button
}

export default function TripForm({ onSubmit, submitting, disabled, statusSlot }: Props) {
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
    <form className="trp-sidebits" onSubmit={handleSubmit}>
      <div className="trp-quick">
        <div className="trp-label">Quick fill</div>
        <div className="trp-chips">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              className="trp-chip"
              onClick={() => {
                setForm(p.build());
                setValidationError(null);
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="trp-form">
        <div className="trp-label">Plan a trip</div>

        <label className="trp-field">
          <span>Destination</span>
          <input
            type="text"
            value={form.destination}
            placeholder="Where to?"
            onChange={(e) => set("destination", e.target.value)}
          />
        </label>

        <label className="trp-field">
          <span>Desired area (optional)</span>
          <input
            type="text"
            value={form.desiredArea}
            placeholder="e.g. Le Marais"
            onChange={(e) => set("desiredArea", e.target.value)}
          />
        </label>

        <div className="trp-row2">
          <label className="trp-field">
            <span>Check-in</span>
            <input
              type="date"
              value={form.checkIn}
              onChange={(e) => set("checkIn", e.target.value)}
            />
          </label>
          <label className="trp-field">
            <span>Check-out</span>
            <input
              type="date"
              value={form.checkOut}
              onChange={(e) => set("checkOut", e.target.value)}
            />
          </label>
        </div>

        <div className="trp-row2">
          <label className="trp-field">
            <span>Adults</span>
            <input
              type="number"
              min={1}
              value={form.adults}
              onChange={(e) => set("adults", e.target.value)}
            />
          </label>
          <label className="trp-field">
            <span>Children ages (e.g. 6, 9)</span>
            <input
              type="text"
              value={form.childrenAges}
              onChange={(e) => set("childrenAges", e.target.value)}
            />
          </label>
        </div>

        <div className="trp-row2">
          <label className="trp-field">
            <span>Currency</span>
            <input
              type="text"
              value={form.currency}
              onChange={(e) => set("currency", e.target.value)}
            />
          </label>
          <label className="trp-field">
            <span>Guest nationality</span>
            <input
              type="text"
              value={form.guestNationality}
              onChange={(e) => set("guestNationality", e.target.value)}
            />
          </label>
        </div>

        <fieldset className="trp-fieldset">
          <legend>Filters (optional)</legend>
          <div className="trp-row2">
            <label className="trp-field">
              <span>Min price / night</span>
              <input
                type="number"
                min={0}
                value={form.priceMin}
                onChange={(e) => set("priceMin", e.target.value)}
              />
            </label>
            <label className="trp-field">
              <span>Max price / night</span>
              <input
                type="number"
                min={0}
                value={form.priceMax}
                onChange={(e) => set("priceMax", e.target.value)}
              />
            </label>
          </div>
          <div className="trp-row2">
            <label className="trp-field">
              <span>Min stars</span>
              <select value={form.minStar} onChange={(e) => set("minStar", e.target.value)}>
                <option value="">Any</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={String(n)}>
                    {n}+
                  </option>
                ))}
              </select>
            </label>
            <label className="trp-field">
              <span>Min guest rating</span>
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
          <label className="trp-field">
            <span>Refundable</span>
            <select
              value={form.refundable}
              onChange={(e) => set("refundable", e.target.value as RefundablePref)}
            >
              <option value="either">Either</option>
              <option value="refundable">Refundable only</option>
              <option value="nonrefundable">Non-refundable only</option>
            </select>
          </label>
          <div className="trp-amenities">
            <span>Must-have amenities</span>
            <div className="trp-amenity-grid">
              {AMENITIES.map((a) => (
                <label key={a} className="trp-check">
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
          <label className="trp-field">
            <span>Picks per lens</span>
            <input
              type="number"
              min={1}
              value={form.picksPerLens}
              onChange={(e) => set("picksPerLens", e.target.value)}
            />
          </label>
        </fieldset>

        {validationError && <p className="trp-form-error">{validationError}</p>}

        <button type="submit" className="trp-submit" disabled={submitting || disabled}>
          {submitting ? "Searching…" : "Find my trip"}
        </button>
        {statusSlot}
        {disabled && <p className="trp-hint">Sign in to plan a trip.</p>}
      </div>
    </form>
  );
}

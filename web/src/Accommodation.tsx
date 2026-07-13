// The Accommodation center container (spec/ui.md). Renders the job lifecycle: a warming-up state
// while pending/running (cold start can take a few minutes: spec/architecture.md), the error
// message on error, and the hotel picks on done. Picks come from results.hotel.lenses, rendered as
// the three lens groups (empty groups omitted); there is no results.hotel.items in the contract.
import {
  LENS_LABELS,
  LENS_NAMES,
  type HotelPayload,
  type Pick,
  type TripDoc,
} from "./types";

interface Props {
  doc: TripDoc | null;
  submitting: boolean;
  submitError: string | null;
}

export default function Accommodation({ doc, submitting, submitError }: Props) {
  if (submitError) {
    return <p className="error">Could not start the job: {submitError}</p>;
  }
  if (!doc && !submitting) {
    return <p className="placeholder">Submit a trip to see hotel picks.</p>;
  }

  const status = doc?.status;
  if (submitting || status === "pending" || status === "running") {
    return (
      <p className="thinking">
        Thinking / warming up... the first request can take a few minutes on a cold start.
      </p>
    );
  }

  if (status === "error") {
    const message = doc?.error?.message ?? doc?.results?.error?.message ?? "Unknown error.";
    return <p className="error">The job failed: {message}</p>;
  }

  if (status === "done") {
    const hotel = doc?.results?.hotel;
    if (!hotel) return <p className="error">Job finished without hotel results.</p>;
    return <HotelResults hotel={hotel} />;
  }

  return <p className="placeholder">Submit a trip to see hotel picks.</p>;
}

function HotelResults({ hotel }: { hotel: HotelPayload }) {
  const lenses = hotel.lenses ?? {};
  const groups = LENS_NAMES.map((name) => ({ name, picks: lenses[name] ?? [] })).filter(
    (g) => g.picks.length > 0,
  );
  const total = groups.reduce((n, g) => n + g.picks.length, 0);

  return (
    <div className="hotel-results">
      {hotel.agent_status !== "ok" && (
        <p className="agent-status">Agent status: {hotel.agent_status}</p>
      )}
      {(hotel.warnings ?? []).map((w, i) => (
        <p key={i} className="warning">
          {w}
        </p>
      ))}

      {total === 0 ? (
        <p className="placeholder">No hotels matched this search.</p>
      ) : (
        groups.map((g) => (
          <div key={g.name} className="lens-group">
            <h3>{LENS_LABELS[g.name]}</h3>
            <ul className="picks">
              {g.picks.map((p, i) => (
                <PickRow key={`${p.name}-${i}`} pick={p} />
              ))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}

function PickRow({ pick }: { pick: Pick }) {
  const price =
    pick.price_per_night != null
      ? `${pick.price_per_night}${pick.currency ? ` ${pick.currency}` : ""} / night`
      : null;
  const meta = [
    pick.star_rating != null ? `${pick.star_rating}★` : null,
    pick.rating != null
      ? `${pick.rating}/10${pick.review_count != null ? ` (${pick.review_count})` : ""}`
      : null,
    pick.area ?? null,
    price,
  ].filter(Boolean);

  return (
    <li className="pick">
      <div className="pick-head">
        <strong>{pick.url ? <a href={pick.url}>{pick.name}</a> : pick.name}</strong>
        {meta.length > 0 && <span className="pick-meta"> — {meta.join(" · ")}</span>}
      </div>
      {pick.rationale && <p className="rationale">{pick.rationale}</p>}
      {(pick.amenities?.length ?? 0) > 0 && (
        <p className="amenity-list">{pick.amenities!.join(", ")}</p>
      )}
    </li>
  );
}

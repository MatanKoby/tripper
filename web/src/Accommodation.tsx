// The Accommodation center container (spec/ui.md). Renders the job lifecycle: a dashed idle card,
// the "Warming up… / Thinking…" spinner + skeletons while pending/running (cold start can take a
// few minutes: spec/architecture.md), a red-tinted card on error, and on done the hotel picks from
// results.hotel.lenses grouped by lens (empty groups omitted).
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
    return (
      <div className="trp-error">
        <strong>Could not start the job.</strong> {submitError}
      </div>
    );
  }

  const status = doc?.status;
  if (submitting || status === "pending" || status === "running") {
    return (
      <div className="trp-thinking">
        <div className="trp-spinner" aria-hidden />
        <div>
          <div className="trp-thinking-title">
            {status === "running" ? "Thinking…" : "Warming up…"}
          </div>
          <div className="trp-thinking-sub">
            The first search can take a few minutes on a cold start.
          </div>
        </div>
        <div className="trp-skeletons">
          {[0, 1, 2].map((i) => (
            <div key={i} className="trp-skel" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      </div>
    );
  }

  if (status === "error") {
    const message = doc?.error?.message ?? doc?.results?.error?.message ?? "Unknown error.";
    return (
      <div className="trp-error">
        <strong>Something went wrong.</strong> {message}
      </div>
    );
  }

  if (status === "done") {
    const hotel = doc?.results?.hotel;
    if (!hotel) {
      return (
        <div className="trp-error">
          <strong>Something went wrong.</strong> Job finished without hotel results.
        </div>
      );
    }
    const dest = doc?.input?.place?.text ?? doc?.input?.place?.city ?? null;
    return <HotelResults hotel={hotel} dest={dest} />;
  }

  return (
    <div className="trp-empty">
      <div className="trp-empty-art" aria-hidden>
        🏨
      </div>
      <p>
        Fill in the trip on the right (or tap a Quick fill) and Tripper will suggest places to
        stay.
      </p>
    </div>
  );
}

function HotelResults({ hotel, dest }: { hotel: HotelPayload; dest: string | null }) {
  const lenses = hotel.lenses ?? {};
  const groups = LENS_NAMES.map((name) => ({ name, picks: lenses[name] ?? [] })).filter(
    (g) => g.picks.length > 0,
  );
  const total = groups.reduce((n, g) => n + g.picks.length, 0);

  return (
    <div className="trp-lenses">
      {hotel.agent_status !== "ok" && (
        <p className="trp-note-warn">Agent status: {hotel.agent_status}</p>
      )}
      {(hotel.warnings ?? []).map((w, i) => (
        <p key={i} className="trp-note-warn">
          {w}
        </p>
      ))}

      {total === 0 ? (
        <div className="trp-empty">
          <p>No hotels matched this search.</p>
        </div>
      ) : (
        groups.map((g) => (
          <div key={g.name} className="trp-lens">
            <div className="trp-lens-head">
              <span className="trp-lens-name">{LENS_LABELS[g.name]}</span>
              <span className="trp-lens-count">
                {g.picks.length} option{g.picks.length > 1 ? "s" : ""}
                {dest ? ` in ${dest}` : ""}
              </span>
            </div>
            <div className="trp-cards">
              {g.picks.map((p, i) => (
                <HotelCard key={`${p.name}-${i}`} pick={p} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function HotelCard({ pick }: { pick: Pick }) {
  return (
    <article className="trp-card">
      <div className="trp-card-main">
        <h3>
          {pick.url ? (
            <a href={pick.url} target="_blank" rel="noreferrer">
              {pick.name}
            </a>
          ) : (
            pick.name
          )}
        </h3>
        {pick.area && <div className="trp-card-area">{pick.area}</div>}
        {pick.rationale && <p>{pick.rationale}</p>}
      </div>
      <div className="trp-card-side">
        {pick.rating != null && <div className="trp-rating">{pick.rating}</div>}
        {pick.price_per_night != null && (
          <div className="trp-price">
            {pick.price_per_night}
            <span>
              {pick.currency ? ` ${pick.currency}` : ""}/night
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

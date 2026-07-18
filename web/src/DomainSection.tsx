// One center container per domain (spec/ui.md). The section's state is driven by its own
// `domains/{domain}.agentStatus` (spec/flows.md): pending / running (or before fan-out has created
// the domain doc) shows the "thinking / warming up" state, idle renders the candidates, error shows
// the message. In the idle state the section adds the M2 feedback / refine / selection controls
// (spec/ui.md): per-candidate like / dislike (writes `feedback`) and select, a per-section Refine
// button (only shown when idle), and a selected slot. The raw-JSON dump of the candidates is kept
// alongside the controls (M2's first-pass render, spec/ui.md); a styled per-domain renderer and
// grouping by lens/round are deferred (spec/roadmap.md). Dismissed candidates are filtered out.
import type { DomainState } from "./useJob";
import type { Domain, Feedback, SuggestedDoc, TripError, TripStatus } from "./types";

interface Props {
  domain: Domain;
  label: string;
  state: DomainState;
  started: boolean; // a trip has been submitted (listeners are live)
  tripStatus: TripStatus | undefined;
  tripError: TripError | null | undefined;
  submitError: string | null;
  onFeedback: (d: Domain, suggestionId: string, feedback: Feedback) => void;
  onRefine: (d: Domain) => void;
  onSelect: (d: Domain, suggestion: SuggestedDoc) => void;
  onDeselect: (d: Domain, selectedId: string) => void;
}

export default function DomainSection({
  domain,
  label,
  state,
  started,
  tripStatus,
  tripError,
  submitError,
  onFeedback,
  onRefine,
  onSelect,
  onDeselect,
}: Props) {
  if (submitError) {
    return <p className="error">Could not start the job: {submitError}</p>;
  }
  if (!started) {
    return <p className="placeholder">Submit a trip to see {label.toLowerCase()} suggestions.</p>;
  }

  // Fan-out itself failed: no domain docs will ever be created (spec/schema.md).
  if (tripStatus === "error") {
    return <p className="error">The trip failed to start: {tripError?.message ?? "Unknown error."}</p>;
  }

  const status = state.doc?.agentStatus;

  // No domain doc yet (fan-out pending) or the run is still going: cold start can take a few
  // minutes (spec/architecture.md). A refine also sets the domain running, so this covers it too.
  if (!state.doc || status === "pending" || status === "running") {
    return (
      <p className="thinking">
        Thinking / warming up... the first request can take a few minutes on a cold start.
      </p>
    );
  }

  if (status === "error") {
    return (
      <p className="error">This search failed: {state.doc.error?.message ?? state.doc.lastError ?? "Unknown error."}</p>
    );
  }

  // idle: a round completed. Render the controls + the raw JSON of the candidates (spec/ui.md).
  const warnings = state.doc.warnings ?? [];
  const visible = state.suggested.filter((s) => !s.dismissed);
  const selectedIds = new Set(state.selected.map((s) => s.suggestionId));
  const refineFailed = state.refinement?.status === "error";

  return (
    <div className="domain-results">
      {warnings.map((w, i) => (
        <p key={i} className="warning">
          {w}
        </p>
      ))}

      {refineFailed && (
        <p className="error">
          The last refine failed: {state.refinement?.error?.message ?? state.refinement?.lastError ?? "Unknown error."}
        </p>
      )}

      <div className="section-actions">
        {/* The Refine button is only reachable in the idle state, so it is always enabled here
            (spec/ui.md: enabled only when the domain is idle). */}
        <button type="button" onClick={() => onRefine(domain)}>
          Refine with my likes / dislikes
        </button>
      </div>

      {state.selected.length > 0 && (
        <div className="selected-slot">
          <h3>Selected</h3>
          <ul>
            {state.selected.map((sel) => (
              <li key={sel.id}>
                {sel.snapshot.title}
                <button type="button" onClick={() => onDeselect(domain, sel.id)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {visible.length === 0 ? (
        <p className="placeholder">No suggestions for this search.</p>
      ) : (
        <>
          <ul className="suggestions">
            {visible.map((s) => (
              <li key={s.id} className="suggestion">
                <span className="suggestion-title">
                  {s.title}
                  {s.round && s.round > 1 ? ` (round ${s.round})` : ""}
                </span>
                <span className="controls">
                  <button
                    type="button"
                    aria-pressed={s.feedback === "liked"}
                    onClick={() => onFeedback(domain, s.id, "liked")}
                  >
                    {s.feedback === "liked" ? "★ Liked" : "Like"}
                  </button>
                  <button
                    type="button"
                    aria-pressed={s.feedback === "disliked"}
                    onClick={() => onFeedback(domain, s.id, "disliked")}
                  >
                    {s.feedback === "disliked" ? "✕ Disliked" : "Dislike"}
                  </button>
                  <button type="button" disabled={selectedIds.has(s.id)} onClick={() => onSelect(domain, s)}>
                    {selectedIds.has(s.id) ? "Selected" : "Select"}
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <pre className="raw-json">{JSON.stringify(visible, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

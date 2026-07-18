// One center container per domain (spec/ui.md). M2's first pass renders each domain's `suggested`
// docs as raw JSON, with the section's state driven by its own `domains/{domain}.agentStatus`
// (spec/flows.md): pending / running (or before fan-out has created the domain doc) shows the
// "thinking / warming up" state, idle renders the candidates, error shows the message. A styled,
// per-domain renderer (cards, grouping by lens, hiding dismissed) is deferred (spec/roadmap.md);
// so are the feedback / refine / selection controls (Batch 13).
import type { DomainState } from "./useJob";
import type { TripError, TripStatus } from "./types";

interface Props {
  label: string;
  state: DomainState;
  started: boolean; // a trip has been submitted (listeners are live)
  tripStatus: TripStatus | undefined;
  tripError: TripError | null | undefined;
  submitError: string | null;
}

export default function DomainSection({
  label,
  state,
  started,
  tripStatus,
  tripError,
  submitError,
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
  // minutes (spec/architecture.md).
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

  // idle: a round completed. Dump the suggestions as raw JSON (spec/ui.md).
  const warnings = state.doc.warnings ?? [];
  return (
    <div className="domain-results">
      {warnings.map((w, i) => (
        <p key={i} className="warning">
          {w}
        </p>
      ))}
      {state.suggested.length === 0 ? (
        <p className="placeholder">No suggestions for this search.</p>
      ) : (
        <pre className="raw-json">{JSON.stringify(state.suggested, null, 2)}</pre>
      )}
    </div>
  );
}

// Three-column frame (spec/ui.md): header wordmark + signed-in user, left scroll-nav tabs, center
// one container per domain section (only Accommodation populated in M1), right the trip-input form
// + job status pill. Auth gate and the Firestore job flow are in useAuth / useJob. Submitting
// scroll-jumps to Accommodation and keeps the submit button disabled until the job resolves.
import { useRef, useState } from "react";
import Accommodation from "./Accommodation";
import TripForm from "./TripForm";
import type { TripDoc, TripInput } from "./types";
import { useAuth } from "./useAuth";
import { useJob } from "./useJob";

const sections = [
  { id: "flights", label: "Flights", soon: true },
  { id: "accommodation", label: "Accommodation", soon: false },
  { id: "activities", label: "Activities", soon: true },
] as const;

type SectionId = (typeof sections)[number]["id"];

const SOON_COPY: Partial<Record<SectionId, { art: string; what: string }>> = {
  flights: { art: "✈", what: "Flight suggestions" },
  activities: { art: "🎟", what: "Activity suggestions" },
};

export default function App() {
  const { user, ready, signIn, signOut } = useAuth();
  const { submitting, doc, tripId, submitError, submit } = useJob(user?.uid ?? null);
  const [active, setActive] = useState<SectionId>("accommodation");
  const sectionRefs = useRef<Partial<Record<SectionId, HTMLElement | null>>>({});

  const jump = (id: SectionId) => {
    setActive(id);
    sectionRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const status = doc?.status;
  const jobActive = submitting || status === "pending" || status === "running";

  const handleSubmit = (input: TripInput) => {
    submit(input);
    jump("accommodation");
  };

  return (
    <div className="trp-root">
      <header className="trp-header">
        <div className="trp-wordmark">
          Tripper<span className="trp-dot">.</span>
        </div>
        <div className="trp-user">
          {!ready ? (
            <span className="trp-hint">Loading…</span>
          ) : user ? (
            <>
              <span className="trp-avatar">
                {(user.displayName ?? user.email ?? "?").charAt(0).toUpperCase()}
              </span>
              <span>Signed in as {user.displayName ?? user.email}</span>
              <button type="button" className="trp-signout" onClick={() => void signOut()}>
                Sign out
              </button>
            </>
          ) : (
            <button type="button" className="trp-signin" onClick={() => void signIn()}>
              Sign in with Google
            </button>
          )}
        </div>
      </header>

      <div className="trp-frame">
        <nav className="trp-nav">
          {sections.map((s) => (
            <button
              key={s.id}
              type="button"
              className={"trp-tab" + (active === s.id ? " is-active" : "")}
              onClick={() => jump(s.id)}
            >
              <span>{s.label}</span>
              {s.soon && <span className="trp-soon-dot" title="Coming soon" />}
            </button>
          ))}
        </nav>

        <main className="trp-main">
          {sections.map((s) => (
            <section
              key={s.id}
              id={s.id}
              ref={(el) => {
                sectionRefs.current[s.id] = el;
              }}
              className="trp-section"
            >
              <div className="trp-section-head">
                <h2>{s.label}</h2>
                {s.soon && <span className="trp-badge">Coming soon</span>}
              </div>
              {s.id === "accommodation" ? (
                <Accommodation doc={doc} submitting={submitting} submitError={submitError} />
              ) : (
                <div className="trp-empty">
                  <div className="trp-empty-art" aria-hidden>
                    {SOON_COPY[s.id]?.art}
                  </div>
                  <p>
                    {SOON_COPY[s.id]?.what} arrive with their agent. For now, start with a place
                    to stay.
                  </p>
                </div>
              )}
            </section>
          ))}
        </main>

        <aside className="trp-side">
          <TripForm
            onSubmit={handleSubmit}
            submitting={jobActive}
            disabled={!user}
            statusSlot={<StatusPill doc={doc} submitting={submitting} submitError={submitError} />}
          />
          {tripId && <p className="trp-hint">Job: {tripId}</p>}
        </aside>
      </div>
    </div>
  );
}

// Dot + short text under the submit button (spec/ui.md under States). Hidden when idle.
function StatusPill({
  doc,
  submitting,
  submitError,
}: {
  doc: TripDoc | null;
  submitting: boolean;
  submitError: string | null;
}) {
  let cls: "warm" | "ok" | "err";
  let text: string;
  if (submitError) {
    cls = "err";
    text = submitError;
  } else if (submitting || doc?.status === "pending") {
    cls = "warm";
    text = "Job queued — warming up";
  } else if (doc?.status === "running") {
    cls = "warm";
    text = "Agent running…";
  } else if (doc?.status === "done") {
    cls = "ok";
    text = "Done — results below";
  } else if (doc?.status === "error") {
    cls = "err";
    text = doc.error?.message ?? doc.results?.error?.message ?? "Error";
  } else {
    return null;
  }
  return (
    <div className={`trp-status trp-status--${cls}`}>
      <span className="trp-status-dot" />
      {text}
    </div>
  );
}

// Three-column wireframe frame (spec/ui.md): left scroll-nav, center one container per domain
// section (all three populated in M2), right the trip-input form + job status. Each section renders
// its own domain's `suggested` from the per-domain read model (useJob). Auth gate and the Firestore
// job flow are in useAuth / useJob.
import DomainSection from "./DomainSection";
import TripForm from "./TripForm";
import { DOMAIN_SECTIONS } from "./types";
import { useAuth } from "./useAuth";
import { useJob } from "./useJob";

export default function App() {
  const { user, ready, signIn, signOut } = useAuth();
  const { submitting, tripId, trip, domains, submitError, submit } = useJob(user?.uid ?? null);
  const started = submitting || tripId !== null;

  return (
    <div className="layout">
      <nav className="left">
        <h1>Tripper</h1>
        <ul>
          {DOMAIN_SECTIONS.map((s) => (
            <li key={s.domain}>
              <a href={`#${s.domain}`}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <main className="center">
        {DOMAIN_SECTIONS.map((s) => (
          <section key={s.domain} id={s.domain} className="section">
            <h2>{s.label}</h2>
            <DomainSection
              label={s.label}
              state={domains[s.domain]}
              started={started}
              tripStatus={trip?.status}
              tripError={trip?.error}
              submitError={submitError}
            />
          </section>
        ))}
      </main>

      <aside className="right">
        <div className="auth-bar">
          {!ready ? (
            <span className="hint">Loading...</span>
          ) : user ? (
            <>
              <span className="hint">{user.email}</span>
              <button type="button" onClick={() => void signOut()}>
                Sign out
              </button>
            </>
          ) : (
            <button type="button" onClick={() => void signIn()}>
              Sign in with Google
            </button>
          )}
        </div>

        <h2>Plan a trip</h2>
        <TripForm onSubmit={submit} submitting={submitting} disabled={!user} />

        {tripId && <p className="job-id hint">Job: {tripId}</p>}
      </aside>
    </div>
  );
}

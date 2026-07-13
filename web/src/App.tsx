// Three-column wireframe frame (spec/ui.md): left scroll-nav, center one container per domain
// section (only Accommodation populated in M1), right the trip-input form + job status. Auth gate
// and the Firestore job flow are in useAuth / useJob.
import Accommodation from "./Accommodation";
import TripForm from "./TripForm";
import { useAuth } from "./useAuth";
import { useJob } from "./useJob";

const sections = [
  { id: "flights", label: "Flights" },
  { id: "accommodation", label: "Accommodation" },
  { id: "activities", label: "Activities" },
] as const;

export default function App() {
  const { user, ready, signIn, signOut } = useAuth();
  const { submitting, doc, tripId, submitError, submit } = useJob(user?.uid ?? null);

  return (
    <div className="layout">
      <nav className="left">
        <h1>Tripper</h1>
        <ul>
          {sections.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <main className="center">
        {sections.map((s) => (
          <section key={s.id} id={s.id} className="section">
            <h2>{s.label}</h2>
            {s.id === "accommodation" ? (
              <Accommodation doc={doc} submitting={submitting} submitError={submitError} />
            ) : (
              <p className="placeholder">Coming soon.</p>
            )}
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

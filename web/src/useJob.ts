// The M2 per-domain job flow (spec/flows.md): create an auto-id trip doc under the signed-in
// user's own users/{uid}/trips, then start listeners on the trip doc PLUS each domain's `suggested`
// collection and its `domains/{domain}` state doc, and finally write { input, status: "pending" }.
// The backend fans out (trip -> one domains/{domain} per active agent) and each domain's search run
// fills its `suggested/*` and drives its `agentStatus`; the listeners stream all of that back so each
// section renders independently (a slow domain never blocks a ready one). The M1 single-doc `results`
// listener this replaces is in spec/archive.md.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  collection,
  doc,
  onSnapshot,
  serverTimestamp,
  setDoc,
  type Unsubscribe,
} from "firebase/firestore";
import { db } from "./firebase";
import {
  DOMAINS,
  type Domain,
  type DomainDoc,
  type SuggestedDoc,
  type TripDoc,
  type TripInput,
} from "./types";

export interface DomainState {
  doc: DomainDoc | null; // null until fan-out creates the domain doc
  suggested: SuggestedDoc[]; // candidates, sorted by round then rank
}

export type DomainStates = Record<Domain, DomainState>;

function emptyDomains(): DomainStates {
  return {
    accommodations: { doc: null, suggested: [] },
    activities: { doc: null, suggested: [] },
    flights: { doc: null, suggested: [] },
  };
}

export interface JobState {
  submitting: boolean; // true from submit() until the pending write lands
  tripId: string | null;
  trip: TripDoc | null; // latest snapshot of the trip doc (null before the first submit)
  domains: DomainStates;
  submitError: string | null; // client-side write / listener failure (e.g. rules denial)
}

const INITIAL: JobState = {
  submitting: false,
  tripId: null,
  trip: null,
  domains: emptyDomains(),
  submitError: null,
};

/** Sort candidates into a stable read order: earliest round first, then the agent's rank. */
function sortSuggested(items: SuggestedDoc[]): SuggestedDoc[] {
  return [...items].sort(
    (a, b) => (a.round ?? 0) - (b.round ?? 0) || (a.rank ?? 0) - (b.rank ?? 0),
  );
}

export function useJob(uid: string | null) {
  const [state, setState] = useState<JobState>(INITIAL);
  const unsubsRef = useRef<Unsubscribe[]>([]);

  const stopListening = useCallback(() => {
    for (const unsub of unsubsRef.current) unsub();
    unsubsRef.current = [];
  }, []);

  // Drop every listener on unmount.
  useEffect(() => stopListening, [stopListening]);

  const patchDomain = useCallback((d: Domain, patch: Partial<DomainState>) => {
    setState((s) => ({
      ...s,
      domains: { ...s.domains, [d]: { ...s.domains[d], ...patch } },
    }));
  }, []);

  const onListenError = useCallback((err: Error) => {
    setState((s) => ({ ...s, submitting: false, submitError: err.message }));
  }, []);

  const submit = useCallback(
    async (input: TripInput) => {
      if (!uid) {
        setState({ ...INITIAL, domains: emptyDomains(), submitError: "Sign in to plan a trip." });
        return;
      }
      stopListening();
      setState({
        submitting: true,
        tripId: null,
        trip: null,
        domains: emptyDomains(),
        submitError: null,
      });

      // Auto-id trip ref under the user's own path, then listen BEFORE writing (flows.md step 2).
      const tripRef = doc(collection(db, "users", uid, "trips"));
      setState((s) => ({ ...s, tripId: tripRef.id }));

      unsubsRef.current.push(
        onSnapshot(
          tripRef,
          (snap) => {
            if (snap.exists()) setState((s) => ({ ...s, trip: snap.data() as TripDoc }));
          },
          onListenError,
        ),
      );

      // Listen to all three possible domains: the backend decides which are active, and an inactive
      // one simply never gets a domain doc or suggestions (spec/flows.md step 3), so its listeners
      // stay empty. The client never enumerates agents.
      for (const d of DOMAINS) {
        const domainRef = doc(tripRef, "domains", d);
        unsubsRef.current.push(
          onSnapshot(
            domainRef,
            (snap) => patchDomain(d, { doc: snap.exists() ? (snap.data() as DomainDoc) : null }),
            onListenError,
          ),
          onSnapshot(
            collection(domainRef, "suggested"),
            (snap) =>
              patchDomain(d, {
                suggested: sortSuggested(
                  snap.docs.map((s) => ({ ...s.data(), id: s.id }) as SuggestedDoc),
                ),
              }),
            onListenError,
          ),
        );
      }

      try {
        await setDoc(tripRef, {
          input,
          status: "pending",
          createdAt: serverTimestamp(),
        });
        setState((s) => ({ ...s, submitting: false }));
      } catch (err) {
        stopListening();
        setState((s) => ({
          ...s,
          submitting: false,
          submitError: err instanceof Error ? err.message : String(err),
        }));
      }
    },
    [uid, stopListening, patchDomain, onListenError],
  );

  return { ...state, submit };
}

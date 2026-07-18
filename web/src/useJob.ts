// The M2 per-domain job flow (spec/flows.md): create an auto-id trip doc under the signed-in
// user's own users/{uid}/trips, then start listeners on the trip doc PLUS, for each domain, its
// `domains/{domain}` state doc and its `suggested` / `selected` / `refinements` subcollections, and
// finally write { input, status: "pending" }. The backend fans out (trip -> one domains/{domain}
// per active agent) and each domain's search run fills its `suggested/*` and drives its
// `agentStatus`; the listeners stream all of that back so each section renders independently (a slow
// domain never blocks a ready one). The client also drives the feedback / refine / selection loop
// (spec/flows.md, spec/access.md): it patches a suggestion's `feedback`, creates a `refinements` doc
// to trigger a refine run, and writes a `selected` doc for a choice. The M1 single-doc `results`
// listener this replaces is in spec/archive.md.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  collection,
  deleteDoc,
  doc,
  type DocumentReference,
  onSnapshot,
  serverTimestamp,
  setDoc,
  updateDoc,
  type Unsubscribe,
} from "firebase/firestore";
import { db } from "./firebase";
import {
  DOMAINS,
  type Domain,
  type DomainDoc,
  type Feedback,
  type RefinementDoc,
  type ResultItem,
  type SelectedDoc,
  type SuggestedDoc,
  type TripDoc,
  type TripInput,
} from "./types";

export interface DomainState {
  doc: DomainDoc | null; // null until fan-out creates the domain doc
  suggested: SuggestedDoc[]; // candidates, sorted by round then rank
  selected: SelectedDoc[]; // the user's choices (single for accommodations, many for activities)
  refinement: RefinementDoc | null; // the latest refine request/run, for its status + errors
}

export type DomainStates = Record<Domain, DomainState>;

function emptyDomain(): DomainState {
  return { doc: null, suggested: [], selected: [], refinement: null };
}

function emptyDomains(): DomainStates {
  return {
    accommodations: emptyDomain(),
    activities: emptyDomain(),
    flights: emptyDomain(),
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

/** The latest refine request/run (highest round), or null when the domain has none. */
function latestRefinement(items: RefinementDoc[]): RefinementDoc | null {
  return items.reduce<RefinementDoc | null>(
    (latest, r) => (latest === null || (r.round ?? 0) >= (latest.round ?? 0) ? r : latest),
    null,
  );
}

/** Copy only the neutral ResultItem fields, so a selection snapshot is clean (no run/sort keys). */
function toSnapshot(s: SuggestedDoc): ResultItem {
  return {
    title: s.title,
    subtitle: s.subtitle ?? null,
    score: s.score ?? null,
    price: s.price ?? null,
    rating: s.rating ?? null,
    image_url: s.image_url ?? null,
    url: s.url ?? null,
    badges: s.badges ?? [],
    rationale: s.rationale ?? null,
    detail: s.detail ?? {},
  };
}

export function useJob(uid: string | null) {
  const [state, setState] = useState<JobState>(INITIAL);
  const unsubsRef = useRef<Unsubscribe[]>([]);
  const tripRef = useRef<DocumentReference | null>(null); // the current trip, for the write actions

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
      const ref = doc(collection(db, "users", uid, "trips"));
      tripRef.current = ref;
      setState((s) => ({ ...s, tripId: ref.id }));

      unsubsRef.current.push(
        onSnapshot(
          ref,
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
        const domainRef = doc(ref, "domains", d);
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
          onSnapshot(
            collection(domainRef, "selected"),
            (snap) =>
              patchDomain(d, {
                selected: snap.docs.map((s) => ({ ...s.data(), id: s.id }) as SelectedDoc),
              }),
            onListenError,
          ),
          onSnapshot(
            collection(domainRef, "refinements"),
            (snap) =>
              patchDomain(d, {
                refinement: latestRefinement(
                  snap.docs.map((s) => ({ ...s.data(), id: s.id }) as RefinementDoc),
                ),
              }),
            onListenError,
          ),
        );
      }

      try {
        await setDoc(ref, {
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

  // --- feedback / refine / selection actions (spec/flows.md, spec/access.md) -------------------

  /** Toggle the wanted/unwanted mark on a candidate (the only field the client may patch). */
  const setFeedback = useCallback(
    async (d: Domain, suggestionId: string, feedback: Feedback) => {
      const trip = tripRef.current;
      if (!trip) return;
      const current = state.domains[d].suggested.find((s) => s.id === suggestionId)?.feedback;
      const next = current === feedback ? null : feedback; // click the active mark again to clear it
      await updateDoc(doc(trip, "domains", d, "suggested", suggestionId), { feedback: next });
    },
    [state.domains],
  );

  /** Create a `refinements` doc to trigger a refine run over the current feedback marks. */
  const refine = useCallback(async (d: Domain) => {
    const trip = tripRef.current;
    if (!trip) return;
    const round = (state.domains[d].doc?.round ?? 1) + 1; // display value; the backend is the source
    await setDoc(doc(collection(trip, "domains", d, "refinements")), {
      round,
      status: "pending",
      createdAt: serverTimestamp(),
    });
  }, [state.domains]);

  /** Write a chosen candidate as a `selected` doc (single-select overwrites the one choice). */
  const select = useCallback(
    async (d: Domain, suggestion: SuggestedDoc) => {
      const trip = tripRef.current;
      if (!trip) return;
      const single = state.domains[d].doc?.selectionMode !== "multi";
      const selectedId = single ? "choice" : suggestion.id; // one slot for single, per-item for multi
      await setDoc(doc(trip, "domains", d, "selected", selectedId), {
        suggestionId: suggestion.id,
        snapshot: toSnapshot(suggestion),
        status: "selected",
        createdAt: serverTimestamp(),
      });
    },
    [state.domains],
  );

  /** Remove a selection (the client owns its `selected` docs, spec/access.md). */
  const deselect = useCallback(async (d: Domain, selectedId: string) => {
    const trip = tripRef.current;
    if (!trip) return;
    await deleteDoc(doc(trip, "domains", d, "selected", selectedId));
  }, []);

  return { ...state, submit, setFeedback, refine, select, deselect };
}

// The M1 job flow (spec/flows.md, steps 1-5): create an auto-id doc under the signed-in user's own
// users/{uid}/trips, start a Firestore listener on it, then write { input, status: "pending" }.
// The backend transitions the doc through running -> done | error; the listener streams each state
// back so the UI can render results or the error message.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  collection,
  doc,
  onSnapshot,
  serverTimestamp,
  setDoc,
} from "firebase/firestore";
import { db } from "./firebase";
import type { TripDoc, TripInput } from "./types";

export interface JobState {
  submitting: boolean; // true from submit() until the pending write lands
  doc: TripDoc | null; // latest snapshot of the job doc (null before the first submit)
  tripId: string | null;
  submitError: string | null; // client-side write / listener failure (e.g. rules denial)
}

const INITIAL: JobState = {
  submitting: false,
  doc: null,
  tripId: null,
  submitError: null,
};

export function useJob(uid: string | null) {
  const [state, setState] = useState<JobState>(INITIAL);
  const unsubRef = useRef<(() => void) | null>(null);

  const stopListening = useCallback(() => {
    unsubRef.current?.();
    unsubRef.current = null;
  }, []);

  // Drop the listener on unmount.
  useEffect(() => stopListening, [stopListening]);

  const submit = useCallback(
    async (input: TripInput) => {
      if (!uid) {
        setState({ ...INITIAL, submitError: "Sign in to plan a trip." });
        return;
      }
      stopListening();
      setState({ submitting: true, doc: null, tripId: null, submitError: null });

      // Auto-id ref under the user's own path, then listen BEFORE writing (flows.md step 2).
      const ref = doc(collection(db, "users", uid, "trips"));
      setState((s) => ({ ...s, tripId: ref.id }));

      unsubRef.current = onSnapshot(
        ref,
        (snap) => {
          if (snap.exists()) {
            setState((s) => ({ ...s, doc: snap.data() as TripDoc }));
          }
        },
        (err) => {
          setState((s) => ({ ...s, submitting: false, submitError: err.message }));
        },
      );

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
    [uid, stopListening],
  );

  return { ...state, submit };
}

// Google sign-in state (spec/access.md). Wraps Firebase Auth's onAuthStateChanged so the app can
// gate the form behind a signed-in user and carry that identity into every Firestore call.
import { useEffect, useState } from "react";
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut as fbSignOut,
  type User,
} from "firebase/auth";
import { auth, googleProvider } from "./firebase";

export interface AuthState {
  user: User | null;
  ready: boolean; // false until the first auth-state callback resolves
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

export function useAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    return onAuthStateChanged(auth, (u) => {
      setUser(u);
      setReady(true);
    });
  }, []);

  return {
    user,
    ready,
    signIn: async () => {
      await signInWithPopup(auth, googleProvider);
    },
    signOut: () => fbSignOut(auth),
  };
}

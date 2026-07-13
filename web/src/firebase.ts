// Firebase app + Auth + Firestore singletons, configured from VITE_FIREBASE_* env vars.
// See spec/architecture.md (the FE talks only to Firebase) and spec/access.md (Google sign-in).
import { initializeApp } from "firebase/app";
import { connectAuthEmulator, getAuth, GoogleAuthProvider } from "firebase/auth";
import { connectFirestoreEmulator, getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);
export const googleProvider = new GoogleAuthProvider();

// Local dev: point the SDK at the Firebase emulators (ports from repo-root firebase.json).
// Guarded so a stray "true" in production is the only way to divert traffic off the real project.
if (import.meta.env.VITE_USE_EMULATOR === "true") {
  connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true });
  connectFirestoreEmulator(db, "localhost", 8080);
}

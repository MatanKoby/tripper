# tripper web

Vite + React (TypeScript) frontend for tripper. Deployed on Vercel with the
project **Root Directory** set to `web/`. M1 is an unstyled wireframe (see
`spec/ui.md`): correct layout + a working end-to-end Firestore job flow, no visual design.

## What it does

- Google sign-in (Firebase Auth), gated by the access allowlist (`spec/access.md`).
- Three-column layout: left scroll-nav (Flights / Accommodation / Activities),
  center one container per section (only **Accommodation** is populated in M1;
  the others say "coming soon"), right the trip-input form + submit + job status.
- On submit it creates `users/{uid}/trips/{autoId}`, listens on it, and writes
  `{ input, status: "pending" }` (`spec/flows.md`). It renders `results.hotel.lenses`
  on `done`, the message on `error`, and a "thinking / warming up" state while
  `pending` / `running` (the first request can cold-start for a few minutes).

## Config

Copy `.env.example` to `.env.local` (gitignored) and fill in the Firebase web
config. In production these are Vercel env vars (Batch 1). Vite only exposes
`VITE_`-prefixed vars to the client.

## Develop

- `npm install`
- `npm run dev` — local dev server.
- `npm run typecheck` — `tsc --noEmit`.
- `npm run build` — typecheck + `vite build` to `dist/`.

### Against the Firebase emulators

Set `VITE_USE_EMULATOR=true` in `.env.local`, then from the repo root run
`firebase emulators:start` (Auth on 9099, Firestore on 8080; ports in the
repo-root `firebase.json`) alongside `npm run dev`. The app connects Auth and
Firestore to the emulators. Seed `config/access` in the Emulator UI (or the app's
create will be denied by the rules) with `{ mode: "open" }` (or an allowlist
containing your sign-in email) — `spec/access.md`.

## Verify

Sign in, submit a trip, and confirm a `done` job renders its hotel picks and an
`error` job shows its message. The Firestore create/listen contract (the exact
doc shape this app writes, allowlist enforcement, and the done/error transitions)
is covered against the real `firestore.rules` by the emulator round-trip run during
Batch 7; the `TripInput` the form builds is cross-checked against the Python
`tripper.contract` (see `CLAIMS.md`).

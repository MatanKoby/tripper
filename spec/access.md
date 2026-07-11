# Access (auth, allowlist & security rules)

## Sign-in

- **Firebase Auth with the Google provider.** The frontend signs the user in with Google; every
  Firestore read and write then carries the user's identity as `request.auth.uid` and email as
  `request.auth.token.email`.
- The backend runs with the **Firebase Admin SDK**, which bypasses security rules. That is why the
  client rules below can be strict while the backend still writes results to the same doc.
- Sign-in replaces the old shared app-secret: there is no public endpoint, and Firestore access is
  gated by auth, the allowlist, and the rules below (`architecture.md` under Access control).

## Access allowlist

Google sign-in is open to any Google account, so access is gated by an admin-only config document:

- `config/access` = `{ mode: "allowlist" | "open", allowedEmails: string[] }` (emails lowercased).
- **`mode: "allowlist"`** lets only listed emails create jobs; **`mode: "open"`** lets any verified
  Google account in. Flip the mode by editing one field; change who is allowed by editing the array.
- The doc is **locked from all clients** (rules deny client read/write), so only the project owner
  edits it, live in the Firebase console, with no redeploy. The rules still read it internally via
  `get()`.
- The backend trigger re-checks membership before doing paid work (defense in depth), refusing a job
  whose owner is not allowed (for example, one created just before the mode changed).

A self-serve admin UI for this is deferred (`roadmap.md`); the console is the M1 knob.

## Ownership model

Jobs live under the signed-in user's own path, so ownership is structural, not a field to guard:
`users/{uid}/trips/{tripId}` (doc shape: `schema.md`). Isolation is the `{uid}` segment matched
against `request.auth.uid`; a user can never name another user's path.

## Security rules

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function accessOk() {
      let cfg = get(/databases/$(database)/documents/config/access).data;
      return request.auth.token.email_verified == true
             && (cfg.mode == 'open'
                 || (request.auth.token.email.lower() in cfg.allowedEmails));
    }

    // Access config + allowlist: admin-only, edited in the console / via Admin SDK.
    match /config/{doc} {
      allow read, write: if false;
    }

    match /users/{uid}/trips/{tripId} {
      allow read:   if request.auth.uid == uid;
      allow create: if request.auth.uid == uid
                    && request.resource.data.status == "pending"
                    && !("results" in request.resource.data)
                    && accessOk();
      allow update, delete: if false;
    }
  }
}
```

- The client may **create** only a clean `pending` doc (no `results`) under its own path *and* only
  if allowed by `accessOk()`, and may **read** its own trips.
- The client may not **update** or **delete**; the backend performs every transition
  (`running` / `done` / `error`) via the Admin SDK.
- `config/access` must be seeded during infra setup, or `get()` fails closed and denies everything.

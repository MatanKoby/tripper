# Access (auth & security rules)

## Sign-in

- **Firebase Auth with the Google provider.** The frontend signs the user in with Google; every
  Firestore read and write then carries the user's identity as `request.auth.uid`.
- The backend runs with the **Firebase Admin SDK**, which bypasses security rules. That is why the
  client rules below can be strict while the backend still writes results to the same doc.
- Sign-in replaces the old shared app-secret: there is no public endpoint, and Firestore access is
  gated by auth + the rules below (`architecture.md` under Access control).

## Ownership model

Jobs live under the signed-in user's own path, so ownership is structural, not a field to guard:
`users/{uid}/trips/{tripId}` (doc shape: `schema.md`). Isolation is the `{uid}` segment matched
against `request.auth.uid`; a user can never name another user's path.

## Security rules

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{uid}/trips/{tripId} {
      allow read:   if request.auth.uid == uid;
      allow create: if request.auth.uid == uid
                    && request.resource.data.status == "pending"
                    && !("results" in request.resource.data);
      allow update, delete: if false;
    }
  }
}
```

- The client may **create** only a clean `pending` doc (no `results`) under its own path, and
  **read** its own trips.
- The client may not **update** or **delete**; the backend performs every transition
  (`running` / `done` / `error`) via the Admin SDK.

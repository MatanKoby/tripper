// Firestore security-rules unit tests for spec/access.md.
//
// Run via `npm test` in this directory, which wraps `node --test` in
// `firebase emulators:exec --only firestore` so a Firestore emulator is up and
// FIRESTORE_EMULATOR_HOST is set. The firebase CLI walks up to the repo-root
// firebase.json for emulator config. Uses the fake `demo-tripper` project so
// the emulator runs fully offline (no credentials).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, before, beforeEach, test } from 'node:test';

import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from '@firebase/rules-unit-testing';
import {
  deleteDoc,
  doc,
  getDoc,
  setDoc,
  setLogLevel,
  updateDoc,
} from 'firebase/firestore';

const HERE = dirname(fileURLToPath(import.meta.url));
const RULES = readFileSync(join(HERE, '..', '..', 'firestore.rules'), 'utf8');

const ALLOWED_EMAIL = 'owner@example.com';

/** @type {import('@firebase/rules-unit-testing').RulesTestEnvironment} */
let testEnv;

// A clean client-writable trip: pending, no results.
function pendingTrip(extra = {}) {
  return { status: 'pending', input: { place: { text: 'Paris' } }, ...extra };
}

// Seed config/access with rules disabled (only the admin path may touch it).
async function seedConfig(mode, allowedEmails) {
  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    await setDoc(doc(ctx.firestore(), 'config/access'), { mode, allowedEmails });
  });
}

// Seed a trip doc directly, bypassing rules (simulates the Admin SDK backend).
async function seedTrip(path, data = pendingTrip()) {
  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    await setDoc(doc(ctx.firestore(), path), data);
  });
}

// Seed any doc directly, bypassing rules (the backend owns the domains subtree).
async function seedDoc(path, data) {
  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    await setDoc(doc(ctx.firestore(), path), data);
  });
}

// Paths under alice's trip subtree (spec/schema.md).
const DOMAIN = 'users/alice/trips/t1/domains/accommodations';
const SUGGESTED = `${DOMAIN}/suggested/s1`;
const SELECTED = `${DOMAIN}/selected/sel1`;
const REFINEMENT = `${DOMAIN}/refinements/r1`;

// A backend-written suggested doc (client may touch only its feedback mark).
function suggestedDoc(extra = {}) {
  return { title: 'Hotel X', score: 0.9, rank: 1, round: 1, dismissed: false,
    feedback: null, ...extra };
}

// A verified user whose (mixed-case) email lowercases onto the allowlist.
function allowed() {
  return testEnv.authenticatedContext('alice', {
    email: 'Owner@Example.com',
    email_verified: true,
  });
}

// A verified user NOT on the allowlist.
function notAllowed() {
  return testEnv.authenticatedContext('mallory', {
    email: 'mallory@example.com',
    email_verified: true,
  });
}

before(async () => {
  setLogLevel('error'); // silence the SDK's expected permission-denied noise
  testEnv = await initializeTestEnvironment({
    projectId: 'demo-tripper',
    firestore: { rules: RULES },
  });
});

after(async () => {
  await testEnv.cleanup();
});

beforeEach(async () => {
  await testEnv.clearFirestore();
  await seedConfig('allowlist', [ALLOWED_EMAIL]); // default: allowlist mode
});

// --- create: the allowlist gate -------------------------------------------

test('allowlisted verified user can create a pending trip under own path', async () => {
  const db = allowed().firestore();
  await assertSucceeds(setDoc(doc(db, 'users/alice/trips/t1'), pendingTrip()));
});

test('non-allowlisted user cannot create', async () => {
  const db = notAllowed().firestore();
  await assertFails(setDoc(doc(db, 'users/mallory/trips/t1'), pendingTrip()));
});

test('open mode lets any verified user create', async () => {
  await seedConfig('open', []);
  const db = notAllowed().firestore();
  await assertSucceeds(setDoc(doc(db, 'users/mallory/trips/t1'), pendingTrip()));
});

test('unverified email is denied even when allowlisted', async () => {
  const db = testEnv
    .authenticatedContext('u', { email: ALLOWED_EMAIL, email_verified: false })
    .firestore();
  await assertFails(setDoc(doc(db, 'users/u/trips/t1'), pendingTrip()));
});

test('unauthenticated user cannot create', async () => {
  const db = testEnv.unauthenticatedContext().firestore();
  await assertFails(setDoc(doc(db, 'users/anon/trips/t1'), pendingTrip()));
});

test('create is denied when config/access is missing (fail closed)', async () => {
  await testEnv.clearFirestore(); // drop the seeded config for this case
  const db = allowed().firestore();
  await assertFails(setDoc(doc(db, 'users/alice/trips/t1'), pendingTrip()));
});

// --- create: shape guards --------------------------------------------------

test('create with a non-pending status is denied', async () => {
  const db = allowed().firestore();
  await assertFails(
    setDoc(doc(db, 'users/alice/trips/t1'), pendingTrip({ status: 'running' })),
  );
});

test('cannot create under another user path', async () => {
  const db = allowed().firestore(); // alice
  await assertFails(setDoc(doc(db, 'users/bob/trips/t1'), pendingTrip()));
});

// --- read: ownership -------------------------------------------------------

test('owner can read own trip', async () => {
  await seedTrip('users/alice/trips/t1');
  const db = allowed().firestore();
  await assertSucceeds(getDoc(doc(db, 'users/alice/trips/t1')));
});

test('cannot read another user trip', async () => {
  await seedTrip('users/alice/trips/t1');
  const db = notAllowed().firestore(); // mallory
  await assertFails(getDoc(doc(db, 'users/alice/trips/t1')));
});

// --- update / delete: backend-only -----------------------------------------

test('client cannot update a trip', async () => {
  await seedTrip('users/alice/trips/t1');
  const db = allowed().firestore();
  await assertFails(updateDoc(doc(db, 'users/alice/trips/t1'), { status: 'done' }));
});

test('client cannot delete a trip', async () => {
  await seedTrip('users/alice/trips/t1');
  const db = allowed().firestore();
  await assertFails(deleteDoc(doc(db, 'users/alice/trips/t1')));
});

// --- config/access: locked from all clients --------------------------------

test('client cannot read config/access', async () => {
  const db = allowed().firestore();
  await assertFails(getDoc(doc(db, 'config/access')));
});

test('client cannot write config/access', async () => {
  const db = allowed().firestore();
  await assertFails(
    setDoc(doc(db, 'config/access'), { mode: 'open', allowedEmails: [] }),
  );
});

// --- domains: backend-owned run state --------------------------------------

test('owner can read own domain doc', async () => {
  await seedDoc(DOMAIN, { domain: 'accommodations', agentStatus: 'idle' });
  const db = allowed().firestore();
  await assertSucceeds(getDoc(doc(db, DOMAIN)));
});

test('client cannot create a domain doc (fan-out is backend-only)', async () => {
  const db = allowed().firestore();
  await assertFails(setDoc(doc(db, DOMAIN), { domain: 'accommodations' }));
});

test('client cannot update a domain doc', async () => {
  await seedDoc(DOMAIN, { domain: 'accommodations', agentStatus: 'running' });
  const db = allowed().firestore();
  await assertFails(updateDoc(doc(db, DOMAIN), { agentStatus: 'idle' }));
});

// --- suggested: read + feedback-only patch ---------------------------------

test('owner can read own suggested doc', async () => {
  await seedDoc(SUGGESTED, suggestedDoc());
  const db = allowed().firestore();
  await assertSucceeds(getDoc(doc(db, SUGGESTED)));
});

test('client can patch only the feedback mark', async () => {
  await seedDoc(SUGGESTED, suggestedDoc());
  const db = allowed().firestore();
  await assertSucceeds(updateDoc(doc(db, SUGGESTED), { feedback: 'liked' }));
});

test('client cannot change a non-feedback field on a suggested doc', async () => {
  await seedDoc(SUGGESTED, suggestedDoc());
  const db = allowed().firestore();
  await assertFails(updateDoc(doc(db, SUGGESTED), { score: 0.1 }));
});

test('client cannot change feedback alongside another field', async () => {
  await seedDoc(SUGGESTED, suggestedDoc());
  const db = allowed().firestore();
  await assertFails(
    updateDoc(doc(db, SUGGESTED), { feedback: 'disliked', dismissed: true }),
  );
});

test('client cannot create a suggested doc', async () => {
  const db = allowed().firestore();
  await assertFails(setDoc(doc(db, SUGGESTED), suggestedDoc()));
});

test('client cannot delete a suggested doc', async () => {
  await seedDoc(SUGGESTED, suggestedDoc());
  const db = allowed().firestore();
  await assertFails(deleteDoc(doc(db, SUGGESTED)));
});

// --- selected: the client owns its own choices -----------------------------

test('owner can create then delete own selected doc', async () => {
  const db = allowed().firestore();
  const ref = doc(db, SELECTED);
  await assertSucceeds(
    setDoc(ref, { suggestionId: 's1', snapshot: { title: 'Hotel X' }, status: 'selected' }),
  );
  await assertSucceeds(deleteDoc(ref));
});

test('cannot create a selected doc under another user path', async () => {
  const db = notAllowed().firestore(); // mallory
  await assertFails(
    setDoc(doc(db, 'users/alice/trips/t1/domains/accommodations/selected/x'),
      { suggestionId: 's1', snapshot: {}, status: 'selected' }),
  );
});

// --- refinements: accessOk()-gated create, backend transitions -------------

test('allowlisted owner can create a pending refinement', async () => {
  const db = allowed().firestore();
  await assertSucceeds(setDoc(doc(db, REFINEMENT), { round: 2, status: 'pending' }));
});

test('refinement create with a non-pending status is denied', async () => {
  const db = allowed().firestore();
  await assertFails(setDoc(doc(db, REFINEMENT), { round: 2, status: 'running' }));
});

test('non-allowlisted user cannot create a refinement', async () => {
  const db = notAllowed().firestore(); // mallory, own path
  await assertFails(
    setDoc(doc(db, 'users/mallory/trips/t1/domains/accommodations/refinements/r1'),
      { round: 2, status: 'pending' }),
  );
});

test('client cannot update a refinement (backend transitions the run)', async () => {
  await seedDoc(REFINEMENT, { round: 2, status: 'pending' });
  const db = allowed().firestore();
  await assertFails(updateDoc(doc(db, REFINEMENT), { status: 'done' }));
});

test('owner can read own refinement', async () => {
  await seedDoc(REFINEMENT, { round: 2, status: 'pending' });
  const db = allowed().firestore();
  await assertSucceeds(getDoc(doc(db, REFINEMENT)));
});

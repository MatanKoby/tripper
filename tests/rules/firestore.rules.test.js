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

test('create carrying results is denied', async () => {
  const db = allowed().firestore();
  await assertFails(
    setDoc(doc(db, 'users/alice/trips/t1'), pendingTrip({ results: {} })),
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

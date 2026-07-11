# Flows

## M1 job lifecycle (happy path)

1. A signed-in user fills the wireframe form (`schema.md` under Trip input) and submits.
2. The frontend creates a ref with an auto-id under its own `users/{uid}/trips`, starts a Firestore
   listener on it, then writes the doc with `input` and `status: "pending"` (`access.md`).
3. The `onCreate` trigger on `users/{userId}/trips/{tripId}` fires the orchestrator (one trigger
   covers all users via the `{userId}` wildcard).
4. The orchestrator **claims the job idempotently** (see below), sets `status: "running"`, then
   runs the active agents through their adapters (M1: hotel). The Nebius endpoint cold-starts if it
   was idle (`architecture.md`).
5. On success it validates the agent output against the contract (`schema.md`) and writes `results`
   + `status: "done"`. The frontend listener renders the options as a plain list (no styling in M1).

## States

`pending` then `running` then `done` or `error`. **`running` is a claim, not proof.** The only
evidence of success is a terminal write: `status: "done"` with schema-valid `results`. Anything
left in `running` means the worker died before it could finish.

## Idempotent claim & lease

Triggers are at-least-once, and the sweeper may re-queue, so the orchestrator claims the job in a
transaction and proceeds only if `status == "pending"` OR (`status == "running"` AND
`leaseExpiresAt < now`). On proceeding it sets `status: "running"`, `startedAt`, `attempts += 1`,
and `leaseExpiresAt = now + budget`, where `budget` covers the worst case (cold start + full loop).
A duplicate delivery whose lease is still valid is skipped. This is the main guard against a second
agent run and its double Nebius spend.

**Lease heartbeat:** while running, a background thread bumps `leaseExpiresAt` every 30 to 60
seconds. This is a Firestore write only; it never touches the Nebius endpoint, so it does not keep
the endpoint warm. It lets a slow-but-alive job (for example, one waiting on a cold start) keep its
lease fresh so the sweeper does not reap it.

## Failure handling

- **Caught errors** (agent error, exception, invalid result): the handler writes `status: "error"`
  with `error{message, kind}` and `lastError`. A failed agent does not crash the request.
- **Hard crashes** (OOM, timeout kill, deploy) never run the except block, so the doc stays in
  `running`. These are caught by the expired lease and the sweeper.

## Sweeper

A scheduled function (Cloud Scheduler, every minute or few) runs a `collectionGroup("trips")` query
for `status == "running"` AND `leaseExpiresAt < now` and, for each hit, either **re-queues** it
(`status: "pending"`) when `attempts < maxAttempts`, or writes terminal `status: "error"` ("worker
died or timed out, gave up") once attempts are exhausted. It writes via the Admin SDK and needs a
composite index on the query. `maxAttempts` stops a poison job from looping and burning spend.

## Cold start

The first request after idle waits about 2 to 3 minutes for the endpoint to warm; we accept this
rather than pay to keep it warm (`architecture.md`). The frontend shows a "thinking / warming up"
state throughout and never has to act: `done` and `error` render their results, and a still-running
job just keeps waiting until the orchestrator or the sweeper drives it to a terminal state.

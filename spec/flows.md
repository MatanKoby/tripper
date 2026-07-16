# Flows

The async job model: the client only ever **creates** Firestore docs, and Firestore `onCreate`
triggers run the backend (there is no direct call path). Each agent invocation (an initial search or
a refine) is a create-triggered, idempotently-claimed, leased job, recovered by the sweeper if its
worker dies. Doc shapes: `schema.md`. Ownership and rules: `access.md`.

## Trip submit & fan-out (happy path)

1. A signed-in user fills the form (`schema.md` → TripInput) and submits.
2. The frontend creates an auto-id trip doc under its own `users/{uid}/trips`, starts its listeners
   (the trip doc plus each domain's `suggested`), then writes `{ input, status: "pending" }`
   (`access.md`).
3. The `onCreate` trigger on `users/{userId}/trips/{tripId}` fires the **fan-out**: the backend sets
   the trip `active` and creates one `domains/{domain}` doc (`agentStatus: "pending"`) per **active**
   agent. The backend decides which agents are active (M2 ships accommodations; activities / flights
   join later, `roadmap.md`), so the client never enumerates agents.
4. Each `domains/{domain}` create fires that domain's **search run**: it claims the domain doc (see
   below), sets `agentStatus: "running"`, runs the agent through its adapter, writes the neutral
   `ResultItem` candidates into `suggested/*` (round 1), then sets `agentStatus: "idle"`.
5. The frontend's per-domain listener renders `suggested` as each domain finishes, independently (a
   slow domain never blocks a ready one), showing each domain's state from its `agentStatus`.

There is **no terminal trip state**: a domain settles at `idle` (viewable, refinable), not "done",
and the user may refine or select at any time.

## Feedback & refine loop

1. The user marks candidates: a write of `feedback: "liked" | "disliked"` on a `suggested` doc (the
   only field the client may change on it, `access.md`). Marks persist as the user browses.
2. The user triggers a refine: the client creates `domains/{domain}/refinements/{refineId}` =
   `{ round: N+1, status: "pending" }`. The FE offers this only once the domain is `idle` (round-1
   results exist), so a cold-start-in-progress search can't be refined against empty suggestions.
3. The `onCreate` on the refinement doc fires the **refine run**: it claims the refinement doc, sets
   the domain `agentStatus: "running"`, reads the current `feedback` marks off `suggested`, calls the
   agent's refine entry point (`agents.md`) with the prior candidates + wanted/unwanted, **appends**
   the returned picks to `suggested` tagged with `round: N+1`, marks the refinement `done`, and
   returns the domain to `idle`.
4. Superseded / unwanted candidates are hidden with `dismissed: true`, not deleted; the FE filters on
   `dismissed` and groups by `round` / `lens`.

## Selection

The user picks a candidate: the client writes a `selected/{itemId}` doc (a `snapshot` of the
suggestion + per-agent `meta`, `schema.md`), and the domain's `selectionStatus` reflects it.
Accommodations is `single` (one selection); the shape supports many for later domains. A selection is
a client write only: it triggers no backend run, and it survives later refine rounds because it holds
a snapshot.

## Idempotent claim & lease (per run)

Both run kinds (search on a domain doc, refine on a refinement doc) use the same claim machinery on
their **own** doc. Triggers are at-least-once and the sweeper may re-queue, so a run claims in a
transaction and proceeds only if the doc is `pending` OR (`running` AND `leaseExpiresAt < now`). On
proceeding it sets `running`, `startedAt`, `attempts += 1`, and `leaseExpiresAt = now + budget`
(budget covers the worst case: cold start + full loop, `architecture.md`). A duplicate delivery whose
lease is still valid is skipped, guarding against a second agent run and its double spend.

**Lease heartbeat:** while a run executes, a background thread bumps `leaseExpiresAt` every 30 to 60
seconds. Firestore write only; it never touches the Nebius endpoint (so it keeps nothing warm), it
just tells the sweeper the worker is alive, so a slow-but-live run (e.g. one waiting on a cold start)
is not reaped.

## Failure handling

- **Caught errors** (agent error, exception, invalid result): the run writes its own doc to `error`
  (`agentStatus` on a domain, `status` on a refinement) with `lastError`. One domain failing never
  fails the others.
- **Hard crashes** (OOM, timeout kill, deploy) never run the except block, so the doc stays
  `running`. These are caught by the expired lease and the sweeper.

## Sweeper

A scheduled function (Cloud Scheduler) runs `collectionGroup` queries for **domain docs** and
**refinement docs** in `running` with `leaseExpiresAt < now`, and for each hit either **re-queues**
it (`pending`) when `attempts < maxAttempts`, or writes terminal `error` once attempts are exhausted.
It writes via the Admin SDK and needs a composite (collection-group) index per query. `maxAttempts`
stops a poison run from looping and burning spend.

## Cold start

The first request after idle waits about 2 to 3 minutes for the Nebius endpoint to warm; we accept
this (`architecture.md`). Fanned-out domains **share** the one endpoint, so the first run warms it and
the rest run warm (fan-out does not multiply cold starts). The FE shows each domain's "thinking /
warming up" state from `agentStatus` and never has to act: `idle` renders results, `error` renders
the message, and a still-`running` run just waits until the run or the sweeper drives it terminal. A
**warm-on-submit ping** (warm the endpoint the instant the trip doc is created) is a deferred option
if the first-search wait becomes a UX problem (`roadmap.md`).

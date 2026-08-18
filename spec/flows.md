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
5. The frontend's per-domain listener renders `suggested` as each domain finishes, independently,
   showing each domain's state from its `agentStatus`. Each domain appears the moment *it* settles,
   but the runs themselves are serialized (see *Fan-out concurrency*), so a slow domain does delay
   the ones queued behind it.

There is **no terminal trip state**: a domain settles at `idle` (viewable, refinable), not "done",
and the user may refine or select at any time.

## Feedback & refine loop

1. The user marks candidates: a write of `feedback: "liked" | "disliked"` on a `suggested` doc (the
   only field the client may change on it, `access.md`). Marks persist as the user browses.
2. The user triggers a refine: the client creates `domains/{domain}/refinements/{refineId}` =
   `{ round: N+1, status: "pending" }`. The FE offers this only once the domain is `idle` (round-1
   results exist), so a cold-start-in-progress search can't be refined against empty suggestions.
3. The `onCreate` on the refinement doc fires the **refine run**: it claims the refinement doc, sets
   the domain `agentStatus: "running"`, reads the current `feedback` marks off `suggested`, and calls
   the agent through its adapter with the prior candidates + wanted/unwanted — the agent's dedicated
   refine entry point where it has one (hotel), or, for an agent that has none (flights, activities),
   a re-run of search with the feedback folded into the request (`agents.md`). It **appends** the
   returned picks to `suggested` tagged with `round: N+1`, marks the refinement `done`, and returns
   the domain to `idle`.
4. Superseded / unwanted candidates are hidden with `dismissed: true`, not deleted; the FE filters on
   `dismissed` and groups by `round` / `lens`.

## Selection

The user picks a candidate: the client writes a `selected/{itemId}` doc (a `snapshot` of the
suggestion + per-agent `meta`, `schema.md`), and the domain's `selectionStatus` reflects it.
Accommodations is `single` (one selection); the shape supports many for later domains. A selection is
a client write only: it triggers no backend run, and it survives later refine rounds because it holds
a snapshot.

## Fan-out concurrency

Every function runs **one instance, one request at a time** (`max_instances = 1`, `concurrency = 1`
in `main.py`). A trip's three domain runs therefore execute **sequentially**, not in parallel, and a
second user's trip queues behind the first.

Both settings are needed for that. `max_instances = 1` on its own still admits up to 80 concurrent
requests into the single container, so the runs would contend for one 256 MB heap and OOM rather
than queue. Pairing it with `concurrency = 1` makes a busy moment cost **latency instead of
failure**, which matters more than usual here because the sweep no longer retries anything: an OOM
is a terminal `error` (see *Sweeper*).

The cost of serializing is smaller than it looks. Fanned-out domains share the one Nebius endpoint,
so the first run absorbs the cold start and the rest run warm (`architecture.md`); sequential runs
mostly pay the warm loop, not three cold starts. The ceiling is a deliberate blast-radius limit
rather than a throughput target (`architecture.md` under *Cost stance*); serving many users at once
would need per-run memory measured first, then `memory` / `concurrency` / `max_instances` chosen
together.

## Idempotent claim & lease (per run)

Both run kinds (search on a domain doc, refine on a refinement doc) use the same claim machinery on
their **own** doc. Triggers are at-least-once, so a run claims in a
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

A backstop for **hard crashes**, not a retry mechanism. It runs `collectionGroup` queries for
**domain docs** and **refinement docs** in `running` with `leaseExpiresAt < now` and drives every hit
straight to terminal `error`; a terminally-failed refinement also resets its parent domain to `idle`.
It writes via the Admin SDK and needs a composite (collection-group) index per query.

**It is not scheduled.** `sweep()` runs at the head of the trip `onCreate` fan-out, so it costs
nothing while the app is idle and runs exactly when stale state starts to matter: someone is about to
look at their trips. Why this is not a Cloud Scheduler job: `architecture.md` under *Cost stance*.

**The reap is terminal, never a re-queue.** Nothing here can re-fire a run: every trigger is an
`onCreate`, a stranded doc already exists, and the Firestore trigger options in `firebase-functions`
expose no `retry`. A re-queue to `pending` would therefore park the doc forever rather than recover
it, and it would never age into the error path either, since `attempts` only increments on claim. So
a dead run is surfaced as `error` for the user to act on instead of being silently retried.
`attempts` / `maxAttempts` stay on the doc as diagnostics but no longer gate the reap.

Recovery is a user action: an `error` domain is terminal until the trip is resubmitted, because
Refine is `idle`-gated (`ui.md`).

## Cold start

The first request after idle waits about 2 to 3 minutes for the Nebius endpoint to warm; we accept
this (`architecture.md`). Fanned-out domains **share** the one endpoint, so the first run warms it and
the rest run warm (fan-out does not multiply cold starts). The FE shows each domain's "thinking /
warming up" state from `agentStatus` and never has to act: `idle` renders results, `error` renders
the message, and a still-`running` run just waits until the run or the sweeper drives it terminal. A
**warm-on-submit ping** (warm the endpoint the instant the trip doc is created) is a deferred option
if the first-search wait becomes a UX problem (`roadmap.md`).

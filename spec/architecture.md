# Architecture

Tripper takes trip parameters from a signed-in user and returns suggestions by delegating to
domain agents, each an agentic loop that calls a Nebius LLM endpoint. Tripper holds the Nebius
credentials and passes them to the agents; it never asks the user for them. Work is asynchronous:
the frontend writes a job to Firestore and listens for the result while the backend does the work.

## Stack

- **Backend**: Python on **Google Cloud Functions (Gen2)**. M1 has two functions: a
  **Firestore-triggered orchestrator** that runs the agents, and a **scheduled sweeper** that
  recovers stuck jobs (`flows.md`). There is no public HTTP job endpoint.
- **Data & auth**: **Firestore** (job docs + real-time listeners) and **Firebase Auth** (Google
  sign-in). See `schema.md` and `access.md`.
- **Agents**: separate public repos, vendored as **git submodules under `vendor/agents/`**
  (read-only to tripper: `agents.md`). M1 uses the **hotel agent** only.
- **Frontend**: a **Vite + React (TypeScript)** single-page app on **Vercel**, using the Firebase
  Web SDK to sign in, write the job, and listen for results. It talks only to Firebase, not to a
  custom backend endpoint. Not styled; layout in `ui.md`.
- **CI/CD**: **GitHub Actions**. Backend deploys to GCP; the frontend deploys to Vercel.

## Major moving parts

- **Orchestrator** (Firestore-triggered): on create of a trip doc it **fans out**, creating a
  `domains/{domain}` doc per active agent; each domain doc (search) and each `refinements` doc
  (refine) is then its own create-triggered, idempotently-claimed, leased run that writes candidates
  into that domain's `suggested`. Independent domains run concurrently. M2 ships accommodations;
  activities / flights join later (`roadmap.md`). Fan-out, lifecycle, and the refine loop: `flows.md`.
- **Sweeper** (scheduled via Cloud Scheduler): recovers domain / refinement runs stuck in `running`
  after a worker crash or timeout. Details: `flows.md`.
- **Agent contract + adapters**: each agent is reached through a tripper-owned **adapter**
  (`tripper/agents/<name>_adapter.py`) that calls the agent's clean API (search, and refine where
  supported), supplies Nebius config, and maps the result to the neutral per-domain storage shape
  (`ResultItem` + `detail`, `schema.md`). The orchestrator knows only that neutral shape and the
  agent contract (`agents.md`).
- **Agent config is per-agent**, read from environment variables (or a settings object) and
  supplied by that agent's adapter. The hotel agent uses `ENABLED_PROVIDERS`, `SCORER`,
  `LLM_BACKEND`, and either the Ollama serverless endpoint (`NEBIUS_ENDPOINT_URL`, optional
  `NEBIUS_ENDPOINT_TOKEN` / `NEBIUS_ENDPOINT_MODEL`, no key) or an OpenAI-compatible LLM
  (`LLM_BASE_URL` + `LLM_API_KEY`), plus `LITEAPI_API_KEY` for real hotel data. There is no
  `NEBIUS_ENDPOINT_ID`. It runs keyless on its defaults (`mock` provider + `heuristic` scorer).

## Deployment & secrets

- **Nebius secret source of truth: GitHub Secrets.** The deploy workflow applies them to the
  agent-running function(s) on every deploy (written to a `.env` the Firebase CLI loads at
  `firebase deploy`). No GCP Secret Manager in M1 (revisit for rotation: `roadmap.md`). CI is
  authoritative for env vars; do not also set them by hand.
- **Deploy split: functions in CI, Firestore config from a workstation.** GitHub Actions deploys the
  **functions** with the Firebase CLI (`firebase deploy --only functions`), the native path for the
  `firebase-functions` SDK, which also wires the Eventarc trigger and the Cloud Scheduler job.
  **Firestore rules and indexes are deployed from a workstation, not from CI**: publishing them
  compiles the rules through the Firebase Rules API, which returns 403 only when the request
  originates from the GitHub-hosted runner (environment-specific, not a missing role; root cause
  unresolved, `roadmap.md`). Runbook and the exact commands: `DEPLOY.md`.
- **Region**: all GCP resources (Cloud Functions, Firestore, Cloud Scheduler) in **`us-central1`**,
  chosen for the broadest free-tier coverage and universal service support. Firestore uses the
  **regional** `us-central1` location (cheaper than multi-region), which is **permanent**.
- **GCP services**: Cloud Functions Gen2 (**event-triggered only**), Firestore, Firebase Auth.
  **No Cloud Scheduler**: the sweep is opportunistic (`flows.md` under *Sweeper*). Everything the
  project runs is inside the free tier, subject to the rules under *Cost stance* below.
- **Access control replaces the old app-secret entirely.** The frontend is gated by Firebase Auth,
  the access allowlist, and Firestore security rules; the backend runs with the Firebase Admin SDK.
  There is no public endpoint to protect (`access.md`).
- **GCP deploy auth** from Actions is **Workload Identity Federation** (no long-lived key); the
  deploy service account and the roles it needs are in `DEPLOY.md`. Infra provisioning steps are a
  `[MANUAL]` checklist you execute.

## Cost stance

The project must cost **₪0.00**, not "little". Two facts drive every decision here:

- **Firestore's free quota applies only to the `(default)` database.** A *named* database is billed
  from the first read, with no free allowance at all. Tripper's `(default)` database is regional
  `us-central1` and reports `freeTier: true`. Never point the backend or the FE at a named database
  (`FirestoreOptions.database`) without pricing it first; a named `dev-firestore` was the sole source
  of this project's only real charge (`archive.md`).
- **Compute, Cloud Scheduler, Cloud Build and Logging free tiers are per *billing account*, not per
  project**, and this account carries the user's other projects. Firestore's quota is per project.
  Idle background work therefore spends quota the rest of the account needs, which is why nothing
  here polls and why Cloud Scheduler is unused: only **three** jobs are free account-wide.

Standing rules:

- Every function declares explicit `memory`, `timeout_sec`, `max_instances`, and `concurrency`.
  These are a ceiling against a runaway, not a tuning knob. `max_instances` is **not** a spending
  dial: with `min_instances = 0` an idle app runs zero instances either way. All functions run at
  `max_instances = 1`, with the agent-running triggers at `concurrency = 3` so a trip's domains
  overlap inside that one instance (`flows.md` under *Fan-out concurrency*).
- **Instance-seconds are the binding resource, and CPU is what caps them.** Gen2 sets `cpu`
  independently of `memory`, and it defaults to a **full vCPU** even at 256 MB. Against the monthly
  free tier (180,000 vCPU-seconds, 360,000 GiB-seconds) that drains CPU quota about **8x faster**
  than memory quota, leaving headroom to roughly 2 GiB of memory before memory binds instead. So:
  cut *instance-time* (concurrency, no idle work) to save quota, and never starve `memory` to save
  a resource that is in surplus. Lowering `cpu` below 1 is the largest unexploited lever, since most
  of a run is spent waiting on the endpoint; size it from measured utilization, not from a guess.
- **Never set `min_instances`.** 0 is the default and the discipline.
- No polling, no keep-warm pings, no scheduled work. A query that matches nothing still bills a read,
  so periodic "check if anything is stuck" work is never free.
- Deployed functions log at `WARNING`; Logging's allotment is account-wide.
- Function images accumulate in Artifact Registry against 0.5 GB free, so the deploy keeps a cleanup
  policy (`DEPLOY.md`).

## Cold starts & long runs

- The Nebius endpoint **scales to zero and is not kept warm**. We accept a cold start of about 2
  to 3 minutes (sometimes more) on the first request after idle; the async job + Firestore listener
  absorbs it. There is deliberately **no keep-warm ping** (we do not want to pay to keep the
  endpoint up when there is no work). This only applies when the LLM scorer is enabled; the default
  heuristic scorer makes no LLM call.
- Because a run can be cold start plus the full agent loop, the function timeout and the job
  **lease** are sized for the worst case, not the typical case (`flows.md`). Concrete values are
  measured later.
- Event-triggered functions have a lower max timeout than HTTP ones and use at-least-once delivery
  with an ack deadline, so a several-minute run risks redelivery mid-flight. **M1 baseline** is the
  event-triggered orchestrator, relying on the idempotency guard (`flows.md`). If measured
  worst-case runs approach the event-function limit, switch the heavy work to a **Cloud Tasks +
  HTTP worker** (Gen2 HTTP timeout up to 60 min); this is the documented fallback (`roadmap.md`).

## M1 defaults

- **Async** job doc + Firestore listener (not synchronous).
- **Google sign-in required**, gated by the access allowlist (`access.md`); **Firestore
  persistence** of the job doc.
- **Cloud Functions Gen2**.

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
- **Frontend**: a simple wireframe on **Vercel** using the Firebase JS SDK to sign in, write the
  job, and listen for results. It talks only to Firebase, not to a custom backend endpoint. Not
  styled; end-to-end correctness only.
- **CI/CD**: **GitHub Actions**. Backend deploys to GCP; the frontend deploys to Vercel.

## Major moving parts

- **Orchestrator** (Firestore-triggered): fires on create of `users/{userId}/trips/{tripId}`,
  claims the job idempotently, routes the relevant fields to each active agent, runs independent
  agents concurrently when there is more than one, and writes results back. M1 has one agent, so
  there is no fan-out yet. Lifecycle and idempotency: `flows.md`.
- **Sweeper** (scheduled via Cloud Scheduler): recovers jobs stuck in `running` after a worker
  crash or timeout. Details: `flows.md`.
- **Agent contract + adapters**: tripper defines one contract (`schema.md`); each agent is reached
  through a tripper-owned **adapter** (`tripper/agents/<name>_adapter.py`) that calls the agent's
  clean API, supplies Nebius config, and maps the result to the contract. The orchestrator knows
  only the contract.
- **Nebius config**: `NEBIUS_API_KEY`, `NEBIUS_ENDPOINT_URL`, `NEBIUS_ENDPOINT_ID`, read from
  environment variables and handed to each agent by its adapter.

## Deployment & secrets

- **Nebius secret source of truth: GitHub Secrets.** The deploy workflow applies them to the
  agent-running function(s) on every deploy (`gcloud functions deploy ... --set-env-vars ...`). No
  GCP Secret Manager in M1 (revisit for rotation: `roadmap.md`). CI is authoritative for env vars;
  do not also set them by hand.
- **GCP services**: Cloud Functions Gen2 (event + scheduled), Firestore, Firebase Auth, Cloud
  Scheduler. All within free tier for M1.
- **Access control replaces the old app-secret entirely.** The frontend is gated by Firebase Auth
  and Firestore security rules; the backend runs with the Firebase Admin SDK. There is no public
  endpoint to protect (`access.md`).
- **GCP deploy auth** from Actions (a service-account key vs Workload Identity Federation) is
  decided in the CI batch.

## Cold starts & long runs

- The Nebius endpoint **scales to zero and is not kept warm**. We accept a cold start of about 2
  to 3 minutes (sometimes more) on the first request after idle; the async job + Firestore listener
  absorbs it. There is deliberately **no keep-warm ping** (we do not want to pay to keep the
  endpoint up when there is no work).
- Because a run can be cold start plus the full agent loop, the function timeout and the job
  **lease** are sized for the worst case, not the typical case (`flows.md`).
- Event-triggered functions have a lower max timeout than HTTP ones and use at-least-once delivery
  with an ack deadline, so a several-minute run risks redelivery mid-flight. **M1 baseline** is the
  event-triggered orchestrator, relying on the idempotency guard (`flows.md`). If measured
  worst-case runs approach the event-function limit, switch the heavy work to a **Cloud Tasks +
  HTTP worker** (Gen2 HTTP timeout up to 60 min); this is the documented fallback (`roadmap.md`).

## M1 defaults

- **Async** job doc + Firestore listener (not synchronous).
- **Google sign-in required**; **Firestore persistence** of the job doc.
- **Cloud Functions Gen2**.

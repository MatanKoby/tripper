# Deploy

How tripper ships. Backend deploys to Google Cloud Functions via GitHub Actions; the frontend
deploys to Vercel via Vercel's Git integration. Region for all GCP resources is `us-central1`
(`spec/architecture.md`).

## Backend — GitHub Actions → Cloud Functions (Gen2)

Workflow: [`.github/workflows/backend.yml`](.github/workflows/backend.yml). Triggers on a push to
`dev` that touches backend-relevant files (frontend-only, test, spec, and docs changes are
skipped), and on manual `workflow_dispatch`.

It authenticates to Google Cloud with **Workload Identity Federation** (no long-lived key), then
runs the **Firebase CLI**:

```
firebase deploy --only functions
```

The Firebase CLI is the native deploy path for the `firebase-functions` Python SDK. From the
decorators in `main.py` it:

- deploys `orchestrate` and wires its Firestore (Eventarc) `onCreate` trigger on
  `users/{userId}/trips/{tripId}`;
- deploys `sweep_stuck_jobs` and **creates/updates the Cloud Scheduler job** (`every 5 minutes`),
  no manual `gcloud scheduler` step.

**Firestore rules and indexes are deployed from a workstation, not from CI** (see the next section).

The `vendor/agents/hotel-finder-agent` submodule is checked out (`submodules: recursive`) and
installed from `requirements.txt` (a local-path entry), so `hotel_finder` is importable at runtime.

### Firestore rules + indexes (deploy from a workstation)

CI deploys **functions only**. Deploying any `firestore` target makes the CLI compile the rules via
`firebaserules.googleapis.com :test`, and that call returns `403 firebaserules.rulesets.test` **only
when the request originates from the GitHub-hosted runner**. The identical impersonated `DEPLOY_SA`
identity passes from a workstation, and both WIF and a static SA key fail the same way from CI, so it
is environment-specific, not a missing role (`DEPLOY_SA` does hold `roles/firebaserules.admin`). Root
cause is unresolved; until it is, deploy Firestore config from a workstation authenticated as an
owner, and re-run whenever `firestore.rules` or `firestore.indexes.json` change (rarely):

```
firebase deploy --only firestore --project <GCP_PROJECT>
```

### Required GitHub configuration

Secrets (Settings → Secrets and variables → Actions → **Secrets**):

| Secret | Purpose |
|---|---|
| `WIF_PROVIDER` | Workload Identity **provider** resource name (`projects/…/locations/global/workloadIdentityPools/…/providers/…`) |
| `DEPLOY_SA` | Deploy **service-account email** the WIF provider impersonates |
| `NEBIUS_ENDPOINT_URL` | Nebius Ollama serverless endpoint URL (only if using the LLM scorer) |
| `NEBIUS_ENDPOINT_TOKEN` | Endpoint token, if the endpoint requires one |
| `LLM_API_KEY` | OpenAI-compatible key, if using the `openai` LLM path instead of the endpoint |
| `LITEAPI_API_KEY` | LiteAPI key, only if `liteapi` is in `ENABLED_PROVIDERS` |

Variables (same screen → **Variables**), all optional — non-secret tuning knobs. When unset, the
backend uses its keyless defaults (`mock` provider + `heuristic` scorer), which need no keys:

| Variable | Default (unset) | Notes |
|---|---|---|
| `GCP_PROJECT` | — (**required**) | Target GCP project id. May instead be a secret of the same name. |
| `ENABLED_PROVIDERS` | `mock` | e.g. `mock,liteapi` |
| `SCORER` | `heuristic` | `heuristic` or `llm` |
| `LLM_BACKEND` | `auto` | `auto` \| `openai` \| `endpoint` |
| `NEBIUS_ENDPOINT_MODEL` | — | Endpoint model id |
| `LLM_BASE_URL` | — | OpenAI-compatible base URL |

Only non-empty values are written to the function env (`spec/architecture.md`: GitHub Secrets are
the source of truth for backend env vars; no GCP Secret Manager in M1).

### GCP prerequisites (provisioned in Batch 1)

Enable these APIs on the project: Cloud Functions, Cloud Run, Cloud Build, Artifact Registry,
Eventarc, Cloud Scheduler, Firestore, and IAM Service Account Credentials.

The deploy service account (`DEPLOY_SA`) needs roles sufficient to deploy Gen2 functions:
`roles/cloudfunctions.developer`, `roles/run.admin`, `roles/cloudbuild.builds.editor`,
`roles/artifactregistry.writer`, `roles/eventarc.admin`, `roles/cloudscheduler.admin`,
`roles/serviceusage.serviceUsageConsumer`, and `roles/iam.serviceAccountUser` on the function's
runtime service account. For the workstation Firestore deploy it also holds `roles/datastore.owner`
(indexes) and `roles/firebaserules.admin` (rules). The WIF provider must be bound to this repository
so Actions can impersonate `DEPLOY_SA`.

First-time Gen2 + Eventarc deploys additionally need these **service-agent** bindings, which the
Firebase CLI tries to add automatically but cannot when `DEPLOY_SA` lacks project IAM-admin. Grant
them once as an owner (the CLI prints the exact commands with the concrete SA emails on failure):

- pubsub service agent → `roles/iam.serviceAccountTokenCreator`
- compute default service account → `roles/run.invoker` and `roles/eventarc.eventReceiver`
- eventarc service agent → `roles/eventarc.serviceAgent` (normally auto-granted; add explicitly only
  if the first `orchestrate` deploy 403s on the Eventarc trigger)

## Frontend — Vercel (Git integration)

The `web/` SPA deploys through **Vercel's Git integration** (already linked in Batch 1): Vercel
builds and deploys automatically on push to `dev`. There is no GitHub Actions workflow for the
frontend by design (`spec/architecture.md` lists "Vercel git integration" as the alternative to a
`frontend.yml`).

Vercel project settings:

- **Root Directory:** `web/`
- **Build Command:** `npm run build` — **Output Directory:** `dist`
- **Environment variables:** the `VITE_FIREBASE_*` values (see `web/.env.example`) and
  `VITE_USE_EMULATOR=false` for production.

## Note: spec drift

`spec/architecture.md` describes the backend deploy as `gcloud functions deploy … --set-env-vars`.
That wording predates the choice of the `firebase-functions` Python SDK, whose functions are
deployed with the Firebase CLI (which also wires the Eventarc trigger and the Cloud Scheduler job
from the decorators — raw `gcloud` would require doing both by hand). This deploy uses the Firebase
CLI accordingly. Left as a `spec:` follow-up for the user to confirm before amending the spec.

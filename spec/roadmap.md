# Roadmap

## Milestones

- **M1 (current)**: orchestrator + hotel agent + Nebius, Google sign-in, Firestore async job flow
  (job doc, trigger, sweeper), simple end-to-end wireframe UI. See `architecture.md`, `flows.md`,
  `access.md`.
- **M2**: replace or augment the deterministic orchestrator with an **orchestration agent**, an
  agentic loop that plans interactively with the user (multi-turn).
- **Later**: add the **flight agent** (needs a clean API first; today it is CLI-only) and the
  **activities agent**, running independent agents concurrently.

## Deferred work

- **Cloud Tasks + HTTP worker** for the heavy agent run if measured worst-case runs (cold start +
  loop) approach the event-function timeout (`architecture.md` under Cold starts & long runs).
- **Warm-on-submit ping** (fire a warm-up the instant the job doc is created) if the first-request
  cold-start wait becomes a UX problem. We deliberately avoid idle keep-warm.
- **GCP Secret Manager + rotation** for the Nebius key (M1 uses GitHub Secrets).
- **Workload Identity Federation** for CI-to-GCP auth if we start on a service-account key.
- **Saved / re-openable trips**: a per-user trip list and profile beyond the single job doc.
- **Admin or cross-user views** via `collectionGroup("trips")` queries.
- **Styled UI** beyond wireframes.
- Read-only enforcement for `vendor/agents/**` via a `.claude/settings.json` deny rule plus a
  `PreToolUse` hook (policy today: see `agents.md`).

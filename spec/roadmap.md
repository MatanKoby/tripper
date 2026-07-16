# Roadmap

## Milestones

- **M1 (shipped)**: deterministic orchestrator + hotel agent + Nebius, Google sign-in, Firestore
  async job flow (single job doc, trigger, sweeper), simple end-to-end wireframe UI. See
  `architecture.md`, `flows.md`, `access.md`. The single-doc `results` model is now superseded
  (`archive.md`).
- **M2 (current)**: the **per-domain data model** (`domains/suggested/selected/refinements`,
  `schema.md`), backend **fan-out** (`flows.md`), and the hotel **feedback / refine loop**. Built
  accommodations-first: the DB batch rebuilds the accommodations vertical on the new model
  (`BUILD_QUEUE.md`), then activities and flights integrate onto the same schema. Upstream
  prerequisites: the hotel agent's **refine** entry point + stable `Pick.id` (`agents.md`), the
  **activities agent** (not yet vendored), and a clean **flight-agent API** (flight is CLI-only
  today).
- **Later**: the **orchestration agent** — an agentic loop that plans interactively with the user,
  multi-turn, replacing or augmenting the deterministic fan-out.

## Deferred work

- **Conversation / plan store for the orchestration agent.** The multi-turn planning layer (a
  trip-level `messages` / `plan` store) is deliberately **not** in the M2 data model; it lands with
  the orchestration agent (`schema.md` models results + curation only).
- **Cloud Tasks + HTTP worker** for the heavy agent run if measured worst-case runs (cold start +
  loop) approach the event-function timeout (`architecture.md` under Cold starts & long runs).
- **Warm-on-submit ping** (fire a warm-up the instant the trip doc is created) if the first-request
  cold-start wait becomes a UX problem. We deliberately avoid idle keep-warm.
- **GCP Secret Manager + rotation** for the Nebius key (M1 uses GitHub Secrets).
- **Root-cause the Firestore-deploy 403 from CI, then re-automate it.** Publishing rules/indexes
  403s on the Firebase Rules `:test` compile step only from the GitHub-hosted runner (the same
  deploy identity passes from a workstation), so M1 deploys Firestore config by hand
  (`architecture.md`, `DEPLOY.md`); revisit to move it back into the CI deploy.
- **Admin UI for the access allowlist / mode** (M1 edits `config/access` in the Firebase console).
- **Saved / re-openable trips**: a per-user trip list and profile beyond the single job doc.
- **Admin or cross-user views** via `collectionGroup("trips")` queries.
- **Meaningful submit / job errors.** The FE currently surfaces the raw SDK message (e.g. a
  Firestore rules denial shows "Missing or insufficient permissions"). Replace with short,
  actionable messages that say what is wrong and how to fix it. When the remedy is developer-facing
  (config / rules / deploy), degrade gracefully: still signal that there is an error, but hide the
  technical detail behind a short error code instead of dumping the raw message. Covers the
  `submitError` and job-`error` paths (`ui.md` under Behavior).
- **Styled UI** beyond wireframes.
- Read-only enforcement for `vendor/agents/**` via a `.claude/settings.json` deny rule plus a
  `PreToolUse` hook (policy today: see `agents.md`).

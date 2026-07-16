# Specification

Tripper is a trip-planning app. A signed-in user (Google sign-in) enters trip parameters, and
tripper returns suggestions by delegating to domain agents (hotel first; flight and activities
later), each an agentic loop that calls a Nebius LLM endpoint. Work runs asynchronously: the
frontend writes a job to Firestore and listens for results, while a Firestore-triggered Cloud
Function runs the agents and writes results back. The Python backend runs on Google Cloud
Functions; a simple wireframe frontend runs on Vercel.

The spec is split across concern-focused files. Each file is small and edited as a unit. When
two sections always change in tandem, they belong in the same file. Edit via the procedure in
`specflow/procedures/spec-edit.md`.

## Files

- **`architecture.md`**: stack, moving parts, deployment, secrets, cold-start stance, M1 defaults.
- **`schema.md`**: trip input, the tripper/agent contract, and the per-domain Firestore data model.
- **`access.md`**: Google sign-in (Firebase Auth), the access allowlist, and Firestore security rules.
- **`flows.md`**: the async job lifecycle (fan-out, per-domain runs, refine loop), reliability, errors.
- **`ui.md`**: frontend layout (the Vite + React wireframe).
- **`agents.md`**: agent vendoring (submodules), the read-only rule, the bump gate.
- **`roadmap.md`**: milestones (M2 is current) and deferred work.
- **`archive.md`**: superseded designs kept for memory (the M1 single-doc job model).

## Reading order

For someone new: README, then `architecture.md`, then the file for the area in front of them
(`flows.md` for the job lifecycle, `schema.md` + `access.md` for the data and its rules, `ui.md`
for the frontend).

For an agent claiming a batch: read the queue entry first, then the 2 to 4 spec files relevant to
the batch's domain.

## Editing convention

Edit the file matching the concern. If a change crosses multiple files, that's a signal the
concern might be miscarved: flag it before duplicating content. Cross-reference by file path
rather than restating. Move historical content to `archive.md` when it stops being part of the
live system. Full procedure: `specflow/procedures/spec-edit.md`.

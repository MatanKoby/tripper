<!-- specflow:start - managed by specflow; do not edit inside these markers (your edits block specflow upgrade). Add your own notes outside them. -->
# Procedure: prune the ledgers into their archives

`BUILD_QUEUE.md` and `CLAIMS.md` are read on every batch, so both are **bounded working sets**, not
growing logs. This procedure keeps them that way. `AGENTS.md` carries only the pointer to this file.

> **Commit & push follow the configured levers** (`config.commit` / `config.push` in
> `specflow/config.json`; see `AGENTS.md` → *Commit & push authority*). Wherever a step below says
> "commit" or "push": if `commit: user`, don't commit, alert the user and hand them the suggested
> message; if `push: user`, commit but don't push. Default is `agent` / `agent`.

## When to run

- **`finish-batch` delegates here** at the end of every batch (its step 4a). That is the normal path.
- **By hand, any time**, when a ledger has already overgrown: `prune-ledgers` as a skill, or just
  follow this file. An install that predates this procedure can be many entries over, so the first
  run is a **catch-up pass** that archives them all at once.

Pruning is never gated behind a stop-and-ask. Archiving is lossless and mechanical: the entry moves
one file away, unedited, and `claim-batch` already resolves a dependency against `CLAIMS.md`
`## Completed` **or** `specflow/history/CLAIMS_DONE.md`. Don't ask the user to approve it, and don't
ask them to pick the retention number.

## 1. `CLAIMS.md`: keep the 5 most recent completed entries

Count the `### Batch …` entries under `## Completed`. If there are **more than 5**, move every entry
past the newest 5 into `specflow/history/CLAIMS_DONE.md`.

- **Order.** `## Completed` is newest-first, so the entries to move are the ones at the **bottom**.
  If the ordering has drifted, sort by `Finished:` before counting.
- **Move, never rewrite.** Copy each entry verbatim, including its `Owner` / `Started` / `Finished` /
  `Commit` lines, its "What shipped" summary, and any `Handoff note:` / `Reclaim note:` lines. Don't
  summarize, shorten, or reformat. The archive is the historical record.
- **Destination order.** `CLAIMS_DONE.md` is also newest-first: insert directly under its header, so
  the newest archived batch stays at the top.
- **Never touch `## In progress`.** An active claim is live state, however old it looks. A stale one
  is a handoff question for the user, not something to archive.

Retention is a **count, not a line or byte budget**: entries vary several-fold in length, a count
cuts on an entry boundary instead of severing a record, and two agents pruning independently reach
the same result. Rationale in `spec/architecture.md` → *Ledger lifecycle*.

## 2. `BUILD_QUEUE.md`: sweep what leaked past

`finish-batch` already deletes a finished batch from the queue as part of completing it (its step 4),
so the queue's retention is zero and this is only a sweep for what got left behind. Delete any
section for a batch that is:

- already present in `CLAIMS.md` `## Completed` or `specflow/history/CLAIMS_DONE.md`; or
- marked **dissolved**, **absorbed** into another batch, or otherwise no longer work to be done.

For each one, confirm `specflow/history/BUILD_QUEUE_DONE.md` carries its one-paragraph summary
(add it if `finish-batch` missed it), then remove the section and drop the batch from any
**pick-order pointer** at the top of the file.

**Leave `[NOT READY]`, `[DEFERRED]`, `[MANUAL]`, and standing non-batch sections alone.** They are
un-done work, which is exactly what the queue is for. Length is not a reason to prune them.

## 3. Commit

Commit the prune on its own, so the diff stays readable and reviewable:

```
meta: prune ledgers (N claims entries archived)
```

Cover `CLAIMS.md`, `specflow/history/CLAIMS_DONE.md`, and, if step 2 changed anything,
`BUILD_QUEUE.md` + `specflow/history/BUILD_QUEUE_DONE.md`. Push.

When `finish-batch` delegated here, folding this into its `meta: complete batch-N` commit is fine
too. One commit or two, but never leave the prune uncommitted.
<!-- specflow:end -->

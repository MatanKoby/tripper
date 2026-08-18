---
name: prune-ledgers
description: Use when CLAIMS.md or BUILD_QUEUE.md has grown long, when finish-batch reaches its prune step, or when the user asks to prune/archive the ledgers by hand. Moves older completed CLAIMS entries into specflow/history/CLAIMS_DONE.md (keeping the 5 most recent) and sweeps completed or dissolved sections out of BUILD_QUEUE.md.
---

# Prune the ledgers

Follow **`specflow/procedures/prune-ledgers.md`** in this repo — that file is the authoritative,
up-to-date procedure (kept in sync by `specflow upgrade`; this skill is a thin trigger).

In short: `CLAIMS.md` `## Completed` keeps its 5 newest entries and the rest move verbatim to the
top of `specflow/history/CLAIMS_DONE.md` (never touch `## In progress`) → sweep `BUILD_QUEUE.md` of
sections whose batch is already completed, dissolved, or absorbed, leaving `[NOT READY]` /
`[DEFERRED]` / `[MANUAL]` alone → commit `meta: prune ledgers (N claims entries archived)`.

An install that predates this procedure may be many entries over: archive them all in one
catch-up pass. Lossless and mechanical, so no stop-and-ask.

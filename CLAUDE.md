<!-- specflow:start - managed by specflow; do not edit inside these markers (your edits block specflow upgrade). Add your own notes outside them. -->
# CLAUDE.md

This repo uses **[specflow](https://github.com/MatanKoby/specflow)** — a spec-driven, batch,
claim-before-work protocol shared by all agents.

**Read [`AGENTS.md`](AGENTS.md) first.** It is the full protocol: spec → queue → claim → build.
The four procedures live in `specflow/procedures/` and are also installed as the skills
`claim-batch`, `spec-edit`, `finish-batch`, and `prune-ledgers`, which trigger automatically:

- Before starting any new batch → `claim-batch`
- Before editing any `spec/**` file or persisting a design decision → `spec-edit`
- When wrapping up a batch → `finish-batch`
- When `CLAIMS.md` or `BUILD_QUEUE.md` has grown long, or to archive them by hand → `prune-ledgers`

**When you install or upgrade specflow for the user** (running `specflow init`, `add-agent`, or
`upgrade`), relay the Claude-Code step-6 handoff hook it prints — don't leave it buried in CLI
scrollback. Tell them the exact block to paste into `.claude/settings.json` and why: it's the
deterministic backstop that blocks the loop after a `meta: complete batch-*` commit so the
finish-batch handoff gets offered every time.

Project-specific guidance (what this codebase is, conventions, tooling) goes **below this line**
or in your own sections — `AGENTS.md` and `specflow/**` are specflow-managed and get overwritten
on `specflow upgrade`.
<!-- specflow:end -->

<!-- Add project-specific Claude guidance here, outside the markers above. -->

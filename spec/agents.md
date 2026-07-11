# Agents (vendoring & integration)

## Layout

- Agents are public repos vendored as **git submodules under `vendor/agents/`** (M1:
  `vendor/agents/hotel-finder-agent`).
- Tripper reaches each agent only through its adapter (`architecture.md` under Agent contract +
  adapters). Agents expose a clean API; tripper does not wrap any CLI.

## Read-only rule

`vendor/agents/**` is owned upstream and **never edited by tripper**. Interface gaps are fixed
either in tripper's adapter or upstream in the agent repo, never by an inline edit to the
submodule. Enforcement (deferred): a `.claude/settings.json` deny rule plus a `PreToolUse` hook
that blocks edits and git-mutations inside these paths.

## Submodule-bump gate

Tripper may advance a submodule pointer (`git submodule update --remote`), but before committing
the bump it must:

1. Compile-check the submodule (`python -m compileall`).
2. Run the submodule's non-e2e tests (no live LLM round-trip).
3. Run tripper's adapter/contract tests for that agent.

On any failure, roll the pointer back and report; do not commit. On green, commit the bump on its
own. This is also a CI job on any submodule-pointer change.

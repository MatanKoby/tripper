#!/usr/bin/env bash
# specflow: Claude Code backstop for finish-batch step 6 (the context handoff).
#
# Registered as a PostToolUse(Bash) hook via the block specflow's installer prints
# (paste it into .claude/settings.json). It fires right after the agent lands a
# `meta: complete batch-*` commit and BLOCKS the agentic loop with a reminder to run
# step 6, so the batch boundary no longer depends on the agent choosing to offer the
# handoff. This is the Claude-only deterministic layer on top of the portable step-6
# text in specflow/procedures/finish-batch.md.
#
# Fails open: a missing dependency or any unexpected state exits 0 (no-op), so the hook
# can never break a commit. When inactive, the portable step-6 text stays the floor.
set -euo pipefail

# jq is required to parse the hook payload and emit the decision JSON. If it's not
# installed, no-op rather than error — the FH text still covers the handoff.
command -v jq >/dev/null 2>&1 || exit 0

input=$(cat)

# Cheap gate: only Bash calls that ran a git commit are candidates.
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

# Robust confirm: did HEAD actually land on a `meta: complete batch-*` commit?
# Matching the landed subject (not the command text) handles -m / -F / heredoc
# uniformly and proves the commit succeeded — a failed commit never moved HEAD. The
# next commit is `meta: claim batch-*`, which doesn't match, so this self-de-dups.
cwd=$(printf '%s' "$input" | jq -r '.cwd // "."')
subject=$(git -C "$cwd" log -1 --pretty=%s 2>/dev/null || true)
case "$subject" in
  "meta: complete batch-"*) ;;
  *) exit 0 ;;
esac

read -r -d '' reason <<'EOF' || true
You just landed a `meta: complete batch-*` commit. Before anything else, run finish-batch step 6: offer the context handoff and end your reply with the exact terminal line — "Batch N complete and committed. The repo is the source of truth, so this transcript is disposable. Recommend /compact (or /clear plus a one-line re-prompt) before the next batch. Keep-line: <one line of what must survive, or 'nothing to carry, it's all in the repo'>." A user "continue" authorizes claiming the next batch but does NOT waive this line. Do not auto-chain into the next batch before offering it.
EOF

# Block the loop and feed the reminder back so the agent must act on it before continuing.
jq -n --arg r "$reason" '{decision:"block",reason:$r}'

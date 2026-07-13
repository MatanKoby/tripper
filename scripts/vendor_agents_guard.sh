#!/usr/bin/env bash
# PreToolUse guard enforcing the vendor/agents/** read-only rule (spec/agents.md).
#
# vendor/agents/** is upstream-owned: tripper reaches each agent only through its
# adapter and never edits the submodule in place. Interface gaps are fixed in the
# adapter or upstream, never by an inline edit. This hook is the runtime backstop
# for that rule; the permissions.deny block in .claude/settings.json is the first
# layer for the Edit/Write tools, and this hook additionally closes the Bash
# escape hatch (shell redirects, sed -i, rm/mv/cp, and git write-commands run
# inside the submodule).
#
# Wired as a PreToolUse hook (matcher "Edit|Write|NotebookEdit|Bash"). It reads the
# hook payload JSON on stdin and, when a call would edit or git-mutate inside a
# protected path, prints a PreToolUse deny decision and exits 0 (a deny decision,
# not a hook error). Anything else prints nothing and exits 0, so the tool proceeds.
#
# Deliberately NOT blocked (these are how the pointer legitimately advances):
#   - git submodule update [--remote] vendor/agents/...   (moves the pointer)
#   - git add vendor/agents/<submodule>                   (stages the gitlink only;
#                                                           from the superproject a
#                                                           submodule is a boundary)
#   - read-only inspection: cat/ls/grep/git log/git diff/python -m compileall ...
set -euo pipefail

PROTECTED='vendor/agents/'

payload="$(cat)"

# jq is a hard dependency of the guard. If it is missing we fail open (exit 0)
# rather than break every tool call; the permissions.deny layer still applies.
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

field() { printf '%s' "$payload" | jq -r "$1 // empty" 2>/dev/null || true; }

deny() {
  # $1: human-readable reason shown to the model and user.
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

REASON="vendor/agents/** is upstream-owned and read-only (spec/agents.md): tripper reaches each agent only through its adapter and never edits the submodule in place. Fix interface gaps in tripper's adapter (or upstream in the agent repo), not with an inline edit. Advance the submodule pointer via scripts/submodule_bump_gate.sh."

# Matches the protected prefix whether the path is absolute
# (/repo/vendor/agents/...) or relative (vendor/agents/..., ./vendor/agents/...).
in_protected() { printf '%s' "$1" | grep -qE "(^|/)${PROTECTED}"; }

tool="$(field '.tool_name')"

case "$tool" in
  Edit | Write | NotebookEdit | MultiEdit)
    path="$(field '.tool_input.file_path')"
    [ -n "$path" ] || path="$(field '.tool_input.notebook_path')"
    if [ -n "$path" ] && in_protected "$path"; then
      deny "$REASON"
    fi
    ;;

  Bash)
    cmd="$(field '.tool_input.command')"
    # Fast path: if the command never names a protected path, nothing to guard.
    # The boundary excludes alnum/_/- (so "myvendor/agents" is not us) but allows
    # a leading "/" or "./" (so "./vendor/agents", "/repo/vendor/agents" match).
    if ! printf '%s' "$cmd" | grep -qE "(^|[^[:alnum:]_-])${PROTECTED}"; then
      exit 0
    fi

    # (a) A shell write whose target is a protected path: an output redirect, an
    #     in-place sed, or a destructive/creating file utility with the path as an
    #     argument. `[^|;&]*` keeps the match within a single simple command so a
    #     later read-only clause in the same line is not implicated.
    if printf '%s' "$cmd" | grep -qE ">>?[[:space:]]*['\"]?([^[:space:]|;&<>]*/)?${PROTECTED}"; then
      deny "$REASON"
    fi
    if printf '%s' "$cmd" | grep -qE "\bsed\b[^|;&]*-i[^|;&]*${PROTECTED}"; then
      deny "$REASON"
    fi
    if printf '%s' "$cmd" | grep -qE "\b(rm|rmdir|mv|cp|tee|dd|truncate|chmod|chown|touch|ln)\b[^|;&]*${PROTECTED}"; then
      deny "$REASON"
    fi

    # (b) A git write-command operating with the submodule as its repo, i.e.
    #     `git -C vendor/agents/... <write>` or `cd vendor/agents/... && git <write>`.
    #     Plain `git add/commit vendor/agents/<sub>` from the superproject only
    #     touches the gitlink (the pointer) and is intentionally allowed.
    git_write='(commit|checkout|switch|restore|reset|revert|rm|mv|add|apply|stash|clean|merge|rebase|cherry-pick|am|push|update-ref|update-index|write-tree|pull)'
    if printf '%s' "$cmd" | grep -qE "git[[:space:]]+(-[A-Za-z]+[[:space:]]+)*-C[[:space:]]+['\"]?([^[:space:]]*/)?${PROTECTED}"; then
      if printf '%s' "$cmd" | grep -qE "\b${git_write}\b"; then
        deny "$REASON"
      fi
    fi
    if printf '%s' "$cmd" | grep -qE "\b(cd|pushd)[[:space:]]+['\"]?([^[:space:]|;&]*/)?${PROTECTED}"; then
      if printf '%s' "$cmd" | grep -qE "\bgit\b[^|;&]*\b${git_write}\b"; then
        deny "$REASON"
      fi
    fi
    ;;
esac

exit 0

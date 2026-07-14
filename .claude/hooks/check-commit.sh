#!/bin/bash
# PreToolUse guard paired with the /commit skill: blocks committing secrets
# and regenerable artifacts, asks user confirmation for files over 5 MB.
# Reads the hook JSON on stdin; silent exit 0 = allow.
set -u

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0

candidates=$(git diff --cached --name-only)
# `git commit -a` / `git add … && git commit` stage files after this hook
# fires, so widen the check to modified + untracked files in those cases
# (over-inclusive on purpose: a wider check is harmless).
if printf '%s' "$cmd" | grep -qE 'git add|git commit.* -a'; then
  candidates="$candidates
$(git ls-files -mo --exclude-standard)"
fi

deny=""
ask=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$(basename "$f")" in
    .env)
      deny="$deny- $f: environment file (secrets), must never be committed
" ;;
  esac
  if [ -f "$f" ]; then
    size=$(stat -f%z "$f" 2>/dev/null || echo 0)
    if [ "$size" -gt 5000000 ]; then
      ask="$ask- $f: $((size / 1000000)) MB
"
    fi
  fi
done <<EOF
$(printf '%s\n' "$candidates" | sort -u)
EOF

if [ -n "$deny" ]; then
  jq -n --arg r "Commit blocked by .claude/hooks/check-commit.sh:
${deny}Unstage these files (git restore --staged <file>) and commit without them." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
elif [ -n "$ask" ]; then
  jq -n --arg r "This commit includes files over 5 MB:
${ask}Large data files need explicit user confirmation." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
fi
exit 0

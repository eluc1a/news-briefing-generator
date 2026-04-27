#!/usr/bin/env bash
# PreToolUse hook on Read|Write|Edit.
# Blocks reading/writing .env secrets files. Templates (.env.example etc.) are allowed.

set -euo pipefail

input="$(cat)"
tool="$(printf '%s' "$input" | jq -r '.tool_name // ""')"
path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""')"

[[ -z "$path" ]] && exit 0

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

basename="$(basename -- "$path")"

# Is this a secrets .env file? (match .env or .env.<something>, but allow templates)
is_env_secret=0
case "$basename" in
  .env.example|.env.template|.env.sample|.env.dist)
    ;;
  .env|.env.*)
    is_env_secret=1
    ;;
esac

if [[ "$is_env_secret" -eq 1 ]]; then
  case "$tool" in
    Write|Edit)
      deny "Blocked: $tool on $path would modify secrets. Ask the user to edit it manually."
      ;;
    Read)
      deny "Blocked: reading $path would persist secrets in the transcript. Ask the user for the specific value."
      ;;
  esac
fi

exit 0

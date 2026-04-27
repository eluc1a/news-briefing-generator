#!/usr/bin/env bash
# PreToolUse hook on Bash.
# Blocks catastrophic commands, force-push to main, mcp_news coexistence violations,
# and .env secret exfiltration. Emits permissionDecision=deny on match, nothing otherwise.

set -euo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""')"

[[ -z "$cmd" ]] && exit 0

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

match() { grep -qE "$1" <<< "$cmd"; }

# --- Catastrophic deletion ---

# rm -rf targeting /, ~, or $HOME root
if match 'rm[[:space:]]+([^[:space:]]*[rRf][^[:space:]]*[[:space:]]+)+(/($|[[:space:]*])|~($|[[:space:]/*])|\$HOME($|[[:space:]/*]))'; then
  deny "Blocked: catastrophic rm (rm -rf on /, ~, or \$HOME). Run outside Claude Code if intentional."
fi

# Fork bomb
if match ':\(\)[[:space:]]*\{[[:space:]]*:\|:&[[:space:]]*\}[[:space:]]*;[[:space:]]*:'; then
  deny "Blocked: fork bomb."
fi

# curl|sh / wget|sh
if match '(curl|wget)[[:space:]]+[^|]*\|[[:space:]]*(sh|bash|zsh|ksh)([[:space:]]|$)'; then
  deny "Blocked: piping a remote download into a shell. Download, inspect, then run."
fi

# dd to a device node
if match 'dd[[:space:]].*of=/dev/'; then
  deny "Blocked: dd writing to a device node."
fi

# Filesystem format
if match 'mkfs\.'; then
  deny "Blocked: mkfs (filesystem format)."
fi

# --- Docker volume wipes ---

# docker compose down -v / --volumes (trashes dev DB state)
if match 'docker([[:space:]]+|-)compose[[:space:]]+down([[:space:]]+[^&;|]*)?([[:space:]]+)(-v([[:space:]]|$)|--volumes)'; then
  deny "Blocked: 'docker compose down -v' wipes volumes. If reset is intentional, run outside Claude Code."
fi

# --- Git force-push to main/master ---

if match 'git[[:space:]]+push.*(--force|--force-with-lease|-f([[:space:]]|$))' && \
   match '(origin[[:space:]]+)?(main|master)([[:space:]]|$)'; then
  deny "Blocked: force-push referencing main/master. If intentional, run outside Claude Code."
fi

# --- mcp_news coexistence (CLAUDE.md: never touch topics/facts/timeline_*/vector_store; no destructive DDL) ---

if match '(psql|pg_restore|pg_dump)'; then
  # Block destructive DDL — always needs manual execution in this project
  if match '(DROP[[:space:]]+(TABLE|DATABASE|SCHEMA)|TRUNCATE)[[:space:]]+'; then
    deny "Blocked: DROP/TRUNCATE via psql. mcp_news coexists with another pipeline — run destructive DDL manually (see CLAUDE.md 'Coexistence')."
  fi
  # Block writes to tables we don't own
  if match '(INSERT[[:space:]]+INTO|UPDATE|DELETE[[:space:]]+FROM)[[:space:]]+(topics|facts|timeline_|vector_store)'; then
    deny "Blocked: write to a coexistence table (topics/facts/timeline_*/vector_store) we don't own. See CLAUDE.md."
  fi
fi

# --- .env secret exfiltration ---

# Reading .env with a pager/cat dumps secrets into the transcript
if match '(cat|less|more|head|tail|bat|xxd|od|strings)[[:space:]]+[^|;&]*\.env([[:space:]]|$|;|\||&)' && \
   ! match '\.env\.(example|template|sample|dist)'; then
  deny "Blocked: dumping .env to the transcript would persist secrets on disk. Ask the user for the specific value."
fi

exit 0

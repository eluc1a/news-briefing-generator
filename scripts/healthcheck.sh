#!/bin/sh
# External health check for themorningfox.com / feeds.elucia.com.
# Checks purely from the outside (public URLs) — never touches DB/logs/cron.
# Run every 30 min via host cron; alerts to ntfy on new failures only.
set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="${HOME}/.cache/jina-clone-healthcheck.state"
mkdir -p "$(dirname "$STATE_FILE")"

NTFY_TOPIC="$(grep -m1 '^NTFY_TOPIC=' "$REPO_DIR/.env" 2>/dev/null | cut -d= -f2-)"

# extract("<json>", "key") -> value of first "key": "value" match
extract() { printf '%s' "$1" | grep -m1 -o "\"$2\": *\"[^\"]*\"" | sed -E 's/.*"([^"]*)"$/\1/'; }

fail=""

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://themorningfox.com/ 2>/dev/null)
[ "${code:-000}" = "200" ] || fail="${fail}SITE_DOWN(${code:-000});"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://feeds.elucia.com/ai-digest/latest.html 2>/dev/null)
[ "${code:-000}" = "200" ] || fail="${fail}DIGEST_DOWN(${code:-000});"

index="$(curl -s --max-time 10 https://themorningfox.com/editions/index.json || true)"
latest_date=$(extract "$index" date)
latest_edition=$(extract "$index" edition)
latest_json=$(extract "$index" json)

if [ -z "$latest_date" ] || [ -z "$latest_edition" ]; then
  fail="${fail}INDEX_UNREADABLE;"
else
  case "$latest_edition" in
    morning) expected="08:15" ;;
    *) expected="20:15" ;;
  esac
  pub_epoch=$(date -d "$latest_date $expected" +%s 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  age_h=$(( (now_epoch - pub_epoch) / 3600 ))
  [ "$age_h" -gt 13 ] && fail="${fail}STALE(${age_h}h_since_${latest_date}_${latest_edition});"

  if [ -n "$latest_json" ]; then
    edition_json="$(curl -s --max-time 10 "https://themorningfox.com/editions/${latest_json}" || true)"
    [ "$(extract "$edition_json" date)" = "(emergency edition)" ] && fail="${fail}EMERGENCY_EDITION(${latest_json});"
  fi
fi

if [ -n "$fail" ]; then
  # TRIAGE_DRY=1 (set by .claude/skills/triage/scripts/triage.sh) reuses these
  # checks for read-only diagnosis without sending an alert or touching state.
  if [ "${TRIAGE_DRY:-0}" != "1" ]; then
    prev="$(cat "$STATE_FILE" 2>/dev/null || true)"
    if [ "$fail" != "$prev" ]; then
      if [ -n "$NTFY_TOPIC" ]; then
        curl -s -o /dev/null --max-time 10 -X POST "https://ntfy.sh/${NTFY_TOPIC}" \
          -H "Title: themorningfox.com healthcheck" -H "Priority: high" -H "Tags: warning" \
          -d "External healthcheck failed: ${fail}"
      else
        echo "$(date -Iseconds) NTFY_TOPIC unset in .env — would have alerted: ${fail}"
      fi
      printf '%s' "$fail" > "$STATE_FILE"
    fi
  fi
  echo "$(date -Iseconds) FAIL: ${fail}"
  exit 1
fi

rm -f "$STATE_FILE"
echo "$(date -Iseconds) OK"

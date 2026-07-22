#!/bin/sh
# Deploy jina-clone on fox: pull, refresh deps, rebuild the extractor
# container. Briefing runs from this checkout via host cron — no restart
# needed, next cron firing picks up the new code.
set -eu
cd "$(dirname "$0")/.."

git pull --ff-only
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/pip install -q -e .
docker compose up -d --build
echo "deployed $(git rev-parse --short HEAD)"

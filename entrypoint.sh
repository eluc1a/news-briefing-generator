#!/bin/sh
set -e
mkdir -p /var/log/jina-clone
cron
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}"

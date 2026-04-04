#!/bin/bash
set -euo pipefail

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

echo "Starting the Job Market Intelligence Loop..."

while true; do
    python3 pull_jobs.py
    python3 pull_desc.py
    sleep 60
done

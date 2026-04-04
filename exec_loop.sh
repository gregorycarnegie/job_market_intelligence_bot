#!/bin/bash
set -euo pipefail

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

echo "Starting the Job Market Intelligence Loop..."

start_callback_worker() {
    worker_pid=""
    trap 'if [ -n "${worker_pid}" ]; then kill "${worker_pid}" 2>/dev/null || true; wait "${worker_pid}" 2>/dev/null || true; fi; exit 0' INT TERM
    while true; do
        python3 telegram_callback_worker.py &
        worker_pid=$!
        if wait "${worker_pid}"; then
            echo "Telegram callback worker exited; restarting in 1 second..." >&2
            sleep 1
        else
            status=$?
            echo "Telegram callback worker exited with status ${status}; restarting in 5 seconds..." >&2
            sleep 5
        fi
        worker_pid=""
    done
}

cleanup() {
    if [ -n "${callback_supervisor_pid:-}" ]; then
        kill "${callback_supervisor_pid}" 2>/dev/null || true
        wait "${callback_supervisor_pid}" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

start_callback_worker &
callback_supervisor_pid=$!

while true; do
    python3 pull_jobs.py
    python3 pull_desc.py
    sleep 60
done

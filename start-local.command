#!/bin/zsh
set -e
cd "${0:A:h}"
export COURSE_PROVIDER="${COURSE_PROVIDER:-local}"
export LOCAL_MODEL_ROOT="${LOCAL_MODEL_ROOT:-../ntu-live-test}"
export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1:3890}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:8890}"
export NTU_DATA_DIR="${NTU_DATA_DIR:-/tmp/ntu-agent-local}"
export OBSIDIAN_REPO_PATH="${OBSIDIAN_REPO_PATH:-/tmp/ntu-agent-vault}"

trap 'kill 0' EXIT INT TERM
.venv311/bin/python -m uvicorn services.api.app.main:app --host 127.0.0.1 --port 8890 &
(API_BASE_URL=http://127.0.0.1:8890 .venv311/bin/python services/mcp/server.py) &
(cd apps/web && npm run dev -- --hostname 127.0.0.1 --port 3890) &
wait

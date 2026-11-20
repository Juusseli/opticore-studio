#!/usr/bin/env bash
# Start the OptiCore engine (port 8000) and the web UI (port 5173) for development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv "$ROOT/backend/.venv"
  "$PY" -m pip install -e "$ROOT/backend[dev]"
fi
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install)
"$PY" -m uvicorn --app-dir "$ROOT/backend" opticore.api.main:app --host 127.0.0.1 --port 8000 &
ENGINE=$!
trap 'kill $ENGINE 2>/dev/null || true' EXIT
cd "$ROOT/frontend" && npm run dev

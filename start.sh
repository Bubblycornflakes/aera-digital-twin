#!/bin/bash
set -eu
cd "$(dirname "$0")"
.venv/bin/python -m uvicorn aera.api:app --host 127.0.0.1 --port 8061 &
api=$!
trap 'kill "$api" 2>/dev/null || true' EXIT
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5161 --strictPort

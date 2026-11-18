#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${ARTPIPE_PYTHON:-.venv/bin/python}" -m uvicorn artpipe.web:app --host 127.0.0.1 --port "${ARTPIPE_PORT:-8765}"

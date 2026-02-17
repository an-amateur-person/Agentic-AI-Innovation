#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"
echo "Startup: PORT=${PORT}"

if [ -f app.py ]; then
    echo "Startup: launching app.py"
    exec python -m streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true
elif [ -f agentic_ai.py ]; then
    echo "Startup: launching agentic_ai.py"
    exec python -m streamlit run agentic_ai.py --server.port "$PORT" --server.address 0.0.0.0 --server.headless true
else
    echo "Error: Neither app.py nor agentic_ai.py exists."
    ls -la
    exit 1
fi
#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"

if [ -f app.py ]; then
    exec python -m streamlit run app.py \
        --server.port "$PORT" \
        --server.address 0.0.0.0 \
        --server.headless true \
        --browser.gatherUsageStats false \
        --logger.level info
elif [ -f agentic_ai.py ]; then
    exec python -m streamlit run agentic_ai.py \
        --server.port "$PORT" \
        --server.address 0.0.0.0 \
        --server.headless true \
        --browser.gatherUsageStats false \
        --logger.level info
else
    echo "Error: Neither app.py nor agentic_ai.py exists."
    ls -la
    exit 1
fi
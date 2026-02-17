#!/usr/bin/env bash
set -e

PORT="${PORT:-80}"
echo "Startup: PORT=${PORT}"

if command -v ss >/dev/null 2>&1; then
    if ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then
        echo "Startup: port ${PORT} is already in use."
        if [ "${PORT}" != "80" ] && ! ss -ltn | awk '{print $4}' | grep -q ":80$"; then
            PORT="80"
            echo "Startup: falling back to PORT=${PORT}"
        else
            echo "Startup: active listeners:"
            ss -ltn
            exit 1
        fi
    fi
fi

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
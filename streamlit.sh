set -e

PORT="${PORT:-8000}"

if [ -f app.py ]; then
	exec python -m streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0
elif [ -f agentic_ai.py ]; then
	exec python -m streamlit run agentic_ai.py --server.port "$PORT" --server.address 0.0.0.0
else
	echo "Error: Neither app.py nor agentic_ai.py exists in deployment root."
	ls -la
	exit 1
fi
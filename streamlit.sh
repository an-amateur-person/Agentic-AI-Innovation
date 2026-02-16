pip install streamlit

if [ -f app.py ]; then
	python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0
elif [ -f agentic_ai.py ]; then
	python -m streamlit run agentic_ai.py --server.port 8000 --server.address 0.0.0.0
else
	echo "Error: Neither app.py nor agentic_ai.py exists in deployment root."
	ls -la
	exit 1
fi
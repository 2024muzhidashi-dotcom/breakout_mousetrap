#!/bin/bash

# Ensure radar state file exists
mkdir -p /app/radar
if [ ! -f /app/radar/state.json ]; then
    echo "{}" > /app/radar/state.json
fi

# Start the background scanner
python3 /app/radar/scanner.py &

# Start the Streamlit app
streamlit run /app/radar/app.py --server.port=8501 --server.address=0.0.0.0

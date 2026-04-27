#!/bin/bash
set -e

# Values to test
THRESHOLDS=(300 500 800 1200 1500)
URL="https://www.youtube.com/watch?v=wjZofJX0v4M"
START="10:00"
END="12:00"

echo "Starting Endpointing Sweep..."
cd "$(dirname "$0")/.." # Move up to repository root so uv run works

for t in "${THRESHOLDS[@]}"; do
    NAME="ep_sweep_${t}ms"
    echo "======================================"
    echo "Running with endpointing = ${t}ms"
    echo "======================================"
    
    # Run the python experiment runner
    uv run real-time-translation-exp-youtube \
        --url "$URL" \
        --start "$START" \
        --end "$END" \
        --name "$NAME" \
        --speed 5.0 \
        --endpointing "$t"
        
    echo "Done with ${t}ms."
    echo ""
done

echo "Sweep complete! Check experiments/results.csv for comparisons."

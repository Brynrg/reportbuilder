#!/bin/bash
# Run ReportBuilder in development mode
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src:$PYTHONPATH"
python3 run.py "$@"

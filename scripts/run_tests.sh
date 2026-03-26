#!/bin/bash
# Run the test suite
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src:$PYTHONPATH"
python3 -m pytest tests/ -v --tb=short "$@"

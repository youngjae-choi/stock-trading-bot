#!/bin/bash
# setup_env.sh - Environment setup for Stock Trading Bot

set -e

echo "START: Setting up Python Virtual Environment..."

# Use uv if available as per project plan
if command -v uv &> /dev/null
then
    echo "Using uv for high-speed package management..."
    uv venv .venv
    source .venv/bin/activate
    uv pip install -r requirements.txt
else
    echo "uv not found, using standard venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

echo "SUCCESS: Environment setup complete. Use 'source .venv/bin/activate' to use it."

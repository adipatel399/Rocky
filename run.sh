#!/bin/zsh
# Launch ROCKY. First run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd "$(dirname "$0")"
exec .venv/bin/python -m rocky

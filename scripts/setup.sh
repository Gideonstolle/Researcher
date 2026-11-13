#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m researcher doctor
"$PYTHON_BIN" -m unittest discover -s tests -v

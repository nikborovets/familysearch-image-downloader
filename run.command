#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
if ! "$PYTHON" -c "import PIL, requests" >/dev/null 2>&1; then
  "$PYTHON" -m pip install -r requirements.txt
fi

exec "$PYTHON" cli.py "$@"

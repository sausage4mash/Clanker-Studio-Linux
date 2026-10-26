#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$APP_DIR"
export PYTHONDONTWRITEBYTECODE=1

for candidate in "$APP_DIR/.venv/bin/python" python3 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" "$APP_DIR/speak.py" "$@"
    fi
done
echo "Python is missing. Run the one-time setup: bash setup.sh"
exit 1

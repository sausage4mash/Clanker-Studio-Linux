#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$APP_DIR"
export PYTHONDONTWRITEBYTECODE=1

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "This copy requires Intel/AMD 64-bit Linux. Its Rhubarb binary does not support ARM."
    exit 1
fi
chmod +x start.sh tools/Rhubarb/rhubarb
if bash "$APP_DIR/start.sh" --check; then
    echo "Setup complete. From now on, run: python3 speak.py"
    exit 0
fi

echo "Installing missing Linux prerequisites may require internet access and your password."
if command -v apt-get >/dev/null 2>&1; then
    ADMIN=()
    if [[ "$EUID" -ne 0 ]]; then
        if ! command -v sudo >/dev/null 2>&1; then
            echo "Ask your administrator to install the system packages listed in README.md."
            exit 1
        fi
        ADMIN=(sudo)
    fi
    "${ADMIN[@]}" apt-get update
    "${ADMIN[@]}" apt-get install -y python3 python3-venv python3-tk ffmpeg xdg-utils libstdc++6 libgomp1
else
    echo "Install Python 3, its venv and Tkinter support, FFmpeg, xdg-utils, libstdc++ and libgomp with your distribution's package manager."
fi

# Python 3.12 can use the included packages without downloading Python packages.
if bash "$APP_DIR/start.sh" --check; then
    echo "Setup complete. From now on, run: python3 speak.py"
    exit 0
fi

# A different Python version needs its own compatible wheels.
echo "Creating a local Python environment and downloading compatible Python packages."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
bash "$APP_DIR/start.sh" --check
echo "Setup complete. From now on, run: python3 speak.py"

"""Check the copied application without opening the GUI or contacting a server."""
import importlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def main():
    base = Path(__file__).resolve().parent
    problems = []
    if sys.platform != "linux" or platform.machine() != "x86_64":
        problems.append("The bundled Rhubarb executable requires Intel/AMD 64-bit Linux.")
    for name in ("tkinter", "PIL.Image", "piper.voice", "onnxruntime"):
        try:
            importlib.import_module(name)
        except Exception as error:
            problems.append(f"Cannot load {name}: {error}")
    for name in ("ffmpeg", "xdg-open"):
        if shutil.which(name) is None:
            problems.append(f"Missing system program: {name}")
    required = [
        "speak.py", "animate.py", "facial.py",
        "voices/en_GB-northern_english_male-medium.onnx",
        "voices/en_GB-northern_english_male-medium.onnx.json",
        "assets/clanker/robot.png",
        "tools/Rhubarb/rhubarb",
    ]
    required += [f"assets/clanker/mouths/{shape}.png" for shape in "ABCDEFGHX"]
    for name in required:
        if not (base / name).is_file():
            problems.append(f"Missing application file: {name}")
    rhubarb = base / "tools/Rhubarb/rhubarb"
    if rhubarb.is_file():
        if not os.access(rhubarb, os.X_OK):
            problems.append("Rhubarb is not executable. Run: chmod +x tools/Rhubarb/rhubarb")
        else:
            try:
                result = subprocess.run(
                    [str(rhubarb), "--version"], capture_output=True,
                    text=True, timeout=15, cwd=base,
                )
                if result.returncode:
                    problems.append("Rhubarb could not start: " + result.stderr.strip())
            except (OSError, subprocess.TimeoutExpired) as error:
                problems.append(f"Rhubarb could not start: {error}")
    if problems:
        print("Setup is needed:")
        for problem in problems:
            print(f"  - {problem}")
        print("See README.md, or run: bash setup.sh")
        return 1
    print("Clanker Studio dependencies are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

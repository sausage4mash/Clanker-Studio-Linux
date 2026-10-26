import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def prepare_runtime():
    """Find the app's environment even when launched directly from an IDE."""
    base = Path(__file__).resolve().parent
    local_python = base / ".venv" / "bin" / "python"
    if local_python.is_file() and os.access(local_python, os.X_OK):
        # Do not resolve symlinks: a venv's Python points at the system binary.
        if os.path.abspath(sys.executable) != str(local_python):
            os.execv(str(local_python), [str(local_python), str(base / "speak.py"), *sys.argv[1:]])
        return

    if sys.version_info[:2] != (3, 12) or platform.machine() != "x86_64":
        python312 = shutil.which("python3.12")
        if (platform.machine() == "x86_64" and python312
                and os.path.abspath(python312) != os.path.abspath(sys.executable)):
            os.execv(python312, [python312, str(base / "speak.py"), *sys.argv[1:]])
        raise SystemExit("Run the one-time setup first: bash setup.sh")

    bundled = str(base / "python-packages")
    sys.path.insert(0, bundled)
    # Piper and the renderer run as child processes and need the same packages.
    pythonpath = os.environ.get("PYTHONPATH", "")
    paths = pythonpath.split(os.pathsep) if pythonpath else []
    if bundled not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([bundled, *paths])


prepare_runtime()

from check_runtime import main as check_runtime

if check_runtime():
    raise SystemExit(1)
if sys.argv[1:] == ["--check"]:
    raise SystemExit(0)

import threading
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox

# ==========================================
# PROJECT SETTINGS
# ==========================================

BASE = Path(__file__).resolve().parent

VOICE = (
    BASE / "voices" /
    "en_GB-northern_english_male-medium.onnx"
)

RHUBARB = BASE / "tools" / "Rhubarb" / "rhubarb"

OUTPUT = BASE / "output"

ANIMATE = BASE / "animate.py"

OUTPUT.mkdir(parents=True, exist_ok=True)

# ==========================================
# GUI
# ==========================================

root = tk.Tk()
root.title("AI Responds - Clanker Studio")
root.geometry("740x490")
root.minsize(580, 380)

frame = ttk.Frame(root, padding=20)
frame.pack(fill="both", expand=True)

ttk.Label(
    frame,
    text="AI RESPONDS",
    font=("Arial", 20, "bold")
).pack(anchor="w")

ttk.Label(
    frame,
    text="Clanker Animation Studio",
    font=("Arial", 11)
).pack(anchor="w", pady=(2, 18))

ttk.Label(
    frame,
    text="What should the clanker say?"
).pack(anchor="w")

text_box = tk.Text(
    frame,
    height=10,
    wrap="word",
    font=("Arial", 12),
    padx=10,
    pady=10
)
text_box.pack(fill="both", expand=True, pady=(6, 15))

status = tk.StringVar(value="Ready")
busy = False

# ==========================================
# FUNCTIONS
# ==========================================

def set_status(message):
    root.after(0, status.set, message)


def clear_text():
    if busy:
        return
    text_box.delete("1.0", tk.END)


def run_command(command, input_text=None):
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        cwd=BASE
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"Command failed: {command[0]}"
        )


def open_video(video):
    try:
        if sys.platform == "win32":
            os.startfile(str(video))
        elif sys.platform == "darwin":
            run_command(["open", str(video)])
        else:
            run_command(["xdg-open", str(video)])
    except Exception as error:
        root.after(
            0,
            messagebox.showwarning,
            "Unable to Open Video",
            f"Your video was saved, but could not be opened automatically.\n\n"
            f"{video}\n\n{error}"
        )


def finish(success, message, video=None):
    global busy
    busy = False

    generate_button.config(state="normal")
    clear_button.config(state="normal")
    status.set(message)

    if success:
        threading.Thread(
            target=open_video,
            args=(video,),
            daemon=True
        ).start()
    else:
        messagebox.showerror(
            "Animation Error",
            message
        )


def animation_worker(dialogue):
    try:
        # Keep each recording together without overwriting previous work.
        run_dir = Path(tempfile.mkdtemp(prefix="clanker_", dir=OUTPUT))
        audio = run_dir / "speech.wav"
        cues = run_dir / "mouth_cues.json"
        video = run_dir / "clanker.mp4"

        # 1. Generate voice
        set_status("1/3 - Piper generating speech...")

        run_command([
            sys.executable,
            "-m", "piper",
            "--model", str(VOICE),
            "--output_file", str(audio)
        ], input_text=dialogue + "\n")

        if not audio.is_file() or audio.stat().st_size == 0:
            raise RuntimeError("Piper did not create the WAV file.")

        # 2. Generate lip-sync
        set_status("2/3 - Rhubarb analysing speech...")

        run_command([
            str(RHUBARB),
            "-f", "json",
            "-o", str(cues),
            str(audio)
        ])

        # 3. Render animation
        set_status("3/3 - Rendering clanker animation...")

        run_command([
            sys.executable,
            str(ANIMATE),
            "--full",
            "--audio", str(audio),
            "--json", str(cues),
            "--output", str(video)
        ])

        if not video.is_file() or video.stat().st_size == 0:
            raise RuntimeError("Animation MP4 was not created.")

        root.after(
            0,
            finish, True, f"Animation complete! Saved: {video}", video
        )

    except Exception as error:
        message = str(error)
        root.after(
            0,
            finish, False, message
        )


def generate_animation():
    global busy

    if busy:
        return

    dialogue = text_box.get("1.0", tk.END).strip()

    if not dialogue:
        messagebox.showwarning(
            "No Dialogue",
            "Please enter some text first."
        )
        return

    required = [VOICE, RHUBARB, ANIMATE]
    missing = [str(p) for p in required if not p.is_file()]

    if missing:
        messagebox.showerror(
            "Missing Files",
            "\n".join(missing)
        )
        return

    busy = True
    generate_button.config(state="disabled")
    clear_button.config(state="disabled")

    threading.Thread(
        target=animation_worker,
        args=(dialogue,),
        daemon=True
    ).start()


# ==========================================
# BUTTONS
# ==========================================

buttons = ttk.Frame(frame)
buttons.pack(fill="x", pady=5)

clear_button = ttk.Button(
    buttons,
    text="Clear",
    command=clear_text
)
clear_button.pack(side="left")

generate_button = ttk.Button(
    buttons,
    text="Text to Animation",
    command=generate_animation
)
generate_button.pack(side="right")

ttk.Separator(frame).pack(fill="x", pady=12)

ttk.Label(
    frame,
    textvariable=status
).pack(anchor="w")

text_box.focus_set()

root.mainloop()

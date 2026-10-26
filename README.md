# Clanker Studio — Linux copy

Type something, click **Text to Animation**, and your clanker speaks it in an MP4.
The finished video opens in your default video player.

## One-time setup

Keep this whole folder together. Extract it into a writable folder on an
Intel/AMD 64-bit Linux computer, open a terminal in it, and run:

```bash
bash setup.sh
```

Once setup finishes, start the app whenever you want with:

```bash
python3 speak.py
```

You can also use your IDE's Run button on `speak.py`, or `bash start.sh`.
The app selects its Python environment and finds the included packages
automatically. You do not need to activate an environment or repeat setup each
time you open it. Keep the whole folder together when moving or sharing it;
run setup once on each new computer.

On Debian/Ubuntu-based systems, setup can install Linux prerequisites using
`sudo`. This can require an administrator password and internet access. On other
distributions, install the equivalent packages with that system's package manager.

## What is included

- `speak.py`: the interface and processing pipeline.
- `animate.py` and `facial.py`: video rendering and facial movement.
- `voices/`: the Northern English male Piper voice and its configuration.
- `assets/clanker/`: the robot artwork and all nine mouth shapes.
- `tools/Rhubarb/`: the Linux executable, recognition resources and license.
- `python-packages/`: copies of the required Python packages and their license
  metadata, taken from the working Python 3.12 environment.
- `requirements-bundled.txt`: exact versions of those bundled packages.
- `requirements.txt`: direct Python dependencies for rebuilding an environment.
- `check_runtime.py`: checks dependencies without opening a window.
- `output/`: where new recordings and videos are saved.

Your original `.env`, API keys, logs, recordings and generated videos are excluded.

## System requirements

The bundled native Python packages target **CPython 3.12, x86-64 Linux**. This is
not a universal Linux executable: an older Linux system can have incompatible
system libraries, and ARM computers need a different Rhubarb binary.

The computer still needs:

- Python 3.12 and Tkinter to use the bundled Python packages.
- FFmpeg with `libx264` and AAC encoding.
- `xdg-open` (usually provided by `xdg-utils`) and a default MP4 video player.
- Standard C/C++ runtime libraries, including `libstdc++` and `libgomp`.
- A graphical desktop session to display the Tkinter interface and player.

On Debian/Ubuntu, the general prerequisites are:

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv python3-tk ffmpeg xdg-utils libstdc++6 libgomp1
```

If the installed Python is not 3.12, `setup.sh` attempts to create a local `.venv`
and download compatible versions of the Python dependencies. Availability depends
on that Python version. Use Python 3.12 if compatible wheels are unavailable.

The app prefers a local `.venv` if one has been created; otherwise it
uses the bundled Python packages with Python 3.12. It resolves all paths relative
to this folder and does not need the original project or its virtual environment.

To check dependencies without launching the app:

```bash
python3 speak.py --check
```

## Output and offline use

Each generation makes a new `output/clanker_<unique-id>/` folder containing:

```text
speech.wav         generated speech
mouth_cues.json    mouth timing
clanker.mp4        finished video
clanker.ffmpeg.log encoder log
```

Once system dependencies are present, the bundled Python 3.12 path needs no
internet access. Speech generation, lip sync and rendering all run locally.
No cloud account, API key or `.env` file is needed.

If automatic playback fails, the app shows the saved file path. Open that MP4
manually or configure a default video player for MP4 files.

`ANIMATION.md` contains technical notes about the renderer. Its example recordings
and test scripts from the development project are not included in this copy.

"""Small, deterministic facial timelines driven by the actual speech WAV.

Only the audio envelope (50 numbers per second) is kept, not the recording.
FFmpeg is already part of the renderer; no audio/DSP dependency is needed.
"""
from array import array
from bisect import bisect_right
from dataclasses import dataclass
import math
import random
import subprocess
import sys
import tempfile
import wave


def ease(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@dataclass(frozen=True)
class Settings:
    intensity: float = 1.0
    mouth_strength: float = 1.0
    mouth_smoothing: float = 1.0
    mouth_attack: float = 0.035
    mouth_release: float = 0.130
    mouth_overshoot: float = 0.065
    blink_frequency: float = 1.0
    blink_min: float = 3.0
    blink_max: float = 6.0
    blink_duration_min: float = 0.120
    blink_duration_max: float = 0.180
    double_blink_chance: float = 0.15
    blink_steps: int = 6
    eye_strength: float = 1.0
    brow_strength: float = 1.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be nonnegative and finite")
        if self.blink_steps < 1 or self.blink_min <= 0 or self.blink_max < self.blink_min:
            raise ValueError("Blink steps and interval bounds must be positive and ordered")
        if self.blink_duration_min <= 0 or self.blink_duration_max < self.blink_duration_min:
            raise ValueError("Blink durations must be positive and ordered")


class AudioEnvelope:
    HOP = 0.020

    def __init__(self, path):
        with wave.open(str(path), "rb") as wav:
            self.duration = wav.getnframes() / wav.getframerate()
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ValueError("Speech WAV must contain audio.")
        command = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
                   "-ac", "1", "-ar", "16000", "pipe:1"]
        self.rms = []
        # Temporary stderr file prevents pipe deadlocks on decoding failures.
        with tempfile.TemporaryFile() as log:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log) as process:
                while True:
                    block = process.stdout.read(640)  # 320 samples / 20 ms.
                    if not block:
                        break
                    samples = array("h")
                    samples.frombytes(block)
                    if sys.byteorder != "little":
                        samples.byteswap()
                    self.rms.append(math.sqrt(sum(s * s for s in samples)
                                              / len(samples)) / 32768.0)
                if process.wait():
                    log.seek(0)
                    raise RuntimeError("Audio analysis failed: " + log.read().decode(errors="replace"))
        if not self.rms:
            raise ValueError("Speech WAV could not be decoded.")
        ordered = sorted(self.rms)
        self.reference = max(0.012, ordered[int((len(ordered) - 1) * 0.90)])
        self.gate = max(0.003, min(0.012, self.reference * 0.045))
        self.levels = [min(1.0, max(0.0, (r - self.gate)
                        / max(0.001, self.reference - self.gate)) ** 0.7)
                       for r in self.rms]

    def at(self, time):
        # Time-indexed blocks; the speech/audio track itself is never shifted.
        index = int(time / self.HOP)
        return self.levels[index] if 0 <= index < len(self.levels) else 0.0


@dataclass(frozen=True)
class Face:
    shape: str
    previous_shape: str
    shape_mix: float
    mouth: float
    energy: float
    blink: int
    gaze: tuple
    brows: tuple


class Timeline:
    def __init__(self, audio, cues, fps=25, seed=42, settings=None):
        self.audio = audio
        self.duration = audio.duration
        self.fps = fps
        self.settings = settings or Settings()
        self.cues = cues
        self.cue_starts = [float(c["start"]) for c in cues]
        if any(float(c["end"]) < float(c["start"]) for c in cues):
            raise ValueError("Mouth cues must have nonnegative durations.")
        if self.cue_starts != sorted(self.cue_starts):
            raise ValueError("Mouth cues must be ordered by start time.")
        # Separate random streams keep one feature's configuration from
        # unexpectedly changing all the other schedules.
        self.blinks = self._blinks(random.Random(seed))
        self.blink_starts = [e[0] for e in self.blinks]
        self.gazes = self._gazes(random.Random(seed + 101))
        self.expressions = self._expressions(random.Random(seed + 202))
        self.frames = self._frames()

    def shape_at(self, time):
        i = bisect_right(self.cue_starts, time) - 1
        if i >= 0 and time < float(self.cues[i]["end"]):
            shape = self.cues[i]["value"]
            if shape in "ABCDEFGHX" and len(shape) == 1:
                return shape
        return "X"

    def _quiet_near(self, time, radius=0.25):
        candidates = [time + n * AudioEnvelope.HOP for n in range(-int(radius / AudioEnvelope.HOP),
                                                                   int(radius / AudioEnvelope.HOP) + 1)]
        candidates = [t for t in candidates if 0 <= t < self.duration]
        return min(candidates, key=lambda t: self.audio.at(t) + 0.15 * abs(t - time)) if candidates else time

    def _blinks(self, rng):
        s = self.settings
        events, end = [], 0.0
        frequency = s.blink_frequency * min(1.5, s.intensity)
        if frequency <= 0:
            return events
        while True:
            start = end + rng.uniform(s.blink_min, s.blink_max) / frequency
            if start >= self.duration:
                return events
            start = max(end + 0.25, self._quiet_near(start))
            end = start + rng.uniform(s.blink_duration_min, s.blink_duration_max)
            events.append((start, end))
            if rng.random() < s.double_blink_chance:
                start = end + rng.uniform(0.09, 0.16)
                if start < self.duration:
                    end = start + rng.uniform(s.blink_duration_min, s.blink_duration_max)
                    events.append((start, end))

    def _gazes(self, rng):
        events, time = [], rng.uniform(1.4, 2.8)
        while time < self.duration:
            start = self._quiet_near(time, 0.5)
            upward = rng.random() < 0.30
            dx = rng.choice((-1, 1)) * rng.uniform(0.5, 1.0)
            dy = -rng.uniform(0.6, 1.0) if upward else 0.0
            end = min(self.duration - 0.08, start + rng.uniform(0.85, 1.6))
            if end - start < 0.55:
                break
            events.append((start, end, dx, dy))
            time = events[-1][1] + rng.uniform(2.8, 5.8)
        return events

    def _expressions(self, rng):
        events, available = [], 0.0
        # Strong syllables, sampled sparsely and with a refractory period.
        for i in range(1, len(self.audio.levels) - 1):
            time = i * AudioEnvelope.HOP
            level = self.audio.levels[i]
            if time < available or level < 0.72:
                continue
            if level < self.audio.levels[i - 1] or level <= self.audio.levels[i + 1]:
                continue
            available = time + rng.uniform(1.8, 3.8)
            if self.shape_at(time) == "X" or rng.random() > 0.75:
                continue
            strength = rng.uniform(0.45, 0.8) * level
            pair = (strength, strength) if rng.random() < 0.65 else rng.choice(((0.9, 0.0), (0.0, 0.9)))
            end = min(self.duration - 0.08, time + rng.uniform(0.65, 1.1))
            if end - time >= 0.4:
                events.append((time, end, *pair))
        # A thinking glance can carry a single raised eyebrow during a pause.
        for start, end, dx, dy in self.gazes:
            if dy < 0 and self.audio.at(start) < 0.2:
                events.append((start, end, 0.75 if dx < 0 else 0, 0.75 if dx >= 0 else 0))
        return sorted(events)

    def blink_at(self, time):
        i = bisect_right(self.blink_starts, time) - 1
        if i < 0 or time >= self.blinks[i][1]:
            return 0
        start, end = self.blinks[i]
        phase = (time - start) / (end - start)
        closed = ease(phase / 0.38) if phase < 0.38 else (1.0 if phase < 0.58
                  else 1.0 - ease((phase - 0.58) / 0.42))
        return round(closed * self.settings.blink_steps)

    @staticmethod
    def reaction(time, start, end):
        return ease((time - start) / 0.20) * (1.0 - ease((time - end + 0.35) / 0.35))

    def _frames(self):
        s = self.settings
        frames, opening, previous_energy, kick, silent = [], 0.0, 0.0, 0.0, 0.0
        previous_shape = current_shape = "X"
        shape_start, last_kick = 0.0, -1.0
        gaze_index = expression_index = 0
        for i in range(math.ceil(self.duration * self.fps)):
            time, dt = i / self.fps, 1.0 / self.fps
            energy = self.audio.at(time)
            shape = self.shape_at(time)
            if shape != current_shape:
                previous_shape, current_shape = current_shape, shape
                shape_start = time
            closed = shape in ("A", "X") or energy == 0
            target = 0.0 if closed else min(0.94, 0.9 * energy * s.mouth_strength * s.intensity)
            tau = s.mouth_attack if target > opening else (min(s.mouth_release, 0.055)
                                                          if shape == "A" else s.mouth_release)
            opening += (target - opening) * (1.0 - math.exp(-dt / max(0.001, tau * s.mouth_smoothing)))
            kick *= math.exp(-dt / 0.065)
            if not closed and energy > 0.7 and energy - previous_energy > 0.18 and time - last_kick > 0.22:
                kick = s.mouth_overshoot * s.mouth_strength * s.intensity * min(1.0, (energy - previous_energy) * 2)
                last_kick = time
            if closed:
                kick = 0.0
            silent = silent + dt if energy == 0 or shape == "X" else 0.0
            if silent >= 0.24 or opening < 0.008:
                opening = 0.0
            visible_opening = (opening + kick) * (1.0 - ease(silent / 0.24))
            previous_energy = energy
            while gaze_index < len(self.gazes) and time >= self.gazes[gaze_index][1]:
                gaze_index += 1
            gaze = (0.0, 0.0)
            if gaze_index < len(self.gazes):
                start, end, dx, dy = self.gazes[gaze_index]
                amount = self.reaction(time, start, end) * min(1.5, max(0, s.eye_strength * s.intensity))
                # Source pixels. Small discrete poses are below one output pixel.
                gaze = (round(dx * amount * 9), round(dy * amount * 7))
            while expression_index < len(self.expressions) and time >= self.expressions[expression_index][1]:
                expression_index += 1
            brows = (0, 0)
            if expression_index < len(self.expressions):
                start, end, left, right = self.expressions[expression_index]
                amount = self.reaction(time, start, end) * min(1.5, max(0, s.brow_strength * s.intensity))
                # Suppress a little during closure; no abrupt cancellation.
                amount *= 1.0 - 0.15 * self.blink_at(time) / s.blink_steps
                brows = (round(left * amount * 10), round(right * amount * 10))
            frames.append(Face(shape, previous_shape, ease((time - shape_start) / 0.080),
                               min(1.0, max(0.0, visible_opening)), energy,
                               self.blink_at(time), gaze, brows))
        return frames

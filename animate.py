import argparse
from bisect import bisect_right
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw
from facial import AudioEnvelope, Settings, Timeline

# ==========================================
# SETTINGS (positions refer to the original artwork)
# ==========================================
BASE = Path(__file__).resolve().parent
ROBOT = BASE / "assets/clanker/robot.png"
MOUTHS = BASE / "assets/clanker/mouths"
JSON_FILE = BASE / "output/hello.json"
AUDIO = BASE / "output/hello.wav"
VIDEO = BASE / "output/clanker_preview.mp4"
FULL_VIDEO = BASE / "output/clanker_animated.mp4"
PREVIEW_SECONDS = 10.0
WIDTH, HEIGHT, FPS = 1280, 720, 25
ROBOT_HEIGHT = 680
# Double the original 462 x 120 overlay around the same centre (628, 725).
MOUTH_X, MOUTH_Y, MOUTH_W, MOUTH_H = 166, 605, 924, 240
# Keep the enlarged animation inside the opening, clear of its metal rim.
MOUTH_APERTURE = ((464, 672), (789, 672), (801, 690), (817, 695),
                  (817, 757), (801, 765), (789, 779), (465, 779),
                  (452, 765), (438, 757), (438, 695), (453, 689))

# Expression controls: 0 disables a feature, 1 is the intended subtle default.
ANIMATION_INTENSITY = 1.0
MOUTH_MOVEMENT_STRENGTH = 1.0
MOUTH_SMOOTHING = 1.0       # Larger = gentler/slower response.
MOUTH_OPEN_SECONDS = 0.035
MOUTH_CLOSE_SECONDS = 0.130
MOUTH_OVERSHOOT = 0.065
BLINK_FREQUENCY = 1.0      # Larger = more frequent; 0 disables blinks.
EYE_MOVEMENT_STRENGTH = 1.0
EYEBROW_EXPRESSION_STRENGTH = 1.0

ENABLE_BLINKING = True
BLINK_INTERVAL_MIN = 3.0
BLINK_INTERVAL_MAX = 6.0
BLINK_DURATION_MIN = 0.120
BLINK_DURATION_MAX = 0.180
DOUBLE_BLINK_CHANCE = 0.15
BLINK_STEPS = 6

ENABLE_EYEBROWS = True
ENABLE_HEAD_MOVEMENT = True
HEAD_BOB_PIXELS = 3
HEAD_TILT_DEGREES = 1.0
RANDOM_SEED = 42

# Optional separated layers; otherwise use a small local texture deformation.
BROW_DIR = BASE / "assets/clanker/eyebrows"

# Inner apertures only: leave the surrounding metal eye rings untouched.
# cx, cy, radius x, radius y, resting lower edge of the upper lid.
EYES = ((471, 500, 80, 81, 494), (782, 500, 80, 81, 494))
# Overlap at the neck keeps small movements from opening a transparent seam.
BODY_TOP = 900
HEAD_BOTTOM = 912
NECK_PIVOT = (627, 909)
HEAD_PADDING = 12  # Output pixels; protects the antenna during rotation.


def smoothstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def speech_spans(cues):
    """Rhubarb X is rest; A (closed talking mouth) still counts as speech."""
    spans = []
    for cue in cues:
        if cue["value"] == "X":
            continue
        start, end = float(cue["start"]), float(cue["end"])
        if spans and start - spans[-1][1] <= 0.16:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return spans


def speech_pose(time, spans, starts):
    index = bisect_right(starts, time + 0.10) - 1
    if index < 0:
        return 0.0, 0.0, 0
    start, end = spans[index]
    release = 0.30
    if index + 1 < len(spans):
        # Finish releasing before the next phrase's anticipation begins.
        release = min(release, max(0.01, spans[index + 1][0] - end - 0.10))
    envelope = (smoothstep((time - start + 0.10) / 0.20)
                * (1.0 - smoothstep((time - end) / release)))
    local = time - start
    bob = -HEAD_BOB_PIXELS * envelope * (0.5 - 0.5 * math.cos(2 * math.pi * 1.6 * local))
    tilt = (HEAD_TILT_DEGREES * envelope * math.sin(math.pi * max(0.0, local)
            / max(0.4, end - start + 0.3)) if index % 3 == 1 else 0.0)
    if index % 2:
        tilt = -tilt
    return bob, tilt, envelope


def make_lids(robot):
    """Map the existing textured metal domes into fitted aperture masks.

    Every row samples inside the original upper dome, avoiding the eye/rim.
    Seven small reusable states are built once, rather than per video frame.
    """
    states = {0: []}
    source = robot.load()
    for step in range(1, BLINK_STEPS + 1):
        patches = []
        for cx, cy, rx, ry, resting_edge in EYES:
            left, top = cx - rx, cy - ry
            size = (2 * rx + 1, 2 * ry + 1)
            patch = Image.new("RGBA", size)
            pixels = patch.load()
            edge = resting_edge + (cy + ry + 2 - resting_edge) * step / BLINK_STEPS
            for y in range(size[1]):
                world_y = y + top
                if world_y > edge:
                    continue
                half_width = rx * math.sqrt(max(0.0, 1 - ((world_y - cy) / ry) ** 2))
                sample_y = top + (world_y - top) * (resting_edge - top - 3) / (edge - top)
                sample_width = rx * math.sqrt(max(0.0, 1 - ((sample_y - cy) / ry) ** 2))
                for x in range(size[0]):
                    offset = x - rx
                    coverage = min(1.0, max(0.0, half_width - abs(offset)))
                    if not coverage:
                        continue
                    sample_x = cx + offset * max(0.0, sample_width - 2) / max(1.0, half_width)
                    color = source[round(sample_x), round(sample_y)]
                    if edge - world_y < 2:
                        color = (27, 33, 33, 255)  # Mechanical shutter's lower lip.
                    pixels[x, y] = (*color[:3], round(255 * coverage))
            patches.append((patch, (left, top)))
        states[step] = patches
    return states


def eyebrow_layers(robot):
    if not ENABLE_EYEBROWS:
        return None
    paths = [BROW_DIR / name for name in ("clean_face.png", "left.png", "right.png")]
    if not all(path.is_file() for path in paths):
        print("Eyebrows: subtle local movement of original artwork.", flush=True)
        return None
    layers = [Image.open(path).convert("RGBA") for path in paths]
    if any(layer.size != robot.size for layer in layers):
        raise ValueError("Eyebrow layers must match robot.png dimensions; see ANIMATION.md")
    return layers


def deform_patch(robot, box, displacement):
    """Inverse mesh warp with fixed patch boundaries; reuse painted pixels."""
    patch = robot.crop(box)
    mesh = []
    step = 4
    def point(x, y):
        dx, dy = displacement(x + box[0], y + box[1])
        return x + dx, y + dy
    for y in range(0, patch.height, step):
        for x in range(0, patch.width, step):
            right, bottom = min(x + step, patch.width), min(y + step, patch.height)
            corners = (point(x, y), point(x, bottom), point(right, bottom), point(right, y))
            mesh.append(((x, y, right, bottom), tuple(v for p in corners for v in p)))
    return patch.transform(patch.size, Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)


def prepare_artwork(robot):
    scale = ROBOT_HEIGHT / robot.height
    width = round(robot.width * scale)
    scaled_size = (width, ROBOT_HEIGHT)
    pad = HEAD_PADDING
    head_height = round(HEAD_BOTTOM * scale)
    body = robot.resize(scaled_size, Image.Resampling.LANCZOS)
    body.paste((0, 0, 0, 0), (0, 0, width, round(BODY_TOP * scale)))
    background = Image.new("RGBA", (WIDTH, HEIGHT), (28, 33, 43, 255))
    background.alpha_composite(body, ((WIDTH - width) // 2, HEIGHT - ROBOT_HEIGHT))

    def head_layer(original):
        scaled = original.resize(scaled_size, Image.Resampling.LANCZOS)
        head = Image.new("RGBA", (width + 2 * pad, head_height + 2 * pad))
        head.alpha_composite(scaled.crop((0, 0, width, head_height)), (pad, pad))
        return head

    base_head = head_layer(robot)

    def small_patch(patch, box):
        x, y, right, bottom = (round(v * scale) for v in box)
        # Use the same source-to-output grid as the whole character. Simply
        # resizing a rounded crop shifts its untouched pixels by up to 1px.
        margin = 4
        if patch.mode == "RGBA":
            expanded = robot.crop((box[0] - margin, box[1] - margin,
                                   box[2] + margin, box[3] + margin))
        else:
            expanded = Image.new(patch.mode, (patch.width + 2 * margin, patch.height + 2 * margin))
        expanded.paste(patch, (margin, margin))
        sample = (x / scale - box[0] + margin, y / scale - box[1] + margin,
                  right / scale - box[0] + margin, bottom / scale - box[1] + margin)
        scaled = expanded.resize((right - x, bottom - y), Image.Resampling.LANCZOS, box=sample)
        return scaled, (x + pad, y + pad)

    mouth_box = (438, 672, 818, 780)
    mouth_mask = Image.new("L", robot.size)
    ImageDraw.Draw(mouth_mask).polygon(MOUTH_APERTURE, fill=255)
    mouth_alpha, mouth_position = small_patch(mouth_mask.crop(mouth_box), mouth_box)
    mouths = {}
    for shape in "ABCDEFGHX":
        mouth = Image.open(MOUTHS / f"{shape}.png").convert("RGBA")
        mouth = mouth.resize((MOUTH_W, MOUTH_H), Image.Resampling.LANCZOS)
        overlay = Image.new("RGBA", robot.size)
        overlay.alpha_composite(mouth, (MOUTH_X, MOUTH_Y))
        character = robot.copy()
        character.alpha_composite(overlay)
        mouths[shape], _ = small_patch(character.crop(mouth_box), mouth_box)

    @lru_cache(maxsize=96)
    def mouth_patch(shape, level):
        # The original X artwork contains two closed mechanical shutter plates.
        # Slide those plates apart to reveal the phoneme artwork underneath.
        closed = mouths["X"]
        patch = mouths[shape].copy()
        seam = round((MOUTH_Y + 61 * MOUTH_H / 128 - mouth_box[1]) * scale)
        distance = round(max(seam, closed.height - seam) * level / 32)
        if distance < seam:
            patch.paste(closed.crop((0, distance, closed.width, seam)), (0, 0))
        if distance < closed.height - seam:
            patch.paste(closed.crop((0, seam, closed.width, closed.height - distance)),
                        (0, seam + distance))
        patch.putalpha(mouth_alpha)
        return patch

    lids = {0: []}
    if ENABLE_BLINKING:
        for step, patches in make_lids(robot).items():
            lids[step] = []
            for patch, (x, y) in patches:
                x1, y1 = round(x * scale), round(y * scale)
                x2, y2 = round((x + patch.width) * scale), round((y + patch.height) * scale)
                lids[step].append((patch.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS),
                                   (x1 + pad, y1 + pad)))

    layers = eyebrow_layers(robot)

    @lru_cache(maxsize=32)
    def brow_patches(left, right):
        if layers:
            clean, left_layer, right_layer = layers
            overlay = clean.copy()
            overlay.alpha_composite(left_layer, (0, -left))
            overlay.alpha_composite(right_layer, (0, -right))
            box = (350, 290, 905, 450)
            return [small_patch(overlay.crop(box), box)]
        patches = []
        for index, height in enumerate((left, right)):
            if not height:
                continue
            cx, cy = ((485, 383) if index == 0 else (768, 383))
            angle = math.radians(16 if index == 0 else -16)
            box = (cx - 128, 305, cx + 128, 448)
            def displacement(x, y):
                u = (x - cx) * math.cos(angle) + (y - cy) * math.sin(angle)
                v = -(x - cx) * math.sin(angle) + (y - cy) * math.cos(angle)
                weight = smoothstep((115 - abs(u)) / 20) * smoothstep((39 - abs(v)) / 14)
                weight *= smoothstep((box[3] - y) / 14)
                # The brow shadows touch the upper eye rings. Pin those rings
                # in place rather than allowing them to bend with the plates.
                eye_cx, eye_cy = EYES[index][:2]
                if abs(x - eye_cx) < 107:
                    rim_top = eye_cy - 105 * math.sqrt(1 - ((x - eye_cx) / 107) ** 2)
                    weight *= smoothstep((rim_top - y - 3) / 18)
                return 0, min(10, height) * weight
            patches.append(small_patch(deform_patch(robot, box, displacement), box))
        return patches

    @lru_cache(maxsize=48)
    def gaze_patches(dx, dy):
        patches = []
        for cx, cy, rx, ry, edge in EYES:
            box = (cx - rx, edge + 2, cx + rx + 1, cy + ry + 1)
            def displacement(x, y):
                radius = ((x - cx) / (rx - 8)) ** 2 + ((y - cy) / (ry - 8)) ** 2
                weight = smoothstep((1 - radius) * 3.5)
                return -dx * weight, -dy * weight
            patches.append(small_patch(deform_patch(robot, box, displacement), box))
        return patches

    pivot = (NECK_PIVOT[0] * scale + pad, NECK_PIVOT[1] * scale + pad)

    @lru_cache(maxsize=8)
    def posed_head(shape, previous_shape, mix, level, blink, gaze, brows, angle):
        head = base_head.copy()
        if shape in ("A", "X"):
            # Let the shutter finish its eased close instead of cutting to X.
            shape = previous_shape if previous_shape not in ("A", "X") else "F"
            mix = 8
        mouth = mouth_patch(shape, level)
        if mix < 8 and previous_shape not in ("A", "X"):
            mouth = Image.blend(mouth_patch(previous_shape, level), mouth, mix / 8)
        head.alpha_composite(mouth, mouth_position)
        if ENABLE_EYEBROWS and any(brows):
            for patch, position in brow_patches(*brows):
                head.alpha_composite(patch, position)
        if any(gaze):
            for patch, position in gaze_patches(*gaze):
                head.alpha_composite(patch, position)
        for patch, position in lids.get(blink, []):
            head.alpha_composite(patch, position)
        if angle:
            head = head.rotate(angle, Image.Resampling.BICUBIC, center=pivot)
        return head

    def frame(face, bob=0.0, tilt=0.0):
        head = posed_head(face.shape, face.previous_shape, round(face.shape_mix * 8),
                           round(face.mouth * 32), face.blink, face.gaze, face.brows, round(tilt, 1))
        canvas = background.copy()
        canvas.alpha_composite(head, ((WIDTH - width) // 2 - pad,
                                    HEIGHT - ROBOT_HEIGHT - pad + round(bob)))
        return canvas.convert("RGB")

    return frame


def main():
    parser = argparse.ArgumentParser(description="Render Clanker; default is a 10-second preview.")
    length = parser.add_mutually_exclusive_group()
    length.add_argument("--full", action="store_true", help="render the entire recording")
    length.add_argument("--duration", type=float, help="preview length in seconds")
    parser.add_argument("--output", type=Path, help="new MP4 path (existing files are protected)")
    parser.add_argument("--audio", type=Path, default=AUDIO, help="WAV file to animate")
    parser.add_argument("--json", type=Path, default=JSON_FILE, help="matching Rhubarb JSON file")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration must be positive and finite")
    output = args.output or (FULL_VIDEO if args.full else VIDEO)
    if output.resolve() == (BASE / "output/hello.mp4").resolve():
        parser.error("hello.mp4 is protected; choose another output path")
    if output.exists():
        parser.error(f"Output already exists: {output}. Choose a new --output path.")

    with args.json.open(encoding="utf-8") as source:
        data = json.load(source)
    cues = data["mouthCues"]
    audio = AudioEnvelope(args.audio)
    recording_duration = audio.duration
    duration = recording_duration if args.full else min(recording_duration, args.duration or PREVIEW_SECONDS)
    if not math.isfinite(duration) or duration <= 0:
        parser.error("Animation duration must be positive and finite")
    robot = Image.open(ROBOT).convert("RGBA")
    if robot.size != (1254, 1254):
        raise ValueError("Eye/neck positions are calibrated for the original 1254 × 1254 robot.png")
    render_frame = prepare_artwork(robot)
    settings = Settings(
        intensity=ANIMATION_INTENSITY,
        mouth_strength=MOUTH_MOVEMENT_STRENGTH,
        mouth_smoothing=MOUTH_SMOOTHING,
        mouth_attack=MOUTH_OPEN_SECONDS,
        mouth_release=MOUTH_CLOSE_SECONDS,
        mouth_overshoot=MOUTH_OVERSHOOT,
        blink_frequency=BLINK_FREQUENCY if ENABLE_BLINKING else 0,
        blink_min=BLINK_INTERVAL_MIN, blink_max=BLINK_INTERVAL_MAX,
        blink_duration_min=BLINK_DURATION_MIN, blink_duration_max=BLINK_DURATION_MAX,
        double_blink_chance=DOUBLE_BLINK_CHANCE, blink_steps=BLINK_STEPS,
        eye_strength=EYE_MOVEMENT_STRENGTH,
        brow_strength=EYEBROW_EXPRESSION_STRENGTH if ENABLE_EYEBROWS else 0,
    )
    timeline = Timeline(audio, cues, FPS, args.seed, settings)
    spans = speech_spans(cues)
    span_starts = [span[0] for span in spans]
    total_frames = math.ceil(duration * FPS)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = output.with_suffix(".ffmpeg.log")
    command = [
        "ffmpeg", "-n", "-threads", "2", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-i", str(args.audio),
        "-t", str(duration), "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
        "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(output),
    ]
    print(f"Rendering {duration:.2f} seconds / {total_frames} frames; seed {args.seed}", flush=True)
    with log_path.open("w") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(total_frames):
                time = i / FPS
                face = timeline.frames[i]
                bob, tilt, _ = speech_pose(time, spans, span_starts)
                bob *= face.energy * ANIMATION_INTENSITY
                tilt *= ANIMATION_INTENSITY
                if not ENABLE_HEAD_MOVEMENT:
                    bob, tilt = 0, 0
                process.stdin.write(render_frame(face, bob, tilt).tobytes())
                if i % (FPS * 5) == 0:
                    print(f"Rendered {time:.0f} / {duration:.1f} seconds", flush=True)
        except BrokenPipeError:
            raise RuntimeError(f"FFmpeg stopped unexpectedly; see {log_path}") from None
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            return_code = process.wait()
    if return_code:
        raise RuntimeError(f"FFmpeg failed with exit code {return_code}; see {log_path}")
    print(f"Animation complete: {output}", flush=True)


if __name__ == "__main__":
    main()

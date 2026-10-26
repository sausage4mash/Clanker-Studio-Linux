Clanker facial animation
========================

The GUI and workflow are unchanged: launch `.venv/bin/python speak.py`, enter
text and click **Text to Animation**. Piper creates the WAV, Rhubarb creates
phoneme cues, and Pillow/FFmpeg render the video. Each run keeps its own
`output/clanker_.../` folder. No original artwork, existing recordings, or older
videos are overwritten. Output remains 1280 × 720 at 25 FPS with H.264/AAC.

Implementation
--------------

`facial.py` analyses the actual PCM WAV in 20 ms RMS blocks, using the existing
FFmpeg installation to decode mono samples. A relative loudness reference and
silence gate make the result usable across recordings. Only envelope values are
retained; the complete decoded audio is never loaded into memory.

A shared, seeded timeline combines this envelope with the original Rhubarb
boundaries. The WAV determines recording duration, avoiding drift from rounded
JSON metadata. Preview renders use a prefix of the full recording's timeline.
Audio is neither stretched nor offset. At 25 FPS, the final video duration can
be up to one frame (40 ms) shorter than the WAV because FFmpeg trims to frames.

The original X mouth supplies closed mechanical shutter plates. These slide
apart to reveal the original phoneme artwork, in proportion to speech intensity.
Opening responds faster than closing. A brief, damped extra displacement on
strong rising syllables adds mechanical overshoot, with a cooldown so it does
not chatter. Mouth shapes blend over 80 ms. Rhubarb A closes for consonants;
X/rest and the audio silence gate ease the shutter fully closed within 240 ms.
Sustained speech follows its intensity rather than an invented open/close cycle.
The 924 × 240 source-pixel overlay stays clipped inside the original metal rim.

Blinking reuses the painted upper lids and its existing six-step animation.
Intervals vary around 3–6 seconds, with small adjustments towards nearby quiet
moments and a 15% double-blink chance. Blinks last 120–180 ms, sampled at 25 FPS.

Small eye glances use the original eye pixels inside a fixed aperture. Gaze
eases sideways and occasionally upward, holds briefly, then returns forward.
The lid and outer ring remain fixed. Gaze events are several seconds apart.

Brow emphasis follows occasional strong syllables, with irregular cooldowns.
Both brows can rise for emphasis; a single brow suggests scepticism. Thinking
glances in pauses can carry a single raised brow. Expressions ease in and out
and soften slightly during blinking. These are expressive timing choices, not
semantic/emotion analysis of the words.

The brows are baked into the face. Small raises therefore use a constrained
local warp of the original plate/shadow pixels, pinning the upper eye rims.
This avoids duplicate brows and missing background patches. Movement is capped
at 10 source pixels and is intended to stay subtle. The existing optional layer
path remains supported for larger, independently prepared artwork:
`assets/clanker/eyebrows/{clean_face,left,right}.png`, each 1254 × 1254 RGBA.
The clean face must remove both plates and shadows; the two plate layers must
sit at their original coordinates with transparency elsewhere. These optional
layers are not needed for the default animation and were not present for testing.

The existing head/neck movement and fixed torso remain. Speech intensity now
also moderates the small head bob. Mouth, eye and brow patches use bounded
caches; head transforms operate on scaled artwork. FFmpeg encoding still uses
two threads. No additional runtime dependency, service or GPU is required.

Settings in animate.py
----------------------

| Constant | Default | Effect |
| --- | --- | --- |
| `MOUTH_MOVEMENT_STRENGTH` | `1.0` | Scales audio-driven opening; `0` keeps the mouth closed. |
| `MOUTH_SMOOTHING` | `1.0` | Scales response times; larger values give slower, smoother motion. |
| `MOUTH_OPEN_SECONDS` | `0.035` | Opening response time. |
| `MOUTH_CLOSE_SECONDS` | `0.130` | Closing response time; consonant closure is faster. |
| `MOUTH_OVERSHOOT` | `0.065` | Extra displacement on strong onsets; `0` disables it. |
| `BLINK_FREQUENCY` | `1.0` | Scales blink frequency; `0` disables blinking. |
| `EYE_MOVEMENT_STRENGTH` | `1.0` | Scales gaze travel; `0` keeps eyes forward. |
| `EYEBROW_EXPRESSION_STRENGTH` | `1.0` | Scales brow raises; `0` keeps brows neutral. |
| `ANIMATION_INTENSITY` | `1.0` | Scales facial/head motion and blink frequency; `0` rests all features. |
| `RANDOM_SEED` | `42` | Repeatable independent blink, gaze and expression schedules. |

Start with strengths around 0.5–1.0. `ENABLE_BLINKING`, `ENABLE_EYEBROWS` and
`ENABLE_HEAD_MOVEMENT` remain available. The blink timing bounds, head bob and
tilt constants are still near the top of the renderer. No GUI controls were added.

Commands and validation
-----------------------

```bash
# Preview an existing GUI recording; choose an unused output filename.
.venv/bin/python animate.py --duration 10 \
  --audio output/facial_sample/speech.wav \
  --json output/facial_sample/mouth_cues.json \
  --seed 7 --output output/clanker_new_preview.mp4

# Render the complete recording using the same arguments plus --full,
# omitting --duration. --seed overrides RANDOM_SEED.

# Automated checks (standard unittest, Pillow and the existing FFmpeg).
.venv/bin/python -m unittest -v test_facial
```

`output/facial_sample/clanker_faces.mp4` is the checked sample. It uses a newly
generated Piper recording of `output/facial_sample/dialogue.txt`, with 0.7 seconds
of sentence silence to exercise pauses, and matching Rhubarb cues. The sample
uses seed 7 so its short duration includes upward glances and single-brow raises
as well as blinks and paired emphasis. Normal GUI speech generation is unchanged.

`output/facial_sample/contact_sheet.jpg` contains decoded frames for rest,
strong speech, a blink, a thinking glance, a single brow and paired emphasis.
`output/facial_sample/validation.json` records stream properties, event timings,
audio alignment and sample performance.

The checked WAV is 9.716 seconds; encoded video is 9.680 seconds (242 frames),
within one frame of the audio. Both streams start at zero. Decoded AAC versus
the Piper WAV has correlation 0.999726 and zero measured lag at 16 kHz in a
±50 ms search. All 64 frames after at least 240 ms of continuous gated silence
have a fully closed shutter. The sample includes two complete blinks, two
glances (one upward), single-brow reactions and paired emphasis. Decoded frames
were visually inspected. Rendering took 11.88 seconds with about 94 MiB peak
Python resident memory in this environment; laptop performance may differ.

Nine automated tests cover actual WAV intensity/silence, asymmetric smoothing,
overshoot, rest cues, deterministic schedules, feature controls, stationary
body/nose/antenna, closed-mouth stability across phonemes and fixed eye rims.
The optional separated eyebrow layers were not tested because none are supplied.

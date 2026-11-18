"""Generate the XPOrbs chime sounds: media/coin1..6.ogg and media/glass1..6.ogg.

The sounds are original: two voices synthesised by this script, released under the repo's GPL-3.0-or-later like the
rest of the addon. Each voice is six files, the same sound at six slightly different pitches (a cluster of base
frequencies around a centre, not a musical scale, so the addon can wobble between them).

coin (the default): a soft coin "clink" within about 100 cents of 1.7 kHz. Four closely spaced metallic partials
(ratios 1, 1.52, 2.27, 3.11, the higher ones fading faster), a 1 ms attack with a couple of milliseconds of
filtered-noise click for the strike, a softer second strike 30 ms later (the coin settling), and a copy of the
fundamental detuned by 6 Hz for a faint metallic beat. Fundamental decay time constant 0.07 s, 0.22 s long.

glass: a glassy, icy "tink" within about 150 cents of 3 kHz. Four inharmonic partials (ratios 1, 2.76, 5.40, 8.93, the
higher ones fading much faster), the same short noise click, no second strike, and a copy of the fundamental
detuned by 3.5 Hz for a faint shimmer. Fundamental decay time constant 0.09 s, 0.25 s long.

Both are mono, 44.1 kHz, end in true silence and peak at about -26 dBFS. The noise uses a fixed seed, so regenerating
gives identical files. Running the script also deletes the old media/chime1..6.ogg.

Needs ffmpeg with libvorbis on PATH (WAVs are written to a temp dir, then encoded with `-c:a libvorbis -q:a 3`).

Usage: uv run python tools/make_sounds.py [--out media]
"""

import argparse
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATE = 44100
FADE = 0.03  # raised-cosine fade to zero over the last 30 ms
ATTACK = 0.001
SEED = 20261118
OLD_PREFIX = "chime"  # the pre-voices file names, deleted on every run

# Each voice: centre pitch, the six offsets from it (cents), length, decay time constant of the fundamental,
# (ratio, amp, decay speed-up) partials, the detuned copy of the fundamental, the second strike (BOUNCE_AMP 0 = none),
# the strike-noise click and the peak level.
VOICES = {
    "coin": {
        "CENTRE": 1700.0,
        "CENTS": [-90, -55, -20, 15, 50, 85],
        "LENGTH": 0.22,
        "TAU": 0.07,
        "PARTIALS": [
            (1.0, 1.0, 1.0),
            (1.52, 0.55, 1.4),
            (2.27, 0.30, 2.0),
            (3.11, 0.14, 3.0),
        ],
        "SHIMMER_HZ": 6.0,
        "SHIMMER_AMP": 0.02,
        "BOUNCE_S": 0.030,
        "BOUNCE_AMP": 0.35,
        "CLICK_S": 0.002,
        "CLICK_AMP": 0.12,
        "PEAK_DBFS": -26.0,
    },
    "glass": {
        "CENTRE": 3000.0,
        "CENTS": [-140, -80, -30, 25, 70, 130],
        "LENGTH": 0.25,
        "TAU": 0.09,
        "PARTIALS": [
            (1.0, 1.0, 1.0),
            (2.76, 0.45, 2.2),
            (5.40, 0.22, 4.0),
            (8.93, 0.10, 6.5),
        ],
        "SHIMMER_HZ": 3.5,
        "SHIMMER_AMP": 0.01,
        "BOUNCE_S": 0.0,
        "BOUNCE_AMP": 0.0,
        "CLICK_S": 0.0025,
        "CLICK_AMP": 0.08,
        "PEAK_DBFS": -26.0,
    },
}


def notes(voice: str) -> list[float]:
    """The six base frequencies (Hz) of a voice."""
    v = VOICES[voice]
    return [round(v["CENTRE"] * 2 ** (c / 1200), 1) for c in v["CENTS"]]


def _strike(freq: float, t: float, v: dict) -> float:
    """The ringing of one strike, t seconds after it."""
    env = t / ATTACK if t < ATTACK else 1.0
    out = 0.0
    for ratio, amp, speed in v["PARTIALS"]:
        out += (
            amp
            * math.exp(-t * speed / v["TAU"])
            * math.sin(2 * math.pi * freq * ratio * t)
        )
    out += (
        v["SHIMMER_AMP"]
        * math.exp(-t / v["TAU"])
        * math.sin(2 * math.pi * (freq + v["SHIMMER_HZ"]) * t)
    )
    return out * env


def synth(freq: float, voice: str = "coin") -> list[int]:
    """One sound of a voice as 16-bit samples (deterministic)."""
    v = VOICES[voice]
    rng = random.Random(SEED)
    n = int(RATE * v["LENGTH"])
    fade_n = int(RATE * FADE)
    click_n = int(RATE * v["CLICK_S"])
    bounce = v["BOUNCE_AMP"] > 0
    bounce_i = int(RATE * v["BOUNCE_S"])
    strikes = [(0, v["CLICK_AMP"])]
    if bounce:
        strikes.append((bounce_i, v["CLICK_AMP"] * v["BOUNCE_AMP"]))
    raw = []
    lp = 0.0
    for i in range(n):
        t = i / RATE
        x = _strike(freq, t, v)
        if bounce and i >= bounce_i:
            x += v["BOUNCE_AMP"] * _strike(freq, t - v["BOUNCE_S"], v)
        for start, amp in strikes:
            k = i - start
            if (
                0 <= k < click_n
            ):  # strike: noise, high-passed by differencing, fading out
                noise = rng.uniform(-1.0, 1.0)
                hp = noise - lp
                lp = noise
                x += amp * hp * (1 - k / click_n)
        if i >= n - fade_n:
            x *= 0.5 * (1 + math.cos(math.pi * (i - (n - fade_n)) / fade_n))
        raw.append(x)
    raw[-1] = 0.0  # true silence on the last sample
    scale = 10 ** (v["PEAK_DBFS"] / 20) / max(abs(x) for x in raw)
    return [round(x * scale * 32767) for x in raw]


def stats(samples: list[int]) -> tuple[float, float]:
    """(peak, rms) in dBFS."""
    peak = max(abs(v) for v in samples) / 32767
    rms = math.sqrt(sum(v * v for v in samples) / len(samples)) / 32767
    return 20 * math.log10(peak), 20 * math.log10(rms)


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "media",
        help="output folder (default: media/)",
    )
    args = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(
            "error: ffmpeg is not on PATH (it needs the libvorbis encoder)",
            file=sys.stderr,
        )
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob(f"{OLD_PREFIX}[1-6].ogg"):
        old.unlink()
        print(f"removed old {old.name}")
    with tempfile.TemporaryDirectory() as tmp:
        for voice in VOICES:
            for i, freq in enumerate(notes(voice), start=1):
                wav = Path(tmp) / f"{voice}{i}.wav"
                ogg = args.out / f"{voice}{i}.ogg"
                samples = synth(freq, voice)
                write_wav(wav, samples)
                cmd = [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(wav),
                    "-c:a",
                    "libvorbis",
                    "-q:a",
                    "3",
                    str(ogg),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode != 0:
                    print(
                        f"error: ffmpeg failed for {ogg.name} (is libvorbis available?):\n{res.stderr}",
                        file=sys.stderr,
                    )
                    return 1
                peak, rms = stats(samples)
                print(
                    f"{ogg.name}: {freq:.1f} Hz, peak {peak:.1f} dBFS, rms {rms:.1f} dBFS, {ogg.stat().st_size} bytes"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())

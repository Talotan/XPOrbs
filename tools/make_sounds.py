"""Generate the XPOrbs chime sounds: media/chime1..6.ogg.

The sounds are original: glassy, icy "tink"s synthesised by this script, released under the repo's GPL-3.0-or-later
like the rest of the addon.

Each file is the same struck-crystal tink at a slightly different pitch: six base frequencies in a cluster within
about 150 cents of 3 kHz (not a musical scale, so the addon can wobble between them). A tink is four inharmonic
partials (ratios 1, 2.76, 5.40, 8.93, the higher ones fading much faster), a 1 ms attack with a couple of
milliseconds of filtered-noise click for the strike, and a second copy of the fundamental detuned by 3.5 Hz for a
faint shimmer. Fundamental decay time constant 0.09 s, 0.25 s long, mono, 44.1 kHz, ending in true silence. The peak
sits at about -20 dBFS. The noise uses a fixed seed, so regenerating gives identical files.

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
CENTRE = 3000.0  # Hz
CENTS = [-140, -80, -30, 25, 70, 130]
NOTES = [round(CENTRE * 2 ** (c / 1200), 1) for c in CENTS]
LENGTH = 0.25  # seconds
ATTACK = 0.001
TAU = 0.09  # decay time constant of the fundamental
PARTIALS = [(1.0, 1.0, 1.0), (2.76, 0.45, 2.2), (5.40, 0.22, 4.0), (8.93, 0.10, 6.5)]  # (ratio, amp, decay speed-up)
SHIMMER_HZ = 3.5
SHIMMER_AMP = 0.01
CLICK_S = 0.0025  # length of the strike noise
CLICK_AMP = 0.08
FADE = 0.03  # raised-cosine fade to zero over the last 30 ms
PEAK_DBFS = -20.0
SEED = 20261118


def synth(freq: float) -> list[int]:
    """One tink as 16-bit samples (deterministic)."""
    rng = random.Random(SEED)
    n = int(RATE * LENGTH)
    fade_n = int(RATE * FADE)
    click_n = int(RATE * CLICK_S)
    raw = []
    lp = 0.0
    for i in range(n):
        t = i / RATE
        env = t / ATTACK if t < ATTACK else 1.0
        v = 0.0
        for ratio, amp, speed in PARTIALS:
            v += amp * math.exp(-t * speed / TAU) * math.sin(2 * math.pi * freq * ratio * t)
        v += SHIMMER_AMP * math.exp(-t / TAU) * math.sin(2 * math.pi * (freq + SHIMMER_HZ) * t)
        v *= env
        if i < click_n:  # strike: noise, high-passed by differencing, fading out
            noise = rng.uniform(-1.0, 1.0)
            hp = noise - lp
            lp = noise
            v += CLICK_AMP * hp * (1 - i / click_n)
        if i >= n - fade_n:
            v *= 0.5 * (1 + math.cos(math.pi * (i - (n - fade_n)) / fade_n))
        raw.append(v)
    raw[-1] = 0.0  # true silence on the last sample
    scale = 10 ** (PEAK_DBFS / 20) / max(abs(v) for v in raw)
    return [round(v * scale * 32767) for v in raw]


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
    ap.add_argument("--out", type=Path, default=ROOT / "media", help="output folder (default: media/)")
    args = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("error: ffmpeg is not on PATH (it needs the libvorbis encoder)", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for i, freq in enumerate(NOTES, start=1):
            wav = Path(tmp) / f"chime{i}.wav"
            ogg = args.out / f"chime{i}.ogg"
            samples = synth(freq)
            write_wav(wav, samples)
            cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libvorbis", "-q:a", "3", str(ogg)]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                print(f"error: ffmpeg failed for {ogg.name} (is libvorbis available?):\n{res.stderr}", file=sys.stderr)
                return 1
            peak, rms = stats(samples)
            print(f"{ogg.name}: {freq:.1f} Hz, peak {peak:.1f} dBFS, rms {rms:.1f} dBFS, {ogg.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

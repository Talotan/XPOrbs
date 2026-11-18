"""Generate the XPOrbs chime sounds: media/chime1.ogg .. chime6.ogg.

The sounds are original: soft bell notes synthesised by this script (a sine plus two quieter, faster-fading overtones),
released under the repo's GPL-3.0-or-later like the rest of the addon.

Six notes on a major pentatonic (C6 D6 E6 G6 A6 C7), each about 0.4 s, mono, 44.1 kHz: a 4 ms attack, then an
exponential decay (time constant 0.12 s) with a short fade to true silence. The peak sits at about -14 dBFS.

Needs ffmpeg with libvorbis on PATH (WAVs are written to a temp dir, then encoded with `-c:a libvorbis -q:a 3`).

Usage: uv run python tools/make_sounds.py [--out media]
"""

import argparse
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RATE = 44100
NOTES = [1046.5, 1174.7, 1318.5, 1568.0, 1760.0, 2093.0]  # C6 D6 E6 G6 A6 C7
LENGTH = 0.40  # seconds
ATTACK = 0.004
TAU = 0.12  # decay time constant of the fundamental (overtone k decays k times faster)
PARTIALS = [(1, 1.0), (2, 0.25), (3, 0.08)]  # (multiple of the fundamental, amplitude)
FADE = 0.03  # raised-cosine fade to zero over the last 30 ms
PEAK_DBFS = -14.0


def synth(freq: float) -> list[int]:
    n = int(RATE * LENGTH)
    fade_n = int(RATE * FADE)
    raw = []
    for i in range(n):
        t = i / RATE
        env = t / ATTACK if t < ATTACK else 1.0
        v = 0.0
        for k, amp in PARTIALS:
            v += amp * math.exp(-t * k / TAU) * math.sin(2 * math.pi * freq * k * t)
        v *= env
        if i >= n - fade_n:
            v *= 0.5 * (1 + math.cos(math.pi * (i - (n - fade_n)) / fade_n))
        raw.append(v)
    raw[-1] = 0.0  # true silence on the last sample
    scale = 10 ** (PEAK_DBFS / 20) / max(abs(v) for v in raw)
    return [round(v * scale * 32767) for v in raw]


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
            write_wav(wav, synth(freq))
            cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libvorbis", "-q:a", "3", str(ogg)]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                print(f"error: ffmpeg failed for {ogg.name} (is libvorbis available?):\n{res.stderr}", file=sys.stderr)
                return 1
            print(f"{ogg.name}: {freq:.1f} Hz, {ogg.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

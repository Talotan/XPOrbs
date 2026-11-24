"""Generate the XPOrbs chime sounds: media/chime/<level>/coin1..6.ogg, glass1..6.ogg and brush1..6.ogg, per volume level.

The sounds are original: three voices synthesised by this script, released under the repo's GPL-3.0-or-later like the
rest of the addon. Each voice is six files, the same sound at six slightly different pitches (a cluster of base
frequencies around a centre, not a musical scale, so the addon can wobble between them).

coin (the default): a soft coin "clink" within about 100 cents of 1.7 kHz. Four closely spaced metallic partials
(ratios 1, 1.52, 2.27, 3.11, the higher ones fading faster), a 1 ms attack with a couple of milliseconds of
filtered-noise click for the strike, a softer second strike 30 ms later (the coin settling), and a copy of the
fundamental detuned by 6 Hz for a faint metallic beat. Fundamental decay time constant 0.07 s, 0.22 s long.

glass: a glassy, icy "tink" within about 150 cents of 3 kHz. Four inharmonic partials (ratios 1, 2.76, 5.40, 8.93, the
higher ones fading much faster), the same short noise click, no second strike, and a copy of the fundamental
detuned by 3.5 Hz for a faint shimmer. Fundamental decay time constant 0.09 s, 0.25 s long.

brush: a soft brushed "shew" at one medium-low pitch, not a tink or a tone. White noise through a resonant 2nd-order
band-pass (RBJ biquad, centre 700 Hz, Q 2.5) whose centre glides down from 1.25x to 0.85x of the pitch over the sound,
plus a little (15 %) wider-band noise (Q 0.7) for air. A 20 ms raised-cosine attack, then an exponential decay (tau
0.06 s), 0.22 s long. All six files share the pitch (at most +-15 cents of jitter); the variety is a different noise
seed per file (SEED + note number). Each file is scaled so its RMS equals the mean RMS of the glass files, because noise
sounds louder than a tink at the same peak.

All are mono, 44.1 kHz and end in true silence. Coin and glass peak at about -26 dBFS at 100 %; brush is matched to
glass by RMS instead (see the printed stats for its peak). The noise uses fixed seeds, so regenerating gives identical
files.

Volume: PlaySoundFile has no volume argument on this client, so every sound is pre-rendered at each level in LEVELS
(percent of the 100 % sound, 100..250 in steps of 25; going quieter than 100 is the game's SFX slider's job) by scaling
the samples before encoding, one folder per level: media/chime/150/glass3.ogg. 250 % stays below -6 dBFS, so nothing
clips. Running the script also deletes the older flat media/coin1..6.ogg, media/glass1..6.ogg and media/chime1..6.ogg,
and any level folder that is no longer in LEVELS (25, 50 and 75).

Needs ffmpeg with libvorbis on PATH (WAVs are written to a temp dir, then encoded with `-c:a libvorbis -q:a 3`).

Usage: uv run python tools/make_sounds.py [--out media]
       uv run python tools/make_sounds.py --candidates DIR
The second form only renders audition WAVs (three brush variants, notes 1 and 2, plus a glass reference, all at
100 %) into DIR and a README.txt; it does not touch media/.
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
LEVELS = range(
    100, 251, 25
)  # volume levels in percent; Core.lua ns.ranges.soundVolume must match
OLD_PATTERNS = (
    "chime[1-6].ogg",
    "coin[1-6].ogg",
    "glass[1-6].ogg",
)  # older layouts, deleted on every run

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
    # noise voice: no partials. CENTRE is the band-pass pitch, SWEEP the (start, end) multiples of it, AIR the level of
    # the wide (Q 0.7) noise, ATTACK a raised-cosine attack. Loudness is matched to RMS_MATCH's mean RMS, not to a peak.
    "brush": {
        "KIND": "noise",
        "CENTRE": 700.0,
        "CENTS": [-14, -8, -3, 4, 9, 14],
        "LENGTH": 0.22,
        "TAU": 0.06,
        "Q": 2.5,
        "SWEEP": (1.25, 0.85),
        "AIR": 0.15,
        "ATTACK": 0.020,
        "RMS_MATCH": "glass",
    },
}

# Brush variants for --candidates (A is the shipped voice); anything not listed comes from VOICES["brush"].
CANDIDATES = {
    "A-soft-swish": {
        "CENTRE": 700.0,
        "Q": 2.5,
        "SWEEP": (1.25, 0.85),
        "TAU": 0.06,
        "LENGTH": 0.22,
    },
    "B-low-whoosh": {
        "CENTRE": 480.0,
        "Q": 3.5,
        "SWEEP": (1.3, 0.8),
        "TAU": 0.08,
        "LENGTH": 0.26,
    },
    "C-airy-shew": {
        "CENTRE": 950.0,
        "Q": 1.6,
        "SWEEP": (1.35, 0.8),
        "TAU": 0.05,
        "LENGTH": 0.20,
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


def _finish(raw: list[float]) -> list[float]:
    """Raised-cosine fade over the last FADE seconds and true silence on the last sample."""
    n = len(raw)
    fade_n = int(RATE * FADE)
    for i in range(n - fade_n, n):
        raw[i] *= 0.5 * (1 + math.cos(math.pi * (i - (n - fade_n)) / fade_n))
    raw[-1] = 0.0
    return raw


def _bandpass(x: float, state: list[float], freq: float, q: float) -> float:
    """One sample through an RBJ band-pass biquad (constant 0 dB peak gain) tuned to freq right now."""
    w0 = 2 * math.pi * freq / RATE
    alpha = math.sin(w0) / (2 * q)
    a0 = 1 + alpha
    b0 = alpha / a0
    a1 = -2 * math.cos(w0) / a0
    a2 = (1 - alpha) / a0
    x1, x2, y1, y2 = state
    y = b0 * x - b0 * x2 - a1 * y1 - a2 * y2
    state[0], state[1], state[2], state[3] = x, x1, y, y1
    return y


def _noise_raw(freq: float, v: dict, seed: int) -> list[float]:
    """The brush: swept band-pass noise (plus a little wide noise) under a soft attack and exponential decay."""
    rng = random.Random(seed)
    n = int(RATE * v["LENGTH"])
    attack_n = int(RATE * v["ATTACK"])
    start, end = v["SWEEP"]
    narrow, wide = [0.0] * 4, [0.0] * 4
    raw = []
    for i in range(n):
        t = i / RATE
        centre = freq * start * (end / start) ** (i / (n - 1))
        x = _bandpass(rng.uniform(-1.0, 1.0), narrow, centre, v["Q"])
        x += v["AIR"] * _bandpass(rng.uniform(-1.0, 1.0), wide, freq, 0.7)
        env = math.exp(-t / v["TAU"])
        if i < attack_n:
            env *= 0.5 * (1 - math.cos(math.pi * i / attack_n))
        raw.append(x * env)
    return _finish(raw)


def _tone_raw(freq: float, v: dict) -> list[float]:
    """The ringing voices (coin, glass): inharmonic partials plus a short noise click per strike."""
    rng = random.Random(SEED)
    n = int(RATE * v["LENGTH"])
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
        raw.append(x)
    return _finish(raw)


def _rms(samples: list[float]) -> float:
    return math.sqrt(sum(x * x for x in samples) / len(samples))


_reference_cache: dict[str, float] = {}


def reference_rms(voice: str) -> float:
    """Mean RMS (full scale = 1.0, at 100 %) of a tonal voice's six files over their whole length; the brush is matched to it."""
    if voice not in _reference_cache:
        v = VOICES[voice]
        values = []
        for freq in notes(voice):
            raw = _tone_raw(freq, v)
            peak = max(abs(x) for x in raw)
            values.append(_rms(raw) / peak * 10 ** (v["PEAK_DBFS"] / 20))
        _reference_cache[voice] = sum(values) / len(values)
    return _reference_cache[voice]


def synth(
    freq: float, voice: str | dict = "coin", level: int = 100, index: int | None = None
) -> list[int]:
    """One sound of a voice as 16-bit samples (deterministic), level percent of the 100 % amplitude.

    voice is a VOICES key (or a voice dict, for --candidates). For the noise voice, index (the 0-based note number)
    picks the noise seed; if omitted it is looked up from freq among the voice's notes (0 if it is not one of them).
    """
    v = VOICES[voice] if isinstance(voice, str) else voice
    if v.get("KIND") == "noise":
        if index is None:
            found = (
                [i for i, f in enumerate(notes(voice)) if f == freq]
                if isinstance(voice, str)
                else []
            )
            index = found[0] if found else 0
        raw = _noise_raw(freq, v, SEED + index)
        scale = reference_rms(v["RMS_MATCH"]) / _rms(raw) * (level / 100)
    else:
        raw = _tone_raw(freq, v)
        scale = 10 ** (v["PEAK_DBFS"] / 20) / max(abs(x) for x in raw) * (level / 100)
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


def remove_stale_levels(out: Path) -> None:
    """Delete media/chime/<level> folders whose level is no longer in LEVELS (25, 50, 75 after the 1.3 range change)."""
    chime_dir = out / "chime"
    if not chime_dir.is_dir():
        return
    keep = {str(level) for level in LEVELS}
    for stale in chime_dir.iterdir():
        if stale.is_dir() and stale.name not in keep:
            shutil.rmtree(stale)
            print(f"removed old level folder {stale.name}")


def render_candidates(out: Path) -> None:
    """Audition renders: note 1 and 2 of each brush variant and one glass note, WAV, 100 %, plus a README.txt."""
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "XP Orbs brush candidates (100 % level, mono 44.1 kHz WAV). Each is band-passed noise whose centre glides down,",
        "matched to the glass voice by RMS. Notes 1 and 2 of each: same pitch, different noise.",
        "",
    ]
    base = VOICES["brush"]
    notes_ = {
        "A-soft-swish": "soft swish (the shipped default)",
        "B-low-whoosh": "low whoosh, longer and darker",
        "C-airy-shew": "airy shew, higher and shorter",
    }
    for name, params in CANDIDATES.items():
        v = {**base, **params}
        for index in (0, 1):
            freq = round(v["CENTRE"] * 2 ** (v["CENTS"][index] / 1200), 1)
            samples = synth(freq, v, 100, index)
            write_wav(out / f"{name}-note{index + 1}.wav", samples)
            peak, rms = stats(samples)
            print(
                f"{name}-note{index + 1}.wav: {freq:.1f} Hz, peak {peak:.1f} dBFS, rms {rms:.1f} dBFS"
            )
        lines.append(
            f"{name}: {notes_[name]}. Centre {v['CENTRE']:.0f} Hz, Q {v['Q']}, sweep {v['SWEEP'][0]}x -> {v['SWEEP'][1]}x, "
            f"tau {v['TAU']} s, length {v['LENGTH']} s."
        )
    samples = synth(notes("glass")[0], "glass", 100)
    write_wav(out / "glass-reference-note1.wav", samples)
    lines += [
        "",
        "glass-reference-note1.wav: the current default voice at 100 %, for loudness comparison.",
    ]
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "media",
        help="output folder (default: media/)",
    )
    ap.add_argument(
        "--candidates",
        type=Path,
        metavar="DIR",
        help="only render the brush audition WAVs (and a README.txt) into DIR",
    )
    args = ap.parse_args()
    if args.candidates:
        render_candidates(args.candidates)
        return 0

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(
            "error: ffmpeg is not on PATH (it needs the libvorbis encoder)",
            file=sys.stderr,
        )
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for pattern in OLD_PATTERNS:
        for old in args.out.glob(pattern):
            old.unlink()
            print(f"removed old {old.name}")
    remove_stale_levels(args.out)
    with tempfile.TemporaryDirectory() as tmp:
        for level in LEVELS:
            level_dir = args.out / "chime" / str(level)
            level_dir.mkdir(parents=True, exist_ok=True)
            for voice in VOICES:
                for i, freq in enumerate(notes(voice), start=1):
                    wav = Path(tmp) / f"{level}-{voice}{i}.wav"
                    ogg = level_dir / f"{voice}{i}.ogg"
                    samples = synth(freq, voice, level, i - 1)
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
                    res = subprocess.run(
                        cmd, capture_output=True, text=True, check=False
                    )
                    if res.returncode != 0:
                        print(
                            f"error: ffmpeg failed for {ogg} (is libvorbis available?):\n{res.stderr}",
                            file=sys.stderr,
                        )
                        return 1
                    peak, rms = stats(samples)
                    print(
                        f"{level}/{ogg.name}: {freq:.1f} Hz, peak {peak:.1f} dBFS, rms {rms:.1f} dBFS, "
                        f"{ogg.stat().st_size} bytes"
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

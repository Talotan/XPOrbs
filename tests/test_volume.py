"""Chime volume: the pre-rendered gain variants (media/chime/<percent>/), the saved setting, the options slider, the
/xporbs sound volume command and the throttled sample."""

import importlib.util
import math
import re
import zipfile

import pytest
from conftest import ROOT
from test_m5 import ctl, show
from test_v013 import reset_shown
from test_v09 import burst, make, restricted_plate
from test_v110 import chime_game, junk_db, last_chat, opts, play, sounds

LEVELS = list(range(100, 251, 25))
VOICES = ("glass", "coin", "swish", "pixel")
CHIME_DIR = ROOT / "media" / "chime"
PATH = re.compile(
    r"Interface\\AddOns\\XPOrbs\\media\\chime\\(\d+)\\(glass|coin|swish|pixel)([1-6])\.ogg"
)


def played(g):
    """(volume, voice, note) of every sound played so far; every path must be a chime path."""
    out = []
    for path, channel in sounds(g):
        found = PATH.fullmatch(path)
        assert found, path
        assert channel == "SFX"
        out.append((int(found.group(1)), found.group(2), int(found.group(3))))
    return out


def volumes(g):
    return [volume for volume, _, _ in played(g)]


# ---------------------------------------------------------------- the files


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("voice", VOICES)
@pytest.mark.parametrize("note", range(1, 7))
def test_every_level_voice_and_note_has_a_small_ogg_file(level, voice, note):
    data = (CHIME_DIR / str(level) / f"{voice}{note}.ogg").read_bytes()
    assert data[:4] == b"OggS" and 1000 < len(data) < 15 * 1024


def test_no_stray_level_folders_or_files():
    assert sorted(p.name for p in CHIME_DIR.iterdir()) == sorted(
        str(level) for level in LEVELS
    )
    for folder in CHIME_DIR.iterdir():
        assert len(list(folder.iterdir())) == 24  # glass, coin, swish, pixel x 6


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        f"xporbs_{name}", ROOT / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generator_scales_the_samples_and_100_is_unchanged():
    mod = load_script("make_sounds")
    assert list(mod.LEVELS) == LEVELS
    freq = mod.notes("glass")[2]
    base = mod.synth(freq, "glass")
    assert mod.synth(freq, "glass", 100) == base

    def peak(samples):
        return max(abs(s) for s in samples)

    assert peak(mod.synth(freq, "glass", 250)) == pytest.approx(2.5 * peak(base), abs=2)
    assert peak(mod.synth(freq, "glass", 150)) == pytest.approx(1.5 * peak(base), abs=2)
    assert (
        mod.stats(mod.synth(freq, "glass", 250))[0] < -17.5
    )  # about -18 dBFS: no clipping


def test_every_voice_has_six_files_and_stays_under_minus_6_dbfs_at_250():
    mod = load_script("make_sounds")
    assert list(mod.VOICES) == ["glass", "coin", "swish", "pixel"]
    for voice in mod.VOICES:
        freqs = mod.notes(voice)
        assert len(freqs) == 6 and len(set(freqs)) == 6
        for i, f in enumerate(freqs):
            samples = mod.synth(f, voice, 250, i)
            assert samples[-1] == 0
            assert mod.stats(samples)[0] < -6, voice


def test_the_zip_ships_the_whole_chime_tree(tmp_path):
    package = load_script("package")
    with zipfile.ZipFile(package.build(tmp_path)) as z:
        names = set(z.namelist())
    for level in LEVELS:
        for voice in VOICES:
            for note in range(1, 7):
                assert f"XPOrbs/media/chime/{level}/{voice}{note}.ogg" in names
    assert not any(
        re.fullmatch(r"XPOrbs/media/(glass|coin|swish|pixel)\d\.ogg", name) for name in names
    )


def test_nothing_references_the_old_flat_files():
    for rel in (
        "Core.lua",
        "Orbs.lua",
        "Options.lua",
        "README.md",
        "tools/package.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"media[\\/](glass|coin|swish|pixel)[1-6N]", text), rel


# ---------------------------------------------------------------- the setting


def test_default_and_range(env):
    env.load_addon()
    assert env.ns.defaults.soundVolume == 100
    r = env.ns.ranges.soundVolume
    assert (r[1], r[2], r[3]) == (100, 250, 25)


@pytest.mark.parametrize(
    "saved,expected",
    [
        (None, 100),
        ("loud", 100),
        (True, 100),
        (float("nan"), 100),
        (0, 100),
        (-40, 100),
        (25, 100),  # the old levels below 100 were dropped
        (50, 100),
        (75, 100),
        (99, 100),
        (9999, 250),
        (125, 125),
        (130, 125),
        (138, 150),
        (251, 250),
    ],
)
def test_sanitize_clamps_and_snaps_the_saved_volume(env, saved, expected):
    db = junk_db(env, soundVolume=saved)
    assert db.soundVolume == expected


# ---------------------------------------------------------------- what plays


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("voice", VOICES)
def test_arrivals_play_the_file_for_the_saved_level_and_voice(env, level, voice):
    g = chime_game(env)
    g.db.soundVolume, g.db.soundVoice = level, voice
    play(g)
    notes = played(g)
    assert notes and all(volume == level and name == voice for volume, name, _ in notes)
    for volume, name, note in notes:
        assert (CHIME_DIR / str(volume) / f"{name}{note}.ogg").is_file()


def test_changing_the_volume_mid_session_takes_effect_on_the_next_burst(env):
    g = chime_game(env)
    g.db.soundVolume = 125
    play(g)
    first = len(played(g))
    g.db.soundVolume = 225
    play(g)
    heard = volumes(g)
    assert first > 0 and set(heard[:first]) == {125} and set(heard[first:]) == {225}


def test_an_off_grid_saved_volume_plays_at_100_instead_of_throwing(env):
    g = chime_game(env)
    g.db.soundVolume = 133  # only reachable by editing the table after load
    play(g)
    assert set(volumes(g)) == {100}
    g.db.soundVolume = "loud"
    play(g)
    assert set(volumes(g)) == {100} and g.orbs.SoundDisabled(g.orbs) is False


MEASURE_LUA = """function(driver, frames, dt)
    -- the stub records every PlaySoundFile call in a table; count instead, so only the addon's own allocations show
    local chimes = 0
    PlaySoundFile = function()
        chimes = chimes + 1
        return true
    end
    local fm = getmetatable(UIParent).__index
    local noop = function() end
    for _, name in ipairs({ "SetPoint", "ClearAllPoints", "SetSize", "SetRotation", "SetVertexColor", "SetTexture",
        "SetBlendMode", "SetDrawLayer" }) do
        fm[name] = noop
    end
    local onUpdate = driver.scripts.OnUpdate
    onUpdate(driver, dt)
    collectgarbage("collect")
    collectgarbage("stop")
    local before = collectgarbage("count")
    for _ = 1, frames do
        onUpdate(driver, dt)
    end
    local after = collectgarbage("count")
    collectgarbage("restart")
    return after - before, chimes
end"""


def measure_frames(g):
    """KB allocated by 300 driver frames over two fresh bursts, and how many chimes played meanwhile."""
    burst(
        g, plate=restricted_plate(g), n=20, x=400, y=300, kind="kill", style="popstream"
    )
    burst(g, n=20, x=600, y=300, kind="kill", style="stream")
    g.tick(0.016, 3)  # warm up: lazily created tables and textures exist now
    return g.env.lua.eval(MEASURE_LUA)(g.orbs.driver, 300, 0.002)


def test_the_driver_allocates_no_more_per_frame_with_the_chime_on(env):
    g = make(env, fixed_random=False, trail=True)
    g.db.flightTime = (
        0.5  # short, so orbs arrive (and chime) inside the measured frames
    )
    g.db.soundVolume = 175
    g.db.sound = False
    quiet_growth, quiet_chimes = measure_frames(g)
    g.tick(0.05, 100)  # let everything land
    g.db.sound = True
    loud_growth, loud_chimes = measure_frames(g)
    assert (
        quiet_chimes == 0 and loud_chimes > 0
    )  # arrivals chimed in the second run only
    assert (
        loud_growth <= quiet_growth + 1
    )  # the chime path adds nothing (KB, over 300 frames)


# ---------------------------------------------------------------- /xporbs sound volume


def test_volume_command_sets_clamps_snaps_prints_and_plays_a_sample(env):
    g = chime_game(env)
    n0 = len(g.stub.sounds)
    g.slash("sound volume 150")
    assert g.db.soundVolume == 150 and "volume 150%" in last_chat(g)
    assert len(g.stub.sounds) == n0 + 1 and volumes(g)[-1] == 150
    g.slash("sound volume 130%")
    assert g.db.soundVolume == 125 and "volume 125%" in last_chat(g)
    g.slash("sound volume 9999")
    assert g.db.soundVolume == 250
    g.slash("sound volume 1")
    assert g.db.soundVolume == 100 and volumes(g)[-1] == 100
    g.slash("sound volume 40")  # the removed levels clamp up to 100
    assert g.db.soundVolume == 100


def test_volume_command_rejects_junk_and_keeps_the_value(env):
    g = chime_game(env)
    g.db.soundVolume = 175
    n0 = len(g.stub.sounds)
    for junk in ("sound volume", "sound volume loud", "sound volume nan"):
        g.slash(junk)
        assert "volume needs a number" in last_chat(g)
    assert g.db.soundVolume == 175 and len(g.stub.sounds) == n0


def test_volume_command_is_silent_with_the_chime_off(env):
    g = chime_game(env)
    g.db.sound = False
    g.slash("sound volume 200")
    assert g.db.soundVolume == 200 and len(g.stub.sounds) == 0


def test_sound_status_shows_the_volume(env):
    g = chime_game(env)
    g.slash("sound")
    assert "chime: on, glass, volume 100%" in last_chat(g)
    g.db.soundVolume = 225
    g.slash("sound")
    assert "volume 225%" in last_chat(g)


def test_help_text_and_readme_mention_the_volume_command(env):
    g = chime_game(env)
    g.slash("sound nonsense")
    assert "volume N" in last_chat(g)
    assert "sound volume" in (ROOT / "README.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- options panel


def test_slider_uses_the_shared_range_and_sits_under_the_sound_row(env):
    m = opts(env)
    show(m)
    s = ctl(m, "soundVolume")
    assert (s.minV, s.maxV, s.step) == (100, 250, 25)
    assert str(m.opt.valueTexts["soundVolume"].text) == "100%"
    row, voice_row = m.opt.rows["soundVolume"], m.opt.rows["soundVoice"]
    assert row.points[1][5] == voice_row.points[1][5] - 28
    assert "100, 250, 25" not in (ROOT / "Options.lua").read_text(encoding="utf-8")


def test_slider_writes_the_db_and_shows_the_percent(env):
    m = opts(env)
    show(m)
    m.stub.slide(ctl(m, "soundVolume"), 150)
    assert m.db.soundVolume == 150
    assert str(m.opt.valueTexts["soundVolume"].text) == "150%"
    m.stub.slide(ctl(m, "soundVolume"), 236)  # snaps to the step
    assert m.db.soundVolume == 225


def test_reset_button_puts_it_back_to_100(env):
    m = opts(env)
    show(m)
    assert not reset_shown(m, "soundVolume")
    m.stub.slide(ctl(m, "soundVolume"), 200)
    assert reset_shown(m, "soundVolume")
    m.stub.hover(m.opt.resets["soundVolume"])
    assert m.stub.tooltip.text == "Reset to default: 100%"
    m.stub.click(m.opt.resets["soundVolume"])
    assert m.db.soundVolume == 100 and ctl(m, "soundVolume").value == 100
    assert not reset_shown(m, "soundVolume")


def test_the_row_dims_with_the_chime_off_but_stays_usable(env):
    m = opts(env)
    show(m)
    row, s = m.opt.rows["soundVolume"], ctl(m, "soundVolume")
    assert m.db.sound is False
    assert row.alpha == pytest.approx(0.4) and s.IsEnabled(s)
    m.stub.slide(s, 175)
    assert m.db.soundVolume == 175  # still works while dimmed
    m.stub.click(ctl(m, "sound"))
    assert m.db.sound is True and row.alpha == 1 and s.IsEnabled(s)
    m.stub.click(ctl(m, "sound"))
    assert row.alpha == pytest.approx(0.4)


def test_the_rows_below_moved_down_by_the_slider_row_and_the_content_grew(env):
    m = opts(env)
    show(m)
    assert m.opt.rows["soundVolume"].points[1][5] == -270
    assert m.opt.rows["debug"].points[1][5] == -1378
    assert m.opt.CONTENT_H == m.opt.child.height == 1422


def test_dragging_plays_one_sample_at_the_new_volume_at_most_every_150_ms(env):
    m = opts(env)
    show(m)
    assert len(m.stub.sounds) == 0  # opening the panel is silent
    s = ctl(m, "soundVolume")
    m.stub.slide(s, 150)
    assert volumes(m) == [150]
    m.stub.slide(s, 175)  # same instant: throttled
    m.stub.tick(0.1)
    m.stub.slide(s, 200)  # 0.1 s since the last sample: still throttled
    assert (
        volumes(m) == [150] and m.db.soundVolume == 200
    )  # the value is stored regardless
    m.stub.tick(0.06)
    m.stub.slide(s, 225)  # 0.16 s: plays
    assert volumes(m) == [150, 225]


def test_reset_does_not_play_a_sample(env):
    m = opts(env)
    show(m)
    m.stub.slide(ctl(m, "soundVolume"), 200)
    m.stub.tick(1)
    n0 = len(m.stub.sounds)
    m.stub.click(m.opt.resets["soundVolume"])
    assert len(m.stub.sounds) == n0


def test_a_failing_playsoundfile_during_a_drag_does_not_throw(env):
    m = opts(env)
    show(m)
    m.stub.soundMode = "error"
    m.stub.slide(ctl(m, "soundVolume"), 150)
    assert m.db.soundVolume == 150


def test_picking_a_voice_previews_at_the_current_volume(env):
    m = opts(env)
    m.db.soundVolume = 200
    show(m)
    m.stub.pickMenu(m.opt.soundDropdown, "Coin")
    heard = played(m)
    assert len(heard) == 1 and heard[0][:2] == (200, "coin")


# ---------------------------------------------------------------- the swish voice


def test_swish_is_deterministic_rms_is_glass_plus_gain_and_never_clips():
    mod = load_script("make_sounds")
    glass = [mod.stats(mod.synth(f, "glass"))[1] for f in mod.notes("glass")]
    glass_rms = sum(10 ** (r / 20) for r in glass) / len(glass)
    freqs = mod.notes("swish")
    assert len(freqs) == 6 and all(
        abs(1200 * math.log2(f / mod.VOICES["swish"]["CENTRE"])) <= 15 for f in freqs
    )
    runs = [mod.synth(f, "swish", 100) for f in freqs]
    assert runs == [
        mod.synth(f, "swish", 100) for f in freqs
    ]  # same seed, same samples
    assert len({tuple(r) for r in runs}) == 6  # a different noise seed per note
    for samples in runs:
        assert samples[-1] == 0 and len(samples) == int(
            mod.RATE * mod.VOICES["swish"]["LENGTH"]
        )
        # RMS-matched to glass, then GAIN (2.0 = +6.02 dB, a test level: the owner found swish quieter in game)
        assert mod.VOICES["swish"]["GAIN"] == 2.0
        assert 20 * math.log10(
            10 ** (mod.stats(samples)[1] / 20) / glass_rms
        ) == pytest.approx(6.02, abs=0.1)
    for i, f in enumerate(freqs):
        assert mod.stats(mod.synth(f, "swish", 250, i))[0] < -6


def test_swish_is_a_swept_band_of_noise_not_a_tone():
    mod = load_script("make_sounds")
    samples = mod.synth(mod.notes("swish")[0], "swish")
    assert max(abs(s) for s in samples[:20]) < 0.1 * max(abs(s) for s in samples)
    # the noise is not periodic: the autocorrelation at any lag past the filter's memory stays small
    n = len(samples) // 2
    energy = sum(s * s for s in samples[:n])
    for lag in (200, 333, 701):
        corr = sum(samples[i] * samples[i + lag] for i in range(n))
        assert abs(corr) < 0.5 * energy


def _onset_ms(samples, frac=0.5, window=88):
    """Time (ms) at which the 2 ms RMS first reaches frac of its maximum."""
    rms = [
        math.sqrt(sum(x * x for x in samples[i : i + window]) / window)
        for i in range(0, len(samples) - window, 22)
    ]
    top = max(rms)
    return next(k for k, r in enumerate(rms) if r >= frac * top) * 22 / 44100 * 1000


def test_swish_onset_is_soft_34ms_raised_cosine_and_softer_than_the_old_hit():
    mod = load_script("make_sounds")
    v = mod.VOICES["swish"]
    assert v["ATTACK"] == 0.034 and v["LENGTH"] == 0.26 and v["AIR"] < 0.15
    old = {**v, **mod.CANDIDATES["swish-original"][1]}  # the 20 ms, air 0.15 voice
    for i, f in enumerate(mod.notes("swish")):
        samples = mod.synth(f, "swish", 100, i)
        peak = max(abs(x) for x in samples)
        # the raised cosine starts from silence: the first 1 ms is far below the peak
        assert max(abs(x) for x in samples[: mod.RATE // 1000]) < 0.1 * peak
        assert samples.index(max(samples, key=abs)) > int(mod.RATE * v["ATTACK"]) // 4
    # the noise makes single notes vary a little, so compare the mean over the six notes: half of the peak level
    # arrives no earlier than 15 ms in, and later than for the 20 ms original
    soft = [
        _onset_ms(mod.synth(f, "swish", 100, i))
        for i, f in enumerate(mod.notes("swish"))
    ]
    hard = [
        _onset_ms(mod.synth(f, old, 100, i)) for i, f in enumerate(mod.notes("swish"))
    ]
    assert sum(soft) / 6 >= 15
    assert sum(soft) / 6 > sum(hard) / 6 + 1


def test_stale_level_folders_are_removed(tmp_path):
    mod = load_script("make_sounds")
    for stale in ("25", "50", "75"):
        (tmp_path / "chime" / stale).mkdir(parents=True)
        (tmp_path / "chime" / stale / "glass1.ogg").write_bytes(b"x")
    (tmp_path / "chime" / "100").mkdir()
    mod.remove_stale_levels(tmp_path)
    assert (tmp_path / "chime" / "100").is_dir()
    assert not any((tmp_path / "chime" / s).exists() for s in ("25", "50", "75"))


# ---------------------------------------------------------------- coin and pixel voices


def _goertzel_power(samples, freq):
    w = 2 * math.pi * freq / 44100
    c = 2 * math.cos(w)
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + c * s1 - s2, s1
    return s1 * s1 + s2 * s2 - c * s1 * s2


def _centroid(samples, step=250, top=20000):
    freqs = range(step, top + 1, step)
    power = [_goertzel_power(samples, f) for f in freqs]
    return sum(f * p for f, p in zip(freqs, power)) / sum(power)


def test_coin_is_the_soft_clink_synthesis_and_files_are_deterministic():
    mod = load_script("make_sounds")
    v = mod.VOICES["coin"]
    assert (v["CENTRE"], v["LENGTH"], v["TAU"], v["PEAK_DBFS"]) == (
        1700.0,
        0.22,
        0.07,
        -26.0,
    )
    assert mod.notes("coin")[0] == 1613.9
    for voice in ("coin", "pixel"):
        f = mod.notes(voice)[1]
        assert mod.synth(f, voice, 100, 1) == mod.synth(f, voice, 100, 1)


def test_pixel_notes_are_pentatonic_stepped_band_limited_and_rms_matched():
    mod = load_script("make_sounds")
    v = mod.VOICES["pixel"]
    pentatonic = {0, 2, 4, 7, 9}  # C D E G A, semitones above C
    freqs = mod.notes("pixel")
    assert len(set(freqs)) == 6 and 750 < min(freqs) and max(freqs) < 1800

    def pitch_class(f):
        return round(12 * math.log2(f / 440) + 9) % 12  # A4 = 440 is 9 above C

    for f, ratio in zip(freqs, v["STEP_RATIOS"]):
        assert pitch_class(f) in pentatonic
        assert ratio in (4 / 3, 3 / 2) and pitch_class(f * ratio) in pentatonic
    assert v["DUTY"] == 0.25 and v["LEVELS"] == 16 and 0.22 <= v["LENGTH"] <= 0.28
    glass = [
        10 ** (mod.stats(mod.synth(f, "glass"))[1] / 20) for f in mod.notes("glass")
    ]
    glass_rms = sum(glass) / len(glass)
    for i, f in enumerate(freqs):
        s = mod.synth(f, "pixel", 100, i)
        assert s[-1] == 0 and len(s) == int(mod.RATE * v["LENGTH"])
        assert 10 ** (mod.stats(s)[1] / 20) == pytest.approx(glass_rms, rel=0.02)
    s = mod.synth(freqs[1], "pixel", 100, 1)
    # stepped envelope: at most 16 distinct levels (peaks of each 0.5 ms block), not a smooth decay
    blocks = {
        round(max(abs(x) for x in s[j : j + 22]) / max(abs(x) for x in s) * 15)
        for j in range(0, len(s) - 22, 22)
    }
    assert len(blocks) <= 17
    # the pitch steps up after STEP_S: the fundamental moves from f to f * ratio
    early = s[int(mod.RATE * 0.01) : int(mod.RATE * 0.045)]
    late = s[int(mod.RATE * 0.06) : int(mod.RATE * 0.095)]
    r = v["STEP_RATIOS"][1]
    assert _goertzel_power(early, freqs[1]) > 3 * _goertzel_power(early, freqs[1] * r)
    assert _goertzel_power(late, freqs[1] * r) > 3 * _goertzel_power(late, freqs[1])
    # band-limited: next to nothing above 18 kHz (no aliasing spikes folded down from past Nyquist)
    total = sum(_goertzel_power(s, f) for f in range(250, 22001, 250))
    high = sum(_goertzel_power(s, f) for f in range(18500, 22001, 250))
    assert high / total < 0.002

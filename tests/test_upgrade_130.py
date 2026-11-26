"""The upgrade from the released 1.3.0: a full SavedVariables table (schema 6, no per-shape look, no flight speed) is
loaded and the whole 1.4.0 outcome is checked."""

from test_shape_look import active, look_of, reload_db
from test_v102 import load_db

SAVE_130 = {
    "version": 6,
    "enabled": True,
    "density": 400,
    "cap": 30,
    "size": 20,
    "flightTime": 0.6,
    "color": {1: 0.1, 2: 0.9, 3: 0.4},
    "classColor": True,
    "restedTint": False,
    "restedColor": {1: 0.9, 2: 0.2, 3: 0.2},
    "trail": False,
    "questBursts": False,
    "exploreBursts": False,
    "targetFrame": "PlayerFrame",
    "showAtMax": True,
    "sound": False,
    "soundVoice": "coin",
    "soundVolume": 25,
    "debug": True,
    "unknownOrigin": "off",
    "zoomSpread": False,
    "style": "crossfade",
    "popMode": "direct",
    "flightPath": "helix",
    "glow": False,
    "glowShape": "round",
    "glowIntensity": 150,
    "glowOffsetX": 7,
    "glowOffsetY": -5,
    "setupDismissed": True,
    "minimap": {"hide": False, "minimapPos": 123},
    "zoomAnchor": False,
    "zoomA": 12,
    "zoomB": 200,
    "zoomMin": 3,
    "zoomPoints": {1: {"z": 5, "off": 30}, 2: {"z": 10, "off": 22}},
    "log": {1: "an old log line"},
}


def test_a_full_130_save_upgrades_to_the_140_shape(env):
    db = load_db(env, SAVE_130)
    assert db.version == 7 and db.lookRev is None
    assert db.orbShape == "starlight"
    star = db.shapeLook.starlight
    assert (star.size, star.density, star.opacity, star.blend) == (20, 300, 100, "natural")
    assert active(db) == (20, 300, 100)
    assert (db.size, db.density) == (star.size, star.density)
    assert look_of(db, "retro") == (2, 100, 100)
    for shape in ("bubble", "crackle"):
        assert look_of(db, shape) == (14, 100, 100)
    # flight: Relative speed (time mode) is the default; the saved time becomes the equivalent speed (100 / 0.6, snapped
    # to 10) for when the player switches to Constant speed, and the time itself is kept
    assert db.flightMode == "time" and db.flightSpeed == 170
    assert db.flightTime == 0.6
    assert db.sound is False and db.soundVoice == "coin" and db.soundVolume == 100
    assert db.flightPath == "helix"
    assert db.minimap.minimapPos == 123
    assert db.targetFrame == "PlayerFrame" and db.style == "crossfade" and db.popMode == "direct"
    assert db.glowShape == "round" and db.glowOffsetX == 7 and db.debug is True


def test_reset_after_the_upgrade_keeps_the_minimap_position(env):
    db = load_db(env, SAVE_130)
    env.G.SlashCmdList.XPORBS("reset")
    assert db.minimap.minimapPos == 123
    assert db.size == 14 and db.density == 100 and db.orbShape == "starlight"
    assert look_of(db, "starlight") == (14, 100, 100)
    assert db.version == 7 and db.lookRev is None


def test_the_upgrade_runs_once(env):
    db = load_db(env, SAVE_130)
    db.shapeLook.starlight.size = 9  # the player changes it
    db = reload_db(env)
    assert db.shapeLook.starlight.size == 9 and db.size == 9
    assert db.shapeLook.starlight.density == 300

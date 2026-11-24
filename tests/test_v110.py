"""1.1.0: XP-bar colours, max-level kill orbs to the portrait, the optional chime."""

import importlib.util
import math
import re
import zipfile

import pytest
from conftest import ROOT, lua_list
from test_m5 import show
from test_v09 import burst, make, pop_textures, set_level

PURPLE = (0.72, 0.28, 1.00)  # default normal orb
BLUE = (0.15, 0.38, 1.00)  # default rested orb
UNDER_PURPLE = tuple(round(0.25 * c, 4) for c in PURPLE)
UNDER_BLUE = tuple(round(0.25 * c, 4) for c in BLUE)
SOUNDS = ROOT / "media"
CHIME_PATH = re.compile(
    r"Interface\\AddOns\\XPOrbs\\media\\chime\\\d+\\(coin|glass|brush)([1-6])\.ogg"
)


def rgb(c):
    return tuple(c[i] for i in (1, 2, 3))


def vc(tex):
    return tuple(tex.calls["SetVertexColor"][i] for i in (1, 2, 3))


def is_under(tex):
    return (
        bool(tex.calls)
        and "SetBlendMode" in tex.calls
        and tex.calls["SetBlendMode"][1] == "BLEND"
    )


def tex_list(g):
    return [f for f in g.stub.frames.values() if f.kind == "Texture"]


def underlays(g, pool=None):
    texs = pop_textures(g) if pool == "pop" else tex_list(g)
    return {tuple(round(c, 4) for c in vc(t)) for t in texs if is_under(t)}


def flash_of(g):
    """The first texture the overlay creates is the arrival flash."""
    same = g.env.lua.eval("rawequal")
    for f in tex_list(g):
        if f.parentFrame is not None and same(f.parentFrame, g.orbs.overlay):
            return f
    raise AssertionError("no flash texture")


def run_until_flash(g, limit=4.0):
    fl, t = flash_of(g), 0.0
    while t < limit:
        g.stub.tick(0.01)
        t += 0.01
        if fl.shown:
            return fl
    return None


def sounds(g):
    return [
        (str(g.stub.sounds[i][1]), str(g.stub.sounds[i][2]))
        for i in range(1, len(g.stub.sounds) + 1)
    ]


def last_chat(g):
    return str(g.stub.chat[len(g.stub.chat)])


def count_calls(g, name):
    """Wraps ns.<name> in a call counter; returns the counter table."""
    return g.env.lua.eval(
        """function(ns, name)
            local base = ns[name]
            local n = { calls = 0 }
            ns[name] = function(...) n.calls = n.calls + 1; return base(...) end
            return n
        end"""
    )(g.ns, name)


# ---------------------------------------------------------------- 1. colours


def test_new_default_colours_and_flight_time(env):
    env.load_addon()
    d = env.ns.defaults
    assert rgb(d.color) == PURPLE and rgb(d.restedColor) == BLUE
    assert d.flightTime == 1.0 and d.sound is False and d.soundVoice == "glass"
    assert (env.ns.ranges.flightTime[1], env.ns.ranges.flightTime[2]) == (
        0.4,
        1.5,
    )  # the slider range is unchanged


def test_stream_underlay_is_a_dark_tint_of_each_orbs_own_colour(env):
    g = make(env)
    burst(g, x=300, y=600, n=2, nPurple=1, kind="kill", style="stream")
    assert underlays(g) == {UNDER_PURPLE, UNDER_BLUE}


def test_class_colour_underlay_follows_the_class_colour(env):
    g = make(env)
    g.db.classColor = True
    g.env.lua.execute("UnitClass = function() return 'Paladin', 'PALADIN' end")
    g.env.lua.execute(
        "C_ClassColor = { GetClassColor = function() return { r = 0.96, g = 0.55, b = 0.73 } end }"
    )
    burst(g, x=300, y=600, n=1, kind="kill", style="stream")
    assert underlays(g) == {
        (round(0.96 * 0.25, 4), round(0.55 * 0.25, 4), round(0.73 * 0.25, 4))
    }


def test_pop_underlay_is_a_dark_tint_of_each_orbs_own_colour(env):
    g = make(env)
    plate = g.stub.addRestrictedPlate(
        "nameplate1", g.env.lua.table_from({"cx": 700, "cy": 400})
    )
    assert (
        burst(g, plate=plate, n=4, nPurple=2, x=300, y=300, kind="kill") == "pop+stream"
    )
    assert underlays(g, "pop") == {UNDER_PURPLE, UNDER_BLUE}


def test_crossfade_underlay_is_a_dark_tint_of_each_orbs_own_colour(env):
    g = make(env)
    plate = g.stub.addRestrictedPlate(
        "nameplate1", g.env.lua.table_from({"cx": 700, "cy": 400})
    )
    assert (
        burst(
            g, plate=plate, n=4, nPurple=2, x=300, y=300, kind="kill", style="crossfade"
        )
        == "crossfade"
    )
    g.stub.tick(0.01)
    assert underlays(g, "pop") == {
        UNDER_PURPLE,
        UNDER_BLUE,
    }  # copy A, on the plate-anchored frame
    assert underlays(g) == {UNDER_PURPLE, UNDER_BLUE}  # and copy B in screen space


def test_no_hardcoded_navy_underlay_left():
    src = (ROOT / "Orbs.lua").read_text(encoding="utf-8")
    assert "UNDER_R" not in src and "0.02, 0.08, 0.30" not in src


def test_no_colour_word_in_the_toc_notes_or_option_text():
    toc = (ROOT / "XPOrbs.toc").read_text(encoding="utf-8")
    notes = re.search(r"^## Notes:(.*)$", toc, re.MULTILINE).group(1).lower()
    assert not any(w in notes for w in ("blue", "purple", "magenta", "violet"))
    opts = (ROOT / "Options.lua").read_text(encoding="utf-8").lower()
    assert "blue orb" not in opts and "purple orb" not in opts


# ---------------------------------------------------------------- 4. max level: kill bursts to the portrait


def arena(env, probe=True, show=True, level=(70, 70)):
    """A game at max level (by default) with showAtMax on."""
    g = make(env, probe=probe)
    g.db.showAtMax = show
    set_level(g, *level)
    return g


def engage_target(g, guid="G1", unit="nameplate1"):
    """A hostile plate that is also the current target."""
    g.plate(unit, guid=guid, name="Boar", cx=300, cy=200)
    g.stub.units["target"] = g.env.lua.table_from({"guid": guid})
    g.ns.fire("PLAYER_TARGET_CHANGED")
    g.tick(0.05)


def die(g, guid="G1", unit="nameplate1", via="unit_died"):
    if via == "unit_died":
        g.ns.fire("UNIT_DIED", guid)
    else:
        g.stub.removePlate(unit, True)
    g.tick(0.1)


def engaged_count(g):
    return g.ns.Kills.engaged.Count(g.ns.Kills.engaged)


def test_engaged_target_death_gives_one_six_orb_burst(env):
    g = arena(env)
    engage_target(g)
    die(g)
    (b,) = g.bursts()
    assert b["n"] == 6 and b["scale"] == 1 and b["nPurple"] == 0 and b["kind"] == "kill"
    assert g.has_log(
        "BURST tier=1 kind=maxlevel amount=0 rested=nil origin=estimate plate=yes"
    )
    s = g.stats()
    assert s["dropped"] == 0 and s["tier1"] == 0
    assert g.ns.Kills.matcher.Pending(g.ns.Kills.matcher) == 0


def test_tier2_removal_while_dead_also_triggers_it(env):
    g = arena(env)
    engage_target(g)
    die(g, via="removed")
    (b,) = g.bursts()
    assert b["n"] == 6
    assert g.has_log("BURST tier=2 kind=maxlevel amount=0")


def test_the_burst_never_waits_for_xp(env):
    g = arena(env)
    engage_target(g)
    die(g)
    g.tick(3.0, 3)
    assert len(g.bursts()) == 1 and g.stats()["dropped"] == 0
    assert not g.ns.Kills.PollActive(g.ns.Kills)


def test_it_uses_the_normal_estimate_and_pop_logic(env):
    g = arena(env)
    engage_target(g)
    die(g)
    (b,) = g.bursts()
    assert b["plate"] is not None  # the dead mob's plate: a pop, like any kill
    assert (b["x"], b["y"]) == (960, 626.4)  # no mouseover sample: the default estimate


def test_unengaged_death_gives_nothing(env):
    g = arena(env)
    g.plate(
        "nameplate1", guid="G1", name="Boar", cx=300, cy=200
    )  # never targeted, no threat
    g.tick(0.05)
    die(g)
    assert g.bursts() == []
    assert not g.has_log("kind=maxlevel")
    assert (
        g.ns.Kills.matcher.Pending(g.ns.Kills.matcher) == 0
    )  # nothing is queued for XP that never comes


def test_a_different_target_is_not_the_dead_mob(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G2"})
    g.ns.fire("PLAYER_TARGET_CHANGED")
    g.tick(0.05)
    die(g)
    assert g.bursts() == []


def test_option_off_gives_nothing(env):
    g = arena(env, show=False)
    engage_target(g)
    die(g)
    assert g.bursts() == [] and not g.has_log("kind=maxlevel")


def test_option_off_does_not_feed_the_engaged_set(env):
    g = arena(env, show=False)
    engage_target(g)
    assert engaged_count(g) == 0


def test_below_max_level_nothing_changes(env):
    g = arena(env, level=(60, 70))
    engage_target(g)
    die(g)
    assert g.bursts() == []  # waits for XP like before
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert b["n"] == 14 and b["kind"] == "kill"
    assert g.has_log("BURST tier=1 kind=kill amount=50") and not g.has_log(
        "kind=maxlevel"
    )


def test_max_level_with_the_option_off_keeps_the_levelling_gain_burst(env):
    # 1.0.2 behaviour: the gain that reaches max level still bursts through the matcher
    g = arena(env, show=False)
    g.plate(guid="G1", name="Boar", cx=1, cy=1)
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "G1")
    g.chat()
    g.tick(0.1)
    (b,) = g.bursts()
    assert b["n"] == 14


def test_a_long_fight_outlives_the_engaged_window_while_it_is_the_target(env):
    g = arena(env)
    engage_target(g)
    g.tick(1.0, 15)  # 15 s in: the target mark is older than the 10 s window
    assert not g.ns.Kills.engaged.IsEngaged(g.ns.Kills.engaged, "G1")
    die(g)
    assert len(g.bursts()) == 1  # but it is still the hostile target when it dies


def test_threat_update_on_a_nameplate_marks_the_unit(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.stub.units["nameplate1"]["threat"] = 0  # on the threat list, not tanking
    g.ns.fire("UNIT_THREAT_LIST_UPDATE", "nameplate1")
    g.tick(0.05)
    assert g.ns.Kills.engaged.IsEngaged(g.ns.Kills.engaged, "G1")
    die(g)
    assert len(g.bursts()) == 1


def test_a_threat_mark_expires_after_ten_seconds(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.stub.units["nameplate1"]["threat"] = 1
    g.ns.fire("UNIT_THREAT_LIST_UPDATE", "nameplate1")
    g.tick(1.0, 11)
    die(g)
    assert g.bursts() == []


def test_not_on_the_threat_list_does_not_mark(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)  # threat nil
    g.ns.fire("UNIT_THREAT_LIST_UPDATE", "nameplate1")
    assert engaged_count(g) == 0


def test_secret_threat_value_does_not_mark(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.stub.units["nameplate1"]["threat"] = g.stub.SECRET
    g.ns.fire("UNIT_THREAT_LIST_UPDATE", "nameplate1")
    assert engaged_count(g) == 0
    die(g)
    assert g.bursts() == [] and not g.has_log("error")


def test_threat_updates_for_non_nameplate_units_are_ignored(env):
    g = arena(env)
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "threat": 3})
    for unit in ("target", "party1target"):
        g.ns.fire("UNIT_THREAT_LIST_UPDATE", unit)
    g.ns.fire("UNIT_THREAT_LIST_UPDATE")
    assert engaged_count(g) == 0


def test_secret_target_guid_does_not_mark(env):
    g = arena(env)
    g.stub.units["target"] = g.env.lua.table_from({"guid": g.stub.SECRET})
    g.ns.fire("PLAYER_TARGET_CHANGED")
    assert engaged_count(g) == 0 and not g.has_log("error")


def test_friendly_target_does_not_mark(env):
    g = arena(env)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "canAttack": False})
    g.ns.fire("PLAYER_TARGET_CHANGED")
    assert engaged_count(g) == 0


def test_unreadable_can_attack_does_not_mark(env):
    g = arena(env)
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1"})
    g.stub.units["target"]["canAttack"] = g.stub.SECRET
    g.ns.fire("PLAYER_TARGET_CHANGED")
    assert engaged_count(g) == 0


def test_throwing_apis_never_throw(env):
    g = arena(env)
    g.env.lua.execute(
        "UnitCanAttack = function() error('x') end; UnitThreatSituation = function() error('x') end;"
        " UnitGUID = function() error('x') end"
    )
    g.plate("nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.ns.fire("PLAYER_TARGET_CHANGED")
    g.ns.fire("UNIT_THREAT_LIST_UPDATE", "nameplate1")
    die(g)
    assert g.bursts() == [] and not g.has_log("Kills error")


def test_events_are_registered(env):
    g = arena(env)
    events = g.ns.Kills.frame.events
    assert events["PLAYER_TARGET_CHANGED"] and events["UNIT_THREAT_LIST_UPDATE"]
    assert g.ns.Kills.threatRegistered is True


def test_a_refused_threat_event_is_tolerated(env):
    from test_plates_stub import Game

    Game(
        env,
        pre=lambda stub: stub.failEvents.__setitem__("UNIT_THREAT_LIST_UPDATE", True),
    )
    assert env.ns.Kills.threatRegistered is False  # the target feeder still works


def test_no_guid_or_name_reaches_the_log(env):
    g = arena(env)
    engage_target(g)
    die(g)
    assert not any("G1" in line or "Boar" in line for line in g.log())


# ---- destination: the portrait


def test_portrait_mode_follows_max_level_and_the_users_pick(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    assert T.PortraitMode(T) is True
    g.db.targetFrame = ""
    assert T.PortraitMode(T) is True
    g.db.targetFrame = "MyBar"
    assert T.PortraitMode(T) is False  # a pick always wins
    g.db.targetFrame = None
    set_level(g, 60, 70)
    assert T.PortraitMode(T) is False
    g.env.lua.execute("UnitLevel = function() error('x') end")
    assert T.PortraitMode(T) is False


def test_destination_prefers_the_player_portrait_centre(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    g.stub.setPlayerPortrait(500, 300)
    x, y, ok = T.GetDestination(T, False, True)
    assert (x, y, ok) == (500, 300, True)
    assert T.lastName == "PlayerPortrait" and (T.lastW, T.lastH) == (60, 60)


def test_destination_applies_the_glow_offset(env):
    g = arena(env, probe=False)
    g.stub.setPlayerPortrait(500, 300)
    g.db.glowOffsetX, g.db.glowOffsetY = 10, -5
    x, y, _ = g.ns.Target.GetDestination(g.ns.Target, False, True)
    assert (x, y) == (510, 295)


def test_destination_falls_back_through_the_portrait_candidates(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    g.stub.setPlayerPortrait(500, 300)
    g.env.G.PlayerFrame.PlayerFrameContainer = (
        None  # no container field: the PlayerPortrait global
    )
    g.stub.makeBar("PlayerPortrait", 570, 70, 40, 40, True)
    assert tuple(T.GetDestination(T, False, True))[:2] == (590, 90)
    g.env.G.PlayerPortrait = None  # no global either: the PlayerFrame itself
    assert tuple(T.GetDestination(T, False, True))[:2] == (500, 300)


def test_a_hidden_portrait_is_skipped(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    g.stub.setPlayerPortrait(500, 300, False)
    g.env.G.PlayerFrame.shown = True  # the frame is visible, its portrait is not
    assert tuple(T.GetDestination(T, False, True))[:2] == (
        500,
        300,
    )  # PlayerFrame centre (200 x 80 at 400, 260)
    assert T.lastW == 200


def test_destination_without_any_portrait_uses_the_bar(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    g.env.G.PlayerFrame = None
    x, y, ok = T.GetDestination(T, False, True)
    assert ok is True and T.lastName == "MainStatusTrackingBarContainer"


def test_a_throwing_portrait_walk_falls_back(env):
    g = arena(env, probe=False)
    T = g.ns.Target
    g.env.lua.execute(
        "PlayerFrame = setmetatable({}, { __index = function() error('boom') end })"
    )
    x, y, ok = T.GetDestination(T, False, True)
    assert ok is True and T.lastName == "MainStatusTrackingBarContainer"


def test_get_destination_decides_portrait_mode_itself_when_not_told(env):
    g = arena(env, probe=False)
    g.stub.setPlayerPortrait(500, 300)
    T = g.ns.Target
    assert tuple(T.GetDestination(T))[:2] == (
        500,
        300,
    )  # status and other callers pass nothing
    set_level(g, 60, 70)
    assert tuple(T.GetDestination(T))[:2] != (500, 300)


def test_kill_orbs_fly_to_the_portrait_with_a_round_flash(env):
    g = arena(env, probe=False)
    g.db.style = "stream"
    assert g.db.glowShape == "bar"  # whatever the shape setting says
    g.stub.setPlayerPortrait(500, 300)
    engage_target(g)
    die(g)
    active, in_use, _, _ = g.orbs.Info(g.orbs)
    assert active and in_use == 6 * 3  # six orbs (underlay, orb, sparkle)
    fl = run_until_flash(g)
    assert fl is not None
    pt = fl.points[1]
    assert (pt[1], pt[4], pt[5]) == ("CENTER", 500, 300)
    tex = str(fl.calls["SetTexture"][1])
    assert "orb" in tex and "flash" not in tex  # the round gradient, not the bar flash
    assert fl.width == fl.height  # a circle, not the 7:1 bar flash
    g.tick(0.1, 30)
    assert g.orbs.driver.scripts.OnUpdate is None and g.orbs.Info(g.orbs)[1] == 0


def test_user_pick_overrides_the_portrait(env):
    g = arena(env, probe=False)
    g.db.style = "stream"
    g.stub.setPlayerPortrait(500, 300)
    g.stub.makeBar("MyBar", 100, 700, 90, 90, True)
    g.db.targetFrame = "MyBar"
    g.db.glowShape = "round"
    engage_target(g)
    die(g)
    fl = run_until_flash(g)
    pt = fl.points[1]
    assert (pt[4], pt[5]) == (145, 745)  # the picked frame's centre, not the portrait
    assert g.ns.Target.lastName == "MyBar"


def test_below_max_level_the_bar_and_its_flash_are_unchanged(env):
    g = arena(env, probe=False, level=(60, 70))
    g.stub.setPlayerPortrait(500, 300)
    burst(g, x=300, y=600, n=3, kind="kill", style="stream")
    fl = run_until_flash(g)
    assert "flash" in str(fl.calls["SetTexture"][1])  # the horizontal bar flash
    assert g.ns.Target.lastName == "MainStatusTrackingBarContainer"


def test_portrait_mode_is_decided_once_per_burst(env):
    g = arena(env, probe=False)
    g.stub.setPlayerPortrait(500, 300)
    counter = count_calls(g, "AtMaxLevel")
    burst(g, x=300, y=600, n=6, kind="kill", style="stream")
    after_burst = counter.calls
    assert after_burst >= 1
    for _ in range(40):
        g.stub.tick(0.02)
    assert counter.calls == after_burst  # the driver never asks per frame


# ---- the debug override


def test_debug_maxlevel_command(env):
    g = arena(env, probe=False, level=(60, 70))
    T = g.ns.Target
    assert g.ns.AtMaxLevel() is False
    g.slash("debug maxlevel on")
    assert g.ns.AtMaxLevel() is True and T.PortraitMode(T) is True
    assert "debug maxlevel on" in last_chat(g)
    g.slash("debug maxlevel off")
    assert g.ns.AtMaxLevel() is False
    g.slash("debug maxlevel")
    assert "usage: /xporbs debug maxlevel on|off" in last_chat(g)


def test_debug_maxlevel_is_not_saved_and_does_not_touch_the_debug_log(env):
    g = arena(env, probe=False, level=(60, 70))
    g.db.debug = False
    g.slash("debug maxlevel on")
    assert g.db.debug is False
    assert not any(
        "force" in str(k).lower() or "maxlevel" in str(k).lower() for k in g.db.keys()
    )
    g.slash("debug maxlevel off")


def test_debug_maxlevel_lets_you_test_below_the_cap(env):
    g = arena(env, level=(60, 70))
    g.slash("debug maxlevel on")
    engage_target(g)
    die(g)
    assert len(g.bursts()) == 1 and g.has_log("kind=maxlevel")


def test_help_and_usage_mention_the_new_commands(env):
    g = arena(env, probe=False)
    g.slash("help")
    text = "\n".join(str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1))
    assert "/xporbs debug maxlevel on|off" in text and "/xporbs sound on|off" in text
    g.slash("debug bogus")
    assert "debug on|off|maxlevel on|off" in last_chat(g)


# ---------------------------------------------------------------- 5. the chime


def chime_game(env):
    g = make(
        env, probe=False, fixed_random=False
    )  # real stagger: orbs arrive at different moments
    g.db.sound = True
    g.db.style = "stream"
    return g


def play(g, n=6, seconds=3.0, step=0.01):
    burst(g, x=300, y=600, n=n, kind="kill", style="stream")
    for _ in range(int(seconds / step)):
        g.stub.tick(step)


def test_sound_is_off_by_default(env):
    g = make(env, probe=False)
    assert g.db.sound is False
    play(g)
    assert sounds(g) == []


def test_chime_plays_wobbling_notes_on_the_sfx_channel(env):
    g = chime_game(env)
    play(g, n=12)
    played = sounds(g)
    assert 1 <= len(played) <= 6  # at most one per 70 ms and six per burst
    assert all(ch == "SFX" for _, ch in played)
    idx = []
    for path, _ in played:
        m = CHIME_PATH.fullmatch(path)
        assert m and m.group(1) == "glass", path  # the default voice
        idx.append(int(m.group(2)))
    assert all(1 <= i <= 6 for i in idx)
    assert all(
        a != b for a, b in zip(idx, idx[1:])
    )  # never the same note twice running


def test_at_most_six_notes_per_burst(env):
    g = chime_game(env)
    g.db.cap = 80
    play(g, n=40, seconds=4.0, step=0.005)
    assert len(sounds(g)) <= 6


def test_chime_gap_between_notes(env):
    g = chime_game(env)
    times = g.env.lua.table()
    g.env.lua.eval(
        """function(rec, ns)
            local base = PlaySoundFile
            PlaySoundFile = function(...) rec[#rec + 1] = ns.stub.time; return base(...) end
        end"""
    )(times, g.ns)
    play(g, n=12, seconds=3.0, step=0.005)
    stamps = lua_list(times)
    assert len(stamps) >= 2 and all(
        b - a >= 0.07 - 1e-9 for a, b in zip(stamps, stamps[1:])
    )


def test_chime_works_with_the_glow_off(env):
    g = chime_game(env)
    g.db.glow = False
    play(g)
    assert len(sounds(g)) >= 1


def test_chime_off_plays_nothing_and_the_bookkeeping_still_clears(env):
    g = chime_game(env)
    g.db.sound = False
    play(g)
    assert sounds(g) == []
    assert g.orbs.chime.Open(g.orbs.chime) == 0


def test_burst_counters_are_cleared_when_bursts_finish(env):
    g = chime_game(env)
    for _ in range(5):
        burst(g, x=300, y=600, n=6, kind="kill", style="stream")
        g.stub.tick(0.1)
    for _ in range(300):
        g.stub.tick(0.01)
    assert g.orbs.chime.Open(g.orbs.chime) == 0 and g.orbs.Info(g.orbs)[1] == 0


def test_each_burst_gets_its_own_key(env):
    g = chime_game(env)
    burst(g, x=300, y=600, n=6, kind="kill", style="stream")
    burst(g, x=300, y=600, n=6, kind="kill", style="stream")
    for _ in range(25):
        g.stub.tick(0.01)
    assert (
        g.orbs.chime.Open(g.orbs.chime) <= 2
    )  # each live burst has at most one counter
    for _ in range(300):
        g.stub.tick(0.01)
    assert g.orbs.chime.Open(g.orbs.chime) == 0


@pytest.mark.parametrize("mode", ["false", "error"])
def test_first_sound_failure_logs_once_and_disables_sound(env, mode):
    g = chime_game(env)
    g.stub.soundMode = mode
    play(g, n=12)
    assert len(sounds(g)) == 1  # it gave up after the first failure
    assert g.orbs.SoundDisabled(g.orbs) is True
    assert sum("SOUND_ERR" in line for line in g.log()) == 1
    play(g, n=12)
    assert len(sounds(g)) == 1 and sum("SOUND_ERR" in line for line in g.log()) == 1
    assert g.db.sound is True  # the saved setting is not touched


def test_missing_playsoundfile_disables_sound_without_throwing(env):
    g = chime_game(env)
    g.env.G.PlaySoundFile = None
    play(g)
    assert g.orbs.SoundDisabled(g.orbs) is True and not g.has_log("DRIVER_ERR")


def test_sound_command_toggles_and_clears_a_shutdown(env):
    g = chime_game(env)
    g.stub.soundMode = "false"
    play(g)
    assert g.orbs.SoundDisabled(g.orbs) is True
    g.stub.soundMode = None
    g.slash("sound off")
    assert g.db.sound is False
    g.slash("sound")
    assert "chime: off, glass" in last_chat(g)
    g.slash("sound on")
    assert g.db.sound is True and g.orbs.SoundDisabled(g.orbs) is False
    g.slash("sound loud")
    assert "use on, off, coin, glass, brush or volume N" in last_chat(g)
    n = len(sounds(g))
    play(g)
    assert len(sounds(g)) > n


def test_sound_setting_is_sanitised(env):
    env.G.XPOrbsDB = env.lua.table_from({"version": 5, "sound": "yes"})
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    assert env.G.XPOrbsDB.sound is False


def test_driver_goes_idle_with_sound_on(env):
    g = chime_game(env)
    play(g, n=40, seconds=4.0, step=0.01)
    assert g.stub.updaters() == 0


def test_the_chime_path_is_built_once_at_load():
    src = (ROOT / "Orbs.lua").read_text(encoding="utf-8")
    assert (
        src.count('media\\\\chime\\\\" .. volume') == 1
    )  # one concatenation, in the load-time table, none in the driver
    assert 'media\\\\" .. voice' not in src


# ---- the sound files and the generator


@pytest.mark.parametrize("voice", ["coin", "glass"])
@pytest.mark.parametrize("i", range(1, 7))
def test_chime_files_exist_and_are_small(voice, i):
    p = SOUNDS / "chime" / "100" / f"{voice}{i}.ogg"
    assert p.is_file()
    data = p.read_bytes()
    assert data[:4] == b"OggS" and 1000 < len(data) < 15 * 1024


def test_old_chime_files_are_gone():
    assert not list(
        SOUNDS.glob("*.ogg")
    )  # every sound lives under media/chime/<level>/
    assert len(list((SOUNDS / "chime").glob("*/*.ogg"))) == 7 * 30


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_sounds", ROOT / "tools" / "make_sounds.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_is_stdlib_only_and_documents_the_licence():
    src = (ROOT / "tools" / "make_sounds.py").read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:import|from) (\w+)", src, re.MULTILINE))
    assert imports <= {
        "argparse",
        "math",
        "random",
        "shutil",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "wave",
        "pathlib",
    }
    assert "original" in src and "GPL" in src and "libvorbis" in src


@pytest.mark.parametrize(
    "voice,centre,cents",
    [("glassb", 1700, 100), ("coin", 3100, 120), ("glass", 3000, 150)],
)
def test_generator_makes_six_close_pitches_per_voice(voice, centre, cents):
    mod = load_generator()
    assert set(mod.VOICES) == {"coin", "glass", "glassb", "brush", "ding"}
    notes = mod.notes(voice)
    assert len(notes) == 6 and notes == sorted(notes) and len(set(notes)) == 6
    for f in notes:
        assert abs(1200 * math.log2(f / centre)) <= cents + 1


@pytest.mark.parametrize("voice", ["glassb", "glass"])
def test_generator_voices_are_quiet_short_and_deterministic(voice):
    mod = load_generator()
    for f in mod.notes(voice):
        s = mod.synth(f, voice)
        assert len(s) / 44100 <= 0.3 and s[-1] == 0
        peak_db = 20 * math.log10(max(abs(v) for v in s) / 32767)
        assert -29 <= peak_db <= -23
        assert mod.synth(f, voice) == s  # fixed noise seed: identical on every run


def test_glass_has_no_second_strike_and_coin_does():
    mod = load_generator()
    assert mod.VOICES["glass"]["BOUNCE_AMP"] == 0
    assert mod.VOICES["glassb"]["BOUNCE_AMP"] > 0
    # glassb's settling strike lands at 30 ms; without it the same voice is identical before and different after
    one_strike = dict(mod.VOICES["glassb"], BOUNCE_AMP=0.0)
    mod.VOICES["plain"] = one_strike
    i = int(44100 * 0.03)
    with_b, without = mod.synth(1700.0, "glassb"), mod.synth(1700.0, "plain")
    assert with_b[i + 100 : i + 400] != without[i + 100 : i + 400]
    # the glass voice is already a single strike: forcing its bounce on changes it, so it really has none
    mod.VOICES["glass2"] = dict(mod.VOICES["glass"], BOUNCE_S=0.03, BOUNCE_AMP=0.35)
    assert mod.synth(3000.0, "glass2") != mod.synth(3000.0, "glass")


def test_generator_fails_clearly_without_ffmpeg(monkeypatch, capsys, tmp_path):
    mod = load_generator()
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mod.sys, "argv", ["make_sounds.py", "--out", str(tmp_path)])
    assert mod.main() == 1
    assert "ffmpeg" in capsys.readouterr().err


def test_packaged_zip_includes_the_chimes_and_new_modules_but_no_tools(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "xporbs_package", ROOT / "tools" / "package.py"
    )
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    with zipfile.ZipFile(package.build(tmp_path)) as z:
        names = z.namelist()
    for voice in ("coin", "glass"):
        for i in range(1, 7):
            assert f"XPOrbs/media/chime/100/{voice}{i}.ogg" in names
    assert not any(
        n.startswith("XPOrbs/media/chime") and "/chime/" not in n for n in names
    )  # no old flat files
    for rel in ("logic/Engaged.lua", "logic/Chime.lua"):
        assert f"XPOrbs/{rel}" in names
    assert not any("/tools/" in n or "make_sounds" in n for n in names)


def test_pkgmeta_ships_media_and_ignores_tools():
    pk = (ROOT / ".pkgmeta").read_text(encoding="utf-8")
    ignored = {ln.strip()[2:] for ln in pk.splitlines() if ln.strip().startswith("- ")}
    assert "tools" in ignored and "media" not in ignored


# ---------------------------------------------------------------- options panel and docs


def test_options_has_the_new_checkboxes_with_tooltips(env):
    from test_m5 import build

    m = build(env)
    texts = [
        f.text
        for f in m.stub.frames.values()
        if f.kind == "FontString" and getattr(f, "text", None)
    ]
    assert "Orbs at max level" in texts and "Chime when orbs arrive" in texts
    cb = m.opt.controls["showAtMax"]
    m.stub.hover(cb)
    assert m.stub.tooltip.shown and "small burst of orbs to your portrait" in str(
        m.stub.tooltip.text
    )
    m.stub.unhover(cb)
    assert not m.stub.tooltip.shown
    snd = m.opt.controls["sound"]
    m.stub.click(snd)
    assert m.db.sound is True
    m.stub.click(snd)
    assert m.db.sound is False


def test_docs_mention_the_new_features():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "/xporbs sound",
        r"coin\|glass",
        "/xporbs debug maxlevel",
        "portrait",
    ):
        assert needle in readme, needle
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 1.1.0 (" in log and "## 1.0.2 (unreleased)" not in log
    assert "chime" in log.lower() and "portrait" in log
    assert "coin" in log and "glass" in log


def test_no_local_paths_in_new_files():
    bad = re.compile(
        r"D:\\|C:\\Users", re.IGNORECASE
    )  # names are checked by the release grep, outside the repo
    for rel in (
        "logic/Engaged.lua",
        "logic/Chime.lua",
        "tools/make_sounds.py",
        "README.md",
        "CHANGELOG.md",
    ):
        assert not bad.search((ROOT / rel).read_text(encoding="utf-8")), rel


# ---------------------------------------------------------------- the sound voice (coin / glass / brush)


def played_voices(g):
    out = []
    for path, _ in sounds(g):
        m = CHIME_PATH.fullmatch(path)
        assert m, path
        out.append(m.group(1))
    return out


def junk_db(env, **kw):
    env.G.XPOrbsDB = env.lua.table_from({"version": 5, **kw})
    env.load_addon()
    env.ns.fire("ADDON_LOADED", "XPOrbs")
    return env.G.XPOrbsDB


@pytest.mark.parametrize("bad", ["bell", 5, True, "", "Glass", "coin2"])
def test_sound_voice_junk_values_fall_back_to_glass(env, bad):
    assert junk_db(env, soundVoice=bad).soundVoice == "glass"


def test_a_valid_saved_voice_is_kept(env):
    assert junk_db(env, soundVoice="glass").soundVoice == "glass"
    assert junk_db(env, soundVoice="brush").soundVoice == "brush"


@pytest.mark.parametrize("voice", ["coin", "glass", "brush"])
def test_arrivals_play_the_selected_voice(env, voice):
    g = chime_game(env)
    g.db.soundVoice = voice
    play(g, n=12)
    assert played_voices(g) and set(played_voices(g)) == {voice}


def test_an_unknown_voice_in_the_db_still_plays_glass(env):
    g = chime_game(env)
    g.db.soundVoice = "bogus"  # bypasses sanitize, as a live edit would
    play(g, n=12)
    assert played_voices(g) and set(played_voices(g)) == {"glass"}


def test_switching_voice_mid_session_takes_effect_on_the_next_burst(env):
    g = chime_game(env)
    play(g, n=12)
    g.db.soundVoice = "coin"
    play(g, n=12)
    v = played_voices(g)
    assert v[0] == "glass" and v[-1] == "coin"


def test_slash_voice_choices_turn_sound_on_and_report_state(env):
    g = make(env, probe=False)
    assert g.db.sound is False
    g.slash("sound glass")
    assert g.db.sound is True and g.db.soundVoice == "glass"
    assert "chime: on, glass" in last_chat(g)
    g.slash("sound off")
    assert g.db.sound is False and g.db.soundVoice == "glass"  # off keeps the voice
    assert "chime: off, glass" in last_chat(g)
    g.slash("sound coin")
    assert g.db.sound is True and g.db.soundVoice == "coin"
    assert "chime: on, coin" in last_chat(g)
    g.slash("sound off")
    g.slash("sound brush")
    assert g.db.sound is True and g.db.soundVoice == "brush"
    assert "chime: on, brush" in last_chat(g)
    g.slash("sound glass")
    g.slash("sound on")  # plain on keeps the current voice
    assert g.db.soundVoice == "glass"
    g.slash("sound")
    assert "chime: on, glass" in last_chat(g)


def test_help_lists_the_voices(env):
    g = make(env, probe=False)
    g.slash("help")
    text = "\n".join(str(g.stub.chat[i]) for i in range(1, len(g.stub.chat) + 1))
    assert "/xporbs sound on|off|coin|glass" in text


# ---- the options-panel dropdown


def opts(env, **kw):
    from test_m5 import build

    return build(env, **kw)


def entries(dd):
    dd.GenerateMenu(dd)
    root = dd.menuRoot
    return [
        (str(root.entries[i]["text"]), bool(root.entries[i]["selected"]))
        for i in range(1, len(root.entries) + 1)
    ]


def test_dropdown_is_built_from_the_modern_template(env):
    m = opts(env)
    dd = m.opt.soundDropdown
    assert (
        dd is not None
        and dd.kind == "DropdownButton"
        and dd.template == "WowStyle1DropdownTemplate"
    )
    assert m.lua.eval("rawequal")(m.opt.controls["soundVoice"], dd)
    assert entries(dd) == [("Glass", True), ("Coin", False), ("Brush", False)]


def test_dropdown_row_sits_under_the_chime_checkbox_inside_the_panel(env):
    m = opts(env)
    row, chk = m.opt.rows["soundVoice"], m.opt.rows["sound"]
    assert row.points[1][5] == chk.points[1][5] - 28 and row.height == 28
    dd = m.opt.soundDropdown
    assert dd.points[1][4] == 260 and dd.width == 150
    assert dd.points[1][4] + dd.width < 548  # clear of the reset button column
    assert "Sound" in {f.text for f in m.stub.frames.values() if f.kind == "FontString"}


def test_picking_from_the_dropdown_sets_the_voice_and_previews_one_note(env):
    m = opts(env)
    m.db.sound = True
    show(m)
    dd = m.opt.soundDropdown
    n0 = len(m.stub.sounds)
    assert m.stub.pickMenu(dd, "Glass") is True
    assert m.db.soundVoice == "glass"
    assert len(m.stub.sounds) == n0 + 1
    path, ch = str(m.stub.sounds[n0 + 1][1]), str(m.stub.sounds[n0 + 1][2])
    assert CHIME_PATH.fullmatch(path).group(1) == "glass" and ch == "SFX"
    assert entries(dd) == [("Glass", True), ("Coin", False), ("Brush", False)]
    assert m.stub.pickMenu(dd, "Coin") is True
    assert m.db.soundVoice == "coin" and len(m.stub.sounds) == n0 + 2
    assert m.stub.pickMenu(dd, "Brush") is True and m.db.soundVoice == "brush"
    assert len(m.stub.sounds) == n0 + 3
    assert CHIME_PATH.fullmatch(str(m.stub.sounds[n0 + 3][1])).group(1) == "brush"


def test_preview_plays_even_with_the_chime_off(env):
    m = opts(env)
    assert m.db.sound is False
    m.stub.pickMenu(m.opt.soundDropdown, "Glass")  # the menu callback itself
    assert m.db.soundVoice == "glass" and len(m.stub.sounds) == 1
    assert m.db.sound is False  # choosing in the panel does not turn the chime on


def test_preview_survives_a_failing_playsoundfile(env):
    m = opts(env)
    m.stub.soundMode = "error"
    m.stub.pickMenu(m.opt.soundDropdown, "Glass")
    assert m.db.soundVoice == "glass"  # no throw, the choice stands


def test_dropdown_refreshes_from_the_db_and_follows_the_slash_command(env):
    m = opts(env)
    dd = m.opt.soundDropdown
    m.db.soundVoice = "coin"
    show(m)
    assert entries(dd) == [("Glass", False), ("Coin", True), ("Brush", False)]
    m.slash("sound glass")
    assert entries(dd) == [("Glass", True), ("Coin", False), ("Brush", False)]


def test_dropdown_reset_button_restores_glass(env):
    m = opts(env)
    m.db.soundVoice = "coin"
    show(m)
    btn = m.opt.resets["soundVoice"]
    assert btn.shown
    m.stub.click(btn)
    assert m.db.soundVoice == "glass" and not btn.shown
    assert entries(m.opt.soundDropdown)[0] == ("Glass", True)


def test_reset_all_returns_the_voice_to_glass(env):
    m = opts(env)
    m.slash("sound coin")
    m.slash("reset")
    assert m.db.soundVoice == "glass" and m.db.sound is False
    assert entries(m.opt.soundDropdown) == [
        ("Glass", True),
        ("Coin", False),
        ("Brush", False),
    ]


def test_dropdown_stays_enabled_with_the_chime_off(env):
    m = opts(env)
    row, dd = m.opt.rows["soundVoice"], m.opt.soundDropdown
    show(m)
    assert m.db.sound is False
    assert row.alpha in (None, 1) and dd.IsEnabled(
        dd
    )  # never dimmed: the player can preview the voices before turning the chime on


def test_sound_tooltip_describes_all_voices(env):
    m = opts(env)
    m.stub.hover(m.opt.controls["sound"])
    tip = str(m.stub.tooltip.text)
    assert "Coin: a soft coin clink." in tip and "Glass: a glassy tink." in tip
    assert "Brush: a soft brushed swish." in tip
    assert "Off by default." in tip


# ---- the radio fallback (no dropdown template, or SetupMenu missing)


def no_dropdown(env):
    env.lua.execute(
        """
        local base = CreateFrame
        function CreateFrame(kind, name, parent, template)
            if kind == "DropdownButton" or template == "WowStyle1DropdownTemplate" then
                error("template not found: " .. tostring(template))
            end
            return base(kind, name, parent, template)
        end
        """
    )


def no_setupmenu(env):
    env.lua.execute(
        """
        local base = CreateFrame
        function CreateFrame(kind, name, parent, template)
            local f = base(kind, name, parent, template)
            if kind == "DropdownButton" then f.SetupMenu = nil end
            return f
        end
        """
    )


@pytest.mark.parametrize("hook", [no_dropdown, no_setupmenu])
def test_radio_fallback_when_the_dropdown_is_unavailable(env, hook):
    m = opts(env, pre=hook)
    assert m.opt.category is not None and m.opt.soundDropdown is None
    coin, glass = m.opt.controls["soundVoice_coin"], m.opt.controls["soundVoice_glass"]
    assert m.opt.controls["soundVoice_brush"].template == "UIRadioButtonTemplate"
    assert coin.template == "UIRadioButtonTemplate"
    assert glass.template == "UIRadioButtonTemplate"
    labels = {f.text for f in m.stub.frames.values() if f.kind == "FontString"}
    assert {"Sound", "Coin", "Glass", "Brush"} <= labels
    show(m)
    assert glass.checked is True and coin.checked is False
    n0 = len(m.stub.sounds)
    m.stub.click(coin)
    assert m.db.soundVoice == "coin"
    assert coin.checked is True and glass.checked is False
    assert len(m.stub.sounds) == n0 + 1
    assert CHIME_PATH.fullmatch(str(m.stub.sounds[n0 + 1][1])).group(1) == "coin"
    m.slash("sound glass")
    assert glass.checked is True and coin.checked is False


def test_radio_fallback_sits_inside_the_panel_width(env):
    m = opts(env, pre=no_dropdown)
    xs = [
        m.opt.controls[f"soundVoice_{v}"].points[1][4]
        for v in ("glass", "coin", "brush")
    ]
    assert xs == sorted(xs) and xs[0] >= 258
    assert xs[2] + 24 + 7 * len("Brush") + 8 < 548  # label end clear of the resets


def test_radio_fallback_resets_and_stays_enabled(env):
    m = opts(env, pre=no_dropdown)
    m.db.soundVoice = "coin"
    show(m)
    assert m.opt.rows["soundVoice"].alpha in (None, 1)  # never dimmed
    m.stub.click(m.opt.resets["soundVoice"])
    assert m.db.soundVoice == "glass"
    assert m.opt.controls["soundVoice_glass"].checked is True

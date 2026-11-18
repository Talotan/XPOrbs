"""1.1.0: XP-bar colours, max-level kill orbs to the portrait, the optional chime."""

import importlib.util
import math
import re
import zipfile

import pytest
from conftest import ROOT, lua_list
from test_v09 import burst, make, pop_textures, set_level

PURPLE = (0.85, 0.38, 1.00)  # default normal orb
BLUE = (0.15, 0.38, 1.00)  # default rested orb
UNDER_PURPLE = tuple(round(0.25 * c, 4) for c in PURPLE)
UNDER_BLUE = tuple(round(0.25 * c, 4) for c in BLUE)
SOUNDS = ROOT / "media"
CHIME_PATH = re.compile(r"Interface\\AddOns\\XPOrbs\\media\\chime([1-6])\.ogg")


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
    assert d.flightTime == 1.0 and d.sound is False
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
        assert m, path
        idx.append(int(m.group(1)))
    assert all(1 <= i <= 6 for i in idx)
    assert all(a != b for a, b in zip(idx, idx[1:]))  # never the same note twice running


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
    assert "chime: off" in last_chat(g)
    g.slash("sound on")
    assert g.db.sound is True and g.orbs.SoundDisabled(g.orbs) is False
    g.slash("sound loud")
    assert "use on or off" in last_chat(g)
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
        src.count("media\\\\chime") == 1
    )  # one concatenation, in the load-time table, none in the driver


# ---- the sound files and the generator


@pytest.mark.parametrize("i", range(1, 7))
def test_chime_files_exist_and_are_small(i):
    p = SOUNDS / f"chime{i}.ogg"
    assert p.is_file()
    data = p.read_bytes()
    assert data[:4] == b"OggS" and 1000 < len(data) < 15 * 1024


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


def test_generator_makes_six_close_pitches_around_3khz():
    mod = load_generator()
    assert len(mod.NOTES) == 6 and mod.NOTES == sorted(mod.NOTES)
    for f in mod.NOTES:
        assert abs(1200 * math.log2(f / 3000)) <= 150 + 1


def test_generator_tink_is_quiet_short_and_deterministic():
    mod = load_generator()
    for f in mod.NOTES:
        s = mod.synth(f)
        assert len(s) / 44100 <= 0.3 and s[-1] == 0
        peak_db = 20 * math.log10(max(abs(v) for v in s) / 32767)
        assert -23 <= peak_db <= -17
        assert mod.synth(f) == s  # fixed noise seed: identical on every run


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
    for i in range(1, 7):
        assert f"XPOrbs/media/chime{i}.ogg" in names
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
    assert "Kill orbs at max level" in texts and "Chime when orbs arrive" in texts
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
    for needle in ("/xporbs sound", "/xporbs debug maxlevel", "portrait"):
        assert needle in readme, needle
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 1.1.0 (unreleased)" in log and "## 1.0.2 (unreleased)" not in log
    assert "chime" in log.lower() and "portrait" in log


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

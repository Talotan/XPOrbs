"""v0.10: cursor-informed mob estimate (MobEstimate + Mouseover sampler), pop exit vector, crossfade on plate BOTTOM."""

import math

import pytest
from conftest import lua_list
from test_v09 import (
    OWN,
    burst,
    chat_lines,
    kill_with_secret_pos_plate,
    make,
    pop_frames,
    pop_textures,
    restricted_plate,
    stream_textures,
)

W, H = 1920, 1080
DEF_X, DEF_Y = W / 2, H * 0.58  # MobEstimate.Default
HEAD = 40


def new_est(env, t, **cfg):
    env.load_addon()
    c = {"now": lambda: t[0]}
    c.update(cfg)
    return env.ns.MobEstimate.New(env.lua.table_from(c))


def estimate(est, guid, cursor=None, w=W, h=H):
    cx, cy = cursor if cursor else (None, None)
    x, y, source, wm = est.Estimate(est, guid, cx, cy, w, h)
    return x, y, source, wm


def blend(cursor):
    # v0.11: cursorWeight is 0, so the idle cursor no longer moves the estimate (it is just the default point)
    return DEF_X, DEF_Y


# ---------------------------------------------------------------- MobEstimate (pure)


def test_default_point_is_single_source_of_truth(env):
    env.load_addon()
    me = env.ns.MobEstimate
    assert me.ASSUMED_MOB_Y == 0.58 and tuple(me.Default(W, H)) == (
        DEF_X,
        pytest.approx(DEF_Y),
    )


def test_sample_ageing_weights(env):
    t = [0.0]
    est = new_est(env, t)
    est.AddSample(est, "A", 100, 200)
    for age, want in (
        (0.0, 1),
        (0.5, 1),
        (1.0, 1),
        (2.0, 0.5),
        (2.5, 0.25),
        (3.0, 0),
        (4.0, 0),
    ):
        t[0] = age
        assert estimate(est, "A")[3] == pytest.approx(want), age


def test_weight_blend_numbers(env):
    t = [0.0]
    est = new_est(env, t)
    est.AddSample(est, "A", 100, 200)
    cur = (600, 300)
    bx, by = blend(cur)
    # fresh: exactly the sample plus the head offset
    assert estimate(est, "A", cur) == (
        pytest.approx(100),
        pytest.approx(200 + HEAD),
        "mouseover",
        1,
    )
    # 2 s old: w_m = 0.5, the rest is the cursor/default blend
    t[0] = 2.0
    x, y, src, wm = estimate(est, "A", cur)
    assert src == "mouseover" and wm == pytest.approx(0.5)
    assert x == pytest.approx(0.5 * 100 + 0.5 * bx) and y == pytest.approx(
        0.5 * (200 + HEAD) + 0.5 * by
    )
    # expired: the default point (the cursor has weight 0), with or without a cursor
    t[0] = 3.0
    assert estimate(est, "A", cur) == (
        pytest.approx(bx),
        pytest.approx(by),
        "default",
        0,
    )
    assert estimate(est, "A") == (
        pytest.approx(DEF_X),
        pytest.approx(DEF_Y),
        "default",
        0,
    )


def test_guid_mismatch_nil_and_unknown_fall_back(env):
    t = [0.0]
    est = new_est(env, t)
    est.AddSample(est, "A", 100, 200)
    cur = (600, 300)
    bx, by = blend(cur)
    for guid in ("B", None, 42):
        assert estimate(est, guid, cur) == (
            pytest.approx(bx),
            pytest.approx(by),
            "default",
            0,
        )
        assert estimate(est, guid) == (
            pytest.approx(DEF_X),
            pytest.approx(DEF_Y),
            "default",
            0,
        )


def test_estimate_needs_a_screen_size(env):
    est = new_est(env, [0.0])
    assert tuple(est.Estimate(est, "A", 1, 1, None, H)) == (None, None, "default", 0)
    assert tuple(est.Estimate(est, "A", 1, 1, 0, H))[0] is None


def test_prune_after_five_seconds(env):
    t = [0.0]
    est = new_est(env, t)
    est.AddSample(est, "A", 1, 1)
    t[0] = 5.0
    est.AddSample(
        est, "B", 2, 2
    )  # A is exactly 5 s old: kept (prune is strictly > 5 s)
    assert est.Count(est) == 2
    t[0] = 5.01
    est.AddSample(est, "C", 3, 3)  # A is now > 5 s old
    assert est.Count(est) == 2


def test_cap_of_20_evicts_the_oldest(env):
    t = [0.0]
    est = new_est(env, t)
    for i in range(25):
        t[0] = i * 0.1
        assert est.AddSample(est, f"G{i}", i, i)
    assert est.Count(est) == 20
    assert (
        estimate(est, "G0")[3] == 0 and estimate(est, "G4")[3] == 0
    )  # the 5 oldest are gone
    assert estimate(est, "G5")[3] > 0 and estimate(est, "G24")[3] == 1
    est.AddSample(est, "G24", 5, 5)  # an update of a known guid never evicts
    assert est.Count(est) == 20 and estimate(est, "G5")[3] > 0


def test_add_sample_rejects_bad_input(env):
    est = new_est(env, [0.0])
    assert not est.AddSample(est, None, 1, 2)
    assert not est.AddSample(est, 12, 1, 2)
    assert not est.AddSample(est, "A", "x", 2)
    assert not est.AddSample(est, "A", 1, None)
    assert est.Count(est) == 0


def test_pick_origin_rules(env):
    env.load_addon()
    pick = env.ns.MobEstimate.PickOrigin
    # v0.11: the estimate always wins when there is one; the portrait is only the no-estimate fallback
    assert tuple(pick(10, 20, 250, 900)) == (10, 20, "estimate")
    assert tuple(pick(10, 20, None, None)) == (10, 20, "estimate")
    assert tuple(pick(None, None, 250, 900)) == (250, 900, "targetframe")
    # nothing usable -> nil, the caller falls back to the screen centre
    assert pick(None, None, None, None) is None
    assert pick(10, None, None, None) is None


# ---------------------------------------------------------------- Mouseover sampler (WoW side)


def hover(g, guid="G1", can_attack=True, exists=True, cursor=None):
    g.stub.units["mouseover"] = g.env.lua.table_from(
        {"guid": guid, "canAttack": can_attack, "exists": exists}
    )
    if cursor:
        g.stub.cursor.x, g.stub.cursor.y = cursor
    g.ns.fire("UPDATE_MOUSEOVER_UNIT")


def mo_estimate(g, guid):
    mo = g.ns.Mouseover
    return tuple(mo.Estimate(mo, guid))


def test_hostile_hover_records_a_sample(env):
    g = make(env)
    hover(g, cursor=(700, 500))
    assert g.ns.Mouseover.est.Count(g.ns.Mouseover.est) == 1
    x, y, src, wm = mo_estimate(g, "G1")
    assert (x, y, src, wm) == (
        pytest.approx(700),
        pytest.approx(500 + HEAD),
        "mouseover",
        1,
    )
    assert mo_estimate(g, "OTHER")[2] == "default"


def test_cursor_is_divided_by_ui_scale(env):
    g = make(env)
    g.env.G.UIParent.scale = 2
    hover(g, cursor=(1400, 1000))
    x, y, _, _ = mo_estimate(g, "G1")
    assert (x, y) == (pytest.approx(700), pytest.approx(500 + HEAD))


def test_secret_guid_is_not_sampled(env):
    g = make(env)
    hover(g, guid=g.stub.SECRET)
    assert g.ns.Mouseover.est.Count(g.ns.Mouseover.est) == 0
    assert g.ns.Mouseover.PollActive(
        g.ns.Mouseover
    )  # the unit exists, so we still poll for the next change


def test_non_hostile_is_not_sampled(env):
    g = make(env)
    hover(g, can_attack=False)
    assert g.ns.Mouseover.est.Count(g.ns.Mouseover.est) == 0


def test_idle_without_mouseover_and_throttled_poll(env):
    g = make(env)
    mo = g.ns.Mouseover
    assert mo.registered and not mo.PollActive(mo)
    hover(g, exists=False)
    assert (
        not mo.PollActive(mo) and mo.frame.scripts.OnUpdate is None
    )  # nothing moused over: stay idle
    hover(g, cursor=(100, 100))
    assert mo.PollActive(mo)
    g.stub.cursor.x, g.stub.cursor.y = 300, 300
    g.stub.tick(0.05)  # throttled: no new sample yet
    assert mo_estimate(g, "G1")[0] == pytest.approx(100)
    g.stub.tick(0.06)  # >= 0.1 s accumulated
    assert mo_estimate(g, "G1")[0] == pytest.approx(300)
    g.stub.units[
        "mouseover"
    ].exists = False  # cursor left the unit without an event reaching us
    g.stub.tick(0.11)
    assert not mo.PollActive(mo) and mo.frame.scripts.OnUpdate is None
    g.ns.fire("UPDATE_MOUSEOVER_UNIT")
    assert not mo.PollActive(mo)


# ---------------------------------------------------------------- KillMatcher guid passthrough


def test_killmatcher_passes_guid_through_and_tier4_has_none(env):
    env.load_addon()
    t = [0.0]
    m = env.ns.KillMatcher.New(env.lua.table_from({"now": lambda: t[0]}))
    m.AddDeath(m, env.lua.table_from({"tier": 1, "guid": "Creature-1"}))
    m.AddKillXP(m, env.lua.table_from({"amount": 10}))
    (b,) = lua_list(m.Poll(m))
    assert b.guid == "Creature-1" and b.tier == 1
    m.AddKillXP(m, env.lua.table_from({"amount": 10}))
    t[0] = 1.0
    (b,) = lua_list(m.Poll(m))
    assert b.tier == 4 and b.guid is None


# ---------------------------------------------------------------- Kills: estimate and stream origin


def kill_after_hover(g, wait=0.0):
    """Hover G1 (cursor 700, 500), optionally let the sample age, then kill it (plate guid G1)."""
    hover(g, cursor=(700, 500))
    hover(
        g, exists=False
    )  # stop the poll so the sample is not refreshed while time passes
    g.stub.time = g.stub.time + wait
    return kill_with_secret_pos_plate(g)


def test_kill_uses_estimate_when_mouseover_confident(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)  # visible, but the confident estimate wins
    kill_after_hover(g, 0.3)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (pytest.approx(700), pytest.approx(540))
    assert (
        (b["ex"], b["ey"]) == (b["x"], b["y"])
        and b["est"] == "mouseover"
        and b["estW"] == 1
    )
    assert g.has_log("origin=estimate plate=yes est=mouseover w=1.00")


def test_kill_uses_estimate_even_when_not_confident_and_frame_visible(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)
    kill_after_hover(g, 1.85)  # sample 2.0 s old when the burst is emitted: w_m = 0.5
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (b["ex"], b["ey"]) and b["x"] != 250
    assert b["estW"] == pytest.approx(0.5)
    assert g.has_log("origin=estimate plate=yes est=mouseover w=0.50")


def test_kill_uses_estimate_when_target_frame_hidden(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, False)
    kill_after_hover(g, 1.85)  # w_m = 0.5
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (b["ex"], b["ey"]) and b["x"] != 250
    assert g.has_log("origin=estimate plate=yes est=mouseover w=0.50")


def test_other_xp_keeps_centre_origin_and_no_estimate(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setXP(50)
    g.tick(0.6)
    (b,) = g.bursts()
    assert (
        b["kind"] == "other"
        and b["ex"] is None
        and (b["x"], b["y"]) == (960, 1080 * 0.55)
    )
    assert g.has_log("kind=other") and g.has_log("est=none w=0.00")


def test_burst_log_has_est_and_never_a_guid_or_name(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)
    hover(g, guid="Creature-0-1-GUIDTEST", cursor=(700, 500))
    g.plate(
        guid="Creature-0-1-GUIDTEST", name="Boar", cx=g.stub.SECRET, cy=g.stub.SECRET
    )
    g.tick(0.05)
    g.ns.fire("UNIT_DIED", "Creature-0-1-GUIDTEST")
    g.chat()
    g.tick(0.1)
    assert g.has_log("est=mouseover w=1.00")
    assert all("GUIDTEST" not in line and "Boar" not in line for line in g.log())


def test_stream_style_keeps_portrait_origin(env):
    g = make(env)
    g.fake_orbs_on()
    g.db.style = "stream"
    g.stub.setTargetFrame(250, 900, False)
    kill_after_hover(g, 0.3)
    (b,) = g.bursts()
    assert (b["x"], b["y"]) == (250, 900) and g.has_log("origin=targetframe plate=no")


def test_tier4_has_no_guid_so_default_or_cursor_estimate(env):
    g = make(env)
    g.fake_orbs_on()
    g.stub.setTargetFrame(250, 900, True)
    hover(g, cursor=(700, 500))
    g.chat()
    g.tick(0.6)  # tier 4: no death, no guid
    assert g.has_log("tier=4") and g.has_log("est=default w=0.00")


# ---------------------------------------------------------------- OrbMath: exit vector, PopControl


def test_exit_vector_towards_stream_origin(env):
    env.load_addon()
    ev = env.ns.OrbMath.ExitVector
    ux, uy = ev(300, 300, 900, 500, 400, 25)
    assert (ux, uy) == (
        pytest.approx(-600 / math.hypot(600, 200)),
        pytest.approx(-200 / math.hypot(600, 200)),
    )


def test_exit_vector_falls_back_to_destination_then_up(env):
    env.load_addon()
    ev = env.ns.OrbMath.ExitVector
    # stream origin within 20 px of the pop estimate: head for the bar
    ux, uy = ev(505, 405, 500, 400, 500, 0)
    assert (ux, uy) == (pytest.approx(0), pytest.approx(-1))
    # exactly 20 px away is not degenerate
    assert tuple(ev(520, 400, 500, 400, 500, 0)) == (1, 0)
    # everything coincides: straight up
    assert tuple(ev(500, 400, 500, 400, 500, 400)) == (0, 1)


def test_pop_control_spread_and_lift(env):
    env.load_addon()
    pc = env.ns.OrbMath.PopControl
    half = lambda: 0.5  # noqa: E731
    ang = (0 + 0.5 * 0.8) / 1 * 2 * math.pi
    r = 45 + 0.5 * 55
    c1x, c1y, rr = pc(1, 1, 100, 200, half)  # defaults unchanged
    assert rr == pytest.approx(r)
    assert (c1x, c1y) == (
        pytest.approx(100 + math.cos(ang) * r * 2.2),
        pytest.approx(200 + (0.8 * math.sin(ang) + 0.35) * r * 2.2),
    )
    c1x, c1y, rr = pc(1, 1, 100, 200, half, 0.45, 0.10)
    r2 = r * 0.45
    assert rr == pytest.approx(r2)
    assert (c1x, c1y) == (
        pytest.approx(100 + math.cos(ang) * r2 * 2.2),
        pytest.approx(200 + (0.8 * math.sin(ang) + 0.10) * r2 * 2.2),
    )


# ---------------------------------------------------------------- Orbs: pop exit, crossfade bottom anchor


def expected_pop_offset(t, ux, uy):
    """Offset of the single fixed-random pop orb after t seconds (random() = 0.5)."""
    p = min(1, t / 0.55)
    e = 1 - (1 - p) ** 3
    ang = (0 + 0.5 * 0.8) / 1 * 2 * math.pi
    rad = 30 + 0.5 * (55 - 30)
    dx, dy, drift = math.cos(ang) * rad, math.sin(ang) * rad, 0.5 * 12
    q = (p - 0.45) / 0.55 if p > 0.45 else 0
    gather = 1 - 0.5 * q
    ex = 140 * q * q
    return (dx * e * gather + ux * ex, (dy + drift) * e * gather + uy * ex)


def pop_orb_offset(g):
    orb = [t for t in pop_textures(g) if t.shown and t.calls["SetDrawLayer"][2] == 0][0]
    return orb.points[1][4], orb.points[1][5]


def test_pop_exits_along_the_stream_origin_direction(env):
    g = make(env)
    plate = restricted_plate(g)
    # stream origin (300, 300), estimate (900, 500): the pop launches up-right to down-left, towards the stream
    burst(g, plate=plate, n=1, x=300, y=300, ex=900, ey=500, kind="kill")
    g.stub.tick(0.5)
    ux, uy = -600 / math.hypot(600, 200), -200 / math.hypot(600, 200)
    ox, oy = pop_orb_offset(g)
    ex, ey = expected_pop_offset(0.5, ux, uy)
    assert (ox, oy) == (pytest.approx(ex, abs=1e-6), pytest.approx(ey, abs=1e-6))
    assert ex < 0  # it really moved towards the stream origin (left), not away


def test_pop_exit_falls_back_to_bar_when_stream_starts_at_estimate(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(
        g, plate=plate, n=1, x=900, y=500, ex=900, ey=500, kind="kill"
    )  # stream origin == P-hat
    g.stub.tick(0.5)
    dest = tuple(g.ns.Target.GetDestination(g.ns.Target))[:2]  # XP bar edge (400, 25)
    d = math.hypot(dest[0] - 900, dest[1] - 500)
    ux, uy = (dest[0] - 900) / d, (dest[1] - 500) / d
    ox, oy = pop_orb_offset(g)
    ex, ey = expected_pop_offset(0.5, ux, uy)
    assert (ox, oy) == (pytest.approx(ex, abs=1e-6), pytest.approx(ey, abs=1e-6))


def test_pop_is_gone_by_pop_time_and_stream_follows_after_launch(env):
    g = make(env)
    plate = restricted_plate(g)
    burst(g, plate=plate, n=1, x=300, y=300, kind="kill")
    g.stub.tick(0.3)
    assert len(stream_textures(g)) == 0  # STREAM_DELAY 0.30 + stagger 0.04
    g.stub.tick(0.1)
    assert len(stream_textures(g)) == 3
    g.stub.tick(0.2)
    assert not any(t.shown for t in pop_textures(g))


def test_crossfade_copy_a_anchored_to_plate_bottom_and_curve_starts_at_estimate(env):
    g = make(env)
    plate = restricted_plate(g, cx=700, cy=400)
    assert (
        burst(
            g,
            plate=plate,
            n=1,
            x=300,
            y=300,
            ex=700,
            ey=500,
            kind="kill",
            style="crossfade",
        )
        == "crossfade"
    )
    (G,) = pop_frames(g)
    pt = G.points[1]
    assert (
        len(G.points) == 1
        and OWN(g, pt[2], plate)
        and pt[1] == "CENTER"
        and pt[3] == "BOTTOM"
    )
    assert (pt[4], pt[5]) == (0, 0)
    g.stub.tick(
        0.1
    )  # v0.11: inside the bloom hold (delay 0.04 + hold 0.22): copy A only, a small offset from P-hat
    b = [t for t in stream_textures(g) if t.calls["SetDrawLayer"][2] == 0]
    a = [t for t in pop_textures(g) if t.shown and t.calls["SetDrawLayer"][2] == 0]
    assert a  # copy A is visible; B is hidden for the whole hold
    ox, oy = (
        a[0].points[1][4],
        a[0].points[1][5],
    )  # offset = (ring position - P-hat) at most XF_BLOOM_R
    assert abs(ox) <= 18 + 1e-6 and abs(oy) <= 18 + 1e-6 and b == []
    # in flight (p = 0.2 of the stretched flight) the screen-space copy starts near P-hat, not at the default point
    g.stub.tick(0.26 - 0.1 + 0.2 * g.db.flightTime * 1.2)  # start delay 0.04 + hold 0.22 are over
    (bt,) = [t for t in stream_textures(g) if t.calls["SetDrawLayer"][2] == 0]
    assert abs(bt.points[1][4] - 700) < 150 and abs(bt.points[1][5] - 500) < 150


# ---------------------------------------------------------------- /xporbs test


def test_test_command_uses_target_estimate_and_prints_it(env):
    g = make(env)
    plate = restricted_plate(g)
    g.stub.plates["target"] = plate
    g.stub.units["target"] = g.env.lua.table_from({"guid": "G1", "isTarget": True})
    g.stub.setTargetFrame(250, 900, True)
    hover(g, cursor=(700, 500))
    g.slash("test 5 popstream")
    line = chat_lines(g)[-1]
    assert "est=mouseover w=1.00" in line and line.endswith(
        "pop=yes stream=estimate style=popstream"
    )
    g.stub.tick(3)
    g.stub.units[
        "target"
    ].guid = "OTHER"  # a different target: no sample, so the default estimate (the portrait is no longer used)
    g.slash("test 5 popstream")
    line = chat_lines(g)[-1]
    assert "est=default w=0.00" in line and line.endswith(
        "pop=yes stream=estimate style=popstream"
    )
    g.stub.tick(3)
    g.slash("test 5 crossfade")
    assert chat_lines(g)[-1].endswith("pop=no stream=estimated style=crossfade")
    assert g.stub.restrictedHits == 0


def test_flash_and_tunables_smoke(env):
    """Arrival flash is bigger and brighter (alpha 0.6 + 0.08/arrival, w = size*12, h = w/7, 0.4 s)."""
    g = make(env)
    burst(g, n=1, x=300, y=300, kind="kill")
    for _ in range(200):
        g.stub.tick(0.01)
        flashes = [
            f
            for f in g.stub.frames.values()
            if f.kind == "Texture" and f.shown and f.width == g.db.size * 12
        ]
        if flashes:
            break
    else:
        pytest.fail("flash never shown")
    f = flashes[0]
    assert f.height == pytest.approx(g.db.size * 12 / 7)
    assert f.alpha == pytest.approx(0.68 * (1 - 0.01 / 0.4), abs=0.005)  # one 10 ms step into the 0.4 s fade
    for _ in range(50):
        g.stub.tick(0.01)
    assert not any(t.shown for t in flashes)

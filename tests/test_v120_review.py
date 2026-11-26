"""Code-review fixes: string escapes, secret-marker pairing window, minimap close in combat, mouseover lift without a
readable zoom, "other" bursts ignoring the zoom-scaled spread, the shared zoom-points cap, the SP_PROFILE scratch."""

import re

import pytest
from conftest import ROOT, addon_files
from test_killmatcher import Rig
from test_m5 import show
from test_p2_styles import fire_known, max_dist, recs, seeded
from test_p2_zoom import make as make_zoom
from test_p2a import NAME, SETTINGS_PANEL
from test_p2a import make as make_p2a
from test_v09 import make
from test_v010 import hover, mo_estimate

# ---------------------------------------------------------------- 1. string escapes (Lua 5.1 drops unknown ones)

VALID_ESCAPES = set("ntrabfv\\\"'0123456789\n")


def bad_escapes(src):
    """(line, escape) for every backslash in a string literal that isn't a valid Lua 5.1 escape. Comments are skipped."""
    out = []
    for no, line in enumerate(src.splitlines(), 1):
        quote, i = None, 0
        while i < len(line):
            c = line[i]
            if quote is None:
                if line.startswith("--", i):
                    break
                if c in "\"'":
                    quote = c
            elif c == "\\":
                if i + 1 < len(line) and line[i + 1] not in VALID_ESCAPES:
                    out.append((no, line[i : i + 2]))
                i += 1
            elif c == quote:
                quote = None
            i += 1
    return out


def test_scanner_flags_a_single_backslash_path():
    assert bad_escapes('x = "Interface\\Tooltips\\UI"') == [(1, "\\T"), (1, "\\U")]
    assert bad_escapes('x = "Interface\\\\Tooltips" -- "a\\b\\q"') == []
    assert bad_escapes('x = "a\\n\\t\\\\ \\"q\\" \\065"') == []


@pytest.mark.parametrize("rel", [f for f in addon_files() if f.endswith(".lua")])
def test_no_invalid_string_escapes(rel):
    assert bad_escapes((ROOT / rel).read_text(encoding="utf-8")) == []


# ---------------------------------------------------------------- 2. secret markers pair only with nearby deaths


@pytest.fixture
def rig(env):
    r = Rig(env)
    r.secret = lambda: r.m.AddSecretChat(r.m)
    return r


def test_secret_marker_ignores_a_death_older_than_the_window(rig):
    rig.death("old")  # t = 0, never polled
    rig.at(3.0)
    rig.secret()
    rig.delta(50)
    assert rig.poll() == []  # not a kill
    rig.at(3.5)
    (b,) = rig.poll()
    assert b.kind == "other" and b.amount == 50
    s = rig.stats()
    assert s.secret == 0 and s.other == 1 and s.dropped == 1


def test_secret_marker_still_pairs_a_recent_death(rig):
    rig.death("d1")
    rig.at(0.9)
    rig.secret()
    rig.delta(50)
    (b,) = rig.poll()
    assert (b.kind, b.guid, b.secret, b.amount) == ("kill", "d1", True, 50)
    assert rig.stats().secret == 1


def test_secret_marker_pairs_a_death_that_comes_after_it(rig):
    rig.secret()
    rig.delta(50)
    rig.at(0.9)
    rig.death("late")
    (b,) = rig.poll()
    assert (b.kind, b.guid) == ("kill", "late")


def test_secret_marker_skips_the_stale_death_for_a_recent_one(rig):
    rig.death("old")
    rig.at(3.0)
    rig.death("new")
    rig.secret()
    rig.delta(50)
    (b,) = rig.poll()
    assert (b.kind, b.guid) == ("kill", "new")


# ---------------------------------------------------------------- 3. minimap close


def stub_settings(m, close=True, combat=None):
    """An open Settings window on our category. HideUIPanel is a recorder that hides the frame it is given."""
    sp = m.lua.eval(SETTINGS_PANEL)(m.G)
    sp.shown = True
    m.lua.eval(
        """function(G, sp, close, combat)
            sp.hideUI = 0
            sp.closes = 0
            sp.closeArg = nil
            sp.Close = nil
            if close == "error" then
                function sp:Close(skip) self.closeArg = skip; self.closes = self.closes + 1; error("boom") end
            elseif close then
                function sp:Close(skip) self.closeArg = skip; self.shown = false; self.closes = self.closes + 1 end
            end
            G.HideUIPanel = function(f) sp.hideUI = sp.hideUI + 1; f:Hide() end
            G.InCombatLockdown = function() return combat end
        end"""
    )(m.G, sp, close, combat)
    show(m)
    m.opt.panel.Show(m.opt.panel)
    return sp


def test_minimap_close_in_combat_does_nothing_but_say_so(env):
    m = make_p2a(env)
    sp = stub_settings(m, combat=True)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.shown is True and sp.hides == 0 and sp.closes == 0 and sp.hideUI == 0
    assert len(m.opened) == 0  # and it does not reopen either
    assert any("can't close the options in combat" in line for line in m.say())


def test_minimap_close_out_of_combat_prefers_settingspanel_close(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=True, combat=False)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.shown is False and sp.closes == 1 and sp.hideUI == 0 and sp.hides == 0


def test_minimap_close_skips_the_transition_back_to_the_game_menu(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=True, combat=False)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.closeArg is True  # Close(true): no ToggleGameMenu, so no protected-call chain


def test_minimap_close_error_falls_back_to_hideuipanel(env):
    m = make_p2a(env)
    sp = stub_settings(m, close="error", combat=False)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.closes == 1 and sp.hideUI == 1 and sp.shown is False


def test_minimap_close_in_combat_never_calls_close_or_hideuipanel(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=True, combat=True)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.closes == 0 and sp.hideUI == 0 and sp.closeArg is None


def test_minimap_close_falls_back_to_hideuipanel(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=False, combat=False)
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "LeftButton")
    assert sp.shown is False and sp.hideUI == 1  # HideUIPanel did the hiding


def test_minimap_close_never_calls_settingspanel_hide_itself(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=False, combat=False)
    m.lua.eval("function(G) G.HideUIPanel = function() end end")(
        m.G
    )  # a HideUIPanel that does nothing
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.hides == 0


def test_minimap_close_works_when_incombatlockdown_is_missing(env):
    m = make_p2a(env)
    sp = stub_settings(m, close=True, combat=False)
    m.G.InCombatLockdown = None
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.shown is False and sp.closes == 1


# ---------------------------------------------------------------- 4. mouseover lift needs a readable zoom


def test_estimate_drops_the_head_lift_only_with_a_readable_zoom(env):
    g = make_zoom(env)
    g.slash("zoomanchor on")
    head = g.ns.MobEstimate.HEAD_OFFSET
    hover(g, cursor=(700, 500))
    assert mo_estimate(g, "G1")[1] == pytest.approx(
        500
    )  # readable zoom (stub default): body
    g.stub.zoom = "far"  # unreadable: Orbs leaves the frames at the head, so the estimate lifts again
    assert mo_estimate(g, "G1")[1] == pytest.approx(500 + head)
    g.stub.zoom = g.stub.SECRET
    assert mo_estimate(g, "G1")[1] == pytest.approx(500 + head)
    g.stub.zoom = 15
    g.slash("zoomanchor off")
    assert mo_estimate(g, "G1")[1] == pytest.approx(500 + head)


# ---------------------------------------------------------------- 5. "other" bursts ignore the zoom-scaled spread


def test_other_burst_start_disc_does_not_scale_with_zoom_but_a_kill_does(env):
    seeded(env)
    g = make(env, fixed_random=False)
    g.stub.zoom = 5  # factor 2
    g.db.zoomSpread = True
    fire_known(g, "stream", 40, plate=None, kind="other")
    assert max_dist(recs(g)) <= 6 + 1e-9  # START_RADIUS, unscaled
    g.tick(0.05, 80)
    fire_known(g, "stream", 40, plate=None, kind="kill")
    assert max_dist(recs(g)) > 6 * 2 * 0.85  # the located kill still scales


# ---------------------------------------------------------------- 6. one zoom-points cap


def test_calib_uses_the_core_zoom_points_cap(env):
    env.load_addon()
    assert env.ns.ZOOM_POINTS_MAX == 8
    assert not re.search(
        r"POINTS_MAX\s*=\s*\d", (ROOT / "Calib.lua").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------- 7. no styleOf wrapper


def test_orbs_has_no_styleof_wrapper():
    assert "styleOf" not in (ROOT / "Orbs.lua").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 8. SP_PROFILE plan uses scratch arrays


def sp_profile(g):
    """SP_PROFILE, reached through the XF_PROFILE upvalue of Orbs.Burst (test-only peek)."""
    return g.env.lua.eval(
        """function(burst)
            local i = 1
            while true do
                local n, v = debug.getupvalue(burst, i)
                if not n then return nil end
                if n == "XF_PROFILE" then return v.sp end
                i = i + 1
            end
        end"""
    )(g.orbs.Burst)


def test_streampop_plan_reuses_scratch_arrays_and_trims_stale_slots(env):
    g = make(env)
    sp = sp_profile(g)
    assert sp is not None and sp.dist is not None and sp.idx is not None
    dist, idx = sp.dist, sp.idx

    def direct(n):
        fire_known(g, "popstream", n, plate=None, popMode="direct")

    direct(10)
    g.tick(0.05, 80)
    assert len(idx) == 10
    direct(3)
    same = g.env.lua.eval("function(a, b) return rawequal(a, b) end")
    assert same(sp.dist, dist) and same(sp.idx, idx)  # same tables, not reallocated
    assert (
        len(idx) == 3
    )  # the 7 stale slots are gone, so table.sort only sees this burst
    assert sorted(idx[i] for i in (1, 2, 3)) == [1, 2, 3]
    holds = sorted(sp.blooms[i] for i in (1, 2, 3))
    assert holds == [
        pytest.approx(sp.bloomMin + sp.bloomSpan * r / 2) for r in range(3)
    ]

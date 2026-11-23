"""v0.15: Arrival panel order/labels, rested fallback detection (OrbMath.RestedFallback + Kills), exhaustion diagnostics."""

import re

import pytest
from test_m5 import build, ctl, panel_texts, show
from test_plates_stub import CHAT, CHAT_RESTED, Game
from test_v014 import fontstring


# ---------------------------------------------------------------- A. panel


@pytest.fixture
def m(env):
    return build(env)


def y_of(m, key):
    return -m.opt.rows[key].points[1][5]


def test_arrival_rows_are_in_the_requested_order(m):
    order = [
        "glowShape",
        "glowShapeDesc",
        "glowOffsetX",
        "glowOffsetY",
        "glow",
        "glowIntensity",
    ]
    ys = [y_of(m, k) for k in order]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)
    desc_y = -m.opt.offsetDesc.points[1][5]
    assert (
        y_of(m, "glowOffsetY") < desc_y < y_of(m, "glow")
    )  # the offsets' description sits between them
    assert y_of(m, "glowIntensity") == y_of(m, "glow") + 28


def test_arrival_labels_renamed(m):
    texts = panel_texts(m)
    for t in (
        "Target frame shape",
        "Target offset X",
        "Target offset Y",
        "Show glow",
        "Glow intensity",
    ):
        assert t in texts, t
    assert "Shape" not in texts and "Offset X" not in texts and "Offset Y" not in texts


@pytest.mark.parametrize(
    "name",
    ["Target frame shape", "Target offset X", "Target offset Y", "Glow intensity"],
)
def test_longer_labels_fit_the_label_column(m, name):
    lab = fontstring(m, name)
    x = lab.points[1][4]
    assert x == 32
    assert (
        x + lab.GetStringWidth(lab) <= 257 - 8
    )  # clear of the control column (checkbox 257, sliders 260)


def test_only_intensity_dims_with_show_glow_off(m):
    show(m)
    m.stub.click(ctl(m, "glow"))
    assert m.opt.rows["glowIntensity"].alpha not in (None, 1)
    for k in ("glowShape", "glowOffsetX", "glowOffsetY", "glow"):
        assert m.opt.rows[k].alpha in (None, 1), k


# ---------------------------------------------------------------- B. RestedFallback (pure)


@pytest.fixture
def fb(env):
    g = Game(env)
    f = g.ns.OrbMath.RestedFallback
    return lambda *a: tuple(f(*a))


def test_fallback_chat_wins_over_everything(fb):
    assert fb(100, 40, 30, 500) == (40, "chat")
    assert fb(100, 0, 30, 500) == (0, "chat")


def test_fallback_pool_drop(fb):
    assert fb(100, None, 30, 500) == (15, "pool")
    assert fb(100, None, 30, None) == (15, "pool")


def test_fallback_drop_is_capped_at_the_amount(fb):
    assert fb(100, None, 250, 500) == (50, "pool")


def test_fallback_zero_or_bad_drop_falls_through_to_estimate(fb):
    assert fb(100, None, 0, 500) == (50, "estimate")
    assert fb(100, None, -5, 500) == (50, "estimate")
    assert fb(100, None, "x", 500) == (50, "estimate")


def test_fallback_estimate_rounds_half_up_and_caps_at_the_pool(fb):
    assert fb(101, None, None, 500) == (51, "estimate")
    assert fb(99, None, None, 500) == (50, "estimate")
    assert fb(100, None, None, 20) == (10, "estimate")
    assert fb(1, None, None, 500) == (1, "estimate")


def test_fallback_pool_drop_equal_to_amount_is_half(fb):
    assert fb(246, None, 246, 1832) == (123, "pool")  # in-game log: exhDrop == delta


def test_fallback_pool_drop_below_amount_is_drop_over_two(fb):
    assert fb(100, None, 40, 500) == (20, "pool")
    assert fb(100, None, 41, 500) == (21, "pool")  # half up


def test_fallback_pool_drop_above_amount_is_amount_over_two(fb):
    assert fb(100, None, 300, 500) == (50, "pool")


def test_fallback_estimate_with_small_pool_is_pool_over_two(fb):
    assert fb(100, None, None, 30) == (15, "estimate")
    assert fb(100, None, None, 31) == (16, "estimate")
    assert fb(100, None, None, 100) == (50, "estimate")


def test_fallback_none_cases(fb):
    assert fb(100, None, None, 0) == (None, "none")
    assert fb(100, None, None, None) == (None, "none")
    assert fb(100, None, None, -3) == (None, "none")
    assert fb(0, None, None, 500) == (None, "none")
    assert fb(None, None, None, 500) == (None, "none")
    assert fb(100, None, 0, 0) == (None, "none")


def test_fallback_secret_pool_counts_as_unknown(env):
    g = Game(env)
    secret = (
        g.stub.SECRET
    )  # unreadable values are not numbers, so the logic never uses them
    assert tuple(g.ns.OrbMath.RestedFallback(100, None, None, secret)) == (None, "none")
    assert tuple(g.ns.OrbMath.RestedFallback(100, None, secret, None)) == (None, "none")


# ---------------------------------------------------------------- B. Kills end to end


def kill(g, msg=CHAT, xp=None, ticks=3):
    """One kill: a plate that dies, its chat line, optionally the XP update; then let the matcher run."""
    g.plate(unit="nameplate1", guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.chat(msg)
    if xp is not None:
        g.stub.setXP(xp)
    g.tick(0.5, ticks)


def setup(env, pre=None):
    g = Game(env, probe=False, pre=pre)
    g.fake_orbs_on()
    g.db.questBursts = True
    return g


def burst_logs(g):
    return [x for x in g.log() if "BURST" in x]


def src_of(line):
    return re.search(r"restedSrc=(\w+)", line).group(1)


def test_plain_chat_while_rested_estimates_and_goes_purple(env):
    g = setup(env)
    g.stub.exh = 500
    kill(g, xp=50)
    (b,) = g.bursts()
    assert b["n"] == 14 and b["nPurple"] == 7  # estimate 25 of 50
    line = burst_logs(g)[-1]
    assert src_of(line) == "estimate" and "rested=25 " in line


def test_drop_known_before_emit_uses_the_pool(env):
    g = setup(env)
    g.stub.exh = 500
    g.ns.fire("PLAYER_ENTERING_WORLD")  # baseline 500
    g.plate(guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.stub.exh = 490
    g.stub.setXP(50)  # XP update first: exhDrop 10
    g.chat()
    g.tick(0.5, 3)
    (b,) = g.bursts()
    assert b["nPurple"] == 1  # rested 5 (half of the 10 covered): floor(14 * 5 / 50 + 0.5); the estimate would give 7
    line = burst_logs(g)[-1]
    assert src_of(line) == "pool" and "rested=5 " in line


@pytest.mark.parametrize("early", [True, False])
def test_exhaustion_event_around_the_xp_update_counts_once(env, early):
    g = setup(env)
    g.stub.exh = 500
    g.ns.fire("PLAYER_ENTERING_WORLD")
    g.plate(guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    if early:  # UPDATE_EXHAUSTION first, then the XP update
        g.stub.exh = 490
        g.ns.fire("UPDATE_EXHAUSTION")
        g.stub.setXP(50)
    else:  # XP update first (pool not yet shrunk), then UPDATE_EXHAUSTION shortly after
        g.stub.setXP(50)
        g.stub.exh = 490
        g.tick(0.1)
        g.ns.fire("UPDATE_EXHAUSTION")
    g.chat()
    g.tick(0.5, 3)
    (b,) = g.bursts()
    assert b["nPurple"] == 1
    assert src_of(burst_logs(g)[-1]) == "pool"


def test_xp_update_after_emit_does_not_leak_its_drop_to_the_next_kill(env):
    g = setup(env)
    g.stub.exh = 500
    g.ns.fire("PLAYER_ENTERING_WORLD")
    kill(g, ticks=1)  # emitted before its XP update: estimate
    g.stub.exh = 475
    g.stub.setXP(50)  # late update, drop 25, belongs to the first burst
    g.tick(0.2)
    kill(
        g, xp=100
    )  # same amount again, no drop this time: estimate, not a stolen "pool"
    assert [src_of(x) for x in burst_logs(g)] == ["estimate", "estimate"]


def test_not_rested_gives_none_and_no_purple(env):
    g = setup(env)
    kill(g, xp=50)
    (b,) = g.bursts()
    assert b["nPurple"] == 0
    line = burst_logs(g)[-1]
    assert src_of(line) == "none" and "rested=nil " in line


def test_pool_zero_is_not_rested(env):
    g = setup(env)
    g.stub.exh = 0
    kill(g, xp=50)
    assert g.bursts()[0]["nPurple"] == 0 and src_of(burst_logs(g)[-1]) == "none"


@pytest.mark.parametrize("secret", [False, True])
def test_unreadable_or_failing_exhaustion_is_unknown(env, secret):
    g = setup(env)
    if secret:
        g.stub.exh = g.stub.SECRET
    else:
        g.stub.exhError = True
    kill(g, xp=50)
    assert g.bursts()[0]["nPurple"] == 0 and src_of(burst_logs(g)[-1]) == "none"
    assert not g.has_log("Kills error")


def test_rested_tint_off_no_purple_whatever_the_source(env):
    g = setup(env)
    g.db.restedTint = False
    g.stub.exh = 500
    kill(g, xp=50)
    assert g.bursts()[0]["nPurple"] == 0 and src_of(burst_logs(g)[-1]) == "estimate"


def test_rested_tint_off_with_chat_bonus(env):
    g = setup(env)
    g.db.restedTint = False
    kill(g, CHAT_RESTED, xp=50)
    assert g.bursts()[0]["nPurple"] == 0 and src_of(burst_logs(g)[-1]) == "chat"


def test_chat_rested_wins_over_the_pool(env):
    g = setup(env)
    g.stub.exh = 500
    kill(g, CHAT_RESTED, xp=50)
    assert g.bursts()[0]["nPurple"] == 7 and src_of(burst_logs(g)[-1]) == "chat"


def test_estimate_is_capped_by_the_pool(env):
    g = setup(env)
    g.stub.exh = 10
    kill(g, xp=50)
    assert g.bursts()[0]["nPurple"] == 1  # pool 10 covers 10 of 50: rested 5, floor(14 * 5 / 50 + 0.5)


def test_other_bursts_ignore_the_pool(env):
    g = setup(env)
    g.stub.exh = 500  # a pool must not tint quest XP
    g.chat("You gain 100 experience.")
    g.stub.setXP(100)
    g.tick(0.5, 3)
    (b,) = g.bursts()
    assert b["kind"] == "other" and b["nPurple"] == 0
    assert src_of(burst_logs(g)[-1]) == "none"


def test_other_burst_with_a_chat_bonus_is_purple(env):
    g = setup(env)
    g.chat("You gain 100 experience. (+50 exp Rested bonus)")
    g.stub.setXP(100)
    g.tick(0.5, 3)
    (b,) = g.bursts()
    assert b["kind"] == "other" and b["nPurple"] > 0
    assert src_of(burst_logs(g)[-1]) == "chat"


# ---------------------------------------------------------------- B. diagnostics


def chat_lines(g):
    return [x for x in g.log() if " CHAT " in x]


def tail_of(line):
    return re.search(r'tail="(.*)"$', line).group(1)


def test_chat_line_tail_has_no_mob_name(env):
    g = setup(env)
    g.chat()
    g.chat(CHAT_RESTED)
    plain, rested = chat_lines(g)
    assert tail_of(plain) == ""
    assert tail_of(rested) == " (+25 exp Rested bonus)"
    assert "Boar" not in plain and "Boar" not in rested


def test_chat_tail_starts_after_the_first_experience_and_truncates(env):
    g = setup(env)
    g.chat("Wolf dies, you gain 50 experience. junk experience." + "z" * 100)
    t = tail_of(chat_lines(g)[-1])
    assert t.startswith(" junk experience.") and len(t) == 60 and "Wolf" not in t


def test_chat_tail_omitted_when_unreadable(env):
    g = setup(env)
    g.chat(g.stub.SECRET)
    (line,) = chat_lines(g)
    assert "msgReadable=false" in line and "tail=" not in line


def test_xpupdate_logs_exh_and_exhdrop(env):
    g = setup(env)
    g.stub.exh = 500
    g.ns.fire("PLAYER_ENTERING_WORLD")
    g.stub.setXP(50)
    g.stub.exh = 480
    g.stub.setXP(100)
    lines = [x for x in g.log() if "XPUPDATE delta" in x]
    assert lines[0].endswith("exh=500 exhDrop=nil")
    assert lines[1].endswith("exh=480 exhDrop=20")


def test_xpupdate_exh_nil_when_not_rested_or_secret(env):
    g = setup(env)
    g.stub.setXP(50)
    g.stub.exh = g.stub.SECRET
    g.stub.setXP(100)
    lines = [x for x in g.log() if "XPUPDATE delta" in x]
    assert len(lines) == 2 and all(x.endswith("exh=nil exhDrop=nil") for x in lines)


def test_pool_refilling_is_not_a_drop(env):
    g = setup(env)
    g.stub.exh = 100
    g.ns.fire("PLAYER_ENTERING_WORLD")
    g.stub.exh = 300
    g.stub.setXP(50)
    assert [x for x in g.log() if "XPUPDATE delta" in x][-1].endswith(
        "exh=300 exhDrop=nil"
    )


def test_update_exhaustion_is_logged(env):
    g = setup(env)
    g.stub.exh = 500
    g.ns.fire("PLAYER_ENTERING_WORLD")
    g.stub.exh = 460
    g.ns.fire("UPDATE_EXHAUSTION")
    assert any(x.endswith("EXH exh=460 drop=40") for x in g.log())


def test_update_exhaustion_registered_via_pcall(env):
    g = Game(env)
    assert g.ns.Kills.exhaustionRegistered is True
    assert g.ns.Kills.frame.events["UPDATE_EXHAUSTION"]


def test_update_exhaustion_registration_failure_does_not_crash(env):
    def pre(stub):
        stub.failEvents["UPDATE_EXHAUSTION"] = True

    g = setup(env, pre=pre)
    assert g.ns.Kills.exhaustionRegistered is False
    g.stub.exh = 500
    kill(g, xp=50)  # the rest of the pipeline still works, estimate included
    assert g.bursts()[0]["nPurple"] == 7


def test_logs_never_contain_names(env):
    g = setup(env)
    g.stub.exh = 500
    kill(g, xp=50)
    assert not any("Boar" in x for x in g.log())


def test_same_kill_gives_the_same_purple_via_pool_and_estimate(env):
    """Forever drains the pool by the whole gain, so a pool drop of 246 and an estimate for 246 must agree."""
    g = setup(env)
    g.stub.exh = 1832
    g.ns.fire("PLAYER_ENTERING_WORLD")
    # kill 1, pool route: the drop of the full 246 arrives with the XP update
    g.plate(guid="G1", name="Boar", cx=300, cy=200)
    g.tick(0.05)
    g.stub.removePlate("nameplate1", True)
    g.stub.exh = 1832 - 246
    g.stub.setXP(246)
    g.chat("Boar dies, you gain 246 experience.")
    g.tick(0.5, 3)
    g.tick(2, 2)
    # kill 2, estimate route: the pool does not move, so no drop is seen
    kill(g, "Boar dies, you gain 246 experience.", xp=492)
    b1, b2 = g.bursts()
    lines = burst_logs(g)
    assert [src_of(x) for x in lines] == ["pool", "estimate"]
    assert all("rested=123 " in x for x in lines)
    assert b1["nPurple"] == b2["nPurple"] > 0

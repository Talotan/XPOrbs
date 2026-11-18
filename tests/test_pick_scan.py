"""/xporbs pick for XP bars that ignore the mouse: EnumerateFrames scan, pick by name, KNOWN_BARS auto-detect, and
StatusBar fill points in every direction."""

import pytest
from conftest import TESTS
from test_m5 import build


@pytest.fixture
def m5(env):
    return build(env)


def click(m):
    m.slash("pick")
    m.stub.mouseDown("LeftButton")


def draw_only(m, name, left=400, bottom=100, w=300, h=20, parent=None):
    return m.stub.drawOnly(name, left, bottom, w, h, parent)


def over(m, x, y):
    m.stub.cursor.x, m.stub.cursor.y = x, y


def label_text(m):
    hl = m.ns.Target.highlight
    for f in m.stub.frames.values():
        if f.kind == "FontString" and m.lua.eval("rawequal")(f.parentFrame, hl):
            return f.text
    return None


def with_v09(m):
    m.load_chunk(TESTS / "stubs_v09.lua", "stubs_v09.lua")(m.ns)


def place(f, left, bottom, w, h):
    f.left, f.bottom, f.width, f.height = left, bottom, w, h


# ---------------------------------------------------------------- click picks a draw-only frame


def test_click_over_a_draw_only_bar_picks_it(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame == "EQOL_XPBar"
    assert "XP bar frame set to EQOL_XPBar" in m5.say()[-1]


def test_click_away_from_it_picks_nothing_and_hints_at_the_name_form(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 100, 900)
    click(m5)
    assert m5.db.targetFrame is None
    line = m5.say()[-1]
    assert (
        "no named frame" in line
        and "/xporbs pick <FrameName>" in line
        and "/fstack" in line
    )


def test_a_mouse_focus_frame_wins_and_no_scan_runs(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    m5.stub.focus = m5.stub.namedFrame("ClickyThing")
    before = m5.stub.enumStarts
    click(m5)
    assert m5.db.targetFrame == "ClickyThing" and m5.stub.enumStarts == before


def test_smallest_frame_wins_and_ties_go_to_the_later_one(m5):
    draw_only(m5, "Big", 300, 80, 600, 100)
    draw_only(m5, "Small", 450, 100, 100, 20)
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame == "Small"
    draw_only(m5, "SameSize", 450, 100, 100, 20)
    click(m5)
    assert m5.db.targetFrame == "SameSize"


def test_a_named_child_of_a_named_holder_picks_the_smaller_child(m5):
    parent = draw_only(m5, "Holder", 300, 80, 600, 100)
    draw_only(m5, "Kid", 450, 100, 100, 20, parent)
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame == "Kid"


def test_unnamed_and_hidden_frames_are_ignored(m5):
    anon = m5.lua.eval("CreateFrame")("Frame", None, m5.G.UIParent)
    place(anon, 400, 100, 50, 10)
    hidden = draw_only(m5, "HiddenBar")
    hidden.shown = False
    over(m5, 410, 105)
    click(m5)
    assert m5.db.targetFrame is None


def test_forbidden_frames_are_skipped(m5):
    f = draw_only(m5, "Locked")
    f.forbidden = True
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame is None


def test_the_area_cap_skips_full_screen_frames(m5):
    over(m5, 500, 110)
    draw_only(m5, "FullScreen", 0, 0, 1920, 1080)
    draw_only(m5, "TooBig", 0, 0, 1920, 541)  # just over half of UIParent
    click(m5)
    assert m5.db.targetFrame is None
    draw_only(m5, "ExactlyHalf", 0, 0, 1920, 540)  # at the cap: allowed
    click(m5)
    assert m5.db.targetFrame == "ExactlyHalf"


def test_our_own_frames_are_never_scanned(m5):
    m5.slash("test 5")
    ov = m5.orbs.overlay
    ov.name = "XPOrbsOverlayForTest"
    place(ov, 400, 100, 100, 20)
    over(m5, 410, 105)
    click(m5)
    assert m5.db.targetFrame is None


def test_no_enumerate_frames_means_no_scan(m5):
    m5.G.EnumerateFrames = None
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame is None and "no named frame" in m5.say()[-1]


def test_a_raising_enumerate_frames_is_survived(m5):
    m5.lua.execute("EnumerateFrames = function() error('boom') end")
    over(m5, 500, 110)
    click(m5)
    assert m5.db.targetFrame is None and not m5.ns.Target.IsPicking(m5.ns.Target)


# ---------------------------------------------------------------- nameplates are never considered or measured


def test_plates_and_their_children_are_never_considered_or_measured(m5):
    with_v09(m5)
    create = m5.lua.eval("CreateFrame")
    plate = m5.stub.addRestrictedPlate("nameplate1", m5.lua.table_from({"guid": "G1"}))
    place(plate, 400, 100, 100, 20)
    plate.name = "InnocentLookingName"  # a live plate, found by identity
    kid = create("Frame", "PlateKid", plate)
    kid.name = "PlateKid"
    kid.restricted = True
    place(kid, 400, 100, 10, 10)
    named_plate = create("Frame", "NamePlate42", m5.G.UIParent)
    named_plate.name = "NamePlate42"
    named_plate.restricted = True
    place(named_plate, 400, 100, 10, 10)
    deep = create("Frame", "DeepKid", named_plate)
    deep.name = "DeepKid"
    deep.restricted = True
    place(deep, 400, 100, 5, 5)
    over(m5, 405, 105)
    click(m5)
    assert m5.db.targetFrame is None
    assert m5.stub.restrictedHits == 0
    m5.slash(
        "pick"
    )  # and hovering (the throttled highlight scan) never measures them either
    m5.run(1.0)
    assert m5.stub.restrictedHits == 0 and m5.ns.Target.scanCount > 0


def test_naming_a_plate_is_refused(m5):
    with_v09(m5)
    create = m5.lua.eval("CreateFrame")
    plate = m5.stub.addRestrictedPlate("nameplate1", m5.lua.table_from({"guid": "G1"}))
    m5.G.MyPlateGlobal = plate
    kid = create("Frame", "KidOfPlate", plate)
    kid.name = "KidOfPlate"
    kid.restricted = True
    m5.G.KidOfPlate = kid
    np5 = create("Frame", "NamePlate5", m5.G.UIParent)
    np5.name = "NamePlate5"
    m5.G.NamePlate5 = np5
    for name in ("MyPlateGlobal", "KidOfPlate", "NamePlate5"):
        m5.slash(f"pick {name}")
        assert m5.db.targetFrame is None and "can't be used" in m5.say()[-1], name
    assert m5.stub.restrictedHits == 0


# ---------------------------------------------------------------- hover highlight and throttle


def test_hover_highlight_shows_the_scanned_name(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    m5.slash("pick")
    m5.run(0.2)
    assert label_text(m5) == "EQOL_XPBar" and m5.ns.Target.highlight.shown


def test_the_hover_scan_is_throttled_and_only_runs_while_picking(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    m5.run(2.0)  # not picking: no scans
    assert m5.stub.enumStarts == 0 and m5.ns.Target.scanCount == 0
    m5.slash("pick")
    m5.run(1.0, step=0.02)  # 50 ticks at 50 Hz
    scans = m5.ns.Target.scanCount
    assert 3 <= scans <= 5, scans
    m5.stub.mouseDown("RightButton")
    m5.run(1.0)
    assert m5.ns.Target.scanCount == scans


def test_the_hover_scan_skips_when_the_mouse_focus_already_names_a_frame(m5):
    draw_only(m5, "EQOL_XPBar")
    over(m5, 500, 110)
    m5.stub.focus = m5.stub.namedFrame("ClickyThing")
    m5.slash("pick")
    m5.run(1.0)
    assert m5.ns.Target.scanCount == 0 and label_text(m5) == "ClickyThing"


# ---------------------------------------------------------------- /xporbs pick <FrameName>


def test_typed_name_keeps_its_case(m5):
    draw_only(m5, "EQOL_XPBar")
    m5.slash("pick EQOL_XPBar")
    assert m5.db.targetFrame == "EQOL_XPBar"
    line = m5.say()[-1]
    assert "pick: XP bar set to EQOL_XPBar" in line and "hidden" not in line
    assert not m5.ns.Target.IsPicking(m5.ns.Target)


def test_typed_name_of_a_hidden_frame_is_saved_with_a_note(m5):
    f = draw_only(m5, "EQOL_XPBar")
    f.shown = False
    m5.slash("pick EQOL_XPBar")
    assert m5.db.targetFrame == "EQOL_XPBar"
    assert "(hidden right now; orbs use auto-detect until it shows)" in m5.say()[-1]


def test_wrong_case_is_not_a_frame(m5):
    draw_only(m5, "EQOL_XPBar")
    m5.slash("pick eqol_xpbar")
    assert m5.db.targetFrame is None and "no frame called eqol_xpbar" in m5.say()[-1]


def test_bad_names_are_refused_and_change_nothing(m5):
    m5.db.targetFrame = "Keep"
    m5.slash("test 5")
    m5.G.NotAFrame = m5.lua.table_from({"x": 1})
    m5.G.AString = "hello"
    m5.G.WorldFrame = m5.stub.namedFrame("WorldFrame")
    m5.G.OurOverlay = m5.orbs.overlay
    m5.G.OurPanel = m5.opt.panel
    for name in (
        "banana",
        "NotAFrame",
        "AString",
        "UIParent",
        "WorldFrame",
        "OurOverlay",
        "OurPanel",
        "a b c",
    ):
        m5.slash(f"pick {name}")
        assert m5.db.targetFrame == "Keep", name
        assert "pick:" in m5.say()[-1] and "XP bar set" not in m5.say()[-1], name
    assert not m5.ns.Target.IsPicking(m5.ns.Target)


def test_pick_clear_still_works_in_any_case(m5):
    for word in ("clear", "CLEAR"):
        m5.db.targetFrame = "Foo"
        m5.slash(f"pick {word}")
        assert m5.db.targetFrame is None and "auto-detect" in m5.say()[-1]


def test_other_commands_still_get_lowercased_args(m5):
    m5.slash("debug ON")
    assert m5.db.debug is True


def test_help_lists_the_name_form(m5):
    m5.slash("help")
    assert any("pick [clear|FrameName]" in line for line in m5.say())


# ---------------------------------------------------------------- KNOWN_BARS


def test_eqol_bar_is_auto_detected_when_visible(m5):
    m5.stub.xp, m5.stub.xpMax = 500, 1000
    m5.stub.makeBar("EQOL_XPBar", 100, 700, 400, 12, True)
    T = m5.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and T.lastName == "EQOL_XPBar"
    assert x == pytest.approx(300) and y == pytest.approx(706)


def test_a_hidden_eqol_bar_falls_through_to_blizzards(m5):
    m5.stub.makeBar("EQOL_XPBar", 100, 700, 400, 12, False)
    T = m5.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert ok and T.lastName == "MainStatusTrackingBarContainer"


def test_a_users_pick_beats_the_known_bars(m5):
    m5.stub.makeBar("EQOL_XPBar", 100, 700, 400, 12, True)
    m5.stub.makeBar("MyBar", 1000, 300, 200, 10, True)
    m5.db.targetFrame = "MyBar"
    T = m5.ns.Target
    T.GetDestination(T, False, False)
    assert T.lastName == "MyBar"
    m5.db.targetFrame = (
        "NotThere"  # an unavailable pick falls to the known bars before Blizzard's
    )
    T.GetDestination(T, False, False)
    assert T.lastName == "EQOL_XPBar"


# ---------------------------------------------------------------- StatusBar fill points


def test_status_fill_maths(env):
    env.load_addon()
    f = env.ns.OrbMath.StatusFill
    assert tuple(f(100, 200, 400, 20, 0.25, False, False)) == (200, 210)
    assert tuple(f(100, 200, 400, 20, 0.25, False, True)) == (400, 210)
    assert tuple(f(100, 200, 20, 400, 0.25, True, False)) == (110, 300)
    assert tuple(f(100, 200, 20, 400, 0.25, True, True)) == (110, 500)
    assert tuple(f(0, 0, 10, 10, 7, False, False)) == (10, 5)  # clamped high
    assert tuple(f(0, 0, 10, 10, -3, True, False)) == (5, 0)  # clamped low


# (orientation, reverse, expected point at 25 % and at 76 %) for a 400 x 20 horizontal / 20 x 400 vertical bar at
# left 100, bottom 200
DIRECTIONS = [
    ("LEFT", "HORIZONTAL", False, 20, 400, (200, 210), (404, 210)),
    ("RIGHT", "HORIZONTAL", True, 20, 400, (400, 210), (196, 210)),
    ("UP", "VERTICAL", False, 400, 20, (110, 300), (110, 504)),
    ("DOWN", "VERTICAL", True, 400, 20, (110, 500), (110, 296)),
]


@pytest.mark.parametrize("label,orient,reverse,h,w,at25,at76", DIRECTIONS)
def test_eqol_like_bar_aims_at_the_real_fill_point(
    m5, label, orient, reverse, h, w, at25, at76
):
    # width/height here: horizontal = 400 x 20, vertical = 20 x 400 (the params are named for the long axis)
    width, height = (400, 20) if orient == "HORIZONTAL" else (20, 400)
    bar = m5.stub.makeStatusBar(
        "EQOL_XPBar", 100, 200, width, height, 0, 2000, 500, orient, reverse
    )
    T = m5.ns.Target
    m5.stub.xp, m5.stub.xpMax = (
        999,
        1000,
    )  # the XP numbers must be ignored: the bar's own value is what it draws
    for value, want in ((500, at25), (1520, at76)):
        bar.sb.v = value
        x, y, ok = T.GetDestination(T, False, False)
        assert ok and T.lastName == "EQOL_XPBar"
        assert (x, y) == pytest.approx(want), (label, value)
    assert T.lastVertical == (orient == "VERTICAL")


def test_a_secret_status_value_falls_back_to_the_xp_fill_edge(m5):
    bar = m5.stub.makeStatusBar(
        "EQOL_XPBar", 100, 200, 400, 20, 0, 2000, 500, "HORIZONTAL", True
    )
    m5.stub.xp, m5.stub.xpMax = 500, 1000
    for field, secret in (
        ("v", m5.stub.SECRET),
        ("hi", m5.stub.SECRET),
        ("orient", m5.stub.SECRET),
    ):
        saved = bar.sb[field]
        bar.sb[field] = secret
        T = m5.ns.Target
        x, y, ok = T.GetDestination(T, False, False)
        assert ok and (x, y) == pytest.approx((300, 210)), (
            field
        )  # left-to-right at 50 %: today's behaviour
        bar.sb[field] = saved


def test_a_degenerate_range_falls_back(m5):
    m5.stub.makeStatusBar("EQOL_XPBar", 100, 200, 400, 20, 0, 0, 0, "HORIZONTAL", False)
    m5.stub.xp, m5.stub.xpMax = 250, 1000
    T = m5.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert (x, y) == pytest.approx((200, 210))


def test_centre_aiming_ignores_the_status_value(m5):
    m5.stub.makeStatusBar(
        "EQOL_XPBar", 100, 200, 400, 20, 0, 2000, 100, "HORIZONTAL", False
    )
    T = m5.ns.Target
    x, y, ok = T.GetDestination(T, True, False)
    assert (x, y) == pytest.approx((300, 210))


def test_blizzards_non_statusbar_frames_behave_as_before(m5):
    m5.stub.xp, m5.stub.xpMax = 250, 1000
    T = m5.ns.Target
    x, y, ok = T.GetDestination(T, False, False)
    assert T.lastName == "MainStatusTrackingBarContainer" and T.lastVertical is False
    assert (x, y) == pytest.approx((400 + 800 * 0.25, 25))

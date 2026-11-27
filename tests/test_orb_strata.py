"""db.orbStrata: the frame strata of the orb overlay and the pop frames, and the Arrival tab's "Orb layer" dropdown."""

import pytest
from conftest import TESTS, lua_list
from test_m5 import build, ctl, show

ORDER = [
    "BACKGROUND",
    "LOW",
    "MEDIUM",
    "HIGH",
    "DIALOG",
    "FULLSCREEN",
    "FULLSCREEN_DIALOG",
]


@pytest.fixture
def m(env):
    # the plate stubs come along so a burst on a nameplate makes a real pop frame
    m = build(
        env, pre=lambda e: e.load_chunk(TESTS / "stubs_v09.lua", "stubs_v09.lua")(e.ns)
    )
    m.plate_n = 0
    return m


def pop(m):
    """Start one pop on a fresh nameplate."""
    m.plate_n += 1
    plate = m.stub.addRestrictedPlate(
        f"nameplate{m.plate_n}", m.lua.table_from({"canAttack": False})
    )
    return m.orbs.Burst(
        m.orbs,
        m.lua.table_from({"plate": plate, "n": 3, "kind": "kill", "x": 300, "y": 300}),
    )


def strata_of(frame):
    return frame.calls["SetFrameStrata"][1]


def orb_frames(m):
    """The overlay and every pop frame made so far."""
    return [m.ns.Orbs.overlay] + lua_list(m.ns.Orbs.popFrames)


def menu_entries(m):
    dropdown = m.opt.orbStrataDropdown
    dropdown.GenerateMenu(dropdown)
    return lua_list(dropdown.menuRoot.entries)


def test_the_default_is_fullscreen_dialog_on_the_overlay_and_every_pop(m):
    assert m.db.orbStrata == "FULLSCREEN_DIALOG"
    pop(m)
    frames = orb_frames(m)
    assert len(frames) >= 2
    for frame in frames:
        assert strata_of(frame) == "FULLSCREEN_DIALOG"


def test_the_overlay_and_pops_follow_the_saved_setting(m):
    m.db.orbStrata = "HIGH"
    pop(m)
    frames = orb_frames(m)
    assert len(frames) >= 2
    for frame in frames:
        assert strata_of(frame) == "HIGH"


def test_changing_the_setting_updates_existing_frames_and_later_pops(m):
    pop(m)
    before = len(lua_list(m.ns.Orbs.popFrames))
    assert before >= 1
    m.db.orbStrata = "MEDIUM"
    m.ns.Orbs.ApplyStrata()
    for frame in orb_frames(m):
        assert strata_of(frame) == "MEDIUM"
    pop(
        m
    )  # the first pop is still flying, so this one needs a new frame made after the change
    assert len(lua_list(m.ns.Orbs.popFrames)) > before
    for frame in orb_frames(m):
        assert strata_of(frame) == "MEDIUM"


def test_apply_before_any_burst_is_harmless(m):
    m.db.orbStrata = "LOW"
    m.ns.Orbs.ApplyStrata()  # no overlay and no pops yet
    pop(m)
    assert strata_of(m.ns.Orbs.overlay) == "LOW"


@pytest.mark.parametrize("bad", ["TOOLTIP", "banana", "", 42, True])
def test_an_invalid_saved_value_sanitizes_to_the_default(env, bad):
    m = build(
        env,
        pre=lambda e: e.G.__setitem__("XPOrbsDB", e.lua.table_from({"orbStrata": bad})),
    )
    assert m.G.XPOrbsDB.orbStrata == "FULLSCREEN_DIALOG"


def test_an_invalid_live_value_draws_in_the_default(m):
    m.db.orbStrata = "TOOLTIP"
    assert m.ns.Orbs.Strata() == "FULLSCREEN_DIALOG"
    pop(m)
    assert strata_of(m.ns.Orbs.overlay) == "FULLSCREEN_DIALOG"


def test_slash_reset_restores_the_default_and_moves_the_frames(m):
    m.db.orbStrata = "BACKGROUND"
    pop(m)
    m.ns.Orbs.ApplyStrata()
    assert strata_of(m.ns.Orbs.overlay) == "BACKGROUND"
    m.slash("reset")
    assert m.db.orbStrata == "FULLSCREEN_DIALOG"
    for frame in orb_frames(m):
        assert strata_of(frame) == "FULLSCREEN_DIALOG"


# ---------------------------------------------------------------- the Arrival tab row


def test_the_dropdown_lists_the_seven_layers_with_the_default_marked(m):
    show(m)
    entries = menu_entries(m)
    assert [str(e["text"]) for e in entries] == [
        "Background",
        "Low",
        "Medium",
        "High",
        "Dialog",
        "Fullscreen",
        "Fullscreen Dialog (default)",
    ]
    assert [bool(e["selected"]) for e in entries] == [False] * 6 + [True]


def test_picking_a_layer_saves_it_and_moves_the_live_frames(m):
    show(m)
    pop(m)
    assert m.stub.pickMenu(m.opt.orbStrataDropdown, "Dialog")
    assert m.db.orbStrata == "DIALOG"
    for frame in orb_frames(m):
        assert strata_of(frame) == "DIALOG"
    assert [bool(e["selected"]) for e in menu_entries(m)] == [False] * 4 + [True] + [
        False
    ] * 2


def test_the_arrows_step_through_the_layers(m):
    show(m)
    m.opt.orbStrataDropdown.Decrement(m.opt.orbStrataDropdown)
    assert m.db.orbStrata == "FULLSCREEN"


def test_the_reset_button_shows_when_changed_and_restores_the_layer(m):
    show(m)
    pop(m)
    button = m.opt.resets["orbStrata"]
    assert not button.shown
    m.stub.pickMenu(m.opt.orbStrataDropdown, "Low")
    assert button.shown
    m.stub.click(button)
    assert m.db.orbStrata == "FULLSCREEN_DIALOG" and not button.shown
    for frame in orb_frames(m):
        assert strata_of(frame) == "FULLSCREEN_DIALOG"
    assert menu_entries(m)[6]["selected"]


def test_each_layer_has_a_menu_tooltip_and_the_low_ones_warn(m):
    show(m)
    for entry, name in zip(menu_entries(m), ORDER, strict=True):
        seen = []
        tooltip = m.lua.table_from(
            {
                "SetText": lambda _self, t, *a, seen=seen: seen.append(t),
                "AddLine": lambda _self, t, *a, seen=seen: seen.append(t),
            }
        )
        entry["tooltipFn"](tooltip, entry)
        body = seen[-1]
        if name == "FULLSCREEN_DIALOG":
            assert (
                body
                == "Above almost everything, including the game menu and other addons' windows."
            )
        else:
            assert "game menu and popups then draw over the orbs" in body
            assert "Test Kill may pass behind the preview windows" in body


def test_the_row_sits_below_the_glow_intensity_row(m):
    show(m)
    rows = m.opt.rows
    # y grows downwards, so a lower row has the more negative offset
    assert rows["orbStrata"].points[1][5] < rows["glowIntensity"].points[1][5]
    assert ctl(m, "orbStrata") is m.opt.orbStrataDropdown or ctl(m, "orbStrata")

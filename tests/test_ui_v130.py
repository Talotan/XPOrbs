"""Options reorganisation, the Flight Style dropdown, split quest / exploration bursts, the minimap Shift + right-click
and the window drag fix."""

import pytest
from conftest import lua_list
from test_m5 import build, ctl, show
from test_p2_zoom import make as make_calib
from test_p2a import make as make_minimap
from test_setup import open_now
from test_sources import World
from test_v102 import load_db

SECTION_ORDER = [
    ("General", ["enabled", "showAtMax", "questBursts", "exploreBursts", "minimap"]),
    ("Sound", ["sound", "soundVoice", "soundVolume"]),
    (
        "Look",
        [
            "density",
            "cap",
            "size",
            "flightTime",
            "trail",
            "color",
            "restedTint",
            "restedColor",
        ],
    ),
    (
        "Style",
        [
            "flightPath",
            "style_popstream",
            "style_crossfade",
            "style_stream",
            "zoomSpread",
        ],
    ),
    (
        "Arrival",
        [
            "targetFrame",
            "glowShape",
            "glowOffsetX",
            "glowOffsetY",
            "glow",
            "glowIntensity",
        ],
    ),
    ("Advanced", ["debug"]),
]


def row_y(m, key):
    return -m.opt.rows[key].points[1][5]


def texts(m):
    return [
        str(f.text) for f in m.stub.frames.values() if f.kind == "FontString" and f.text
    ]


# ---------------------------------------------------------------- panel order


def test_sections_and_rows_run_in_the_agreed_order(env):
    m = build(env)
    flat = [key for _, keys in SECTION_ORDER for key in keys]
    ys = [row_y(m, key) for key in flat]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)
    names = {name for name, _ in SECTION_ORDER}
    assert {t for t in texts(m)} >= names
    assert "XP bar" not in texts(m)  # merged into Arrival


def test_content_height_fits_the_last_row_exactly(env):
    m = build(env)
    assert m.opt.CONTENT_H == m.opt.child.height == row_y(m, "debug") + 28 + 16 == 1328


def test_exploration_checkbox_and_tooltips(env):
    m = build(env)
    show(m)
    assert {"Quest bursts", "Exploration bursts"} <= set(texts(m))
    box = ctl(m, "exploreBursts")
    assert box.checked is True
    m.stub.click(box)
    assert m.db.exploreBursts is False and m.db.questBursts is True
    assert m.opt.resets["exploreBursts"].shown
    m.stub.hover(box)
    assert "discovering" in str(m.stub.tooltip.text)
    m.stub.hover(ctl(m, "questBursts"))
    assert "quest" in str(m.stub.tooltip.text)


# ---------------------------------------------------------------- Flight Style dropdown


def menu(dropdown):
    dropdown.GenerateMenu(dropdown)
    root = dropdown.menuRoot
    return [root.entries[i] for i in range(1, len(root.entries) + 1)]


def selection(dropdown):
    return [(str(e["text"]), bool(e["selected"])) for e in menu(dropdown)]


def test_flight_style_is_a_dropdown_like_the_voice_one(env):
    m = build(env)
    dropdown = m.opt.flightDropdown
    assert (
        dropdown.kind == "DropdownButton"
        and dropdown.template == "WowStyle1DropdownTemplate"
    )
    assert m.lua.eval("rawequal")(m.opt.controls["flightPath"], dropdown)
    assert dropdown.points[1][4] == 260 and dropdown.width == 150
    assert "Flight style" in texts(m) and "Kill style" in texts(m) and "Flight path" not in texts(m)
    assert selection(dropdown) == [
        ("Smooth (default)", True),
        ("Chaos", False),
        ("Helix", False),
    ]
    assert not any(
        t.startswith("How orbs fly") for t in texts(m)
    )  # the descriptions live in tooltips


def test_picking_a_flight_style_saves_it_and_the_slash_command_refreshes_it(env):
    m = build(env)
    show(m)
    dropdown = m.opt.flightDropdown
    assert m.stub.pickMenu(dropdown, "Helix") is True
    assert m.db.flightPath == "helix"
    assert [s for _, s in selection(dropdown)] == [False, False, True]
    m.slash("path chaos")
    assert [s for _, s in selection(dropdown)] == [False, True, False]


def test_flight_style_reset_button(env):
    m = build(env)
    show(m)
    btn = m.opt.resets["flightPath"]
    assert not btn.shown
    m.stub.pickMenu(m.opt.flightDropdown, "Chaos")
    assert btn.shown
    m.stub.click(btn)
    assert m.db.flightPath == "smooth" and not btn.shown
    assert selection(m.opt.flightDropdown)[0][1] is True


def test_each_menu_option_has_its_own_tooltip(env):
    m = build(env)
    expected = {
        "Smooth (default)": "A clean arc from the mob to your XP bar.",
        "Chaos": "Orbs dart and weave like fireflies on the way.",
        "Helix": "Orbs spiral around each other in pairs.",
    }
    for entry in menu(m.opt.flightDropdown):
        name, seen = str(entry["text"]), []
        tooltip = m.lua.table_from(
            {
                "SetText": lambda _self, t, *a, seen=seen: seen.append(("title", t)),
                "AddLine": lambda _self, t, *a, seen=seen: seen.append(("body", t)),
            }
        )
        # the stub has no GameTooltip_* helpers, so this is the SetText / AddLine fallback
        entry["tooltipFn"](tooltip, entry)
        assert seen == [("title", name), ("body", expected[name])]


def test_menu_tooltip_uses_blizzards_helpers_when_they_exist(env):
    m = build(env)
    seen = []
    m.G.GameTooltip_SetTitle = lambda tip, t: seen.append(("title", t))
    m.G.GameTooltip_AddNormalLine = lambda tip, t: seen.append(("line", t))
    entry = menu(m.opt.flightDropdown)[1]
    entry["tooltipFn"](m.lua.table(), entry)
    assert seen == [
        ("title", "Chaos"),
        ("line", "Orbs dart and weave like fireflies on the way."),
    ]


def test_the_button_itself_shows_the_current_options_tooltip(env):
    m = build(env)
    dropdown = m.opt.flightDropdown
    m.stub.hover(dropdown)
    assert str(m.stub.tooltip.text) == "Smooth" and m.stub.tooltip.shown
    assert "A clean arc" in str(lua_list(m.stub.tooltip.lines)[-1])
    m.stub.unhover(dropdown)
    assert not m.stub.tooltip.shown
    m.db.flightPath = "helix"
    m.stub.hover(dropdown)
    assert str(m.stub.tooltip.text) == "Helix"


def test_a_menu_element_without_set_tooltip_still_works(env):
    def pre(e):
        # radios that return nothing (no element description): the menu must still build
        e.lua.execute(
            """
            local make = CreateFrame
            function CreateFrame(kind, ...)
                local f = make(kind, ...)
                if kind == "DropdownButton" then
                    function f:GenerateMenu()
                        local root = { entries = {} }
                        function root:CreateRadio(text, isSelected, setSelected)
                            self.entries[#self.entries + 1] = { text = text, selected = isSelected(), setSelected = setSelected }
                        end
                        self.menuRoot = root
                        if self.menuGen then self.menuGen(self, root) end
                    end
                end
                return f
            end
            """
        )

    m = build(env, pre=pre)
    assert len(menu(m.opt.flightDropdown)) == 3 and m.opt.category is not None


def test_radios_replace_the_dropdown_when_the_template_is_missing(env):
    def pre(e):
        e.lua.execute(
            """
            local make = CreateFrame
            function CreateFrame(kind, name, parent, template)
                if kind == "DropdownButton" then error("no dropdown") end
                return make(kind, name, parent, template)
            end
            """
        )

    m = build(env, pre=pre)
    assert m.opt.flightDropdown is None
    show(m)
    assert ctl(m, "flightPath_smooth").checked
    m.stub.click(ctl(m, "flightPath_helix"))
    assert m.db.flightPath == "helix" and ctl(m, "flightPath_helix").checked


def test_help_calls_it_flight_style(env):
    m = build(env)
    m.slash("help")
    assert any("flight style" in line and "/xporbs path" in line for line in m.say())


# ---------------------------------------------------------------- split quest / exploration bursts


def test_explore_bursts_defaults_on_and_junk_is_replaced(env):
    assert load_db(env, {}).exploreBursts is True


def test_junk_explore_bursts_becomes_the_default(env):
    assert load_db(env, {"version": 7, "exploreBursts": "junk"}).exploreBursts is True


@pytest.mark.parametrize("saved", [True, False])
def test_old_save_copies_quest_bursts_into_explore_bursts(env, saved):
    db = load_db(env, {"version": 7, "questBursts": saved})
    assert db.exploreBursts is saved and db.questBursts is saved


def test_a_saved_explore_bursts_wins_over_the_copy(env):
    db = load_db(env, {"version": 7, "questBursts": False, "exploreBursts": True})
    assert db.exploreBursts is True and db.questBursts is False


def test_explore_switch_gates_exploration_only(env):
    w = World(env)
    w.e.db.exploreBursts = False
    w.frame("SubZoneTextFrame", 960, 900)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained")
    w.gain(150)
    w.run(1.0)
    assert (
        w.bursts() == [] and "source=explore" in w.burst_lines()[0]
    )  # classified, then dropped
    w.fire("QUEST_TURNED_IN", 11, 120, 5)
    w.gain(120)
    w.run(1.0)
    assert len(w.bursts()) == 1 and w.burst_lines()[-1].endswith("source=quest")


def test_quest_switch_gates_quests_and_plain_non_kill_xp_but_not_exploration(env):
    w = World(env)
    w.e.db.questBursts = False
    w.fire("QUEST_TURNED_IN", 11, 120, 5)
    w.gain(120)
    w.run(1.0)
    w.gain(40)  # no hint: plain "other" XP
    w.run(1.0)
    assert w.bursts() == []
    w.frame("SubZoneTextFrame", 960, 900)
    w.fire("CHAT_MSG_SYSTEM", "Discovered Goldshire: 150 experience gained")
    w.gain(150)
    w.run(1.0)
    assert len(w.bursts()) == 1 and w.burst_lines()[-1].endswith("source=explore")


# ---------------------------------------------------------------- minimap Shift + right-click


def shift(m, down):
    m.G.IsShiftKeyDown = (lambda: down) if down is not None else None


def test_shift_right_click_hides_the_button_and_says_how_to_bring_it_back(env):
    m = make_minimap(env)
    shift(m, True)
    m.p2a.object.OnClick(None, "RightButton")
    assert m.db.minimap.hide is True and m.p2a.shown["XPOrbs"] is False
    assert m.db.enabled is True  # not the orbs toggle
    say = m.say()
    assert (
        len(say) == 1
        and "/xporbs minimap on" in say[0]
        and "Show minimap button" in say[0]
    )


def test_shift_right_click_unticks_an_open_options_checkbox(env):
    m = make_minimap(env)
    show(m)
    assert ctl(m, "minimap").checked is True
    shift(m, True)
    m.p2a.object.OnClick(None, "RightButton")
    assert ctl(m, "minimap").checked is False


def test_plain_right_click_still_toggles_the_orbs(env):
    m = make_minimap(env)
    shift(m, False)
    m.p2a.object.OnClick(None, "RightButton")
    assert m.db.enabled is False and m.db.minimap.hide is False
    assert m.say()[-1].endswith(": orbs off")


def test_right_click_works_when_shift_state_is_unavailable(env):
    m = make_minimap(env)
    shift(m, None)
    m.p2a.object.OnClick(None, "RightButton")
    assert m.db.enabled is False and m.db.minimap.hide is False


def test_shift_left_click_still_opens_the_options(env):
    m = make_minimap(env)
    shift(m, True)
    m.p2a.object.OnClick(None, "LeftButton")
    assert len(m.opened) == 1 and m.db.minimap.hide is False


def test_shift_right_click_works_from_the_addon_compartment_too(env):
    m = make_minimap(env)
    shift(m, True)
    m.G.XPOrbs_OnAddonCompartmentClick("XPOrbs", "RightButton")
    assert m.db.minimap.hide is True


def test_tooltip_mentions_shift_right_click(env):
    m = make_minimap(env)
    tooltip = m.stub.newTooltip()
    m.p2a.object.OnTooltipShow(tooltip)
    assert "Shift + right-click: hide this button" in [
        str(line.text) for line in lua_list(tooltip.lines)
    ]


# ---------------------------------------------------------------- dragging

STUCK_MESSAGE = "OnDragStop must end the move (StopMovingOrSizing exists; StopMovingAndSizing does not)"


def test_setup_window_drag_stop_ends_the_move(env):
    m = build(env)
    m.slash("setup")
    win = open_now(m)
    win.scripts.OnDragStart(win)
    win.scripts.OnDragStop(win)
    assert (
        win.calls["StartMoving"] is not None
        and win.calls["StopMovingOrSizing"] is not None
    ), STUCK_MESSAGE


def test_calibration_panel_drag_stop_ends_the_move(env):
    g = make_calib(env)
    g.slash("calib")
    panel = g.ns.Calib.panel
    stopped = []
    panel.StopMovingOrSizing = lambda self: stopped.append(True)
    panel.scripts.OnDragStop(panel)
    assert stopped == [True], STUCK_MESSAGE
    assert (
        not hasattr(panel, "StopMovingAndSizing") or panel.StopMovingAndSizing is None
    )

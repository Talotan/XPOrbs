"""/xporbs status: ns.StatusLines(), the copyable window (StatusWindow.lua), `status chat`, the Copy status button."""

import pytest
from conftest import lua_list
from test_m5 import build, ctl, show


@pytest.fixture
def m(env):
    return build(env)


def same(m, a, b):
    """Lua identity (lupa wrappers are not identical objects for the same table)."""
    return m.lua.eval("rawequal")(a, b)


def window(m):
    return m.ns.StatusWindow.Frame(m.ns.StatusWindow)


def edit_box(m):
    host = next(
        f for f in lua_list(m.stub.frames) if f.template == "ScrollingEditBoxTemplate"
    )
    return host.GetEditBox(host)


def window_text(m):
    return str(edit_box(m).text)


def lines(m):
    return [str(x) for x in lua_list(m.ns.StatusLines())]


def reset_to_defaults(m):
    """The m5 harness tweaks a few keys; a reset gives the pristine defaults (the section then reads 'none')."""
    m.slash("reset")


# ---------------------------------------------------------------- the window


def test_status_opens_the_window_not_chat(m):
    before = len(m.say())
    m.slash("status")
    assert window(m) is not None and window(m).shown
    assert len(m.say()) == before  # nothing went to chat


def test_the_window_text_holds_every_status_line(m):
    m.slash("status")
    text = window_text(m)
    expected = lines(m)
    assert (
        len(expected) > 8
    )  # the header, the log count, the providers, the client, the settings section
    for line in expected:
        assert line in text
    for provider_line in (
        "orbs: driver=",
        "plates: tracked=",
        "xp bar frame:",
        "minimap button:",
        "options panel:",
    ):
        assert provider_line in text


def test_the_frame_is_a_special_frame_in_the_dialog_strata_with_a_title(m):
    m.slash("status")
    frame = window(m)
    assert frame.name == "XPOrbsStatusFrame"
    assert "XPOrbsStatusFrame" in lua_list(m.G.UISpecialFrames)
    assert frame.calls.SetFrameStrata[1] == "DIALOG"
    assert frame.title == "XP Orbs status"
    assert frame.portraitHidden is True and frame.buttonBarHidden is True


def test_reopening_does_not_register_the_frame_twice_or_build_a_second_one(m):
    m.slash("status")
    first = window(m)
    m.ns.StatusWindow.Hide(m.ns.StatusWindow)
    assert not first.shown
    m.slash("status")
    assert same(m, window(m), first) and first.shown
    assert lua_list(m.G.UISpecialFrames).count("XPOrbsStatusFrame") == 1
    assert (
        len([f for f in lua_list(m.stub.frames) if f.name == "XPOrbsStatusFrame"]) == 1
    )


def test_the_text_is_selected_and_focused_a_frame_later(m):
    m.slash("status")
    box = edit_box(m)
    assert (
        not box.hasFocus and not box.highlighted
    )  # deferred: the box lays its text out first
    m.stub.runTimers()
    assert box.hasFocus is True
    assert (box.highlightRange[1], box.highlightRange[2]) == (0, len(window_text(m)))


def test_reopening_refreshes_the_text(m):
    m.slash("status")
    assert "glowOffsetX = 150" not in window_text(m)
    m.db.glowOffsetX = 150
    m.slash("status")
    assert "glowOffsetX = 150" in window_text(m)


def test_the_box_is_read_only(m):
    m.slash("status")
    box = edit_box(m)
    shown = window_text(m)
    box.text = "typed over it"
    box.scripts.OnTextChanged(box, True)  # a keystroke or a paste
    assert window_text(m) == shown
    box.text = "set by the addon"
    box.scripts.OnTextChanged(box, False)  # not the player: left alone
    assert window_text(m) == "set by the addon"


def test_the_hint_names_ctrl_c(m):
    m.slash("status")
    hints = [
        f.text
        for f in lua_list(m.stub.frames)
        if f.kind == "FontString" and f.text and "Ctrl+C" in f.text
    ]
    assert hints == ["Press Ctrl+C to copy, then paste it into your bug report"]


def test_the_title_strip_moves_the_window(m):
    m.slash("status")
    bars = [
        f
        for f in lua_list(m.stub.frames)
        if f.scripts.OnDragStart is not None and same(m, f.createdParent, window(m))
    ]
    assert len(bars) == 1
    bars[0].scripts.OnDragStart(bars[0])  # a stub recorder: must simply not raise
    bars[0].scripts.OnDragStop(bars[0])


def test_toggle_and_hide(m):
    sw = m.ns.StatusWindow
    sw.Toggle(sw)
    assert window(m).shown
    sw.Toggle(sw)
    assert not window(m).shown
    sw.Toggle(sw)
    sw.Hide(sw)
    assert not window(m).shown


@pytest.mark.parametrize("missing", ["ButtonFrameTemplate", "ScrollingEditBoxTemplate"])
def test_a_missing_template_falls_back_to_chat(m, missing):
    m.stub.missingTemplates[missing] = True
    m.slash("status")
    said = m.say()
    assert any("log entries:" in line for line in said)
    assert any("orbs: driver=" in line for line in said)
    assert "XPOrbsStatusFrame" not in lua_list(m.G.UISpecialFrames)
    assert not any(
        f.name == "XPOrbsStatusFrame" and f.shown for f in lua_list(m.stub.frames)
    )
    m.slash("status")  # a second try does not build (or leak) another half window
    assert (
        len([f for f in lua_list(m.stub.frames) if f.name == "XPOrbsStatusFrame"]) <= 1
    )


def test_status_chat_prints_the_same_lines_and_opens_no_window(m):
    m.slash("status chat")
    assert window(m) is None
    said = m.say()
    for line in lines(m):
        assert any(said_line.endswith(line) for said_line in said)
    assert not any(f.name == "XPOrbsStatusFrame" for f in lua_list(m.stub.frames))


def test_help_lists_both_forms(m):
    m.slash("help")
    said = m.say()
    assert any("/xporbs status -" in line and "window" in line for line in said)
    assert any("/xporbs status chat" in line for line in said)


# ---------------------------------------------------------------- what the report says


def test_the_client_line_comes_from_get_build_info(m):
    assert "client: 1.16.1 (build 12345), interface 16001" in lines(m)


def test_a_client_without_get_build_info_says_unknown(m):
    m.G.GetBuildInfo = None
    assert "client: unknown" in lines(m)


def test_unchanged_settings_say_none(m):
    reset_to_defaults(m)
    assert "settings changed from default: none" in lines(m)


def test_only_changed_keys_are_listed_with_dotted_paths_and_sorted(m):
    reset_to_defaults(m)
    m.db.glowOffsetX = 150
    m.db.shapeLook.starlight.size = 20
    m.db.color[1], m.db.color[2], m.db.color[3] = 1, 0, 0.5
    out = lines(m)
    start = out.index("settings changed from default:")
    section = out[start + 1 :]
    assert section == [
        "  color = #ff0080",
        "  glowOffsetX = 150",
        "  shapeLook.starlight.size = 20",
    ]
    text = "\n".join(out)
    for unchanged in ("cap =", "density =", "restedColor", "soundVoice", "glowShape"):
        assert unchanged not in text


def test_log_version_and_debug_are_not_listed_as_settings(m):
    reset_to_defaults(m)
    m.db.debug = True
    m.slash("debug on")
    m.ns.Log(m.ns, "an entry")
    section = lines(m)[lines(m).index("settings changed from default: none") :]
    assert section == ["settings changed from default: none"]
    assert any(line.startswith("XPOrbs ") and "debug=true" in line for line in lines(m))


def test_the_calibration_array_is_a_count(m):
    reset_to_defaults(m)
    m.db.zoomPoints = m.lua.table_from(
        [
            m.lua.table_from({"z": 5, "off": 10}),
            m.lua.table_from({"z": 8, "off": 30}),
            m.lua.table_from({"z": 12, "off": 40}),
        ]
    )
    out = lines(m)
    assert "  zoomPoints = 3 entries" in out
    assert not any(line.startswith("  zoomPoints.") for line in out)


def test_the_picked_frame_token_is_not_dumped_as_a_setting(m):
    reset_to_defaults(m)
    m.db.targetFrame = "SomeFrame"
    assert not any("targetFrame" in line for line in lines(m))


def test_nothing_identifying_is_in_the_report(m):
    m.stub.units = m.lua.table_from(
        {
            "player": m.lua.table_from(
                {"name": "Secretchar", "guid": "Player-1234-ABCDEF01"}
            ),
            "target": m.lua.table_from(
                {"name": "Secretchar", "guid": "Player-1234-ABCDEF01"}
            ),
        }
    )
    m.G.GetRealmName = lambda: "SecretRealm"
    m.G.UnitName = lambda unit: "Secretchar"
    m.G.UnitGUID = lambda unit: "Player-1234-ABCDEF01"
    m.slash("status")
    text = window_text(m) + "\n".join(m.say())
    for private in ("Secretchar", "SecretRealm", "Player-1234"):
        assert private not in text


# ---------------------------------------------------------------- the General tab button


def test_the_copy_status_button_opens_the_window_and_has_a_tooltip(m):
    show(m)
    button = ctl(m, "copyStatus")
    assert button.GetText(button) == "Copy status"
    m.stub.hover(button)
    assert (
        m.stub.tooltip.text
        == "Opens your addon status in a window to copy into a bug report"
    )
    m.stub.unhover(button)
    assert window(m) is None
    m.stub.click(button)
    assert window(m).shown
    assert "log entries:" in window_text(m)


def test_the_copy_status_button_falls_back_to_chat_too(m):
    m.stub.missingTemplates["ScrollingEditBoxTemplate"] = True
    show(m)
    m.stub.click(ctl(m, "copyStatus"))
    assert any("log entries:" in line for line in m.say())

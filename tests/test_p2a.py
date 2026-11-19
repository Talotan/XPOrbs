"""P2a: minimap button (LibDataBroker + LibDBIcon), Addon Compartment entry, /xporbs minimap, option checkbox."""

import struct

import pytest
from conftest import ROOT, TESTS, addon_files, lua_list
from test_m5 import build, ctl, show

NAME = "XPOrbs"


def make(env, libs=True, drop=None):
    """Full addon with the options stubs; libs=False leaves LibStub undefined, drop= removes one library."""

    def pre(e):
        e.load_chunk(TESTS / "stubs_p2a.lua", "stubs_p2a.lua")(e.ns)
        if drop:
            e.ns.stub.p2a.libs[drop] = None
        if not libs:
            e.G.LibStub = None

    m = build(env, pre=pre)
    m.p2a = env.ns.stub.p2a
    m.opened = env.lua.table()
    env.lua.eval(
        "function(ns, t) ns.commands.options = function() t[#t + 1] = 1 end end"
    )(env.ns, m.opened)
    return m


@pytest.fixture
def m(env):
    return make(env)


# ---------------------------------------------------------------- toc and icon


def toc_fields():
    out = {}
    for line in (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and ":" in line:
            k, v = line[3:].split(":", 1)
            out[k.strip()] = v.strip()
    return out


def test_icon_texture_is_a_64px_32bit_tga():
    assert toc_fields()["IconTexture"] == "Interface\\AddOns\\XPOrbs\\media\\icon-list"
    path = ROOT / "media" / "icon-list.tga"  # bordered: AddOns list draws no frame
    assert path.is_file()
    hdr = path.read_bytes()[:18]
    w, h = struct.unpack("<HH", hdr[12:16])
    assert (w, h, hdr[16]) == (64, 64, 32)
    assert hdr[1] == 0 and hdr[2] in (2, 10)  # no colour map; true-colour, raw or RLE


def test_libs_listed_first_in_toc():
    lines = (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines()
    files = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    assert [f.replace("\\", "/") for f in files[:4]] == [
        "Libs/LibStub/LibStub.lua",
        "Libs/CallbackHandler-1.0/CallbackHandler-1.0.lua",
        "Libs/LibDataBroker-1.1/LibDataBroker-1.1.lua",
        "Libs/LibDBIcon-1.0/LibDBIcon-1.0.lua",
    ]
    assert "Minimap.lua" in addon_files()
    assert addon_files()[0] == "Core.lua"


@pytest.mark.parametrize(
    "field",
    [
        "AddonCompartmentFunc",
        "AddonCompartmentFuncOnEnter",
        "AddonCompartmentFuncOnLeave",
    ],
)
def test_compartment_functions_exist_after_load(m, field):
    fn = toc_fields()[field]
    assert fn.startswith("XPOrbs_OnAddonCompartment")
    assert m.G[fn] is not None


# ---------------------------------------------------------------- libs present


def test_registered_once_with_name_and_minimap_db(m):
    regs = m.p2a.registers
    assert len(regs) == 1
    assert regs[1].name == NAME
    assert m.lua.eval("rawequal")(regs[1].db, m.db.minimap)
    obj = m.p2a.object
    assert obj.type == "launcher"
    assert obj.icon == "Interface\\AddOns\\XPOrbs\\media\\icon"
    # the texture path the game resolves must exist as a 64x64 32-bit TGA
    tga = (ROOT / "media" / "icon.tga").read_bytes()
    assert (
        obj.icon != toc_fields()["IconTexture"]
    )  # the minimap button stays borderless (LibDBIcon rings it)
    assert tga[2] == 2 and tga[12:16] == bytes([64, 0, 64, 0]) and tga[16] == 32
    assert obj.label == "XP Orbs" and obj.text == "XP Orbs"


def test_left_click_opens_options(m):
    m.p2a.object.OnClick(None, "LeftButton")
    assert len(m.opened) == 1


def test_right_click_toggles_enabled_and_prints(m):
    m.p2a.object.OnClick(None, "RightButton")
    assert m.db.enabled is False
    assert m.say()[-1].endswith(": orbs off")
    m.p2a.object.OnClick(None, "RightButton")
    assert m.db.enabled is True
    assert m.say()[-1].endswith(": orbs on")
    assert len(m.opened) == 0


def test_right_click_refreshes_open_panel(m):
    show(m)
    m.p2a.object.OnClick(None, "RightButton")
    assert ctl(m, "enabled").checked is False


def test_tooltip_lines(m):
    tt = m.stub.newTooltip()
    m.p2a.object.OnTooltipShow(tt)
    assert tt.title == "XP Orbs"
    lines = lua_list(tt.lines)
    assert [x.text for x in lines] == [
        "orbs on",
        "Left-click: options",
        "Right-click: turn orbs on/off",
    ]
    assert lines[1].r == lines[1].g == lines[1].b < 1  # grey hints
    m.db.enabled = False
    tt = m.stub.newTooltip()
    m.p2a.object.OnTooltipShow(tt)
    assert tt.lines[1].text == "orbs off"


def test_compartment_click_enter_leave(m):
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "LeftButton")
    assert len(m.opened) == 1
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "RightButton")
    assert m.db.enabled is False
    m.G.XPOrbs_OnAddonCompartmentEnter(NAME, m.lua.table())
    gt = m.G.GameTooltip
    assert gt.owner is not None and gt.shown is True
    assert gt.title == "XP Orbs" and gt.lines[1].text == "orbs off"
    m.G.XPOrbs_OnAddonCompartmentLeave()
    assert gt.shown is False


# ---------------------------------------------------------------- /xporbs minimap and the checkbox


def test_slash_minimap_off_on(m):
    m.slash("minimap off")
    assert m.db.minimap.hide is True
    assert m.p2a.calls[len(m.p2a.calls)] == "Hide" and m.p2a.shown[NAME] is False
    m.slash("minimap on")
    assert m.db.minimap.hide is False
    assert m.p2a.calls[len(m.p2a.calls)] == "Show" and m.p2a.shown[NAME] is True


def test_slash_minimap_reports_state_and_help(m):
    m.slash("minimap")
    assert "minimap button shown" in m.say()[-1]
    m.slash("minimap off")
    m.slash("minimap")
    assert "minimap button hidden" in m.say()[-1]
    m.slash("minimap banana")
    assert "usage: /xporbs minimap on|off" in m.say()[-1]
    m.slash("help")
    assert any("/xporbs minimap on|off" in line for line in m.say())
    m.slash("status")
    assert any(line.endswith("minimap button: hidden") for line in m.say())


def test_checkbox_drives_same_path(m):
    show(m)
    box = ctl(m, "minimap")
    assert box.checked is True
    m.stub.click(box)
    assert m.db.minimap.hide is True and m.p2a.shown[NAME] is False
    m.stub.click(box)
    assert m.db.minimap.hide is False and m.p2a.shown[NAME] is True
    m.slash("minimap off")
    show(m)
    assert box.checked is False


# ---------------------------------------------------------------- saved settings


def test_old_save_without_minimap_gets_default(env):
    env.G.XPOrbsDB = env.lua.table_from({"density": 250, "version": 5})
    m = make(env)
    assert m.db.minimap.hide is False and m.db.density == 250


@pytest.mark.parametrize("bad", ["yes", 7, True])
def test_corrupt_minimap_is_reset(env, bad):
    env.G.XPOrbsDB = env.lua.table_from({"minimap": bad, "version": 5})
    m = make(env)
    assert m.db.minimap.hide is False


def test_non_boolean_hide_is_reset(env):
    env.G.XPOrbsDB = env.lua.table_from(
        {"version": 5, "minimap": env.lua.table_from({"hide": "no"})}
    )
    m = make(env)
    assert m.db.minimap.hide is False


def test_minimap_pos_survives_sanitize(env):
    mm = env.lua.table_from({"hide": True, "minimapPos": 123.5})
    env.G.XPOrbsDB = env.lua.table_from({"version": 5, "minimap": mm})
    m = make(env)
    assert m.db.minimap.minimapPos == 123.5 and m.db.minimap.hide is True


def test_reset_restores_default_and_keeps_table(m):
    table = m.db.minimap
    m.slash("minimap off")
    table.minimapPos = 10
    refreshes = m.p2a.refreshes
    m.slash("reset")
    assert m.lua.eval("rawequal")(
        m.db.minimap, table
    )  # LibDBIcon still holds this table
    assert m.db.minimap.hide is False and m.db.minimap.minimapPos is None
    assert m.p2a.shown[NAME] is True and m.p2a.refreshes == refreshes + 1


# ---------------------------------------------------------------- libs missing


@pytest.mark.parametrize(
    "kw", [{"libs": False}, {"drop": "LibDBIcon-1.0"}, {"drop": "LibDataBroker-1.1"}]
)
def test_libs_missing_addon_still_works(env, kw):
    m = make(env, **kw)
    assert len(m.p2a.registers) == 0
    assert m.ns.Minimap.err is not None
    m.slash("status")
    assert any("minimap button: unavailable (" in line for line in m.say())
    # the slash command and the options checkbox still save the choice
    m.slash("minimap off")
    assert m.db.minimap.hide is True
    show(m)
    m.stub.click(ctl(m, "minimap"))
    assert m.db.minimap.hide is False
    # the compartment entry needs no library
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "LeftButton")
    assert len(m.opened) == 1
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "RightButton")
    assert m.db.enabled is False
    m.slash("reset")  # reset with no library must not throw either


def test_libs_missing_error_logged_once(env):
    env.G.XPOrbsDB = env.lua.table_from({"debug": True, "version": 5})
    m = make(env, libs=False)
    entries = [str(x) for x in lua_list(m.db.log)]
    assert sum("MINIMAP_ERR" in x for x in entries) == 1


# ---------------------------------------------------------------- left-click toggles the options


SETTINGS_PANEL = """
function(G)
    local sp = { shown = false, hides = 0 }
    function sp:IsShown() return self.shown end
    function sp:Hide() self.shown = false; self.hides = self.hides + 1 end
    function sp:Close() self.shown = false end
    G.SettingsPanel = sp
    return sp
end
"""


def open_window(m, ours=True):
    """Stub the Settings window as open; ours=False means another addon's category is showing."""
    sp = m.lua.eval(SETTINGS_PANEL)(m.G)
    sp.shown = True
    if ours:
        show(m)
        m.opt.panel.Show(m.opt.panel)
    else:
        m.opt.panel.Hide(
            m.opt.panel
        )  # stub frames start shown; a real canvas panel is hidden off-category
    return sp


@pytest.mark.parametrize("via", ["button", "compartment"])
def test_second_click_closes_open_options(m, via):
    def click():
        if via == "button":
            m.p2a.object.OnClick(None, "LeftButton")
        else:
            m.G.XPOrbs_OnAddonCompartmentClick(NAME, "LeftButton")

    click()  # window not open yet: opens
    assert len(m.opened) == 1
    sp = open_window(m)
    click()  # open on our category: closes, does not reopen
    assert sp.shown is False and len(m.opened) == 1
    click()
    assert len(m.opened) == 2


def test_click_switches_from_another_category(m):
    sp = open_window(m, ours=False)
    m.p2a.object.OnClick(None, "LeftButton")
    assert sp.shown is True and len(m.opened) == 1


def test_click_without_settings_panel_global(m):
    m.G.SettingsPanel = None
    m.p2a.object.OnClick(None, "LeftButton")
    m.G.XPOrbs_OnAddonCompartmentClick(NAME, "LeftButton")
    assert len(m.opened) == 2

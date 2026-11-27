"""Options panel tabs: one child frame per section under a tab strip, one shared scroll frame."""

import itertools

import pytest
from test_m5 import build, ctl, show
from test_v013 import no_template

NAMES = ["General", "Sound", "Look", "Flight", "Arrival"]
N = len(NAMES)


@pytest.fixture
def m(env):
    return build(env)


def same(m, a, b):
    return bool(m.lua.eval("rawequal")(a, b))


def shown_children(m):
    return [n for n in NAMES if m.opt.tabChildren[n].IsShown(m.opt.tabChildren[n])]


def test_five_tabs_in_order_sized_to_their_labels(m):
    o = m.opt
    assert [str(o.tabs[i].xpName) for i in range(1, N + 1)] == NAMES
    assert o.tabTemplate == "PanelTopTabButtonTemplate"
    tabs = [o.tabs[i] for i in range(1, N + 1)]
    assert tabs[0].xpX == 16 and all(t.xpW >= 64 for t in tabs)
    for prev, nxt in itertools.pairwise(tabs):
        assert nxt.xpX == prev.xpX + prev.xpW + 4  # 4 px gap, anchored to the previous tab's right edge
        assert nxt.points[1][2] is not None and nxt.points[1][3] == "TOPRIGHT" and nxt.points[1][4] == 4
    assert tabs[-1].xpX + tabs[-1].xpW <= 16 + 552
    assert o.tabs[1].points[1][5] == -o.tabTop == -42
    assert o.tabTop + o.tabHeight < o.scrollTop  # the strip clears the scroll area


def rules(m):
    o = m.opt
    return [(r.points[1][4], -r.points[1][5], r.width, r.height) for r in (o.tabRuleL, o.tabRuleR)]


def test_the_rule_is_the_baseline_and_breaks_at_the_selected_tab(m):
    o = m.opt
    base = o.tabBase
    assert base == 70 and o.scrollTop == 74
    sel = o.tabs[1]
    (lx, ly, lw, lh), (rx, ry, rw, rh) = rules(m)
    assert (lx, ly, lw, lh) == (16, base, sel.xpX - 16, 1)
    assert (rx, ry, rw, rh) == (sel.xpX + sel.xpW, base, 568 - (sel.xpX + sel.xpW), 1)
    m.opt.SelectTab(m.opt, "Look")
    sel = o.tabs[3]
    (lx, _, lw, _), (rx, _, rw, _) = rules(m)
    assert (lx, lw) == (16, sel.xpX - 16) and (rx, rw) == (sel.xpX + sel.xpW, 568 - (sel.xpX + sel.xpW))
    assert lx + lw == sel.xpX and rx + rw == 568


def test_first_show_is_general_and_only_one_child_is_shown(m):
    show(m)
    assert same(m, m.opt.scroll.scrollChild, m.opt.tabChildren.General)
    assert same(m, m.opt.child, m.opt.tabChildren.General)
    assert shown_children(m) == ["General"]


def test_select_tab_swaps_the_child_and_resets_the_scroll(m):
    show(m)
    m.opt.scroll.SetVerticalScroll(m.opt.scroll, 90)
    assert m.opt.SelectTab(m.opt, "Look") is True
    assert same(m, m.opt.scroll.scrollChild, m.opt.tabChildren.Look)
    assert m.opt.scroll.GetVerticalScroll(m.opt.scroll) == 0
    assert shown_children(m) == ["Look"]
    assert [bool(m.opt.tabs[i].xpSelected) for i in range(1, N + 1)] == [n == "Look" for n in NAMES]
    m.opt.SelectTab(m.opt, 5)  # by index too
    assert shown_children(m) == ["Arrival"]
    assert m.opt.SelectTab(m.opt, "Nope") is False and shown_children(m) == ["Arrival"]


def test_clicking_a_tab_selects_it(m):
    show(m)
    m.stub.click(m.opt.tabs[4])
    assert shown_children(m) == ["Flight"]


def test_every_control_hangs_off_a_tab_child(m):
    children = [m.opt.tabChildren[n] for n in NAMES]
    keys = list(m.opt.controls.keys())
    assert len(keys) > 30
    for key in keys:
        node = m.opt.controls[key]
        seen = 0
        while node is not None and seen < 20 and not any(same(m, node, c) for c in children):
            node = node.createdParent
            seen += 1
        assert node is not None and any(same(m, node, c) for c in children), key
    for key in m.opt.rows:
        node = m.opt.rows[key].createdParent
        seen = 0
        while node is not None and seen < 20 and not any(same(m, node, c) for c in children):
            node = node.createdParent  # rows inside the Look tab's shape box hang off the box
            seen += 1
        assert node is not None and any(same(m, node, c) for c in children), key


def test_heights_and_content_h(m):
    o = m.opt
    h = {n: o.tabHeights[n] for n in NAMES}
    assert o.CONTENT_H == max(h.values())
    for n in NAMES:
        assert o.tabChildren[n].height == h[n] and o.tabChildren[n].width == 584
    assert h["General"] == 234 and h["Sound"] == 112 and h["Look"] == 422 and h["Flight"] == 446 and o.CONTENT_H == h["Flight"]


def test_refresh_updates_a_control_on_a_hidden_tab(m):
    show(m)
    assert shown_children(m) == ["General"]
    box = ctl(m, "glow")  # Arrival tab
    assert box.checked is True
    m.db.glow = False
    m.opt.Refresh(m.opt)
    assert box.checked is False


def test_reset_all_resets_a_value_on_a_hidden_tab(m):
    show(m)
    m.db.glow, m.db.soundVolume = False, 150
    m.opt.Refresh(m.opt)
    assert ctl(m, "glow").checked is False  # Arrival tab, not visible
    default_volume = m.ns.defaults.soundVolume
    dlg = m.G.StaticPopupDialogs["XPORBS_RESET_ALL"]
    dlg.OnAccept()
    assert m.db.glow is True and m.db.soundVolume == default_volume
    assert ctl(m, "glow").checked is True


def test_hidden_tab_reset_button_still_works(m):
    show(m)
    m.opt.SelectTab(m.opt, "Arrival")
    m.stub.click(ctl(m, "glow"))
    assert m.db.glow is False and m.opt.resets["glow"].shown
    m.stub.click(m.opt.resets["glow"])
    assert m.db.glow is True


def test_the_selected_tab_persists_across_hide_and_show(m):
    show(m)
    m.opt.SelectTab(m.opt, "Arrival")
    p = m.opt.panel
    p.scripts.OnHide(p)
    show(m)
    assert shown_children(m) == ["Arrival"]
    assert same(m, m.opt.scroll.scrollChild, m.opt.tabChildren.Arrival)


def test_flat_text_tabs_when_the_tab_template_is_missing(env):
    m = build(env, pre=no_template("PanelTopTabButtonTemplate"))
    o = m.opt
    assert o.category is not None and o.tabTemplate == "flat"
    tabs = [o.tabs[i] for i in range(1, N + 1)]
    assert [str(t.xpName) for t in tabs] == NAMES and all(t.height == 28 for t in tabs)
    show(m)
    assert shown_children(m) == ["General"]

    def colour(t):
        return tuple(round(t.xpLabel.textColor[i], 2) for i in (1, 2, 3))

    assert colour(tabs[0]) == (1, 0.82, 0) and colour(tabs[1]) == (0.7, 0.7, 0.7)
    assert [bool(t.xpBar.shown) for t in tabs] == [True] + [False] * 4  # the 2 px gold bar marks the selection
    assert tabs[0].xpBar.calls["SetHeight"][1] == 2 and tabs[0].xpBar.points[1][1] == "BOTTOMLEFT"
    m.stub.hover(tabs[1])
    assert colour(tabs[1]) == (1, 1, 1)
    tabs[1].scripts.OnLeave(tabs[1])
    assert colour(tabs[1]) == (0.7, 0.7, 0.7)
    m.stub.click(tabs[2])
    assert shown_children(m) == ["Look"]
    assert colour(tabs[2]) == (1, 0.82, 0) and colour(tabs[0]) == (0.7, 0.7, 0.7)
    assert [bool(t.xpBar.shown) for t in tabs] == [False, False, True, False, False]
    tabs[0].scripts.OnEnter(tabs[0])  # hover on an unselected tab only
    assert colour(tabs[0]) == (1, 1, 1)
    tabs[2].scripts.OnEnter(tabs[2])
    assert colour(tabs[2]) == (1, 0.82, 0)  # the selected one stays gold
    assert tabs[-1].xpX + tabs[-1].xpW <= 568
    (lx, _, lw, _), (rx, _, rw, _) = rules(m)
    assert lx + lw == tabs[2].xpX and rx + rw == 568


def test_a_failing_template_call_is_reported_once_with_debug_on(m):
    m.lua.execute("PanelTemplates_SelectTab = function() error('boom') end")
    m.lua.execute("PanelTemplates_DeselectTab = function() error('boom') end")
    m.opt.SelectTab(m.opt, "Sound")  # debug is off: silent
    assert not any("tab template" in line for line in m.say())
    m.db.debug = True
    m.opt.SelectTab(m.opt, "Look")
    m.opt.SelectTab(m.opt, "Flight")
    assert sum("tab template call failed" in line for line in m.say()) == 1


def test_scroll_bar_hides_when_the_tab_fits(m):
    o = m.opt
    bar = m.lua.eval("CreateFrame")("Frame")
    o.scroll.ScrollBar = bar
    # General is 204 px tall, Flight 446
    o.scroll.SetSize(o.scroll, 600, 500)
    o.SelectTab(o, "General")
    assert not bar.IsShown(bar)
    o.SelectTab(o, "Flight")  # 446 <= 500: still fits
    assert not bar.IsShown(bar)
    o.scroll.SetSize(o.scroll, 600, 300)
    o.scroll.scripts.OnSizeChanged(o.scroll)
    assert bar.IsShown(bar)  # 446 > 300
    o.SelectTab(o, "Sound")
    assert not bar.IsShown(bar)
    o.scroll.SetSize(o.scroll, 600, 0)  # unknown size: never hide on a guess
    o.SelectTab(o, "Sound")
    assert bar.IsShown(bar)


def test_tab_fits_decision(m):
    fits = m.opt.TabFits
    assert fits(100, 200) and fits(200, 200)
    assert not fits(201, 200) and not fits(100, 0) and not fits(100, None)

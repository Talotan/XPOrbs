"""The Look tab: the orb shape first, a boxed group of per-shape settings (size, quantity, opacity and one options row
that depends on the shape), then the shared settings, with the burst cap last."""

import pytest
from test_m5 import build, ctl, show
from test_shape_look import look_of

SHAPES = ["starlight", "retro", "bubble", "crackle"]
PICK = {
    "starlight": "Starlight (default)",
    "retro": "Retro",
    "bubble": "Bubble",
    "crackle": "Crackle",
}
LOOK_ORDER = [
    "orbShape",
    "size",
    "density",
    "opacity",
    "blend",
    "shapeExtra",
    "trail",
    "trailOpacity",
    "color",
    "restedTint",
    "cap",
]
BOX_ROWS = ["size", "density", "opacity", "blend", "shapeExtra", "crackleSpeed"]
NOTE = "No outline or extras: Starlight is always a soft glow with a spinning sparkle."


@pytest.fixture
def m(env):
    m = build(env)
    show(m)
    return m


def same(m, a, b):
    return bool(m.lua.eval("rawequal")(a, b))


def pick(m, shape):
    assert m.stub.pickMenu(m.opt.shapeDropdown, PICK[shape]) is True
    assert m.db.orbShape == shape


def row_y(m, key):
    return -m.opt.rows[key].points[1][5]


def in_chain(m, node, target):
    seen = 0
    while node is not None and seen < 20:
        if same(m, node, target):
            return True
        node = node.createdParent
        seen += 1
    return False


def row_texts(m, key):
    row = m.opt.rows[key]
    return [
        (str(f.text), bool(f.shown))
        for f in m.stub.frames.values()
        if f.kind == "FontString"
        and f.text
        and f.parentFrame is not None
        and same(m, f.parentFrame, row)
    ]


def shown_options(m):
    """Which widgets of the options row are visible: note / blend / sparkle / pulse."""
    c = m.opt.controls
    note = [shown for text, shown in row_texts(m, "blend") if text == NOTE]
    return {
        "note": note == [True],
        "blend": bool(c.blend_natural.shown and c.blend_solid.shown),
        "sparkle": bool(c.sparkle.shown),
        "pulse": bool(c.pulse.shown),
    }


def test_row_order(m):
    ys = [row_y(m, k) for k in LOOK_ORDER]
    assert ys[0] == 8 and ys == sorted(ys) and len(set(ys)) == len(ys)
    assert ys[1:6] == [70, 102, 134, 166, 196]
    # the global rows are grouped: trail | colours | cap (flight speed/time live on the Flight tab)
    assert [row_y(m, k) for k in ("trail", "trailOpacity", "color", "restedTint", "cap")] == [
        240, 268, 308, 338, 374,
    ]
    assert same(m, m.opt.rows.restedTint, m.opt.rows.restedColor)  # one row holds the tickbox and the swatch
    assert row_y(m, "crackleSpeed") == row_y(m, "shapeExtra") - 2  # the 32 px slider row, centred on the 28 px slot
    assert m.opt.tabHeights.Look == 422
    for key in ("flightSpeed", "flightTime"):
        assert same(m, m.opt.rows[key].createdParent, m.opt.tabChildren.Flight), key
        assert not in_chain(m, m.opt.rows[key].createdParent, m.opt.tabChildren.Look), key


def test_box_rows_hang_off_the_box_and_the_others_do_not(m):
    box = m.opt.shapeBox
    for key in BOX_ROWS:
        assert in_chain(m, m.opt.rows[key].createdParent, box), key
    for key in LOOK_ORDER:
        if key not in BOX_ROWS:
            assert not in_chain(m, m.opt.rows[key].createdParent, box), key
    assert same(m, box.createdParent, m.opt.tabChildren.Look)


def test_box_geometry_and_indented_labels(m):
    box = m.opt.shapeBox
    pt = box.points[1]
    assert (pt[1], pt[4], pt[5]) == ("TOPLEFT", 32, -42)
    assert (box.width, box.height) == (536, 188)
    # the rows' labels are indented 16 px from the other tabs' column
    labels = {
        key: [
            f
            for f in m.stub.frames.values()
            if f.kind == "FontString" and f.text == txt
        ]
        for key, txt in (
            ("size", "Orb size"),
            ("density", "Orb quantity"),
            ("cap", "Max orbs per burst"),
        )
    }
    assert [f.points[1][4] for f in labels["size"]] == [48]
    assert [f.points[1][4] for f in labels["density"]] == [48]
    assert [f.points[1][4] for f in labels["cap"]] == [32]
    cap = m.opt.rows["cap"]
    assert row_y(m, "cap") + 32 + 16 == m.opt.tabHeights.Look
    # box rows' resets end 4 px inside the border (x 544), global rows keep 548
    for key in ("size", "density", "opacity", "blend", "shapeExtra", "crackleSpeed"):
        assert m.opt.resets[key].points[1][4] == 544, key
    assert m.opt.resets["cap"].points[1][4] == 548 and cap is not None
    assert m.opt.resets["trail"].points[1][4] == 548
    # the box ends 10 px above the next row
    assert row_y(m, "trail") == 42 + box.height + 10


def test_the_box_has_the_same_height_for_every_shape(m):
    heights = set()
    for shape in SHAPES:
        pick(m, shape)
        heights.add(
            (m.opt.shapeBox.height, row_y(m, "trail"), row_y(m, "blend"), row_y(m, "shapeExtra"))
        )
    assert len(heights) == 1


def test_the_caption_follows_the_shape(m):
    for shape, name in zip(SHAPES, ["Starlight", "Retro", "Bubble", "Crackle"]):
        pick(m, shape)
        assert str(m.opt.shapeBoxCaption.text) == name + " settings"
    cap = m.opt.shapeBoxCaption
    assert [cap.textColor[i] for i in (1, 2, 3)] == pytest.approx([0.7, 0.7, 0.7])
    assert cap.points[1][4] == 16 and cap.points[1][5] == -8  # on the rows' label column


@pytest.mark.parametrize(
    "shape, expect",
    [
        ("starlight", {"note": True, "blend": False, "sparkle": False, "pulse": False}),
        ("retro", {"note": False, "blend": True, "sparkle": True, "pulse": False}),
        ("bubble", {"note": False, "blend": True, "sparkle": False, "pulse": True}),
        ("crackle", {"note": False, "blend": True, "sparkle": False, "pulse": False}),
    ],
)
def test_the_options_row_shows_what_the_shape_uses(m, shape, expect):
    pick(m, shape)
    assert shown_options(m) == expect
    # the radios' captions travel with them
    c = m.opt.controls
    assert bool(c.blend_natural.xpLabel.shown) == expect["blend"]
    assert bool(c.blend_solid.xpLabel.shown) == expect["blend"]
    # row B holds only the checkbox: its caption and box follow the same shape
    extra = {t: bool(sh) for t, sh in row_texts(m, "shapeExtra")}
    assert extra["Sparkle"] == expect["sparkle"] and extra["Pulsing"] == expect["pulse"]


def test_the_extra_checkbox_sits_like_a_standard_checkbox_row(m):
    c = m.opt.controls
    assert c.sparkle.points[1][4] == 257 and c.pulse.points[1][4] == 257  # CTRL_X - 3, like Trail
    assert c.sparkle.points[1][4] == m.opt.controls.trail.points[1][4]
    for text in ("Sparkle", "Pulsing"):
        label = next(
            f for f in m.stub.frames.values()
            if f.kind == "FontString" and f.text == text and f.points[1][4] == 48
        )
        assert label is not None
    assert row_y(m, "shapeExtra") == row_y(m, "blend") + 30


def test_the_starlight_note_is_centred_across_both_rows(m):
    note = next(
        f for f in m.stub.frames.values() if f.kind == "FontString" and f.text == NOTE
    )
    assert note.points[1][4] == 48 and note.points[1][5] == -14
    assert not m.opt.controls.sparkle.shown and not m.opt.controls.pulse.shown


def test_blend_radios_write_per_shape(m):
    pick(m, "retro")
    c = m.opt.controls
    assert c.blend_natural.checked is True and c.blend_solid.checked is False
    m.stub.click(c.blend_solid)
    assert m.db.blend == "solid" and m.db.shapeLook.retro.blend == "solid"
    assert m.db.shapeLook.bubble.blend == "natural"
    assert c.blend_solid.checked is True and c.blend_natural.checked is False
    pick(m, "bubble")
    assert m.db.blend == "natural" and c.blend_natural.checked is True
    pick(m, "retro")
    assert c.blend_solid.checked is True


def test_blend_tooltips(m):
    pick(m, "crackle")
    c = m.opt.controls
    m.stub.hover(c.blend_natural)
    assert "brightening where they overlap" in " ".join(str(x) for x in m.stub.tooltip.lines.values())
    m.stub.hover(c.blend_solid)
    assert "colours stay true on bright ground" in " ".join(str(x) for x in m.stub.tooltip.lines.values())


def test_sparkle_and_pulse_checkboxes_write_per_shape(m):
    c = m.opt.controls
    pick(m, "retro")
    assert c.sparkle.checked is True
    m.stub.click(c.sparkle)
    assert m.db.sparkle is False and m.db.shapeLook.retro.sparkle is False
    assert m.db.shapeLook.bubble.sparkle is True
    pick(m, "bubble")
    assert c.pulse.checked is False  # Pulsing starts off
    m.stub.hover(c.pulse)
    assert str(m.stub.tooltip.text) == "Bubble orbs gently swell and shrink."
    m.stub.click(c.pulse)
    assert m.db.pulse is True and m.db.shapeLook.bubble.pulse is True
    assert m.db.shapeLook.retro.pulse is False


def size_label(m):
    return [
        str(f.text)
        for f in m.stub.frames.values()
        if f.kind == "FontString" and f.text in ("Orb size", "Pixel size")
    ]


def test_retro_calls_it_pixel_size_with_a_hint(m):
    assert size_label(m) == ["Orb size"]
    pick(m, "retro")
    assert size_label(m) == ["Pixel size"]
    m.stub.hover(ctl(m, "size"))
    assert "size of each art pixel" in str(m.stub.tooltip.text)
    m.stub.hover(m.opt.valueButtons["size"])
    assert "size of each art pixel" in str(m.stub.tooltip.text)
    pick(m, "bubble")
    assert size_label(m) == ["Orb size"]
    m.stub.tooltip.text = None
    m.stub.hover(ctl(m, "size"))
    assert m.stub.tooltip.text is None or "art pixel" not in str(m.stub.tooltip.text)
    m.stub.hover(m.opt.valueButtons["size"])
    assert "art pixel" not in str(m.stub.tooltip.text)


def test_the_size_slider_follows_the_shape(m):
    s = ctl(m, "size")
    text = lambda: str(m.opt.valueTexts["size"].text)
    assert (s.minV, s.maxV, s.step) == (8, 32, 1) and text() == "14"
    pick(m, "retro")
    assert (s.minV, s.maxV, s.step) == (1, 5, 1) and text() == "2 px" and s.value == 2
    for shape in ("bubble", "crackle", "starlight"):
        pick(m, shape)
        assert (s.minV, s.maxV, s.step) == (8, 32, 1) and text() == "14"


def test_switching_shapes_never_writes_a_clamped_size_back(m):
    s = ctl(m, "size")
    pick(m, "bubble")
    m.stub.slide(s, 14)
    pick(m, "retro")
    assert m.db.size == 2
    m.stub.slide(s, 5)
    assert m.db.shapeLook.retro.size == 5 and m.db.shapeLook.bubble.size == 14
    pick(m, "bubble")
    assert m.db.size == 14 and s.value == 14
    pick(m, "retro")
    assert m.db.size == 5 and s.value == 5 and look_of(m.db, "bubble")[0] == 14


def test_a_typed_size_uses_the_current_range(m):
    pick(m, "retro")
    m.stub.rightClick(m.opt.valueButtons["size"])
    m.stub.enterText(m.opt.editBoxes["size"], "40")
    assert m.db.size == 5  # nearest permitted value on Retro, not on the 8..32 range
    m.stub.hover(m.opt.valueButtons["size"])
    assert "(1" in str(m.stub.tooltip.text) and "5 px)" in str(m.stub.tooltip.text)
    pick(m, "bubble")
    m.stub.hover(m.opt.valueButtons["size"])
    assert "(8" in str(m.stub.tooltip.text) and "32)" in str(m.stub.tooltip.text)


def test_the_two_option_resets_are_separate_and_per_shape(m):
    c = m.opt.controls
    blend_btn, extra_btn = m.opt.resets["blend"], m.opt.resets["shapeExtra"]
    assert not blend_btn.shown and not extra_btn.shown
    assert m.opt.resets["sparkle"] is not None and m.opt.resets["pulse"] is not None
    pick(m, "retro")
    m.stub.click(c.blend_solid)
    assert blend_btn.shown and not extra_btn.shown
    m.stub.click(c.sparkle)
    assert extra_btn.shown
    m.stub.hover(blend_btn)
    assert str(m.stub.tooltip.text) == "Reset to default: Overlap Type glow"
    m.stub.hover(extra_btn)
    assert str(m.stub.tooltip.text) == "Reset to default: Sparkle on"
    pick(m, "bubble")
    assert not blend_btn.shown and not extra_btn.shown
    m.stub.click(c.pulse)
    assert extra_btn.shown
    m.stub.hover(extra_btn)
    assert str(m.stub.tooltip.text) == "Reset to default: Pulsing off"
    m.stub.click(extra_btn)
    assert m.db.pulse is False and not extra_btn.shown
    # Retro's own entry is untouched
    assert m.db.shapeLook.retro.blend == "solid" and m.db.shapeLook.retro.sparkle is False
    pick(m, "retro")
    m.stub.click(blend_btn)
    m.stub.click(extra_btn)
    assert m.db.shapeLook.retro.blend == "natural" and m.db.shapeLook.retro.sparkle is True
    assert not blend_btn.shown and not extra_btn.shown


def test_starlight_and_crackle_have_no_extra_to_reset(m):
    for shape in ("starlight", "crackle"):
        pick(m, shape)
        assert not m.opt.resets["shapeExtra"].shown
        m.stub.hover(m.opt.resets["shapeExtra"])
        assert str(m.stub.tooltip.text) == "Reset to default: nothing to reset"
    assert not m.opt.resets["blend"].shown


def test_the_cap_comes_last_with_its_tooltip(m):
    assert row_y(m, "cap") > row_y(m, "restedColor")  # restedColor is the Rested orb colour row
    m.stub.hover(ctl(m, "cap"))
    assert (
        str(m.stub.tooltip.text)
        == "Lowering the cap can improve performance on less powerful computers."
    )


def test_the_quantity_label(m):
    texts = [
        str(f.text) for f in m.stub.frames.values() if f.kind == "FontString" and f.text
    ]
    assert "Orb quantity" in texts and "Orb quantity multiplier" not in texts

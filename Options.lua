-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Settings panel (v0.13): a canvas category under Esc > Options > AddOns. Fixed title and footer, a scrolling body with
-- a label column and a control column (layout spec: docs/review-v012/review.md). Every control writes ns.db directly
-- (changes apply to the next burst) and the panel re-reads ns.db whenever it is shown or a slash command changes it.

local Options = {}
ns.Options = Options

local OrbMath = ns.OrbMath
local floor = math.floor

-- Layout (UI px, relative to the scroll child; y grows downwards).
local HEADER_X, LABEL_X, CTRL_X, VALUE_X, RESET_X = 16, 32, 260, 472, 548
local SLIDER_W = 200
local RULE_W = 552
local CONTENT_W, CONTENT_H = 584, 0 -- CONTENT_H: the tallest tab's height (|last y| + 16); newTabs sets it
local DIM = 0.4
local SWATCH_OFF_ALPHA = 0.35
local GREY = 0.70
local EN_DASH = "\226\128\147"
local POPUP = "XPORBS_RESET_ALL"
local ICON_ATLAS = "transmog-icon-revert"
local ICON_FALLBACK = "Interface\\Buttons\\UI-RefreshButton"
local HILITE = "Interface\\Buttons\\ButtonHilight-Square"

-- Kill styles (schema 6): three archetypes; Popstream has a Nameplate / Direct sub-choice (db.popMode). Each line says
-- whether the style uses the nameplate, the estimated mob position or both, and whether it has a pop.
local STYLES = { "popstream", "crossfade", "stream" }
local STYLE_NAME = { popstream = "Popstream", crossfade = "Crossfade", stream = "Direct Stream" }
local STYLE_DESC = {
    popstream = "A pop of orbs at the mob, then a stream to the bar. Pick where it pops:",
    crossfade = "Pop on the nameplate (if shown); the orbs reappear just above the bar.",
    stream = "A plain stream from the estimated position. No pop, no nameplate needed.",
}
local POPMODES = { "nameplate", "direct" }
local POPMODE_NAME = { nameplate = "Nameplate", direct = "Direct" }
local POPMODE_DESC = {
    nameplate = "Pop on the nameplate (if shown), stream from the estimated position.",
    direct = "Pop and stream from the estimated position. No nameplate needed.",
}
local SPREAD_DESC = "Wider when zoomed in, tighter when zoomed out."
local SPREAD_TIP = "Applies to all three styles: the nameplate pop, the pop or stream start at the estimated position. "
    .. "At the default camera zoom nothing changes. A mob you didn't mouse over always starts over a wide area that "
    .. "scales with zoom, whatever this says."
local DESC_DIM = 0.55 -- dimmed descriptions stay readable (rows and controls use DIM)
local SHAPES = { "bar", "vertical", "round" }
local SHAPE_NAME = { bar = "Horizontal", vertical = "Vertical", round = "Circular" }
local SHAPE_SPACING = 100 -- px between the shape radios
local SHAPE_TIP = {
    bar = "Orbs land on the bar's fill edge. A vertical bar the addon recognises gets the vertical glow automatically.",
    vertical = "A bar that fills bottom to top.",
    round = "The centre of a round frame, such as a portrait.",
}
local QUEST_TIP = "Orbs for quest turn-ins and other XP that is not a kill or exploration."
local EXPLORE_TIP = "Orbs for the XP you get from discovering a new area."
local FLIGHT_PATH_DESC = {
    smooth = "A clean arc from the mob to your XP bar.",
    chaos = "Orbs dart and weave like fireflies on the way.",
    helix = "Orbs spiral around each other in pairs.",
}
local ORB_SHAPE_DESC = {
    starlight = "Soft glowing orbs with a spinning sparkle.",
    retro = "Chunky pixel-art orbs that move in blocky steps.",
    bubble = "Smooth glossy orbs with a long soft tail; they can gently pulse.",
    crackle = "A bright core with lightning crackling round its edge.",
}
local PULSE_TIP = "Bubble orbs gently swell and shrink."
local CAP_TIP = "Lowering the cap can improve performance on less powerful computers."
local MAX_TIP = "At max level, each kill sends a small burst of orbs to your portrait."
local SOUND_TIP = "Glass: a glassy tink. Coin: a soft coin clink. Swish: a soft brushed whoosh. "
    .. "Pixel: a retro chip-tune ding. "
    .. "One per arriving orb (up to six per burst). On by default."
local PLAY_X = 156 -- px right of CTRL_X: just past the 150 px voice dropdown
local PLAY_ATLAS = "voicechat-icon-speaker"
local PLAY_FALLBACK = "Interface\\Common\\VoiceChat-Speaker"
local PLAY_TIP = "Play a sample: a handful of orbs arriving"
local VOICES = { "glass", "coin", "swish", "pixel" }
local VOICE_NAME = { glass = "Glass", coin = "Coin", swish = "Swish", pixel = "Pixel" }
local RADIO_STEP = 64 -- radio fallback: px between the four voice radios (they fit between CTRL_X and the reset button)
local OFFSET_TIP = "Moves where orbs land and the glow appears (pixels)."
local PICK_HINT = "For a replaced XP bar, or to target your portrait (Circular)."

local refreshers, postRefresh, resets = {}, {}, {}
local refreshing = false
-- Size, quantity and opacity belong to the current orb shape (ns.SetLook / ns.ShapeDefault, Core.lua): a slider writes
-- the active value and the shape's own entry, and a reset button restores the current shape's default.
local LOOK = {}
for _, lookKey in ipairs(ns.SHAPE_LOOK_KEYS) do
    LOOK[lookKey] = true
end
local child -- the scroll child every row hangs off
-- when set, newRow hangs rows off this frame instead (the Look tab's shape box); positions stay child-relative
local rowParent
Options.controls = {} -- key -> the widget (checkbox, slider, swatch, radio)
Options.rows = {} -- key -> the row frame (dimming and layout)
Options.resets = {} -- key -> the per-row reset button
Options.descs = {} -- style / popMode / "zoomSpread" -> its description FontString
Options.CONTENT_H = CONTENT_H

local function settings()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function lookDefault(key)
    return ns.ShapeDefault(settings().orbShape, key)
end

local LOOK_RESET = {
    default = lookDefault,
    reset = function(key)
        ns.SetLook(key, lookDefault(key))
    end,
}

-- The orb shape's own reset: back to the default shape (which swaps the look settings, like picking it does).
local SHAPE_RESET = {
    default = function()
        return ns.defaults.orbShape
    end,
    reset = function()
        ns.SetOrbShape(ns.defaults.orbShape)
    end,
}

local function writeValue(key, value)
    if LOOK[key] then
        ns.SetLook(key, value)
    else
        settings()[key] = value
    end
end

local function updateResets()
    for i = 1, #resets do
        pcall(resets[i])
    end
end

local function applyDim()
    for i = 1, #postRefresh do
        pcall(postRefresh[i])
    end
end

-- After any value change made through the panel.
local function changed()
    updateResets()
    applyDim()
end

-- Re-read every control from ns.db (OnShow, reset, slash changes).
function Options:Refresh()
    if #refreshers == 0 then
        return
    end
    refreshing = true
    for i = 1, #refreshers do
        pcall(refreshers[i])
    end
    refreshing = false
    changed()
end

local function copyDefault(v)
    if type(v) == "table" then
        local t = {}
        for k, x in pairs(v) do
            t[k] = x
        end
        return t
    end
    return v
end

local function hex(colour)
    if type(colour) ~= "table" then
        return "?"
    end
    local function byte(v)
        return floor((tonumber(v) or 0) * 255 + 0.5)
    end
    return string.format("#%02X%02X%02X", byte(colour[1]), byte(colour[2]), byte(colour[3]))
end

local function onOff(v)
    return v and "on" or "off"
end

local function showTip(owner, str)
    if not GameTooltip then
        return
    end
    pcall(function()
        GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
        GameTooltip:SetText(str)
        GameTooltip:Show()
    end)
end

-- A title line and a wrapped body (style radios, the Wide checkbox).
local function showTip2(owner, title, body)
    if not GameTooltip then
        return
    end
    pcall(function()
        GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
        GameTooltip:SetText(title)
        GameTooltip:AddLine(body, 1, 1, 1, true)
        GameTooltip:Show()
    end)
end

local function hideTip()
    if GameTooltip then
        pcall(GameTooltip.Hide, GameTooltip)
    end
end

-- ---------------------------------------------------------------- building blocks

local function text(parent, template, str, x, y, width)
    local fontString = parent:CreateFontString(nil, "ARTWORK", template)
    fontString:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    fontString:SetJustifyH("LEFT")
    if width then
        fontString:SetWidth(width)
    end
    fontString:SetText(str)
    return fontString
end

-- A full-width row frame of height h at y. Its label, control and reset button anchor LEFT to it, so they share its
-- centre line; it is also what dimming hangs on.
local function newRow(y, h)
    local row = CreateFrame("Frame", nil, rowParent or child)
    row:SetSize(CONTENT_W, h)
    row:SetPoint("TOPLEFT", child, "TOPLEFT", 0, -y)
    return row
end

local function label(row, str, x)
    local fontString = row:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    fontString:SetPoint("LEFT", row, "LEFT", x, 0)
    fontString:SetJustifyH("LEFT")
    fontString:SetText(str)
    return fontString
end

local function hideTemplateText(btn)
    for _, k in ipairs({ "Text", "text" }) do
        local fontString = btn[k]
        if type(fontString) == "table" and fontString.Hide then
            if fontString.SetText then
                fontString:SetText("")
            end
            fontString:Hide()
        end
    end
end

local function enable(frame, on)
    if not frame then
        return
    end
    if on then
        if frame.Enable then
            pcall(frame.Enable, frame)
        end
    elseif frame.Disable then
        pcall(frame.Disable, frame)
    end
end

-- Dim a row and disable what's in it while its parent setting is off.
local function setDim(row, controls, on)
    if row then
        row:SetAlpha(on and 1 or DIM)
    end
    for _, c in ipairs(controls) do
        enable(c, on)
    end
end

local function newCheck(row, x)
    local cb = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate")
    cb:SetSize(24, 24)
    cb:SetPoint("LEFT", row, "LEFT", x, 0)
    hideTemplateText(cb)
    return cb
end

local RADIO = 20

-- A radio button that owns its label (a row FontString at x + 24). The hit rect extends over the label so clicking the
-- label selects it. Falls back to a check button when the template is missing.
local function newRadio(row, x, labelStr)
    local ok, rb = pcall(CreateFrame, "CheckButton", nil, row, "UIRadioButtonTemplate")
    if ok and rb then
        rb:SetSize(RADIO, RADIO)
        rb:SetPoint("LEFT", row, "LEFT", x - 2, 0)
        hideTemplateText(rb)
    else
        rb = newCheck(row, x - 4)
    end
    local fs = label(row, labelStr, x + 24)
    rb.xpLabel = fs -- so a row that shows and hides its radios can hide the caption with them
    local okW, w = pcall(function()
        return fs:GetStringWidth()
    end)
    if not (okW and type(w) == "number") then
        w = 100
    end
    if rb.SetHitRectInsets then
        pcall(rb.SetHitRectInsets, rb, 0, -(w + 8), -4, -4)
    end
    return rb
end

-- The small revert button in the gutter. keys: db keys it resets (a colour row has two). describe() -> default text.
-- custom { default(key), reset(key) } replaces the plain ns.defaults value for keys whose default depends on something
-- else (the current orb shape).
local function addReset(row, name, keys, describe, custom, x)
    local btn = CreateFrame("Button", nil, row)
    btn:SetSize(20, 20)
    btn:SetPoint("LEFT", row, "LEFT", x or RESET_X, 0)
    local tex = btn:CreateTexture(nil, "ARTWORK")
    tex:SetAllPoints(btn)
    local okAtlas = false
    if C_Texture and C_Texture.GetAtlasInfo then
        local okInfo, info = pcall(C_Texture.GetAtlasInfo, ICON_ATLAS)
        if okInfo and info then
            okAtlas = pcall(tex.SetAtlas, tex, ICON_ATLAS)
        end
    end
    if not okAtlas then
        tex:SetTexture(ICON_FALLBACK)
    end
    pcall(btn.SetHighlightTexture, btn, HILITE, "ADD")
    btn:SetAlpha(0.75)
    btn:SetScript("OnEnter", function(self)
        self:SetAlpha(1)
        showTip(self, "Reset to default: " .. describe())
    end)
    btn:SetScript("OnLeave", function(self)
        self:SetAlpha(0.75)
        hideTip()
    end)
    btn:SetScript("OnClick", function()
        local saved = settings()
        for _, k in ipairs(keys) do
            if custom then
                custom.reset(k)
            else
                saved[k] = copyDefault(ns.defaults[k])
            end
        end
        hideTip()
        Options:Refresh()
    end)
    btn:Hide() -- shown by updateResets once the db is known; it keeps its space either way
    resets[#resets + 1] = function()
        local saved, differs = settings(), false
        for _, k in ipairs(keys) do
            local default = ns.defaults[k]
            if custom then
                default = custom.default(k)
            end
            if OrbMath.Differs(saved[k], default) then
                differs = true
            end
        end
        if differs then
            btn:Show()
        else
            btn:Hide()
        end
    end
    for _, k in ipairs(keys) do
        Options.resets[k] = btn
    end
    Options.resets[name] = btn
    return btn
end

-- opts.get() / opts.set(bool) replace the flat ns.db[key] read and write (the minimap row lives in a nested table);
-- such a row has no per-row reset button (the global reset covers it).
local function checkbox(y, key, labelStr, opts)
    opts = opts or {}
    local row = newRow(y, 28)
    label(row, labelStr, opts.labelX or LABEL_X)
    local cb = newCheck(row, CTRL_X - 3)
    local resetX = opts.resetX
    local get = opts.get or function()
        return settings()[key]
    end
    local set = opts.set or function(v)
        settings()[key] = v
    end
    cb:SetScript("OnClick", function(self)
        set(self:GetChecked() and true or false)
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        cb:SetChecked(get() and true or false)
    end
    if not opts.set then
        addReset(row, key, { key }, function()
            return onOff(ns.defaults[key])
        end, nil, resetX)
    end
    if opts.tip then
        cb:SetScript("OnEnter", function(self)
            showTip(self, opts.tip)
        end)
        cb:SetScript("OnLeave", hideTip)
    end
    Options.controls[key] = cb
    Options.rows[key] = row
    return row, cb
end

-- The slider adapter: the one place that knows the template's API. MinimalSliderWithSteppersTemplate is the slider the
-- game's own Settings panel uses (arrows either side, a bronze thumb on Forever), so reskin addons treat it like the
-- game's. Its host Frame is dressed here as the plain Slider the rest of the panel was written against:
-- SetMinMaxValues, SetValueStep (the template wants min, max and a step COUNT, so each change re-Inits), SetValue /
-- GetValue, Enable / Disable, SetScript("OnValueChanged") and OnEnter / OnLeave (forwarded to the bar and arrows).
-- minV, maxV, step and value mirror what was set. An Init never reaches the OnValueChanged handler, so only a real
-- change (a drag, an arrow or our own SetValue) does; Refresh guards its own SetValue with `refreshing`, as before.
local function dressMinimalSlider(host)
    local inner, mixin = host.Slider, MinimalSliderWithSteppersMixin
    if not (inner and inner.SetValue and inner.GetValue and mixin and mixin.Event and host.Init
        and host.RegisterCallback) then
        return false
    end
    local tplSetEnabled, noLabels, rebuilding = host.SetEnabled, {}, false
    for _, k in ipairs({ "LeftText", "RightText", "TopText", "MinText", "MaxText" }) do
        if host[k] and host[k].Hide then
            host[k]:Hide() -- our own label and value text sit beside it
        end
    end
    local function rebuild()
        if not (host.minV and host.maxV and host.step and host.step > 0) then
            return
        end
        local steps = math.max(1, floor((host.maxV - host.minV) / host.step + 0.5))
        local v = math.max(host.minV, math.min(host.maxV, host.value or host.minV))
        rebuilding = true
        local ok = pcall(host.Init, host, v, host.minV, host.maxV, steps, noLabels)
        rebuilding = false
        host.value = ok and inner:GetValue() or v
    end
    local onChanged
    host:RegisterCallback(mixin.Event.OnValueChanged, function(_, v)
        host.value = v
        if onChanged and not rebuilding then
            onChanged(host, v)
        end
    end, host)
    function host:SetMinMaxValues(lo, hi)
        self.minV, self.maxV = lo, hi
        rebuild()
    end
    function host:SetValueStep(step)
        self.step = step
        rebuild()
    end
    function host:SetValue(v)
        inner:SetValue(v)
        self.value = inner:GetValue()
    end
    function host:GetValue()
        return inner:GetValue()
    end
    local function setEnabled(self, on)
        self.xpEnabled = on
        if tplSetEnabled then
            tplSetEnabled(self, on)
        else
            pcall(inner[on and "Enable" or "Disable"], inner)
        end
    end
    function host:SetEnabled(on)
        setEnabled(self, on and true or false)
    end
    function host:Enable()
        setEnabled(self, true)
    end
    function host:Disable()
        setEnabled(self, false)
    end
    function host:IsEnabled()
        return self.xpEnabled ~= false
    end
    local setScript = host.SetScript
    function host:SetScript(name, fn)
        if name == "OnValueChanged" then
            onChanged = fn
        elseif name == "OnEnter" or name == "OnLeave" then
            for _, part in ipairs({ inner, host.Back, host.Forward }) do
                if part and part.SetScript then
                    local hook = part.HookScript or part.SetScript -- keeps the template's own highlight
                    pcall(hook, part, name, fn and function(_, ...)
                        fn(host, ...)
                    end or nil)
                end
            end
        else
            setScript(self, name, fn)
        end
    end
    return true
end

-- A slider in `row`: the stepper template (see dressMinimalSlider), else OptionsSliderTemplate, else a bare Slider.
-- Also Options.NewSlider, for the setup window.
local function newSlider(row)
    local ok, host = pcall(CreateFrame, "Frame", nil, row, "MinimalSliderWithSteppersTemplate")
    if ok and host then
        local dressed, usable = pcall(dressMinimalSlider, host)
        if dressed and usable then
            return host
        end
        pcall(host.Hide, host)
    end
    local sliderFrame
    ok, sliderFrame = pcall(CreateFrame, "Slider", nil, row, "OptionsSliderTemplate")
    if ok and sliderFrame then
        -- the template's own title and min/max captions are replaced by our label and value text
        for _, k in ipairs({ "Text", "Low", "High" }) do
            if sliderFrame[k] and sliderFrame[k].Hide then
                sliderFrame[k]:Hide()
            end
        end
        return sliderFrame
    end
    sliderFrame = CreateFrame("Slider", nil, row)
    sliderFrame:SetOrientation("HORIZONTAL")
    sliderFrame:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
    local bg = sliderFrame:CreateTexture(nil, "BACKGROUND")
    bg:SetColorTexture(0, 0, 0, 0.5)
    bg:SetPoint("LEFT", sliderFrame, "LEFT", 0, 0)
    bg:SetPoint("RIGHT", sliderFrame, "RIGHT", 0, 0)
    bg:SetHeight(6)
    return sliderFrame
end
Options.NewSlider = newSlider

-- Right-click the value to type one: an InputBoxTemplate box replaces the text; Enter or losing focus applies the
-- nearest permitted value, Escape cancels, junk restores the old value. Returns nothing when the template is missing.
-- range() -> lo, hi, step and unit (a string or a function) are read each time, so a slider whose range follows the
-- orb shape stays right.
local function attachValueEdit(row, key, val, range, unit, hint)
    local okE, eb = pcall(CreateFrame, "EditBox", nil, row, "InputBoxTemplate")
    if not okE or not eb then
        return
    end
    local hit = CreateFrame("Button", nil, row)
    hit:SetSize(56, 20)
    hit:SetPoint("LEFT", row, "LEFT", VALUE_X, 0)
    pcall(hit.RegisterForClicks, hit, "RightButtonUp")
    eb:SetSize(50, 20)
    eb:SetPoint("LEFT", row, "LEFT", VALUE_X + 5, 0)
    pcall(eb.SetAutoFocus, eb, false)
    pcall(eb.SetMaxLetters, eb, 8)
    eb:Hide()
    local editing = false
    local function finish(apply)
        if not editing then
            return
        end
        editing = false
        local typed = eb:GetText()
        eb:Hide()
        hit:Show()
        val:Show()
        if apply then
            local lo, hi, step = range()
            local v = OrbMath.Snap(OrbMath.ParseNumber(typed), lo, hi, step)
            if v then
                writeValue(key, v)
            end
        end
        Options:Refresh() -- repaints the slider and the value text (the old value when the input was junk)
    end
    eb:SetScript("OnEnterPressed", function()
        finish(true)
    end)
    eb:SetScript("OnEscapePressed", function()
        finish(false)
    end)
    eb:SetScript("OnEditFocusLost", function()
        finish(true)
    end)
    hit:SetScript("OnClick", function(_, button)
        if button ~= "RightButton" or editing then
            return
        end
        local cur = settings()[key]
        if type(cur) ~= "number" then
            return
        end
        hideTip()
        editing = true
        val:Hide()
        hit:Hide()
        eb:SetText(string.format("%g", cur))
        eb:Show()
        pcall(eb.SetFocus, eb)
        pcall(eb.HighlightText, eb)
    end)
    hit:SetScript("OnEnter", function()
        val:SetTextColor(1, 1, 1)
        local lo, hi = range()
        local u = type(unit) == "function" and unit() or unit
        local extra = hint and hint()
        local rangeTip = string.format("Right-click to type a value (%g%s%g%s)", lo, EN_DASH, hi, u)
        showTip(hit, rangeTip .. (extra and ("\n" .. extra) or ""))
    end)
    hit:SetScript("OnLeave", function()
        val:SetTextColor(1, 0.82, 0)
        hideTip()
    end)
    Options.editBoxes = Options.editBoxes or {}
    Options.editBoxes[key] = eb
    Options.valueTexts = Options.valueTexts or {}
    Options.valueTexts[key] = val
    Options.valueButtons = Options.valueButtons or {}
    Options.valueButtons[key] = hit
end

-- The range (min, max, step) comes from ns.ranges (Core.lua), the same table InitDB clamps saved values with.
-- onChange(v), if given, runs after a drag (or a click on the bar) stores a new value, not on Refresh.
-- opts (all optional): range() -> { lo, hi, step } and fmt / unit as functions replace the fixed ones (the size slider
-- follows the orb shape); labelX moves the label (rows inside a box); tip is a tooltip on the slider.
local function slider(y, key, labelStr, fmt, unit, onChange, opts)
    opts = opts or {}
    local function range()
        local r = opts.range and opts.range() or ns.ranges[key]
        return r[1], r[2], r[3]
    end
    local function fmtNow()
        return type(fmt) == "function" and fmt() or fmt
    end
    local lo, hi, step = range()
    local row = newRow(y, 32)
    local labelText = label(row, labelStr, opts.labelX or LABEL_X)
    local sliderFrame = newSlider(row)
    sliderFrame:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
    sliderFrame:SetSize(SLIDER_W, 16)
    sliderFrame:SetMinMaxValues(lo, hi)
    sliderFrame:SetValueStep(step)
    if sliderFrame.SetObeyStepOnDrag then
        sliderFrame:SetObeyStepOnDrag(true)
    end
    local val = row:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    val:SetPoint("LEFT", row, "LEFT", VALUE_X, 0)
    val:SetJustifyH("LEFT")
    sliderFrame:SetScript("OnValueChanged", function(_, v)
        local low, high, stepSize = range()
        v = OrbMath.Snap(v, low, high, stepSize)
        if not v then
            return
        end
        val:SetText(string.format(fmtNow(), v))
        if not refreshing then
            writeValue(key, v)
            changed()
            if onChange then
                onChange(v)
            end
        end
    end)
    refreshers[#refreshers + 1] = function()
        local v = settings()[key]
        if type(v) ~= "number" then
            return
        end
        local low, high, stepSize = range()
        if opts.label then
            labelText:SetText(opts.label())
        end
        if opts.range then
            -- new limits first: the client may clamp (and report) the old value while they change; `refreshing` keeps
            -- that from being written back
            sliderFrame:SetMinMaxValues(low, high)
            sliderFrame:SetValueStep(stepSize)
        end
        sliderFrame:SetValue(v)
        val:SetText(string.format(fmtNow(), OrbMath.Snap(v, low, high, stepSize) or v))
    end
    attachValueEdit(row, key, val, range, unit, opts.hint)
    addReset(row, key, { key }, function()
        return string.format(fmtNow(), LOOK[key] and lookDefault(key) or ns.defaults[key])
    end, LOOK[key] and LOOK_RESET or nil, opts.resetX)
    if opts.tip then
        sliderFrame:SetScript("OnEnter", function(self)
            local tip = type(opts.tip) == "function" and opts.tip() or opts.tip
            if tip then
                showTip(self, tip)
            end
        end)
        sliderFrame:SetScript("OnLeave", hideTip)
    end
    Options.controls[key] = sliderFrame
    Options.rows[key] = row
end

-- Black has no hue, so a picker that round-trips through RGB snaps its wheel to the centre when the value slider hits 0
-- (and brings back grey). The ColorSelect widget keeps HSV: the last hue and saturation (value above HS_MIN_V) is
-- remembered per colour key in db.colorHS and pushed back whenever the picker loses it. All of it is optional: with no
-- HSV API nothing here does anything.
local HS_MIN_V = 0.02
local HS_EPS = 0.002
local pickerSyncing = false -- SetColorHSV may fire OnColorSelect -> swatchFunc again: ignore that echo

local function colorSelect()
    local content = ColorPickerFrame and ColorPickerFrame.Content
    local colourPicker = content and content.ColorPicker
    if type(colourPicker) == "table" and colourPicker.GetColorHSV and colourPicker.SetColorHSV then
        return colourPicker
    end
end

local function readHSV(colourPicker)
    local ok, h, s, v = pcall(colourPicker.GetColorHSV, colourPicker)
    if ok and type(h) == "number" and type(s) == "number" and type(v) == "number" then
        return h, s, v
    end
end

local function pushHSV(colourPicker, h, s, v)
    pickerSyncing = true
    pcall(colourPicker.SetColorHSV, colourPicker, h, s, v)
    pickerSyncing = false
end

local function rememberHS(key, h, s)
    local db = settings()
    if type(db.colorHS) ~= "table" then
        db.colorHS = {}
    end
    db.colorHS[key] = { h, s }
end

local function savedHS(key)
    local pair = type(settings().colorHS) == "table" and settings().colorHS[key]
    if type(pair) == "table" and type(pair[1]) == "number" and type(pair[2]) == "number" then
        return pair
    end
end

-- Called from the picker's swatchFunc with what the widget holds now.
local function keepHue(key)
    local colourPicker = colorSelect()
    if not colourPicker or pickerSyncing then
        return
    end
    local h, s, v = readHSV(colourPicker)
    if not h then
        return
    end
    if v > HS_MIN_V then
        rememberHS(key, h, s)
        return
    end
    local saved = savedHS(key)
    if saved and (math.abs(h - saved[1]) > HS_EPS or math.abs(s - saved[2]) > HS_EPS) then
        pushHSV(colourPicker, saved[1], saved[2], v)
    end
end

-- Right after the picker opens on a colour: remember its hue, or (opened on black) show the remembered one.
local function openHue(key, red, green, blue)
    local colourPicker = colorSelect()
    if not colourPicker then
        return
    end
    local value = math.max(red or 0, green or 0, blue or 0)
    if value <= HS_MIN_V then
        local saved = savedHS(key)
        if saved then
            pushHSV(colourPicker, saved[1], saved[2], value)
        end
        return
    end
    local h, s, v = readHSV(colourPicker)
    if h and v > HS_MIN_V then
        rememberHS(key, h, s)
    end
end

-- A colour swatch at x in the row. Returns the swatch button (hidden when there is no colour picker).
local function swatch(row, key, x)
    local swatchBtn = CreateFrame("Button", nil, row)
    swatchBtn:SetSize(22, 22)
    swatchBtn:SetPoint("LEFT", row, "LEFT", x, 0)
    local border = swatchBtn:CreateTexture(nil, "BACKGROUND")
    border:SetAllPoints(swatchBtn)
    border:SetColorTexture(0.75, 0.75, 0.75, 1)
    local fill = swatchBtn:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("TOPLEFT", swatchBtn, "TOPLEFT", 2, -2)
    fill:SetPoint("BOTTOMRIGHT", swatchBtn, "BOTTOMRIGHT", -2, 2)
    local function paint()
        local colour = settings()[key]
        if type(colour) == "table" then
            fill:SetColorTexture(colour[1] or 1, colour[2] or 1, colour[3] or 1, 1)
        end
    end
    swatchBtn:SetScript("OnClick", function()
        if swatchBtn.IsEnabled and not swatchBtn:IsEnabled() then
            return
        end
        if not ColorPickerFrame or not ColorPickerFrame.SetupColorPickerAndShow then
            return
        end
        local colour = settings()[key]
        local prev = { colour[1], colour[2], colour[3] }
        ColorPickerFrame:SetupColorPickerAndShow({
            r = prev[1],
            g = prev[2],
            b = prev[3],
            hasOpacity = false,
            swatchFunc = function()
                if pickerSyncing then
                    return
                end
                local r, g, blue = ColorPickerFrame:GetColorRGB()
                settings()[key] = { r, g, blue }
                paint()
                changed()
                keepHue(key)
            end,
            cancelFunc = function()
                settings()[key] = { prev[1], prev[2], prev[3] }
                paint()
                changed()
            end,
        })
        openHue(key, prev[1], prev[2], prev[3])
    end)
    if not (ColorPickerFrame and ColorPickerFrame.SetupColorPickerAndShow) then
        swatchBtn:Hide()
    end
    refreshers[#refreshers + 1] = paint
    Options.controls[key] = swatchBtn
    return swatchBtn
end

local function button(row, str, x, w, onClick)
    local btn = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
    btn:SetSize(w, 22)
    btn:SetPoint("LEFT", row, "LEFT", x, 0)
    btn:SetText(str)
    btn:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return btn
end

local function destinationText()
    local saved, Target = settings(), ns.Target
    pcall(Target.GetDestination, Target)
    local using, picked = Target.lastName, saved.targetFrame
    local pickedSource = Target.PickSource(picked)
    if pickedSource then
        if Target.lastSource == pickedSource.id then
            return pickedSource.label .. " (picked)"
        end
        return "Picked " .. pickedSource.label .. " is unavailable; using "
            .. (using or "the bottom-centre fallback")
    end
    if picked and Target.lastSourceViaPick then
        return picked .. " (picked; using " .. Target.lastSourceLabel .. ")"
    elseif Target.lastSourceLabel and not picked then
        return Target.lastSourceLabel .. " (auto)"
    elseif picked and using == picked then
        return picked .. " (picked)"
    elseif picked then
        return "Picked frame " .. picked .. " is unavailable; using " .. (using or "the bottom-centre fallback")
    end
    return using and (using .. " (auto)") or "none found, using the bottom-centre fallback"
end

-- Radio click: store the value, then repaint (this is also what re-ticks a radio the user clicked while selected).
local function radioClick(key, v)
    settings()[key] = v
    Options:Refresh()
end

-- Dropdown geometry (px). The stepper template puts an arrow either side of the 150 px menu button, so the host starts
-- PAD left of the control column and the voice row's play button moves right of the right arrow.
local DROPDOWN_SIZE = { W = 150, PAD = 8, ARROW = 28, PLAY_X = 204 }

-- A dropdown in `row` whose menu is built by setup(owner, root) (radio items). Returns the DropdownButton that carries
-- the menu, or nothing when this client has no usable template (the caller then draws radios). First choice: our
-- XPOrbsDropdownWithSteppersTemplate (Templates.xml: Blizzard's DropdownWithSteppersTemplate around a WowStyle2
-- dropdown, the Settings panel's own look); the arrows cycle the radio items through the menu's own selection, so they
-- reach the same setSelected callbacks as picking from the list. The host Frame is dropdown.xpHost. Second: the plain
-- WowStyle1DropdownTemplate button.
local function newDropdown(row, setup)
    local tiers = {
        function()
            local host = CreateFrame("Frame", nil, row, "XPOrbsDropdownWithSteppersTemplate")
            local dropdown = host.Dropdown
            if not (dropdown and dropdown.SetupMenu) then
                pcall(host.Hide, host)
                error("no inner dropdown")
            end
            host:SetPoint("LEFT", row, "LEFT", CTRL_X - DROPDOWN_SIZE.PAD, 0)
            host:SetSize(DROPDOWN_SIZE.W + 2 * DROPDOWN_SIZE.ARROW, 26)
            dropdown:SetWidth(DROPDOWN_SIZE.W)
            dropdown.xpHost = host
            return dropdown, host
        end,
        function()
            local dropdown = CreateFrame("DropdownButton", nil, row, "WowStyle1DropdownTemplate")
            dropdown:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
            dropdown:SetSize(DROPDOWN_SIZE.W, 26)
            return dropdown, dropdown
        end,
    }
    for _, build in ipairs(tiers) do
        local made, dropdown, host = pcall(build)
        if made and dropdown and pcall(dropdown.SetupMenu, dropdown, setup) then
            return dropdown
        end
        if made and host then
            pcall(host.Hide, host) -- a half-built dropdown must not sit over the radios
        end
    end
end

-- The "Sound" row under the chime checkbox: a modern dropdown (newDropdown) with arrows,
-- or one radio per voice when this client has no such template. Picking a voice plays one sample note,
-- even with the chime off, so the player can audition them before turning the chime on. The row stays enabled.
local function soundVoiceRow(y)
    local row = newRow(y, 28)
    Options.rows.soundVoice = row
    label(row, "Voice", LABEL_X + 24)
    local function pick(v)
        settings().soundVoice = v
        if ns.Orbs and ns.Orbs.PreviewSound then
            pcall(ns.Orbs.PreviewSound, ns.Orbs, v)
        end
        Options:Refresh()
    end
    local dropdown = newDropdown(row, function(_, root)
        for _, v in ipairs(VOICES) do
            root:CreateRadio(VOICE_NAME[v], function()
                return settings().soundVoice == v
            end, function()
                pick(v)
            end)
        end
    end)
    local playX = dropdown and dropdown.xpHost and DROPDOWN_SIZE.PLAY_X or PLAY_X
    if dropdown then
        Options.soundDropdown = dropdown
        Options.controls.soundVoice = dropdown
        refreshers[#refreshers + 1] = function()
            if dropdown.GenerateMenu then
                dropdown:GenerateMenu()
            end
        end
    else
        Options.soundDropdown = nil
        local radioBtns = {}
        playX = #VOICES * RADIO_STEP + 4 -- the sample button sits after the last radio
        for i, v in ipairs(VOICES) do
            local radio = newRadio(row, CTRL_X + (i - 1) * RADIO_STEP, VOICE_NAME[v])
            radio:SetScript("OnClick", function()
                pick(v)
            end)
            radioBtns[i] = radio
            Options.controls["soundVoice_" .. v] = radio
        end
        refreshers[#refreshers + 1] = function()
            for i, v in ipairs(VOICES) do
                radioBtns[i]:SetChecked(settings().soundVoice == v)
            end
        end
    end
    -- Play button right of the voice control: a sample of about six orbs arriving, through the real chime path. Dimmed
    -- and disabled with the chime off (the voice and volume stay usable so they can still be auditioned).
    local play = CreateFrame("Button", nil, row)
    play:SetSize(22, 22)
    play:SetPoint("LEFT", row, "LEFT", CTRL_X + playX, 0)
    local playTex = play:CreateTexture(nil, "ARTWORK")
    playTex:SetAllPoints(play)
    local okPlayAtlas = false
    if C_Texture and C_Texture.GetAtlasInfo then
        local okInfo, info = pcall(C_Texture.GetAtlasInfo, PLAY_ATLAS)
        if okInfo and info then
            okPlayAtlas = pcall(playTex.SetAtlas, playTex, PLAY_ATLAS)
        end
    end
    if not okPlayAtlas then
        playTex:SetTexture(PLAY_FALLBACK)
    end
    pcall(play.SetHighlightTexture, play, HILITE, "ADD")
    play:SetScript("OnClick", function()
        if ns.Orbs and ns.Orbs.PlayChimeSample then
            pcall(ns.Orbs.PlayChimeSample, ns.Orbs)
        end
    end)
    play:SetScript("OnEnter", function(self)
        showTip(self, PLAY_TIP)
    end)
    play:SetScript("OnLeave", hideTip)
    Options.controls.chimeSample = play
    postRefresh[#postRefresh + 1] = function()
        local on = settings().sound == true
        play:SetAlpha(on and 1 or DIM)
        enable(play, on)
    end
    addReset(row, "soundVoice", { "soundVoice" }, function()
        return VOICE_NAME[ns.defaults.soundVoice] or tostring(ns.defaults.soundVoice)
    end)
end

-- The sample played while dragging the Chime volume slider: one note at the new volume, at most one per
-- VOLUME_SAMPLE_GAP seconds so a drag across the whole bar isn't a machine gun.
local VOLUME_SAMPLE_GAP = 0.15
local lastVolumeSample = -math.huge
local function previewVolume()
    local now = GetTime and GetTime() or 0
    if now - lastVolumeSample < VOLUME_SAMPLE_GAP then
        return
    end
    lastVolumeSample = now
    if ns.Orbs and ns.Orbs.PreviewSound then
        pcall(ns.Orbs.PreviewSound, ns.Orbs, settings().soundVoice)
    end
end

local function registerPopup()
    if type(StaticPopupDialogs) ~= "table" then
        return false
    end
    StaticPopupDialogs[POPUP] = {
        text = "Reset all XPOrbs settings, on every tab, to their defaults?",
        button1 = "Reset",
        button2 = "Cancel",
        OnAccept = function()
            pcall(ns.commands.reset)
        end,
        timeout = 0,
        whileDead = true,
        hideOnEscape = true,
        preferredIndex = 3,
    }
    return true
end

local function confirmReset()
    if StaticPopup_Show and type(StaticPopupDialogs) == "table" and StaticPopupDialogs[POPUP] then
        if pcall(StaticPopup_Show, POPUP) then
            return
        end
    end
    ns.Print("couldn't show the confirmation; use /xporbs reset instead")
end

local function newScroll(panel)
    for _, tpl in ipairs({ "ScrollFrameTemplate", "UIPanelScrollFrameTemplate" }) do
        local ok, sf = pcall(CreateFrame, "ScrollFrame", nil, panel, tpl)
        if ok and sf then
            return sf, tpl
        end
    end
    -- no template: a bare scroll frame with mouse-wheel scrolling and no bar
    local sf = CreateFrame("ScrollFrame", nil, panel)
    pcall(sf.EnableMouseWheel, sf, true)
    sf:SetScript("OnMouseWheel", function(self, delta)
        local cur, range = self:GetVerticalScroll() or 0, self:GetVerticalScrollRange() or 0
        self:SetVerticalScroll(math.max(0, math.min(range, cur - (delta or 0) * 40)))
    end)
    return sf, nil
end

-- ---------------------------------------------------------------- the sections
-- Each builder draws one tab's rows starting at y (8, the top of its own child frame) and returns the y after them.
-- Splitting them keeps every function well under Lua 5.1's 60-upvalue limit.

local function buildGeneral(y)
    for _, c in ipairs({
        { "enabled", "Enabled" },
        { "showAtMax", "Orbs at max level", { tip = MAX_TIP } },
        { "questBursts", "Quest bursts", { tip = QUEST_TIP } },
        { "exploreBursts", "Exploration bursts", { tip = EXPLORE_TIP } },
    }) do
        checkbox(y, c[1], c[2], c[3])
        y = y + 28
    end
    checkbox(y, "minimap", "Show minimap button", {
        get = function()
            return not settings().minimap.hide
        end,
        set = function(v)
            if ns.Minimap then
                ns.Minimap.SetShown(v)
            else
                settings().minimap.hide = not v
            end
        end,
    })
    return y + 28
end

-- The "Flight pathing" (db.flightPath, /xporbs path) and "Orb shape" (db.orbShape, /xporbs shape) dropdowns: both apply
-- to every kill style, so they never dim. Built like the Sound voice dropdown. Each option explains itself in its own
-- menu tooltip and the button's tooltip explains the current one, so no description takes page space. Radios replace
-- the dropdown on a client without the template. "Smooth (default)" inside the dropdown menu only; everywhere else
-- (button text, tooltips, radios) the plain name.
local FLIGHT_DROPDOWN = {
    key = "flightPath", text = "Flight pathing", order = ns.PATH_ORDER, labels = ns.PATH_LABEL,
    desc = FLIGHT_PATH_DESC, field = "flightDropdown", radioX = { 0, 140, 230 }, -- px right of CTRL_X (the first
    -- label is the long one)
}
-- The "Speed type" dropdown (db.flightMode): whether the Flight tab's one slider row is a speed or a time.
local SPEED_TYPE_DROPDOWN = {
    key = "flightMode", text = "Speed type", order = { "speed", "time" },
    labels = { speed = "Constant speed", time = "Relative speed" },
    desc = {
        speed = "Orbs always move at the same speed, wherever they start.",
        time = "Orbs from different locations move at different speeds so they always arrive after a set time.",
    },
    field = "speedTypeDropdown", radioX = { 0, 130 },
}
local SHAPE_DROPDOWN = {
    key = "orbShape", text = "Orb shape", order = ns.SHAPE_ORDER, labels = ns.SHAPE_LABEL,
    desc = ORB_SHAPE_DESC, field = "shapeDropdown", radioX = { 0, 90, 165, 235 },
    -- switching shape also swaps in that shape's own size, quantity and opacity (ns.SetOrbShape)
    set = function(kind)
        ns.SetOrbShape(kind)
    end,
    reset = SHAPE_RESET,
}

local function choiceName(spec, kind, withDefault)
    return spec.labels[kind] .. (withDefault and kind == ns.defaults[spec.key] and " (default)" or "")
end

-- Fills a menu tooltip (Blizzard's GameTooltip_* helpers when they exist, plain tooltip calls otherwise).
local function fillMenuTooltip(tooltip, title, body)
    pcall(function()
        if GameTooltip_SetTitle and GameTooltip_AddNormalLine then
            GameTooltip_SetTitle(tooltip, title)
            GameTooltip_AddNormalLine(tooltip, body)
        else
            tooltip:SetText(title)
            tooltip:AddLine(body, 1, 1, 1, true)
        end
    end)
end

local function choiceRow(spec, y)
    local key = spec.key
    local row = newRow(y, 28)
    Options.rows[key] = row
    label(row, spec.text, LABEL_X)
    local function pick(kind)
        if spec.set then
            spec.set(kind)
        else
            settings()[key] = kind
        end
        Options:Refresh()
    end
    local dropdown = newDropdown(row, function(_, root)
        for _, kind in ipairs(spec.order) do
            local name = choiceName(spec, kind, true)
            local element = root:CreateRadio(name, function()
                return settings()[key] == kind
            end, function()
                pick(kind)
            end)
            if element and element.SetTooltip then
                pcall(element.SetTooltip, element, function(tooltip)
                    fillMenuTooltip(tooltip, name, spec.desc[kind])
                end)
            end
        end
    end)
    if dropdown then
        Options[spec.field] = dropdown
        Options.controls[key] = dropdown
        local function showCurrent(self)
            local kind = settings()[key]
            showTip2(self, choiceName(spec, kind), spec.desc[kind] or "")
        end
        -- HookScript keeps whatever highlight the template's own OnEnter does
        local setHandler = dropdown.HookScript or dropdown.SetScript
        pcall(setHandler, dropdown, "OnEnter", showCurrent)
        pcall(setHandler, dropdown, "OnLeave", hideTip)
        refreshers[#refreshers + 1] = function()
            if dropdown.GenerateMenu then
                dropdown:GenerateMenu()
            end
            -- the button shows the plain name; only the menu items carry "(default)"
            if dropdown.OverrideText then
                pcall(dropdown.OverrideText, dropdown, choiceName(spec, settings()[key]))
            end
        end
    else
        Options[spec.field] = nil
        local radioBtns = {}
        for i, kind in ipairs(spec.order) do
            local radio = newRadio(row, CTRL_X + spec.radioX[i], choiceName(spec, kind))
            radio:SetScript("OnClick", function()
                pick(kind)
            end)
            radio:SetScript("OnEnter", function(self)
                showTip2(self, choiceName(spec, kind), spec.desc[kind])
            end)
            radio:SetScript("OnLeave", hideTip)
            radioBtns[i] = radio
            Options.controls[key .. "_" .. kind] = radio
        end
        refreshers[#refreshers + 1] = function()
            for i, kind in ipairs(spec.order) do
                radioBtns[i]:SetChecked(settings()[key] == kind)
            end
        end
    end
    addReset(row, key, { key }, function()
        return choiceName(spec, ns.defaults[key])
    end, spec.reset)
    return y + 34
end

local function flightStyleRow(y)
    return choiceRow(FLIGHT_DROPDOWN, y)
end

-- The Look tab's boxed group: the settings that belong to the current orb shape. Its height is fixed (two option rows
-- always, even when empty), so switching shape never moves what is below. Rows inside hang off the box frame.
-- left edge on the other tabs' label column, right edge on the rule's
local BOX_X, BOX_W = LABEL_X, HEADER_X + RULE_W - LABEL_X
local BOX_LABEL_X = LABEL_X + 16 -- inner padding 16
local BOX_RESET_X = RESET_X - 4 -- the reset buttons end 4 px inside the border
local BOX_TOP_PAD, BOX_BOTTOM_PAD = 28, 8
local BOX_H = BOX_TOP_PAD + 32 * 3 + 28 * 2 + BOX_BOTTOM_PAD -- (bottom pad 8: the option slot sits 2 px lower)
local BOX_GAP = 10 -- under the box
local GROUP_GAP = 8 -- between the global groups (flight / colours / cap)
local BLEND_TIP = { -- the Overlap Type option (db.blend)
    natural = "Soft glowing edge: orbs blend into each other, brightening where they overlap.",
    solid = "A dark outline round opaque orbs that stack in front of each other; colours stay true on bright ground.",
}
local BLEND_NAME = { natural = "Glow", solid = "Solid" }
local STARLIGHT_NOTE = "No outline or extras: Starlight is always a soft glow with a spinning sparkle."
local PIXEL_TIP = "The size of each art pixel."
-- Which shapes each option applies to (Core.lua: Starlight has no outline, only Retro sparkles, only Bubble pulses,
-- only Crackle has a speed)
local OPTION_SHAPES = {
    blend = { retro = true, bubble = true, crackle = true },
    sparkle = { retro = true },
    pulse = { bubble = true },
    crackleSpeed = { crackle = true },
}
local OPTION_NAME = { blend = "Overlap Type", sparkle = "Sparkle", pulse = "Pulsing", crackleSpeed = "Crackle speed" }
local CRACKLE_SPEED_TIP = "How fast the lightning round each orb changes. 200% is twice as fast."

local function currentShape()
    return ns.CanonShape(settings().orbShape) or ns.defaults.orbShape
end

local function optionApplies(key)
    return OPTION_SHAPES[key][currentShape()] and true or false
end

local function optionValueText(key, v)
    if key == "blend" then
        return BLEND_NAME[v] or tostring(v)
    end
    return onOff(v)
end

local function showIf(frame, on)
    if on then
        frame:Show()
    else
        frame:Hide()
    end
end

-- A reset for options that depend on the shape: a key the shape does not use counts as already at its default.
local function optionResetSpec()
    return {
        default = function(key)
            if optionApplies(key) then
                return lookDefault(key)
            end
            return settings()[key]
        end,
        reset = function(key)
            if optionApplies(key) then
                ns.SetLook(key, lookDefault(key))
            end
        end,
    }
end

local function optionDescribe(keys)
    return function()
        local parts = {}
        for _, key in ipairs(keys) do
            if optionApplies(key) then
                parts[#parts + 1] = OPTION_NAME[key] .. " " .. optionValueText(key, lookDefault(key)):lower()
            end
        end
        return #parts > 0 and table.concat(parts, ", ") or "nothing to reset"
    end
end

-- Option row A: "Overlap Type" with the Glow / Solid radios (Starlight: a grey note instead, centred across both rows).
local function blendRow(y)
    local row = newRow(y, 28)
    Options.rows.blend = row
    local note = label(row, STARLIGHT_NOTE, BOX_LABEL_X)
    note:SetTextColor(GREY, GREY, GREY)
    note:ClearAllPoints()
    note:SetPoint("LEFT", row, "LEFT", BOX_LABEL_X, -14)
    local blendLabel = label(row, OPTION_NAME.blend, BOX_LABEL_X)
    local radios = {}
    for i, kind in ipairs({ "natural", "solid" }) do
        local radio = newRadio(row, CTRL_X + (i - 1) * 100, BLEND_NAME[kind])
        radio:SetScript("OnClick", function()
            writeValue("blend", kind)
            Options:Refresh()
        end)
        radio:SetScript("OnEnter", function(self)
            showTip2(self, BLEND_NAME[kind], BLEND_TIP[kind])
        end)
        radio:SetScript("OnLeave", hideTip)
        radios[kind] = radio
        Options.controls["blend_" .. kind] = radio
    end
    refreshers[#refreshers + 1] = function()
        local blend = settings().blend
        for kind, radio in pairs(radios) do
            radio:SetChecked(blend == kind)
        end
    end
    postRefresh[#postRefresh + 1] = function()
        local on = optionApplies("blend")
        showIf(note, currentShape() == "starlight")
        showIf(blendLabel, on)
        for _, radio in pairs(radios) do
            showIf(radio, on)
            showIf(radio.xpLabel, on)
        end
    end
    addReset(row, "blend", { "blend" }, optionDescribe({ "blend" }), optionResetSpec(), BOX_RESET_X)
end

-- Option row B: the shape's extra, a standard checkbox row (Sparkle on Retro, Pulsing on Bubble); Crackle's speed
-- slider sits in the same slot (see buildShapeBox); empty on Starlight.
local function extraRow(y)
    local row = newRow(y, 28)
    Options.rows.shapeExtra, Options.rows.sparkle, Options.rows.pulse = row, row, row
    local ticks = {}
    for _, key in ipairs({ "sparkle", "pulse" }) do
        local caption = label(row, OPTION_NAME[key], BOX_LABEL_X)
        local cb = newCheck(row, CTRL_X - 3)
        cb:SetScript("OnClick", function(self)
            writeValue(key, self:GetChecked() and true or false)
            changed()
        end)
        if key == "pulse" then
            cb:SetScript("OnEnter", function(self)
                showTip(self, PULSE_TIP)
            end)
            cb:SetScript("OnLeave", hideTip)
        end
        ticks[key] = { cb, caption }
        Options.controls[key] = cb
    end
    refreshers[#refreshers + 1] = function()
        for key, pair in pairs(ticks) do
            pair[1]:SetChecked(settings()[key] and true or false)
        end
    end
    postRefresh[#postRefresh + 1] = function()
        for key, pair in pairs(ticks) do
            showIf(pair[1], optionApplies(key))
            showIf(pair[2], optionApplies(key))
        end
    end
    -- one reset button for whichever extra the shape has
    addReset(row, "shapeExtra", { "sparkle", "pulse" }, optionDescribe({ "sparkle", "pulse" }), optionResetSpec(),
        BOX_RESET_X)
    Options.resets.sparkle, Options.resets.pulse = Options.resets.shapeExtra, Options.resets.shapeExtra
end

local function boxEdge(box, point1, point2, w, h)
    local edge = box:CreateTexture(nil, "BORDER")
    edge:SetColorTexture(1, 1, 1, 0.15)
    edge:SetPoint(point1, box, point1, 0, 0)
    edge:SetPoint(point2, box, point2, 0, 0)
    if PixelUtil and PixelUtil.SetWidth and PixelUtil.SetHeight then
        -- a hairline that stays one physical pixel at any UI scale
        PixelUtil.SetWidth(edge, w, 1)
        PixelUtil.SetHeight(edge, h, 1)
    else
        edge:SetSize(w, h)
    end
    return edge
end

local function sizeRange()
    return ns.ShapeRange(currentShape(), "size")
end

local function isRetro()
    return currentShape() == "retro"
end

-- A bordered, faintly filled frame of height h at y on the current tab (the Look tab's shape box, the Flight tab's
-- kill style box).
local function boxFrame(y, h)
    local box = CreateFrame("Frame", nil, child)
    box:SetSize(BOX_W, h)
    box:SetPoint("TOPLEFT", child, "TOPLEFT", BOX_X, -y)
    local fill = box:CreateTexture(nil, "BACKGROUND")
    fill:SetAllPoints(box)
    fill:SetColorTexture(1, 1, 1, 0.04)
    boxEdge(box, "TOPLEFT", "TOPRIGHT", BOX_W, 1)
    boxEdge(box, "BOTTOMLEFT", "BOTTOMRIGHT", BOX_W, 1)
    boxEdge(box, "TOPLEFT", "BOTTOMLEFT", 1, h)
    boxEdge(box, "TOPRIGHT", "BOTTOMRIGHT", 1, h)
    return box
end

-- Draws the box and fills it with size, quantity, opacity and the two option rows. Returns the y under it.
local function buildShapeBox(y)
    local box = boxFrame(y, BOX_H)
    Options.shapeBox = box
    local caption = box:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    caption:SetPoint("TOPLEFT", box, "TOPLEFT", BOX_LABEL_X - BOX_X, -8)
    caption:SetJustifyH("LEFT")
    caption:SetTextColor(GREY, GREY, GREY)
    Options.shapeBoxCaption = caption
    postRefresh[#postRefresh + 1] = function()
        caption:SetText(ns.SHAPE_LABEL[currentShape()] .. " settings")
    end

    rowParent = box
    local ry = y + BOX_TOP_PAD
    slider(ry, "size", "Orb size", function()
        return isRetro() and "%d px" or "%d"
    end, function()
        return isRetro() and " px" or ""
    end, nil, {
        range = sizeRange,
        labelX = BOX_LABEL_X,
        resetX = BOX_RESET_X,
        label = function()
            return isRetro() and "Pixel size" or "Orb size"
        end,
        tip = function()
            return isRetro() and PIXEL_TIP or nil
        end,
        hint = function()
            return isRetro() and PIXEL_TIP or nil
        end,
    })
    slider(ry + 32, "density", "Orb quantity multiplier", "%d%%", "%", nil,
        { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    slider(ry + 64, "opacity", "Orb opacity", "%d%%", "%", nil, { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    blendRow(ry + 96)
    extraRow(ry + 126)
    -- Crackle's slider takes the extra row's slot: its 32 px row sits 2 px higher so the centre lines match
    slider(ry + 124, "crackleSpeed", OPTION_NAME.crackleSpeed, "%d%%", "%", nil,
        { labelX = BOX_LABEL_X, resetX = BOX_RESET_X, tip = CRACKLE_SPEED_TIP })
    postRefresh[#postRefresh + 1] = function()
        showIf(Options.rows.crackleSpeed, optionApplies("crackleSpeed"))
    end
    rowParent = nil
    return y + BOX_H + BOX_GAP
end

local function buildLook(y)
    y = choiceRow(SHAPE_DROPDOWN, y)
    y = buildShapeBox(y)
    checkbox(y, "trail", "Trail")
    y = y + 28
    slider(y, "trailOpacity", "Trail opacity", "%d%%", "%", nil, { labelX = LABEL_X + 16 })
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.trailOpacity, { Options.controls.trailOpacity }, settings().trail)
    end
    y = y + 32 + GROUP_GAP

    -- Orb colour: swatch + "Class colour" checkbox; one reset button resets both
    local colourRow = newRow(y, 28)
    Options.rows.color = colourRow
    local colourLabel = label(colourRow, "Orb colour", LABEL_X)
    local swatchBtn = swatch(colourRow, "color", CTRL_X)
    local classColourCheck = newCheck(colourRow, 297)
    label(colourRow, "Class colour", 297 + 24 + 2)
    classColourCheck:SetScript("OnClick", function(self)
        settings().classColor = self:GetChecked() and true or false
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        classColourCheck:SetChecked(settings().classColor and true or false)
    end
    Options.controls.classColor = classColourCheck
    addReset(colourRow, "color", { "color", "classColor" }, function()
        return hex(ns.defaults.color) .. ", class colour " .. onOff(ns.defaults.classColor)
    end)
    postRefresh[#postRefresh + 1] = function()
        local on = not settings().classColor
        enable(swatchBtn, on)
        swatchBtn:SetAlpha(on and 1 or SWATCH_OFF_ALPHA)
    end
    if not swatchBtn:IsShown() then
        colourLabel:Hide() -- no colour picker on this client: the colour can't be edited, class colour still works
    end

    -- Rested orb colour: the tickbox (db.restedTint) and its swatch (db.restedColor) in one row; the swatch sits under
    -- the Class colour tickbox above and dims while the tickbox is off. One reset button resets both.
    y = y + 30
    local restedRow = newRow(y, 28)
    Options.rows.restedTint, Options.rows.restedColor = restedRow, restedRow
    local restedLabel = label(restedRow, "Rested orb colour", LABEL_X)
    local restedCheck = newCheck(restedRow, CTRL_X - 3)
    restedCheck:SetScript("OnClick", function(self)
        settings().restedTint = self:GetChecked() and true or false
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        restedCheck:SetChecked(settings().restedTint and true or false)
    end
    Options.controls.restedTint = restedCheck
    local restedSwatch = swatch(restedRow, "restedColor", 298)
    addReset(restedRow, "restedTint", { "restedTint", "restedColor" }, function()
        return onOff(ns.defaults.restedTint) .. ", " .. hex(ns.defaults.restedColor)
    end)
    if not restedSwatch:IsShown() then
        restedLabel:SetText("Rested tint") -- no colour picker on this client: only the tickbox is left
    end
    postRefresh[#postRefresh + 1] = function()
        local on = settings().restedTint and true or false
        enable(restedSwatch, on)
        restedSwatch:SetAlpha(on and 1 or SWATCH_OFF_ALPHA)
    end
    y = y + 28 + GROUP_GAP
    slider(y, "cap", "Max orbs per burst", "%d", "", nil, { tip = CAP_TIP })
    return y + 32
end

-- Flight: the Flight pathing dropdown, the Speed type dropdown and its one slider row (Flight speed or Flight time,
-- both at the same y; the one matching db.flightMode is shown, /xporbs flightmode switches it too), then the Kill style
-- group: three radios (row 24 + its description) indented 16 px under the header, Popstream's two sub-radios indented
-- under it at a tighter 42 px pitch with a wider gap after the group (dimmed unless Popstream is picked; clicking one
-- also picks Popstream), then the Zoom-scaled spread checkbox and its description (back on the label column).
local KILL_PAD = 10 -- above the first radio inside the kill style box (the box has no caption row)
local function buildFlight(y)
    y = flightStyleRow(y)
    y = choiceRow(SPEED_TYPE_DROPDOWN, y)
    slider(y, "flightSpeed", "Flight speed", "%d%%", "%")
    slider(y, "flightTime", "Flight time", "%.2f s", " s")
    postRefresh[#postRefresh + 1] = function()
        local speed = settings().flightMode ~= "time"
        local show, hide = Options.rows.flightSpeed, Options.rows.flightTime
        if not speed then
            show, hide = hide, show
        end
        show:Show()
        hide:Hide()
    end
    y = y + 32 + 4 -- a little air before the next group
    -- the three kill styles are their own group: a label so they don't read as options of the dropdown above
    text(child, "GameFontHighlight", "Kill style", LABEL_X, -y)
    Options.killStyleLabelY = y
    y = y + 22
    -- their settings sit in a box like the Look tab's (no caption: the header above is its title); rows hang off it
    local KILL_ROWS_H = 278 -- the radios, sub-radios, descriptions and the spread row
    local boxY = y
    local box = boxFrame(boxY, KILL_PAD + KILL_ROWS_H + BOX_BOTTOM_PAD)
    Options.killBox = box
    rowParent = box
    y = y + KILL_PAD
    local function boxText(str, x, ty, width)
        return text(box, "GameFontHighlight", str, x - BOX_X, -(ty - boxY), width)
    end
    local radios, subs = {}, {}
    local function tipOn(w, title, body)
        w:SetScript("OnEnter", function(self)
            showTip2(self, title, body)
        end)
        w:SetScript("OnLeave", hideTip)
    end
    local function styleRadio(styleKey, rowY)
        local row = newRow(rowY, 24)
        local radio = newRadio(row, BOX_LABEL_X, STYLE_NAME[styleKey])
        radio:SetScript("OnClick", function()
            radioClick("style", styleKey)
        end)
        radios[styleKey] = radio
        Options.controls["style_" .. styleKey] = radio
        Options.rows["style_" .. styleKey] = row
        local desc = boxText(STYLE_DESC[styleKey], BOX_LABEL_X + 24, rowY + 24, 474)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[styleKey] = desc
        return row
    end
    local prow = styleRadio("popstream", y)
    addReset(prow, "style", { "style", "popMode" }, function()
        return ns.StyleLabel(ns.defaults)
    end, nil, BOX_RESET_X)
    for i, pm in ipairs(POPMODES) do
        local ry = y + i * 42
        local row = newRow(ry, 24)
        local radio = newRadio(row, BOX_LABEL_X + 24, POPMODE_NAME[pm])
        radio:SetScript("OnClick", function()
            settings().style = "popstream" -- a sub-choice only means something under Popstream
            radioClick("popMode", pm)
        end)
        subs[pm] = radio
        Options.controls["popMode_" .. pm] = radio
        Options.rows["popMode_" .. pm] = row
        local desc = boxText(POPMODE_DESC[pm], BOX_LABEL_X + 48, ry + 24, 450)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[pm] = desc
    end
    styleRadio("crossfade", y + 136)
    styleRadio("stream", y + 182)
    refreshers[#refreshers + 1] = function()
        local saved = settings()
        for _, st in ipairs(STYLES) do
            radios[st]:SetChecked(saved.style == st)
        end
        for _, pm in ipairs(POPMODES) do
            subs[pm]:SetChecked(saved.popMode == pm)
        end
    end
    -- Zoom-scaled spread (db.zoomSpread, /xporbs wide): applies to every style, so it never dims. The unknown-position
    -- oval (db.unknownOrigin) is separate and has no control here.
    y = y + 236
    local _, scb = checkbox(y, "zoomSpread", "Zoom-scaled spread", { labelX = BOX_LABEL_X, resetX = BOX_RESET_X })
    tipOn(scb, "Zoom-scaled spread", SPREAD_TIP)
    local spreadDescText = boxText(SPREAD_DESC, BOX_LABEL_X, y + 28, 474)
    spreadDescText:SetWordWrap(true)
    spreadDescText:SetTextColor(GREY, GREY, GREY)
    Options.descs.zoomSpread = spreadDescText
    postRefresh[#postRefresh + 1] = function()
        local on = settings().style == "popstream"
        for _, pm in ipairs(POPMODES) do
            -- dimmed but still clickable: picking one also picks Popstream
            Options.rows["popMode_" .. pm]:SetAlpha(on and 1 or DIM)
            Options.descs[pm]:SetAlpha(on and 1 or DESC_DIM)
        end
    end
    rowParent = nil
    return boxY + KILL_PAD + KILL_ROWS_H + BOX_BOTTOM_PAD
end

-- Arrival: where the orbs land. The XP bar row (what was found, plus the picker) comes first, then the target frame's
-- shape and offsets and the glow. The shape and offsets stay live with Show glow off; only the intensity dims.
local function buildArrival(y)
    local destRow = newRow(y, 36)
    Options.rows.targetFrame = destRow
    label(destRow, "XP bar frame", LABEL_X)
    local dest = destRow:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    dest:SetPoint("LEFT", destRow, "LEFT", CTRL_X, 0)
    dest:SetWidth(280)
    dest:SetJustifyH("LEFT")
    dest:SetWordWrap(true)
    refreshers[#refreshers + 1] = function()
        dest:SetText(destinationText())
    end
    addReset(destRow, "targetFrame", { "targetFrame" }, function()
        return "auto-detect"
    end)
    y = y + 36
    local pickRow = newRow(y, 30)
    button(pickRow, "Pick XP bar frame", CTRL_X, 150, function()
        ns.commands.pick("")
    end)
    local pickHintText = text(child, "GameFontHighlight", PICK_HINT, LABEL_X, -(y + 34), 520)
    pickHintText:SetWordWrap(true)
    pickHintText:SetTextColor(GREY, GREY, GREY)
    Options.pickHint = pickHintText
    y = y + 34 + 8 + 22 -- one hint line, then the gap between groups

    local shapeRow = newRow(y, 24)
    Options.rows.glowShape = shapeRow
    label(shapeRow, "Target frame shape", LABEL_X)
    local shapeBtns = {}
    for i, sh in ipairs(SHAPES) do
        local x = CTRL_X + (i - 1) * SHAPE_SPACING
        local radio = newRadio(shapeRow, x, SHAPE_NAME[sh])
        radio:SetScript("OnClick", function()
            radioClick("glowShape", sh)
        end)
        radio:SetScript("OnEnter", function(self)
            showTip2(self, SHAPE_NAME[sh], SHAPE_TIP[sh])
        end)
        radio:SetScript("OnLeave", hideTip)
        shapeBtns[#shapeBtns + 1] = radio
        Options.controls["glowShape_" .. sh] = radio
    end
    refreshers[#refreshers + 1] = function()
        local cur = settings().glowShape
        for i, sh in ipairs(SHAPES) do
            shapeBtns[i]:SetChecked(cur == sh)
        end
    end
    addReset(shapeRow, "glowShape", { "glowShape" }, function()
        return SHAPE_NAME[ns.defaults.glowShape] or tostring(ns.defaults.glowShape)
    end)
    y = y + 32
    slider(y, "glowOffsetX", "Target offset X", "%d px", " px")
    y = y + 32
    slider(y, "glowOffsetY", "Target offset Y", "%d px", " px")
    for _, key in ipairs({ "glowOffsetX", "glowOffsetY" }) do
        local offsetSlider = Options.controls[key]
        offsetSlider:SetScript("OnEnter", function(self)
            showTip(self, OFFSET_TIP)
        end)
        offsetSlider:SetScript("OnLeave", hideTip)
    end
    y = y + 36
    checkbox(y, "glow", "Show glow")
    y = y + 28
    slider(y, "glowIntensity", "Glow intensity", "%d%%", "%")
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.glowIntensity, { Options.controls.glowIntensity }, settings().glow ~= false)
    end
    return y + 32
end

local function buildSound(y)
    checkbox(y, "sound", "Chime when orbs arrive", { tip = SOUND_TIP })
    y = y + 28
    soundVoiceRow(y)
    y = y + 28
    slider(y, "soundVolume", "Chime volume", "%d%%", "%", previewVolume)
    -- dimmed with the chime off but left enabled (no controls passed), so a volume can still be auditioned and set
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.soundVolume, {}, settings().sound == true)
    end
    return y + 32
end

local function buildDebug(y)
    checkbox(y, "debug", "Debug log")
    return y + 28
end

-- ---------------------------------------------------------------- the tabs
-- One tab per section, most-used first. Each tab builds into its own child frame (the scroll frame shows one at a
-- time); the row helpers hang off the module-level `child`, so building a tab just points it at that tab's frame.
-- Options.rows / controls / refreshers / resets stay global, so Refresh and the resets work on every tab. The Debug log
-- row closes the General tab after a 12 px gap.
local TAB_NAMES = { "General", "Sound", "Look", "Flight", "Arrival" }
local TAB_BUILDERS = {
    General = function(y)
        return buildDebug(buildGeneral(y) + 12)
    end,
    Sound = buildSound, Look = buildLook, Flight = buildFlight, Arrival = buildArrival,
}
local TAB_TOP, TAB_H, TAB_GAP, TAB_PAD, TAB_MIN_W = 42, 28, 4, 28, 64
local SCROLL_TOP = TAB_TOP + TAB_H + 4
local TAB_START_Y = 8 -- every tab's first row
local GOLD_R, GOLD_G, GOLD_B = 1, 0.82, 0
local selectedTab = 1 -- remembered for the session only, not saved
local warned = false

-- True when a tab's content fits the visible height, so the scroll bar has nothing to do. An unknown (zero) height
-- counts as not fitting, so the bar is never hidden on a guess.
local function tabFits(contentH, viewH)
    return (viewH or 0) > 0 and contentH <= viewH
end
Options.TabFits = tabFits

local function warnOnce(err)
    if not warned and ns.db and ns.db.debug then
        warned = true
        ns.Print("options: tab template call failed: " .. tostring(err))
    end
end

local function callGuarded(fn, ...)
    if fn then
        local ok, err = pcall(fn, ...)
        if not ok then
            warnOnce(err)
        end
    end
end

-- Real template: normal = GameFontNormal, selected (disabled) = GameFontHighlight, so labels aren't the Small font.
local function applyTabFonts(btn)
    if btn.SetNormalFontObject and GameFontNormal then
        pcall(btn.SetNormalFontObject, btn, GameFontNormal)
    end
    if btn.SetDisabledFontObject and GameFontHighlight then
        pcall(btn.SetDisabledFontObject, btn, GameFontHighlight)
    end
end

local function flatColour(btn, hover)
    local fs = btn.xpLabel
    if btn.xpSelected then
        fs:SetTextColor(GOLD_R, GOLD_G, GOLD_B)
    elseif hover then
        fs:SetTextColor(1, 1, 1)
    else
        fs:SetTextColor(0.70, 0.70, 0.70)
    end
end

local function setTabLook(btn, on)
    btn.xpSelected = on
    if Options.tabTemplate == "flat" then
        flatColour(btn, false)
        if on then
            btn.xpBar:Show()
            btn.xpFill:Show()
        else
            btn.xpBar:Hide()
            btn.xpFill:Hide()
        end
    else
        callGuarded(on and PanelTemplates_SelectTab or PanelTemplates_DeselectTab, btn)
        applyTabFonts(btn)
    end
end

-- The rule under the strip is the tabs' baseline: two segments, left of the selected tab and right of it, so the
-- selected tab breaks through it.
local function placeBaseline(btn)
    local panel, base = Options.panel, Options.tabBase
    local l, r = Options.tabRuleL, Options.tabRuleR
    local left, right = btn.xpX, btn.xpX + btn.xpW
    l:ClearAllPoints()
    l:SetPoint("TOPLEFT", panel, "TOPLEFT", HEADER_X, -base)
    l:SetSize(math.max(0, left - HEADER_X), 1)
    r:ClearAllPoints()
    r:SetPoint("TOPLEFT", panel, "TOPLEFT", right, -base)
    r:SetSize(math.max(0, HEADER_X + RULE_W - right), 1)
end

-- Hides the scroll bar when the selected tab fits (the Settings canvas size isn't known at build time, so this also
-- runs on show and on size changes).
function Options:UpdateScrollBar()
    local scroll = self.scroll
    local bar = scroll and scroll.ScrollBar
    if not bar then
        return
    end
    local fits = tabFits(self.tabHeights[TAB_NAMES[selectedTab]] or 0, scroll:GetHeight())
    pcall(fits and bar.Hide or bar.Show, bar)
end

function Options:SelectTab(which)
    local idx = which
    if type(which) == "string" then
        idx = nil
        for i, name in ipairs(TAB_NAMES) do
            if name == which then
                idx = i
            end
        end
    end
    if not idx or not TAB_NAMES[idx] then
        return false
    end
    selectedTab = idx
    for i, name in ipairs(TAB_NAMES) do
        local c = self.tabChildren[name]
        if i == idx then
            c:Show()
        else
            c:Hide()
        end
        setTabLook(self.tabs[i], i == idx)
    end
    placeBaseline(self.tabs[idx])
    local c = self.tabChildren[TAB_NAMES[idx]]
    self.child = c
    self.scroll:SetScrollChild(c)
    self.scroll:SetVerticalScroll(0)
    self:UpdateScrollBar()
    return true
end

local function labelWidth(panel, name)
    local fs = Options.measure
    if not fs then
        fs = panel:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        fs:Hide()
        Options.measure = fs
    end
    fs:SetText(name)
    local ok, w = pcall(fs.GetStringWidth, fs)
    return (ok and tonumber(w) and w > 0) and w or (#name * 7)
end

local function newFlatTab(panel, name)
    local btn = CreateFrame("Button", nil, panel)
    btn.xpFill = btn:CreateTexture(nil, "BACKGROUND")
    btn.xpFill:SetAllPoints(btn)
    btn.xpFill:SetColorTexture(1, 1, 1, 0.04)
    btn.xpBar = btn:CreateTexture(nil, "ARTWORK")
    btn.xpBar:SetPoint("BOTTOMLEFT", btn, "BOTTOMLEFT", 0, 0)
    btn.xpBar:SetPoint("BOTTOMRIGHT", btn, "BOTTOMRIGHT", 0, 0)
    btn.xpBar:SetHeight(2)
    btn.xpBar:SetColorTexture(GOLD_R, GOLD_G, GOLD_B, 1)
    btn.xpLabel = btn:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    btn.xpLabel:SetPoint("CENTER", btn, "CENTER", 0, 0)
    btn.xpLabel:SetText(name)
    btn.text = name
    if btn.SetFontString then
        pcall(btn.SetFontString, btn, btn.xpLabel)
    end
    btn:SetScript("OnEnter", function(self)
        flatColour(self, true)
    end)
    btn:SetScript("OnLeave", function(self)
        flatColour(self, false)
    end)
    return btn
end

local function newTabButton(panel, i, prev)
    local name = TAB_NAMES[i]
    local w = math.max(TAB_MIN_W, math.floor(labelWidth(panel, name) + 0.5) + TAB_PAD)
    local btn
    if Options.tabTemplate ~= "flat" then
        local ok, b = pcall(CreateFrame, "Button", nil, panel, "PanelTopTabButtonTemplate")
        if ok and b then
            btn, Options.tabTemplate = b, "PanelTopTabButtonTemplate"
        else
            Options.tabTemplate = "flat"
        end
    end
    if Options.tabTemplate == "flat" then
        btn = newFlatTab(panel, name)
        btn:SetSize(w, TAB_H)
    else
        btn:SetText(name)
        applyTabFonts(btn)
        callGuarded(PanelTemplates_TabResize, btn, 0, w) -- the template keeps its own height
        btn:SetWidth(w)
    end
    btn.xpName, btn.xpW = name, w
    if prev then
        btn:SetPoint("TOPLEFT", prev, "TOPRIGHT", TAB_GAP, 0)
        btn.xpX = prev.xpX + prev.xpW + TAB_GAP
    else
        btn:SetPoint("TOPLEFT", panel, "TOPLEFT", HEADER_X, -TAB_TOP)
        btn.xpX = HEADER_X
    end
    btn:SetScript("OnClick", function()
        Options:SelectTab(i)
    end)
    return btn
end

-- Builds the tab strip, the baseline rule, the scroll frame under them and one child per tab.
local function newTabs(panel)
    Options.tabTemplate, Options.tabs, Options.tabChildren, Options.tabHeights = nil, {}, {}, {}
    Options.tabTop = TAB_TOP
    for i = 1, #TAB_NAMES do
        Options.tabs[i] = newTabButton(panel, i, Options.tabs[i - 1])
    end
    -- the baseline is the strip's bottom edge: the template's own height when it reports one, else TAB_H
    local h = Options.tabs[1]:GetHeight()
    Options.tabHeight = (h and h > 0) and h or TAB_H
    Options.tabBase = TAB_TOP + Options.tabHeight
    SCROLL_TOP = math.max(TAB_TOP + TAB_H + 4, Options.tabBase + 4)
    Options.tabRuleL = panel:CreateTexture(nil, "ARTWORK")
    Options.tabRuleR = panel:CreateTexture(nil, "ARTWORK")
    Options.tabRuleL:SetColorTexture(1, 1, 1, 0.15)
    Options.tabRuleR:SetColorTexture(1, 1, 1, 0.15)
    Options.topRule = Options.tabRuleL

    local scroll, tpl = newScroll(panel)
    Options.scroll, Options.scrollTemplate, Options.scrollTop = scroll, tpl, SCROLL_TOP
    scroll:SetPoint("TOPLEFT", panel, "TOPLEFT", 0, -SCROLL_TOP)
    scroll:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -28, 44)
    local maxH = 0
    for _, name in ipairs(TAB_NAMES) do
        child = CreateFrame("Frame", nil, scroll)
        local ch = TAB_BUILDERS[name](TAB_START_Y) + 16 -- |last y| + 16
        child:SetSize(CONTENT_W, ch)
        child:Hide()
        Options.tabChildren[name], Options.tabHeights[name] = child, ch
        maxH = math.max(maxH, ch)
    end
    -- the tallest tab (the scroll range follows the selected tab's own height)
    CONTENT_H = maxH
    Options.CONTENT_H = CONTENT_H
    Options:SelectTab(selectedTab)
    scroll:SetScript("OnSizeChanged", function()
        Options:UpdateScrollBar()
    end)
    return scroll
end

-- ---------------------------------------------------------------- the panel

local function build()
    local panel = CreateFrame("Frame")
    Options.panel = panel
    text(panel, "GameFontNormalLarge", "XP Orbs", 16, -16)

    Options.rightX = HEADER_X + RULE_W -- the right edge of the rules and the footer button
    newTabs(panel)
    Options.footerY = 44 -- the footer rule's px above the panel's bottom
    -- the orb preview window (ShapePreview.lua) follows every change made here
    postRefresh[#postRefresh + 1] = function()
        if ns.ShapePreview then
            ns.ShapePreview:Sync()
        end
    end

    -- fixed footer
    local rule = panel:CreateTexture(nil, "ARTWORK")
    rule:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X, 44)
    rule:SetSize(RULE_W, 1)
    Options.footerRule = rule
    rule:SetColorTexture(1, 1, 1, 0.15)
    local resetAll = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    resetAll:SetSize(160, 22)
    resetAll:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X + RULE_W - 160, 11)
    resetAll:SetText("Reset all to default")
    resetAll:SetScript("OnClick", confirmReset)
    Options.resetAll = resetAll
    registerPopup()

    -- The Test Kill button lives under the "Test target" window (Preview.lua). Only when that window can't be built
    -- does the panel get its own footer button, made on first need, so testing still works.
    local function ensureFooterTest(needed)
        if needed and not Options.footerTest then
            local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
            test:SetSize(110, 22)
            test:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 11)
            test:SetText("Test Kill")
            test:SetScript("OnClick", function()
                -- the same orbs a kill would make: rested ones too when Rested tint is on
                pcall(ns.TestKill, settings().restedTint and "5 rested" or "5")
            end)
            Options.footerTest = test
        end
        if Options.footerTest then
            if needed then
                Options.footerTest:Show()
            else
                Options.footerTest:Hide()
            end
        end
    end
    panel:SetScript("OnShow", function()
        Options:Refresh()
        Options:UpdateScrollBar()
        -- the orb preview window (ShapePreview.lua) goes up first: the "Test target" window docks under it
        if ns.ShapePreview then
            pcall(ns.ShapePreview.Sync, ns.ShapePreview, true)
        end
        -- the "Test target" stand-in window follows this panel (Preview.lua); never let it break the panel
        local okSync, windowUp = false, false
        if ns.Preview then
            okSync, windowUp = pcall(ns.Preview.Sync, ns.Preview, true)
        end
        ensureFooterTest(not (okSync and windowUp))
    end)
    panel:SetScript("OnHide", function()
        if ns.Preview then
            pcall(ns.Preview.Sync, ns.Preview, false)
        end
        if ns.ShapePreview then
            -- hides it; its OnUpdate runs only while the panel shows
            pcall(ns.ShapePreview.Sync, ns.ShapePreview, false)
        end
    end)
    return panel
end

Options.POPUP = POPUP

if Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory then
    local ok, err = pcall(function()
        local panel = build()
        Options.category = Settings.RegisterCanvasLayoutCategory(panel, "XP Orbs")
        Settings.RegisterAddOnCategory(Options.category)
    end)
    if not ok then
        Options.category, Options.err = nil, tostring(err)
    end
end

local openWhenCombatEnds = false -- a click in combat is waiting for PLAYER_REGEN_ENABLED
local combatFrame -- built on first use; PLAYER_REGEN_ENABLED is registered only while waiting

local function openNow()
    local id = Options.category:GetID()
    local ok
    -- Blizzard's Settings.OpenToCategory runs gamepad focus code on the addon's call path (blocked-action errors on
    -- Forever); C_SettingsUtil.OpenSettingsPanel through securecallfunction avoids that.
    if type(securecallfunction) == "function" and C_SettingsUtil
        and type(C_SettingsUtil.OpenSettingsPanel) == "function" then
        ok = pcall(securecallfunction, C_SettingsUtil.OpenSettingsPanel, id)
    else
        ok = pcall(Settings.OpenToCategory, id)
    end
    if not ok then
        ns.Print("options: couldn't open the settings panel; try Esc > Options > AddOns > XP Orbs")
    end
end

local function onCombatFrameEvent(self, event)
    if event ~= "PLAYER_REGEN_ENABLED" then
        return
    end
    pcall(self.UnregisterEvent, self, "PLAYER_REGEN_ENABLED")
    if openWhenCombatEnds then
        openWhenCombatEnds = false
        openNow()
    end
end

function ns.commands.options()
    if not Options.category then
        ns.Print("options: the settings panel isn't available ("
            .. (Options.err or "no Settings API on this client") .. "); use /xporbs commands instead")
        return
    end
    if InCombatLockdown and InCombatLockdown() then
        if not openWhenCombatEnds then
            openWhenCombatEnds = true
            combatFrame = combatFrame or CreateFrame("Frame")
            combatFrame:SetScript("OnEvent", onCombatFrameEvent)
            pcall(combatFrame.RegisterEvent, combatFrame, "PLAYER_REGEN_ENABLED")
        end
        ns.Print("options will open after combat")
        return
    end
    openNow()
end

table.insert(ns.statusProviders, function()
    if Options.category then
        return "options panel: registered"
    end
    return "options panel: unavailable (" .. (Options.err or "no Settings API") .. ")"
end)

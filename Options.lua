-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

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
local CONTENT_W, CONTENT_H = 584, 1070 -- |last y| + 16
local DIM = 0.4
local SWATCH_OFF_ALPHA = 0.35
local GREY = 0.70
local EN_DASH = "\226\128\147"
local POPUP = "XPORBS_RESET_ALL"
local ICON_ATLAS = "transmog-icon-revert"
local ICON_FALLBACK = "Interface\\Buttons\\UI-RefreshButton"
local HILITE = "Interface\\Buttons\\ButtonHilight-Square"

local STYLES = { "popstream", "crossfade", "stream", "mob" }
local STYLE_NAME = { popstream = "Popstream (default)", crossfade = "Crossfade", stream = "Stream",
    mob = "At the mob (new)" }
local STYLE_DESC = {
    popstream = "A burst at the corpse, then a stream to the bar.",
    crossfade = "Orbs bloom at the corpse, then fly straight to the bar.",
    stream = "A plain stream from the target frame to the bar.",
    mob = "A wide burst at the corpse that peels off into a stream to the bar.",
}
local SHAPES = { "bar", "round" }
local SHAPE_NAME = { bar = "Horizontal", round = "Circular" }
local SHAPE_DESC = "Horizontal: orbs land on the bar's fill edge. Circular: orbs land on the centre of a round frame "
    .. "such as a portrait."
local MAX_TIP = "At max level, each kill sends a small burst of orbs to your portrait."
local SOUND_TIP = "Coin: a soft coin clink. Glass: a glassy tink. One per arriving orb (up to six per burst). "
    .. "Off by default."
local VOICES = { "glass", "coin" }
local VOICE_NAME = { coin = "Coin", glass = "Glass" }
local OFFSET_DESC = "Moves where orbs land and the glow appears (pixels)."
local PICK_HINT = "Use this if another addon replaces the default XP bar, or to send the orbs somewhere else, such as "
    .. "your portrait with the Circular shape."

local refreshers, postRefresh, resets = {}, {}, {}
local refreshing = false
local child -- the scroll child every row hangs off
Options.controls = {} -- key -> the widget (checkbox, slider, swatch, radio)
Options.rows = {} -- key -> the row frame (dimming and layout)
Options.resets = {} -- key -> the per-row reset button
Options.descs = {} -- style -> its description FontString
Options.CONTENT_H = CONTENT_H

local function D()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
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

local function hex(c)
    if type(c) ~= "table" then
        return "?"
    end
    local function b(v)
        return floor((tonumber(v) or 0) * 255 + 0.5)
    end
    return string.format("#%02X%02X%02X", b(c[1]), b(c[2]), b(c[3]))
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

local function hideTip()
    if GameTooltip then
        pcall(GameTooltip.Hide, GameTooltip)
    end
end

-- ---------------------------------------------------------------- building blocks

local function text(parent, template, str, x, y, width)
    local fs = parent:CreateFontString(nil, "ARTWORK", template)
    fs:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    fs:SetJustifyH("LEFT")
    if width then
        fs:SetWidth(width)
    end
    fs:SetText(str)
    return fs
end

-- Draws a section header at y and returns the y of its first row.
local function header(str, y)
    text(child, "GameFontNormal", str, HEADER_X, -y)
    local rule = child:CreateTexture(nil, "ARTWORK")
    rule:SetPoint("TOPLEFT", child, "TOPLEFT", HEADER_X, -(y + 18))
    rule:SetSize(RULE_W, 1)
    rule:SetColorTexture(1, 1, 1, 0.15)
    return y + 26
end

-- A full-width row frame of height h at y. Its label, control and reset button anchor LEFT to it, so they share its
-- centre line; it is also what dimming hangs on.
local function newRow(y, h)
    local row = CreateFrame("Frame", nil, child)
    row:SetSize(CONTENT_W, h)
    row:SetPoint("TOPLEFT", child, "TOPLEFT", 0, -y)
    return row
end

local function label(row, str, x)
    local fs = row:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    fs:SetPoint("LEFT", row, "LEFT", x, 0)
    fs:SetJustifyH("LEFT")
    fs:SetText(str)
    return fs
end

local function hideTemplateText(b)
    for _, k in ipairs({ "Text", "text" }) do
        local fs = b[k]
        if type(fs) == "table" and fs.Hide then
            if fs.SetText then
                fs:SetText("")
            end
            fs:Hide()
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
local function addReset(row, name, keys, describe)
    local btn = CreateFrame("Button", nil, row)
    btn:SetSize(20, 20)
    btn:SetPoint("LEFT", row, "LEFT", RESET_X, 0)
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
        local d = D()
        for _, k in ipairs(keys) do
            d[k] = copyDefault(ns.defaults[k])
        end
        hideTip()
        Options:Refresh()
    end)
    btn:Hide() -- shown by updateResets once the db is known; it keeps its space either way
    resets[#resets + 1] = function()
        local d, differs = D(), false
        for _, k in ipairs(keys) do
            if OrbMath.Differs(d[k], ns.defaults[k]) then
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
    local get = opts.get or function()
        return D()[key]
    end
    local set = opts.set or function(v)
        D()[key] = v
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
        end)
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

local function newSlider(row)
    local ok, s = pcall(CreateFrame, "Slider", nil, row, "OptionsSliderTemplate")
    if ok and s then
        -- the template's own title and min/max captions are replaced by our label and value text
        for _, k in ipairs({ "Text", "Low", "High" }) do
            if s[k] and s[k].Hide then
                s[k]:Hide()
            end
        end
        return s
    end
    s = CreateFrame("Slider", nil, row)
    s:SetOrientation("HORIZONTAL")
    s:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
    local bg = s:CreateTexture(nil, "BACKGROUND")
    bg:SetColorTexture(0, 0, 0, 0.5)
    bg:SetPoint("LEFT", s, "LEFT", 0, 0)
    bg:SetPoint("RIGHT", s, "RIGHT", 0, 0)
    bg:SetHeight(6)
    return s
end

-- Right-click the value to type one: an InputBoxTemplate box replaces the text; Enter or losing focus applies the
-- nearest permitted value, Escape cancels, junk restores the old value. Returns nothing when the template is missing.
local function attachValueEdit(row, key, val, lo, hi, step, unit)
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
            local v = OrbMath.Snap(OrbMath.ParseNumber(typed), lo, hi, step)
            if v then
                D()[key] = v
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
        local cur = D()[key]
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
        showTip(hit, string.format("Right-click to type a value (%g%s%g%s)", lo, EN_DASH, hi, unit))
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
local function slider(y, key, labelStr, fmt, unit)
    local lo, hi, step = ns.ranges[key][1], ns.ranges[key][2], ns.ranges[key][3]
    local row = newRow(y, 32)
    label(row, labelStr, LABEL_X)
    local s = newSlider(row)
    s:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
    s:SetSize(SLIDER_W, 16)
    s:SetMinMaxValues(lo, hi)
    s:SetValueStep(step)
    if s.SetObeyStepOnDrag then
        s:SetObeyStepOnDrag(true)
    end
    local val = row:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    val:SetPoint("LEFT", row, "LEFT", VALUE_X, 0)
    val:SetJustifyH("LEFT")
    s:SetScript("OnValueChanged", function(_, v)
        v = OrbMath.Snap(v, lo, hi, step)
        if not v then
            return
        end
        val:SetText(string.format(fmt, v))
        if not refreshing then
            D()[key] = v
            changed()
        end
    end)
    refreshers[#refreshers + 1] = function()
        local v = D()[key]
        if type(v) ~= "number" then
            return
        end
        s:SetValue(v)
        val:SetText(string.format(fmt, OrbMath.Snap(v, lo, hi, step) or v))
    end
    attachValueEdit(row, key, val, lo, hi, step, unit)
    addReset(row, key, { key }, function()
        return string.format(fmt, ns.defaults[key])
    end)
    Options.controls[key] = s
    Options.rows[key] = row
end

-- A colour swatch at x in the row. Returns the swatch button (hidden when there is no colour picker).
local function swatch(row, key, x)
    local b = CreateFrame("Button", nil, row)
    b:SetSize(22, 22)
    b:SetPoint("LEFT", row, "LEFT", x, 0)
    local border = b:CreateTexture(nil, "BACKGROUND")
    border:SetAllPoints(b)
    border:SetColorTexture(0.75, 0.75, 0.75, 1)
    local fill = b:CreateTexture(nil, "ARTWORK")
    fill:SetPoint("TOPLEFT", b, "TOPLEFT", 2, -2)
    fill:SetPoint("BOTTOMRIGHT", b, "BOTTOMRIGHT", -2, 2)
    local function paint()
        local c = D()[key]
        if type(c) == "table" then
            fill:SetColorTexture(c[1] or 1, c[2] or 1, c[3] or 1, 1)
        end
    end
    b:SetScript("OnClick", function()
        if b.IsEnabled and not b:IsEnabled() then
            return
        end
        if not ColorPickerFrame or not ColorPickerFrame.SetupColorPickerAndShow then
            return
        end
        local c = D()[key]
        local prev = { c[1], c[2], c[3] }
        ColorPickerFrame:SetupColorPickerAndShow({
            r = prev[1],
            g = prev[2],
            b = prev[3],
            hasOpacity = false,
            swatchFunc = function()
                local r, g, bl = ColorPickerFrame:GetColorRGB()
                D()[key] = { r, g, bl }
                paint()
                changed()
            end,
            cancelFunc = function()
                D()[key] = { prev[1], prev[2], prev[3] }
                paint()
                changed()
            end,
        })
    end)
    if not (ColorPickerFrame and ColorPickerFrame.SetupColorPickerAndShow) then
        b:Hide()
    end
    refreshers[#refreshers + 1] = paint
    Options.controls[key] = b
    return b
end

local function button(row, str, x, w, onClick)
    local b = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
    b:SetSize(w, 22)
    b:SetPoint("LEFT", row, "LEFT", x, 0)
    b:SetText(str)
    b:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return b
end

local function destinationText()
    local d, T = D(), ns.Target
    pcall(T.GetDestination, T)
    local using, picked = T.lastName, d.targetFrame
    if picked and using == picked then
        return picked .. " (picked)"
    elseif picked then
        return "Picked frame " .. picked .. " is unavailable; using " .. (using or "the bottom-centre fallback")
    end
    return using and (using .. " (auto)") or "none found, using the bottom-centre fallback"
end

-- Radio click: store the value, then repaint (this is also what re-ticks a radio the user clicked while selected).
local function radioClick(key, v)
    D()[key] = v
    Options:Refresh()
end

-- The "Sound" row under the chime checkbox: Blizzard's modern dropdown (WowStyle1DropdownTemplate + SetupMenu radios),
-- or two radio buttons when this client has no such template. Picking a voice plays one sample note, even with the chime
-- off, so the player can audition both before turning the chime on. The row stays enabled.
local function soundVoiceRow(y)
    local row = newRow(y, 28)
    Options.rows.soundVoice = row
    label(row, "Sound", 48)
    local function pick(v)
        D().soundVoice = v
        if ns.Orbs and ns.Orbs.PreviewSound then
            pcall(ns.Orbs.PreviewSound, ns.Orbs, v)
        end
        Options:Refresh()
    end
    local dd
    local okMenu = pcall(function()
        dd = CreateFrame("DropdownButton", nil, row, "WowStyle1DropdownTemplate")
        dd:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
        dd:SetSize(150, 26)
        dd:SetupMenu(function(_, root)
            for _, v in ipairs(VOICES) do
                root:CreateRadio(VOICE_NAME[v], function()
                    return D().soundVoice == v
                end, function()
                    pick(v)
                end)
            end
        end)
    end)
    if okMenu and dd then
        Options.soundDropdown = dd
        Options.controls.soundVoice = dd
        refreshers[#refreshers + 1] = function()
            if dd.GenerateMenu then
                dd:GenerateMenu()
            end
        end
    else
        if dd then
            pcall(dd.Hide, dd) -- a half-built dropdown must not sit over the radios
        end
        Options.soundDropdown = nil
        local btns = {}
        for i, v in ipairs(VOICES) do
            local rb = newRadio(row, CTRL_X + (i - 1) * 100, VOICE_NAME[v])
            rb:SetScript("OnClick", function()
                pick(v)
            end)
            btns[i] = rb
            Options.controls["soundVoice_" .. v] = rb
        end
        refreshers[#refreshers + 1] = function()
            for i, v in ipairs(VOICES) do
                btns[i]:SetChecked(D().soundVoice == v)
            end
        end
    end
    addReset(row, "soundVoice", { "soundVoice" }, function()
        return VOICE_NAME[ns.defaults.soundVoice] or tostring(ns.defaults.soundVoice)
    end)
end

local function registerPopup()
    if type(StaticPopupDialogs) ~= "table" then
        return false
    end
    StaticPopupDialogs[POPUP] = {
        text = "Reset all XPOrbs settings to their defaults?",
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

-- ---------------------------------------------------------------- the panel

local function build()
    local panel = CreateFrame("Frame")
    Options.panel = panel
    text(panel, "GameFontNormalLarge", "XP Orbs", 16, -16)
    local top = panel:CreateTexture(nil, "ARTWORK")
    top:SetPoint("TOPLEFT", panel, "TOPLEFT", HEADER_X, -38)
    top:SetSize(RULE_W, 1)
    top:SetColorTexture(1, 1, 1, 0.15)
    Options.topRule = top

    local scroll, tpl = newScroll(panel)
    Options.scroll, Options.scrollTemplate = scroll, tpl
    scroll:SetPoint("TOPLEFT", panel, "TOPLEFT", 0, -40)
    scroll:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -28, 44)
    child = CreateFrame("Frame", nil, scroll)
    child:SetSize(CONTENT_W, CONTENT_H)
    scroll:SetScrollChild(child)
    Options.child = child

    local y = header("General", 8)
    for _, c in ipairs({
        { "enabled", "Enabled" },
        { "trail", "Trail" },
        { "questBursts", "Quest bursts" },
        { "showAtMax", "Kill orbs at max level", { tip = MAX_TIP } },
        { "sound", "Chime when orbs arrive", { tip = SOUND_TIP } },
    }) do
        checkbox(y, c[1], c[2], c[3])
        y = y + 28
    end
    soundVoiceRow(y)
    y = y + 28
    checkbox(y, "minimap", "Show minimap button", {
        get = function()
            return not D().minimap.hide
        end,
        set = function(v)
            if ns.Minimap then
                ns.Minimap.SetShown(v)
            else
                D().minimap.hide = not v
            end
        end,
    })
    y = y + 28

    y = header("Look", y + 14)
    for _, c in ipairs({
        { "density", "Orb quantity multiplier", "%d%%", "%" },
        { "cap", "Max orbs per burst", "%d", "" },
        { "size", "Orb size", "%d", "" },
        { "flightTime", "Flight time", "%.2f s", " s" },
    }) do
        slider(y, c[1], c[2], c[3], c[4])
        y = y + 32
    end

    -- Orb colour: swatch + "Class colour" checkbox; one reset button resets both
    local crow = newRow(y, 28)
    Options.rows.color = crow
    local clabel = label(crow, "Orb colour", LABEL_X)
    local sw = swatch(crow, "color", CTRL_X)
    local ccb = newCheck(crow, 297)
    label(crow, "Class colour", 297 + 24 + 2)
    ccb:SetScript("OnClick", function(self)
        D().classColor = self:GetChecked() and true or false
        changed()
    end)
    refreshers[#refreshers + 1] = function()
        ccb:SetChecked(D().classColor and true or false)
    end
    Options.controls.classColor = ccb
    addReset(crow, "color", { "color", "classColor" }, function()
        return hex(ns.defaults.color) .. ", class colour " .. onOff(ns.defaults.classColor)
    end)
    postRefresh[#postRefresh + 1] = function()
        local on = not D().classColor
        enable(sw, on)
        sw:SetAlpha(on and 1 or SWATCH_OFF_ALPHA)
    end
    if not sw:IsShown() then
        clabel:Hide() -- no colour picker on this client: the colour can't be edited, class colour still works
    end

    y = y + 28
    checkbox(y, "restedTint", "Rested tint")
    y = y + 28
    local rrow = newRow(y, 28)
    Options.rows.restedColor = rrow
    local rlabel = label(rrow, "Rested colour", 48)
    local rsw = swatch(rrow, "restedColor", CTRL_X)
    addReset(rrow, "restedColor", { "restedColor" }, function()
        return hex(ns.defaults.restedColor)
    end)
    if not rsw:IsShown() then
        rlabel:Hide()
    end
    postRefresh[#postRefresh + 1] = function()
        setDim(rrow, { rsw }, D().restedTint)
    end

    y = y + 28
    -- "Arrival": the shape and offsets decide where orbs land even with the glow off
    y = header("Arrival", y + 14)
    local shrow = newRow(y, 24)
    Options.rows.glowShape = shrow
    label(shrow, "Target frame shape", LABEL_X)
    local shapeBtns = {}
    for i, sh in ipairs(SHAPES) do
        local x = CTRL_X + (i - 1) * 130
        local rb = newRadio(shrow, x, SHAPE_NAME[sh])
        rb:SetScript("OnClick", function()
            radioClick("glowShape", sh)
        end)
        shapeBtns[#shapeBtns + 1] = rb
        Options.controls["glowShape_" .. sh] = rb
    end
    refreshers[#refreshers + 1] = function()
        local cur = D().glowShape
        for i, sh in ipairs(SHAPES) do
            shapeBtns[i]:SetChecked(cur == sh)
        end
    end
    addReset(shrow, "glowShape", { "glowShape" }, function()
        return SHAPE_NAME[ns.defaults.glowShape] or tostring(ns.defaults.glowShape)
    end)
    y = y + 26
    local sdrow = newRow(y, 56)
    Options.rows.glowShapeDesc = sdrow
    local sd = sdrow:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    sd:SetPoint("TOPLEFT", sdrow, "TOPLEFT", CTRL_X, 0)
    sd:SetWidth(280)
    pcall(sd.SetSpacing, sd, 2)
    sd:SetJustifyH("LEFT")
    sd:SetWordWrap(true)
    sd:SetTextColor(GREY, GREY, GREY)
    sd:SetText(SHAPE_DESC)
    Options.shapeDesc = sd

    -- the shape and offsets describe the target frame, so they stay live with Show glow off; only the intensity dims
    y = y + 62
    slider(y, "glowOffsetX", "Target offset X", "%d px", " px")
    y = y + 32
    slider(y, "glowOffsetY", "Target offset Y", "%d px", " px")
    y = y + 36
    local od = text(child, "GameFontHighlight", OFFSET_DESC, LABEL_X, -y, 490)
    od:SetTextColor(GREY, GREY, GREY)
    Options.offsetDesc = od
    y = y + 22
    checkbox(y, "glow", "Show glow")
    y = y + 28
    slider(y, "glowIntensity", "Glow intensity", "%d%%", "%")
    postRefresh[#postRefresh + 1] = function()
        setDim(Options.rows.glowIntensity, { Options.controls.glowIntensity }, D().glow ~= false)
    end
    y = y + 32

    y = header("Style", y + 14)
    local radios = {}
    for i, st in ipairs(STYLES) do
        local ry = y + (i - 1) * 46
        local row = newRow(ry, 24)
        local rb = newRadio(row, LABEL_X, STYLE_NAME[st])
        rb:SetScript("OnClick", function()
            radioClick("style", st)
        end)
        radios[st] = rb
        Options.controls["style_" .. st] = rb
        Options.rows["style_" .. st] = row
        local desc = text(child, "GameFontHighlight", STYLE_DESC[st], LABEL_X + 24, -(ry + 24), 490)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[st] = desc
        if i == 1 then
            addReset(row, "style", { "style" }, function()
                return STYLE_NAME[ns.defaults.style] or tostring(ns.defaults.style)
            end)
        end
    end
    refreshers[#refreshers + 1] = function()
        local cur = D().style
        for _, st in ipairs(STYLES) do
            radios[st]:SetChecked(cur == st)
        end
    end

    y = header("XP bar", y + #STYLES * 46 + 14)
    local drow = newRow(y, 36)
    Options.rows.targetFrame = drow
    label(drow, "XP bar frame", LABEL_X)
    local dest = drow:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    dest:SetPoint("LEFT", drow, "LEFT", CTRL_X, 0)
    dest:SetWidth(280)
    dest:SetJustifyH("LEFT")
    dest:SetWordWrap(true)
    refreshers[#refreshers + 1] = function()
        dest:SetText(destinationText())
    end
    addReset(drow, "targetFrame", { "targetFrame" }, function()
        return "auto-detect"
    end)
    y = y + 36
    local prow = newRow(y, 30)
    button(prow, "Pick XP bar frame", CTRL_X, 150, function()
        ns.commands.pick("")
    end)

    local ph = text(child, "GameFontHighlight", PICK_HINT, LABEL_X, -(y + 34), 520)
    ph:SetWordWrap(true)
    ph:SetTextColor(GREY, GREY, GREY)
    Options.pickHint = ph

    y = header("Advanced", y + 34 + 28 + 14)
    checkbox(y, "debug", "Debug log")
    y = y + 28
    CONTENT_H = y + 16
    Options.CONTENT_H = CONTENT_H
    child:SetSize(CONTENT_W, CONTENT_H)

    -- fixed footer
    local rule = panel:CreateTexture(nil, "ARTWORK")
    rule:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X, 44)
    rule:SetSize(RULE_W, 1)
    Options.footerRule = rule
    rule:SetColorTexture(1, 1, 1, 0.15)
    local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    test:SetSize(110, 22)
    test:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 11)
    test:SetText("Test burst")
    test:SetScript("OnClick", function()
        -- the same orbs a kill would make: rested ones too when Rested tint is on
        pcall(ns.commands.test, D().restedTint and "5 rested" or "5")
    end)
    local resetAll = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    resetAll:SetSize(160, 22)
    resetAll:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", HEADER_X + RULE_W - 160, 11)
    resetAll:SetText("Reset all to default")
    resetAll:SetScript("OnClick", confirmReset)
    Options.resetAll = resetAll
    registerPopup()

    panel:SetScript("OnShow", function()
        Options:Refresh()
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

function ns.commands.options()
    if not Options.category then
        ns.Print("options: the settings panel isn't available ("
            .. (Options.err or "no Settings API on this client") .. "); use /xporbs commands instead")
        return
    end
    local ok = pcall(function()
        Settings.OpenToCategory(Options.category:GetID())
    end)
    if not ok then
        ns.Print("options: couldn't open the settings panel; try Esc > Options > AddOns > XP Orbs")
    end
end

table.insert(ns.statusProviders, function()
    if Options.category then
        return "options panel: registered"
    end
    return "options panel: unavailable (" .. (Options.err or "no Settings API") .. ")"
end)

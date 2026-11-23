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
local CONTENT_W, CONTENT_H = 584, 1450 -- |last y| + 16 (build recomputes it from the sections)
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
local STYLE_TIP = {
    popstream = "Has a pop. Pick where it happens below.",
    crossfade = "Has a pop. Nameplate: the pop and where the orbs vanish. Estimated position: the direction they "
        .. "leave in. Without a nameplate it falls back to a plain stream.",
    stream = "No pop. Nameplate: not used. Estimated position: where the stream starts.",
}
local POPMODES = { "nameplate", "direct" }
local POPMODE_NAME = { nameplate = "Nameplate", direct = "Direct" }
local POPMODE_DESC = {
    nameplate = "Pop on the nameplate (if shown), stream from the estimated position.",
    direct = "Pop and stream from the estimated position. No nameplate needed.",
}
local POPMODE_TIP = {
    nameplate = "The pop is drawn on the mob's nameplate, so it sits exactly on the mob; the stream starts at the "
        .. "estimated position. Without a nameplate: no pop, just the stream.",
    direct = "The pop opens at the estimated position and flows straight into the stream, nearest to the bar first. "
        .. "Never uses the nameplate, so it looks the same with nameplates off.",
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
local FLIGHT_STYLE_DESC = {
    smooth = "A clean arc from the mob to your XP bar.",
    chaos = "Orbs dart and weave like fireflies on the way.",
    helix = "Orbs spiral around each other in pairs.",
}
local MAX_TIP = "At max level, each kill sends a small burst of orbs to your portrait."
local SOUND_TIP = "Coin: a soft coin clink. Glass: a glassy tink. One per arriving orb (up to six per burst). "
    .. "Off by default."
local PLAY_X = 156 -- px right of CTRL_X: just past the 150 px voice dropdown
local PLAY_ATLAS = "voicechat-icon-speaker"
local PLAY_FALLBACK = "Interface\\Common\\VoiceChat-Speaker"
local PLAY_TIP = "Play a sample: a handful of orbs arriving"
local VOICES = { "glass", "coin" }
local VOICE_NAME = { coin = "Coin", glass = "Glass" }
local OFFSET_TIP = "Moves where orbs land and the glow appears (pixels)."
local PICK_HINT = "For a replaced XP bar, or to target your portrait (Circular)."

local refreshers, postRefresh, resets = {}, {}, {}
local refreshing = false
local child -- the scroll child every row hangs off
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
        local saved = settings()
        for _, k in ipairs(keys) do
            saved[k] = copyDefault(ns.defaults[k])
        end
        hideTip()
        Options:Refresh()
    end)
    btn:Hide() -- shown by updateResets once the db is known; it keeps its space either way
    resets[#resets + 1] = function()
        local saved, differs = settings(), false
        for _, k in ipairs(keys) do
            if OrbMath.Differs(saved[k], ns.defaults[k]) then
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
    local ok, sliderFrame = pcall(CreateFrame, "Slider", nil, row, "OptionsSliderTemplate")
    if ok and sliderFrame then
        -- the template'sliderFrame own title and min/max captions are replaced by our label and value text
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
                settings()[key] = v
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
-- onChange(v), if given, runs after a drag (or a click on the bar) stores a new value, not on Refresh.
local function slider(y, key, labelStr, fmt, unit, onChange)
    local lo, hi, step = ns.ranges[key][1], ns.ranges[key][2], ns.ranges[key][3]
    local row = newRow(y, 32)
    label(row, labelStr, LABEL_X)
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
        v = OrbMath.Snap(v, lo, hi, step)
        if not v then
            return
        end
        val:SetText(string.format(fmt, v))
        if not refreshing then
            settings()[key] = v
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
        sliderFrame:SetValue(v)
        val:SetText(string.format(fmt, OrbMath.Snap(v, lo, hi, step) or v))
    end
    attachValueEdit(row, key, val, lo, hi, step, unit)
    addReset(row, key, { key }, function()
        return string.format(fmt, ns.defaults[key])
    end)
    Options.controls[key] = sliderFrame
    Options.rows[key] = row
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
                local r, g, blue = ColorPickerFrame:GetColorRGB()
                settings()[key] = { r, g, blue }
                paint()
                changed()
            end,
            cancelFunc = function()
                settings()[key] = { prev[1], prev[2], prev[3] }
                paint()
                changed()
            end,
        })
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

-- The "Sound" row under the chime checkbox: Blizzard's modern dropdown (WowStyle1DropdownTemplate + SetupMenu radios),
-- or two radio buttons when this client has no such template. Picking a voice plays one sample note, even with the
-- chime off, so the player can audition both before turning the chime on. The row stays enabled.
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
    local dropdown
    local okMenu = pcall(function()
        dropdown = CreateFrame("DropdownButton", nil, row, "WowStyle1DropdownTemplate")
        dropdown:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
        dropdown:SetSize(150, 26)
        dropdown:SetupMenu(function(_, root)
            for _, v in ipairs(VOICES) do
                root:CreateRadio(VOICE_NAME[v], function()
                    return settings().soundVoice == v
                end, function()
                    pick(v)
                end)
            end
        end)
    end)
    if okMenu and dropdown then
        Options.soundDropdown = dropdown
        Options.controls.soundVoice = dropdown
        refreshers[#refreshers + 1] = function()
            if dropdown.GenerateMenu then
                dropdown:GenerateMenu()
            end
        end
    else
        if dropdown then
            pcall(dropdown.Hide, dropdown) -- a half-built dropdown must not sit over the radios
        end
        Options.soundDropdown = nil
        local radioBtns = {}
        for i, v in ipairs(VOICES) do
            local radio = newRadio(row, CTRL_X + (i - 1) * 100, VOICE_NAME[v])
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
    play:SetPoint("LEFT", row, "LEFT", CTRL_X + PLAY_X, 0)
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

-- ---------------------------------------------------------------- the sections
-- Each builder draws one section starting at y (the header's y for most of them) and returns the y after it. Splitting
-- them keeps every function well under Lua 5.1's 60-upvalue limit.

local function buildGeneral(y)
    y = header("General", y)
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

local function buildLook(y)
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
    checkbox(y, "trail", "Trail")
    y = y + 28

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

    y = y + 28
    checkbox(y, "restedTint", "Rested tint")
    y = y + 28
    local restedRow = newRow(y, 28)
    Options.rows.restedColor = restedRow
    local restedLabel = label(restedRow, "Rested colour", LABEL_X + 24)
    local restedSwatch = swatch(restedRow, "restedColor", CTRL_X)
    addReset(restedRow, "restedColor", { "restedColor" }, function()
        return hex(ns.defaults.restedColor)
    end)
    if not restedSwatch:IsShown() then
        restedLabel:Hide()
    end
    postRefresh[#postRefresh + 1] = function()
        setDim(restedRow, { restedSwatch }, settings().restedTint)
    end
    return y + 28
end

-- The "Flight style" dropdown (db.flightPath, /xporbs path): applies to every kill style, so it never dims. Built like
-- the Sound voice dropdown. Each option explains itself in its own menu tooltip and the button's tooltip explains the
-- current one, so no description takes page space. Radios replace the dropdown on a client without the template.
-- "Smooth (default)" inside the dropdown menu only; everywhere else (button text, tooltips, radios) the plain name.
local function flightStyleName(kind, withDefault)
    return ns.PATH_LABEL[kind] .. (withDefault and kind == ns.defaults.flightPath and " (default)" or "")
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

local function flightStyleRow(y)
    local row = newRow(y, 28)
    Options.rows.flightPath = row
    label(row, "Flight style", LABEL_X)
    local function pick(kind)
        settings().flightPath = kind
        Options:Refresh()
    end
    local dropdown
    local okMenu = pcall(function()
        dropdown = CreateFrame("DropdownButton", nil, row, "WowStyle1DropdownTemplate")
        dropdown:SetPoint("LEFT", row, "LEFT", CTRL_X, 0)
        dropdown:SetSize(150, 26)
        dropdown:SetupMenu(function(_, root)
            for _, kind in ipairs(ns.PATH_ORDER) do
                local name = flightStyleName(kind, true)
                local element = root:CreateRadio(name, function()
                    return settings().flightPath == kind
                end, function()
                    pick(kind)
                end)
                if element and element.SetTooltip then
                    pcall(element.SetTooltip, element, function(tooltip)
                        fillMenuTooltip(tooltip, name, FLIGHT_STYLE_DESC[kind])
                    end)
                end
            end
        end)
    end)
    if okMenu and dropdown then
        Options.flightDropdown = dropdown
        Options.controls.flightPath = dropdown
        local function showCurrent(self)
            local kind = settings().flightPath
            showTip2(self, flightStyleName(kind), FLIGHT_STYLE_DESC[kind] or "")
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
                pcall(dropdown.OverrideText, dropdown, flightStyleName(settings().flightPath))
            end
        end
    else
        if dropdown then
            pcall(dropdown.Hide, dropdown) -- a half-built dropdown must not sit over the radios
        end
        Options.flightDropdown = nil
        local radioBtns, radioX = {}, { 0, 140, 230 } -- px right of CTRL_X (the first label is the long one)
        for i, kind in ipairs(ns.PATH_ORDER) do
            local radio = newRadio(row, CTRL_X + radioX[i], flightStyleName(kind))
            radio:SetScript("OnClick", function()
                pick(kind)
            end)
            radio:SetScript("OnEnter", function(self)
                showTip2(self, flightStyleName(kind), FLIGHT_STYLE_DESC[kind])
            end)
            radio:SetScript("OnLeave", hideTip)
            radioBtns[i] = radio
            Options.controls["flightPath_" .. kind] = radio
        end
        refreshers[#refreshers + 1] = function()
            for i, kind in ipairs(ns.PATH_ORDER) do
                radioBtns[i]:SetChecked(settings().flightPath == kind)
            end
        end
    end
    addReset(row, "flightPath", { "flightPath" }, function()
        return flightStyleName(ns.defaults.flightPath)
    end)
    return y + 34
end

-- Style: the Flight Style dropdown, then three radios (row 24 + its description), Popstream's two sub-radios indented
-- under it at a tighter 42 px pitch with a wider gap after the group (dimmed unless Popstream is picked; clicking one
-- also picks Popstream), then the Zoom-scaled spread checkbox and its description.
local function buildStyle(y)
    y = header("Style", y + 14)
    y = flightStyleRow(y)
    -- the three kill styles are their own group: a label so they don't read as options of the dropdown above
    text(child, "GameFontHighlight", "Kill style", LABEL_X, -y)
    Options.killStyleLabelY = y
    y = y + 22
    local radios, subs = {}, {}
    local function tipOn(w, title, body)
        w:SetScript("OnEnter", function(self)
            showTip2(self, title, body)
        end)
        w:SetScript("OnLeave", hideTip)
    end
    local function styleRadio(st, ry)
        local row = newRow(ry, 24)
        local radio = newRadio(row, LABEL_X, STYLE_NAME[st])
        radio:SetScript("OnClick", function()
            radioClick("style", st)
        end)
        tipOn(radio, STYLE_NAME[st], STYLE_TIP[st])
        radios[st] = radio
        Options.controls["style_" .. st] = radio
        Options.rows["style_" .. st] = row
        local desc = text(child, "GameFontHighlight", STYLE_DESC[st], LABEL_X + 24, -(ry + 24), 490)
        desc:SetTextColor(GREY, GREY, GREY)
        Options.descs[st] = desc
        return row
    end
    local prow = styleRadio("popstream", y)
    addReset(prow, "style", { "style", "popMode" }, function()
        return ns.StyleLabel(ns.defaults)
    end)
    for i, pm in ipairs(POPMODES) do
        local ry = y + i * 42
        local row = newRow(ry, 24)
        local radio = newRadio(row, LABEL_X + 24, POPMODE_NAME[pm])
        radio:SetScript("OnClick", function()
            settings().style = "popstream" -- a sub-choice only means something under Popstream
            radioClick("popMode", pm)
        end)
        tipOn(radio, "Popstream (" .. ns.POPMODE_LABEL[pm] .. ")", POPMODE_TIP[pm])
        subs[pm] = radio
        Options.controls["popMode_" .. pm] = radio
        Options.rows["popMode_" .. pm] = row
        local desc = text(child, "GameFontHighlight", POPMODE_DESC[pm], LABEL_X + 48, -(ry + 24), 466)
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
    local _, scb = checkbox(y, "zoomSpread", "Zoom-scaled spread")
    tipOn(scb, "Zoom-scaled spread", SPREAD_TIP)
    local spreadDescText = text(child, "GameFontHighlight", SPREAD_DESC, LABEL_X, -(y + 28), 490)
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
    return y + 44
end

-- Arrival: where the orbs land. The XP bar row (what was found, plus the picker) comes first, then the target frame's
-- shape and offsets and the glow. The shape and offsets stay live with Show glow off; only the intensity dims.
local function buildArrival(y)
    y = header("Arrival", y)
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
    y = header("Sound", y + 14)
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

local function buildAdvanced(y)
    y = header("Advanced", y + 14)
    checkbox(y, "debug", "Debug log")
    return y + 28
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

    -- most-used first
    local y = buildGeneral(8)
    y = buildLook(y)
    y = buildStyle(y)
    y = buildArrival(y)
    y = buildSound(y)
    y = buildAdvanced(y)
    CONTENT_H = y + 16
    Options.CONTENT_H = CONTENT_H
    child:SetSize(CONTENT_W, CONTENT_H)

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

    -- The Test burst button lives under the "Test target" window (Preview.lua). Only when that window can't be built
    -- does the panel get its own footer button, made on first need, so testing still works.
    local function ensureFooterTest(needed)
        if needed and not Options.footerTest then
            local test = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
            test:SetSize(110, 22)
            test:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", 16, 11)
            test:SetText("Test burst")
            test:SetScript("OnClick", function()
                -- the same orbs a kill would make: rested ones too when Rested tint is on
                pcall(ns.commands.test, settings().restedTint and "5 rested" or "5")
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

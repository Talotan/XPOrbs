-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Settings panel, shared kit (ns.OptionsKit): the Options table, the change plumbing, the row widgets and the layout
-- constants the other Options*.lua files build on. Mutable state (child, rowParent, refreshing) lives on the kit and is
-- always read as kit.x, never cached in a local.

local Options = {}
ns.Options = Options
local kit = { Options = Options, pages = {} } -- pages: tab name -> builder, registered by OptionsLook / OptionsPages
ns.OptionsKit = kit

local OrbMath = ns.OrbMath
local floor = math.floor

-- Layout (UI px, relative to the scroll child; y grows downwards).
local HEADER_X, LABEL_X, CTRL_X, VALUE_X, RESET_X = 16, 32, 260, 472, 548
local SLIDER_W = 200
local RULE_W = 552
local CONTENT_W = 584
local DIM = 0.4
local GREY = 0.70
local EN_DASH = "\226\128\147"
local ICON_ATLAS = "transmog-icon-revert"
local ICON_FALLBACK = "Interface\\Buttons\\UI-RefreshButton"
local HILITE = "Interface\\Buttons\\ButtonHilight-Square"

local refreshers, postRefresh, resets = {}, {}, {}
kit.refreshing = false

-- Size, quantity and opacity belong to the current orb shape (ns.SetLook / ns.ShapeDefault, Core.lua): a slider writes
-- the active value and the shape's own entry, and a reset button restores the current shape's default.
local LOOK = {}
for _, lookKey in ipairs(ns.SHAPE_LOOK_KEYS) do
    LOOK[lookKey] = true
end
kit.child = nil -- the scroll child every row hangs off (Options.lua points it at each tab's frame while building)
-- when set, newRow hangs rows off this frame instead (the Look tab's shape box); positions stay child-relative
kit.rowParent = nil
Options.controls = {} -- key -> the widget (checkbox, slider, swatch, radio)
Options.rows = {} -- key -> the row frame (dimming and layout)
Options.resets = {} -- key -> the per-row reset button
Options.descs = {} -- style / popMode / "zoomSpread" -> its description FontString

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
    kit.refreshing = true
    for i = 1, #refreshers do
        pcall(refreshers[i])
    end
    kit.refreshing = false
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
    local row = CreateFrame("Frame", nil, kit.rowParent or kit.child)
    row:SetSize(CONTENT_W, h)
    row:SetPoint("TOPLEFT", kit.child, "TOPLEFT", 0, -y)
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
        if not kit.refreshing then
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

-- Box geometry shared by the Look tab's shape box and the Flight tab's kill style box.
-- left edge on the other tabs' label column, right edge on the rule's
local BOX_X, BOX_W = LABEL_X, HEADER_X + RULE_W - LABEL_X
local BOX_LABEL_X = LABEL_X + 16 -- inner padding 16
local BOX_RESET_X = RESET_X - 4 -- the reset buttons end 4 px inside the border
local BOX_BOTTOM_PAD = 8

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

-- A bordered, faintly filled frame of height h at y on the current tab (the Look tab's shape box, the Flight tab's
-- kill style box).
local function boxFrame(y, h)
    local box = CreateFrame("Frame", nil, kit.child)
    box:SetSize(BOX_W, h)
    box:SetPoint("TOPLEFT", kit.child, "TOPLEFT", BOX_X, -y)
    local fill = box:CreateTexture(nil, "BACKGROUND")
    fill:SetAllPoints(box)
    fill:SetColorTexture(1, 1, 1, 0.04)
    boxEdge(box, "TOPLEFT", "TOPRIGHT", BOX_W, 1)
    boxEdge(box, "BOTTOMLEFT", "BOTTOMRIGHT", BOX_W, 1)
    boxEdge(box, "TOPLEFT", "BOTTOMLEFT", 1, h)
    boxEdge(box, "TOPRIGHT", "BOTTOMRIGHT", 1, h)
    return box
end

kit.refreshers, kit.postRefresh = refreshers, postRefresh
kit.settings, kit.lookDefault, kit.writeValue, kit.changed = settings, lookDefault, writeValue, changed
kit.hex, kit.onOff = hex, onOff
kit.showTip, kit.showTip2, kit.hideTip = showTip, showTip2, hideTip
kit.text, kit.newRow, kit.label = text, newRow, label
kit.newCheck, kit.newRadio, kit.enable, kit.setDim = newCheck, newRadio, enable, setDim
kit.addReset, kit.checkbox, kit.slider, kit.button = addReset, checkbox, slider, button
kit.radioClick, kit.newDropdown, kit.choiceRow, kit.boxFrame = radioClick, newDropdown, choiceRow, boxFrame
kit.HEADER_X, kit.LABEL_X, kit.CTRL_X, kit.RESET_X = HEADER_X, LABEL_X, CTRL_X, RESET_X
kit.RULE_W, kit.CONTENT_W, kit.DIM, kit.GREY, kit.HILITE = RULE_W, CONTENT_W, DIM, GREY, HILITE
kit.DROPDOWN_SIZE = DROPDOWN_SIZE
kit.BOX_X, kit.BOX_LABEL_X, kit.BOX_RESET_X, kit.BOX_BOTTOM_PAD = BOX_X, BOX_LABEL_X, BOX_RESET_X, BOX_BOTTOM_PAD

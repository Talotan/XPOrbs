-- M5 stub extensions: Settings, option-panel widgets (sliders, check buttons, font strings), ColorPickerFrame,
-- GLOBAL_MOUSE_DOWN picking helpers. Load AFTER stubs_m2.lua and BEFORE the addon files (Options.lua registers at
-- load). Called as a chunk with (ns).
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

stub.settings = { registered = {}, added = {}, opened = {} }
Settings = {
    RegisterCanvasLayoutCategory = function(frame, name)
        local cat = { frame = frame, name = name, id = 100 + #stub.settings.registered }
        function cat.GetID()
            return cat.id
        end
        stub.settings.registered[#stub.settings.registered + 1] = cat
        return cat
    end,
    RegisterAddOnCategory = function(cat)
        stub.settings.added[#stub.settings.added + 1] = cat
    end,
    OpenToCategory = function(id)
        stub.settings.opened[#stub.settings.opened + 1] = id
    end,
}

-- Real RGB <-> HSV (all 0..1), so the picker's ColorSelect can be simulated: black has no hue.
local function rgbToHsv(r, g, b)
    local hi, lo = math.max(r, g, b), math.min(r, g, b)
    local d = hi - lo
    local h = 0
    if d > 0 then
        if hi == r then
            h = ((g - b) / d) % 6
        elseif hi == g then
            h = (b - r) / d + 2
        else
            h = (r - g) / d + 4
        end
        h = h / 6
    end
    return h, hi > 0 and d / hi or 0, hi
end

local function hsvToRgb(h, s, v)
    local i = math.floor(h * 6)
    local f = h * 6 - i
    local p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    local m = i % 6
    if m == 0 then
        return v, t, p
    elseif m == 1 then
        return q, v, p
    elseif m == 2 then
        return p, v, t
    elseif m == 3 then
        return p, q, v
    elseif m == 4 then
        return t, p, v
    end
    return v, p, q
end

ColorPickerFrame = {
    SetupColorPickerAndShow = function(self, info)
        self.info = info
        self.r, self.g, self.b = info.r, info.g, info.b
        local sel = self.Content and self.Content.ColorPicker
        if sel then
            sel.hsv = nil -- the widget derives HSV from the RGB it was given (black: no hue)
        end
    end,
    GetColorRGB = function(self)
        return self.r, self.g, self.b
    end,
    -- the modern picker's ColorSelect: HSV in, RGB out; stub.noHSV removes the API (older / odd clients)
    Content = {},
}
local colorSelect = {
    -- what the wheel holds: the HSV last set, as long as it still matches the RGB (a test that pokes cp.r/g/b directly
    -- gets the RGB's own HSV)
    GetColorHSV = function(self)
        local cp = ColorPickerFrame
        local hsv = self.hsv
        if hsv then
            local r, g, b = hsvToRgb(hsv[1], hsv[2], hsv[3])
            if math.abs(r - cp.r) < 1e-6 and math.abs(g - cp.g) < 1e-6 and math.abs(b - cp.b) < 1e-6 then
                return hsv[1], hsv[2], hsv[3]
            end
        end
        return rgbToHsv(cp.r, cp.g, cp.b)
    end,
    SetColorHSV = function(self, h, s, v)
        local cp = ColorPickerFrame
        self.hsvSets = (self.hsvSets or 0) + 1
        self.hsv = { h, s, v }
        cp.r, cp.g, cp.b = hsvToRgb(h, s, v)
        if self.echo and cp.info and cp.info.swatchFunc then
            cp.info.swatchFunc() -- OnColorSelect fires swatchFunc, like the real widget
        end
    end,
}
ColorPickerFrame.Content.ColorPicker = colorSelect
-- A player drag on the wheel / value slider. Like Blizzard's picker, black loses hue and saturation in the widget.
function ColorPickerFrame:Drag(h, s, v)
    self.r, self.g, self.b = hsvToRgb(h, s, v)
    if v <= 0 then
        colorSelect.hsv = { 0, 0, 0 }
    else
        colorSelect.hsv = { h, s, v }
    end
    self.info.swatchFunc()
end
stub.rgbToHsv, stub.hsvToRgb = rgbToHsv, hsvToRgb

-- names / parents (the v0.9 wrapper only keeps the parent)
local baseCreate = CreateFrame

-- Blizzard's MinimalSliderWithSteppersTemplate: a host Frame with .Slider (a real Slider), .Back / .Forward stepper
-- buttons, label font strings, Init(value, min, max, steps, formatters), SetValue, SetEnabled and the callback
-- registry (events fire for any value change, programmatic or not, but never for Init). stub.initCalls counts Inits.
MinimalSliderWithSteppersMixin = {
    Event = { OnValueChanged = "OnValueChanged", OnInteractStart = "OnInteractStart", OnInteractEnd = "OnInteractEnd" },
    Label = { Left = 1, Right = 2, Top = 3, Min = 4, Max = 5 },
}
stub.initCalls = 0
function stub.buildStepperSlider(f)
    local inner = baseCreate("Slider")
    inner.parentFrame = f
    f.Slider, f.Back, f.Forward = inner, baseCreate("Button"), baseCreate("Button")
    function inner:GetValue() -- (the shared GetValue below is the StatusBar reading)
        return self.value or 0
    end
    for _, k in ipairs({ "LeftText", "RightText", "TopText", "MinText", "MaxText" }) do
        f[k] = baseCreate("FontString")
    end
    f.callbacks = {}
    function f:RegisterCallback(event, fn, owner)
        self.callbacks[event] = self.callbacks[event] or {}
        table.insert(self.callbacks[event], { fn = fn, owner = owner })
    end
    function f:Init(value, lo, hi, steps, formatters)
        stub.initCalls = stub.initCalls + 1
        self.initArgs = { value = value, min = lo, max = hi, steps = steps, formatters = formatters }
        inner.minV, inner.maxV, inner.step, inner.value = lo, hi, (hi - lo) / steps, value
        inner.enabled = true
    end
    function f:SetValue(v)
        inner:SetValue(v)
    end
    function f:SetEnabled(on)
        inner.enabled = on
        self.tplEnabled = on
    end
    inner.scripts.OnValueChanged = function(_, v)
        for _, cb in ipairs(f.callbacks.OnValueChanged or {}) do
            cb.fn(cb.owner, v)
        end
    end
    -- the arrows move the bar by one step, like a click on them
    f.Back.scripts.OnClick = function()
        inner:SetValue((inner.value or inner.minV) - inner.step)
    end
    f.Forward.scripts.OnClick = function()
        inner:SetValue((inner.value or inner.minV) + inner.step)
    end
end

-- Our XPOrbsDropdownWithSteppersTemplate (Templates.xml): the host with the inner WowStyle2 .Dropdown the XML adds and
-- the two arrow buttons DropdownWithSteppersTemplate makes; they call the dropdown's Increment / Decrement.
function stub.buildStepperDropdown(f)
    f.Dropdown = CreateFrame("DropdownButton", nil, f, "WowStyle2DropdownTemplate")
    f.IncrementButton, f.DecrementButton = baseCreate("Button"), baseCreate("Button")
    f.IncrementButton.scripts.OnClick = function()
        f.Dropdown:Increment()
    end
    f.DecrementButton.scripts.OnClick = function()
        f.Dropdown:Decrement()
    end
end
function CreateFrame(kind, name, parent, template)
    local f = baseCreate(kind, name, parent)
    f.name, f.template = name, template
    if parent ~= nil then
        f.createdParent = parent
    end
    if kind == "CheckButton" then
        f.checked = false
    end
    if template == "MinimalSliderWithSteppersTemplate" then
        stub.buildStepperSlider(f)
    elseif template == "XPOrbsDropdownWithSteppersTemplate" then
        stub.buildStepperDropdown(f)
    elseif template == "TooltipBackdropTemplate" then
        -- the border art; SetBackdropColor / SetBackdropBorderColor are recorders below
        f.NineSlice = baseCreate("Frame")
    end
    if kind == "DropdownButton" then
        -- Blizzard's modern dropdown: SetupMenu keeps the generator, GenerateMenu runs it against a root that records
        -- the radios it is given (text, isSelected() as evaluated now, the setSelected callback)
        function f:SetupMenu(gen)
            self.menuGen = gen
            self:GenerateMenu()
        end
        function f:GenerateMenu()
            local root = { entries = {} }
            function root:CreateRadio(text, isSelected, setSelected, data)
                local entry = { text = text, selected = isSelected(), setSelected = setSelected, data = data }
                self.entries[#self.entries + 1] = entry
                -- the menu element description: SetTooltip keeps the callback so a test can run it on a tooltip
                function entry:SetTooltip(fn)
                    self.tooltipFn = fn
                end
                return entry
            end
            self.menuRoot = root
            if self.menuGen then
                self.menuGen(self, root)
            end
        end
        -- the arrows: step the selected radio one entry (no wrap), through the same setSelected callback a pick runs
        local function step(self, by)
            self:GenerateMenu()
            local entries = self.menuRoot.entries
            for i, e in ipairs(entries) do
                if e.selected then
                    local target = entries[i + by]
                    if target then
                        target.setSelected()
                    end
                    return
                end
            end
        end
        function f:Increment()
            step(self, 1)
        end
        function f:Decrement()
            step(self, -1)
        end
    end
    return f
end
function fm:GetName()
    return self.name
end
function fm:GetParent()
    return self.createdParent or self.parentFrame
end

-- no-op recorders for the cosmetic calls the panel makes
for _, name in ipairs({
    "SetJustifyH", "SetWordWrap", "SetHitRectInsets", "SetSpacing", "SetColorTexture", "SetFontObject", "SetFont", "SetOrientation", "SetThumbTexture",
    "SetObeyStepOnDrag",
}) do
    fm[name] = function(self, ...)
        self.calls = self.calls or {}
        self.calls[name] = { ... }
    end
end
function fm:CreateFontString()
    local fs = CreateFrame("FontString")
    fs.parentFrame = self
    return fs
end
-- HookScript: this stub keeps one handler per script, so a hook on an empty slot is the handler
function fm:HookScript(name, fn)
    if not self.scripts[name] then
        self.scripts[name] = fn
    end
end
function fm:SetText(t)
    self.text = t
end
-- v0.14: a fixed 7 px per character stands in for font metrics
function fm:GetStringWidth()
    return #(self.text or "") * 7
end
function fm:GetText()
    return self.text
end
function fm:SetChecked(b)
    self.checked = b and true or false
end
function fm:GetChecked()
    return self.checked
end

-- sliders: clamp, snap to the step, fire OnValueChanged(self, value, userInput) only when the value changed
function fm:SetMinMaxValues(a, b)
    self.minV, self.maxV = a, b
end
function fm:SetValueStep(s)
    self.step = s
end
function fm:SetValue(v)
    if self.minV then
        v = math.max(self.minV, math.min(self.maxV, v))
    end
    if self.step and self.step > 0 then
        v = (self.minV or 0) + math.floor((v - (self.minV or 0)) / self.step + 0.5) * self.step
    end
    if v ~= self.value then
        self.value = v
        local fn = self.scripts.OnValueChanged
        if fn then
            fn(self, v, false)
        end
    end
end
function fm:GetValue()
    return self.value or 0
end

-- what a user does: drag a slider, click a check button / button
function stub.slide(f, v)
    f:SetValue(v)
end
function stub.click(f)
    if f.kind == "CheckButton" then
        f.checked = not f.checked
    end
    local fn = f.scripts.OnClick
    if fn then
        fn(f, "LeftButton", false)
    end
end

-- what a user does in a modern dropdown: open its menu (regenerated, as the client does) and pick a radio by its text
function stub.pickMenu(dd, text)
    dd:GenerateMenu()
    for _, e in ipairs(dd.menuRoot.entries) do
        if e.text == text then
            e.setSelected()
            return true
        end
    end
    return false
end

-- picking
stub.focus = nil
function GetMouseFoci()
    return { stub.focus }
end
function stub.mouseDown(button)
    ns.fire("GLOBAL_MOUSE_DOWN", button)
end
function stub.namedFrame(name, parent)
    local f = CreateFrame("Frame", name, parent)
    _G[name] = f
    return f
end

-- Draw-only frames (no mouse): EnumerateFrames walks stub.frames (frames only, no textures) in creation order, and
-- IsMouseOver tests stub.cursor against the frame's left/bottom/width/height. stub.enumStarts counts full walks.
stub.enumStarts = 0
function EnumerateFrames(prev)
    local list, i = stub.frames, 1
    if prev == nil then
        stub.enumStarts = stub.enumStarts + 1
    else
        while list[i] ~= nil and not rawequal(list[i], prev) do
            i = i + 1
        end
        i = i + 1
    end
    while list[i] ~= nil do
        local k = list[i].kind
        if k ~= "Texture" and k ~= "FontString" then
            return list[i]
        end
        i = i + 1
    end
    return nil
end
function fm:IsForbidden()
    return self.forbidden == true
end
function fm:IsMouseOver()
    local l, b, w, h = self.left, self.bottom, self.width, self.height
    if not (l and b and w and h) then
        return false
    end
    local x, y = stub.cursor.x, stub.cursor.y
    return x >= l and x <= l + w and y >= b and y <= b + h
end
-- StatusBar readings: a frame carries sb = { lo, hi, v, orient, reverse } (any value may be stub.SECRET); frames
-- without it report nothing, like a plain Frame would.
function fm:GetMinMaxValues()
    if self.sb then
        return self.sb.lo, self.sb.hi
    end
end
function fm:GetValue()
    return self.sb and self.sb.v
end
function fm:GetOrientation()
    return self.sb and self.sb.orient
end
function fm:GetReverseFill()
    return self.sb and self.sb.reverse
end
-- A visible, mouse-less StatusBar like EQOL_XPBar. orient: "HORIZONTAL" or "VERTICAL".
function stub.makeStatusBar(name, left, bottom, width, height, lo, hi, v, orient, reverse)
    local f = stub.makeBar(name, left, bottom, width, height, true)
    f.sb = { lo = lo, hi = hi, v = v, orient = orient, reverse = reverse == true }
    return f
end
-- An unnamed frame that is not registered as a global (a child of some addon's table, like FlareUI_XPBar.Left).
-- Pass lo/hi/v/orient to make it a StatusBar.
function stub.makeFreeBar(left, bottom, width, height, visible, lo, hi, v, orient, reverse)
    local f = CreateFrame("Frame")
    f.left, f.bottom, f.width, f.height = left, bottom, width, height
    f.shown = visible ~= false
    if lo ~= nil then
        f.sb = { lo = lo, hi = hi, v = v, orient = orient or "HORIZONTAL", reverse = reverse == true }
    end
    return f
end
-- A named, visible frame that takes no mouse input (like EQOL_XPBar): rect only, registered as a global.
function stub.drawOnly(name, left, bottom, width, height, parent)
    local f = stub.namedFrame(name, parent)
    f.left, f.bottom, f.width, f.height = left, bottom, width, height
    return f
end

-- ---------------------------------------------------------------- v0.13 extensions
-- scroll frames, enable/disable, edit boxes, tooltip, static popups, atlas, class colours.
for _, name in ipairs({ "SetHighlightTexture", "EnableMouseWheel", "SetMovable", "RegisterForDrag", "SetClampedToScreen",
    "StartMoving", "StopMovingOrSizing", "RegisterForClicks", "SetAutoFocus", "SetMaxLetters" }) do
    fm[name] = function(self, ...)
        self.calls = self.calls or {}
        self.calls[name] = { ... }
    end
end
function fm:SetAtlas(name)
    self.atlas = name
end
function fm:SetTextColor(r, g, b)
    self.textColor = { r, g, b }
end
function fm:Disable()
    self.disabled = true
end
function fm:Enable()
    self.disabled = false
end
function fm:IsEnabled()
    return self.disabled ~= true
end
function fm:SetScrollChild(c)
    self.scrollChild = c
end
function fm:GetScrollChild()
    return self.scrollChild
end
function fm:SetVerticalScroll(v)
    self.vscroll = v
end
function fm:GetVerticalScroll()
    return self.vscroll or 0
end
function fm:GetVerticalScrollRange()
    return 100
end
function fm:SetFocus()
    self.hasFocus = true
end
function fm:ClearFocus()
    if self.hasFocus then
        self.hasFocus = false
        local fn = self.scripts.OnEditFocusLost
        if fn then
            fn(self)
        end
    end
end
function fm:HighlightText()
    self.highlighted = true
end
local baseHide = fm.Hide
function fm:Hide()
    baseHide(self)
    if self.hasFocus then
        self:ClearFocus() -- hiding a focused edit box drops its focus
    end
end

function stub.rightClick(f)
    local fn = f.scripts.OnClick
    if fn then
        fn(f, "RightButton", false)
    end
end
function stub.hover(f)
    f = f.Slider or f -- a stepper slider's tooltip hooks sit on its bar (and arrows)
    local fn = f.scripts.OnEnter
    if fn then
        fn(f)
    end
end
function stub.unhover(f)
    f = f.Slider or f
    local fn = f.scripts.OnLeave
    if fn then
        fn(f)
    end
end
-- type into an edit box and press Enter / Escape (WoW clears focus after both)
function stub.enterText(eb, str)
    eb:SetText(str)
    local fn = eb.scripts.OnEnterPressed
    if fn then
        fn(eb)
    end
    eb:ClearFocus()
end
function stub.escapeText(eb, str)
    eb:SetText(str)
    local fn = eb.scripts.OnEscapePressed
    if fn then
        fn(eb)
    end
    eb:ClearFocus()
end

stub.tooltip = { shown = false }
GameTooltip = {
    SetOwner = function(_, owner, anchor)
        stub.tooltip.owner, stub.tooltip.anchor = owner, anchor
    end,
    SetText = function(_, t)
        stub.tooltip.text = t
        stub.tooltip.lines = {}
    end,
    AddLine = function(_, t)
        stub.tooltip.lines = stub.tooltip.lines or {}
        stub.tooltip.lines[#stub.tooltip.lines + 1] = t
    end,
    Show = function()
        stub.tooltip.shown = true
    end,
    Hide = function()
        stub.tooltip.shown = false
    end,
}

stub.popups = {}
StaticPopupDialogs = {}
function StaticPopup_Show(name)
    stub.popups[#stub.popups + 1] = name
    return true
end

stub.atlases = { ["transmog-icon-revert"] = { width = 20, height = 20 } }
C_Texture = {
    GetAtlasInfo = function(name)
        return stub.atlases[name]
    end,
}

-- Install a class: UnitClass("player") and the class colour APIs. api = false removes C_ClassColor (RAID_CLASS_COLORS
-- stays), api = "none" removes every class colour source.
function stub.setClass(classFile, r, g, b, api)
    function UnitClass()
        return classFile:sub(1, 1) .. classFile:sub(2):lower(), classFile, 2
    end
    RAID_CLASS_COLORS = { [classFile] = { r = r, g = g, b = b } }
    C_ClassColor = {
        GetClassColor = function(cf)
            if cf == classFile then
                return { r = r, g = g, b = b }
            end
        end,
    }
    if api == false then
        C_ClassColor = nil
    elseif api == "none" then
        C_ClassColor, RAID_CLASS_COLORS = nil, nil
    end
end

-- ---------------------------------------------------------------- pick-smart extensions (new methods only)
-- Frame trees for the picker's StatusBar search: stub.child(parent, key, f) links f under parent (parent[key] = f when a
-- key is given, which is what GetParentKey reports), GetChildren lists them, GetObjectType says StatusBar for a frame
-- with sb readings, GetFrameLevel reads f.level.
function stub.child(parent, key, f)
    f.createdParent = parent
    parent.kids = parent.kids or {}
    parent.kids[#parent.kids + 1] = f
    if key then
        f.parentKey = key
        parent[key] = f
    end
    return f
end
function fm:GetChildren()
    return (table.unpack or unpack)(self.kids or {})
end
function fm:GetObjectType()
    return self.sb and "StatusBar" or "Frame"
end
function fm:GetFrameLevel()
    return self.level or 0
end
function fm:SetFrameLevel(level)
    self.level = level
end
function fm:GetParentKey()
    return self.parentKey
end

-- ---------------------------------------------------------------- setup-window extensions (C3, new helpers only)
-- C_Timer.After is controllable: callbacks queue in stub.timers (delay, fn) until stub.runTimers() runs them. Setting
-- the global C_Timer to nil gives the client that has no timers. InCombatLockdown reads stub.inCombat. Backdrop and
-- keyboard calls are recorders (the Frame itself has no such methods in wowstub).
stub.timers = {}
C_Timer = {
    After = function(delay, callback)
        stub.timers[#stub.timers + 1] = { delay = delay, fn = callback }
    end,
}
function stub.runTimers()
    local pending = stub.timers
    stub.timers = {}
    for _, timer in ipairs(pending) do
        timer.fn()
    end
end
stub.inCombat = false
function InCombatLockdown()
    return stub.inCombat
end
for _, name in ipairs({ "SetBackdrop", "SetBackdropColor", "SetBackdropBorderColor", "EnableKeyboard",
    "SetPropagateKeyboardInput" }) do
    fm[name] = function(self, ...)
        self.calls = self.calls or {}
        self.calls[name] = { ... }
    end
end

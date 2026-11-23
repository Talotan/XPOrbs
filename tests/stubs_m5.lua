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

ColorPickerFrame = {
    SetupColorPickerAndShow = function(self, info)
        self.info = info
        self.r, self.g, self.b = info.r, info.g, info.b
    end,
    GetColorRGB = function(self)
        return self.r, self.g, self.b
    end,
}

-- names / parents (the v0.9 wrapper only keeps the parent)
local baseCreate = CreateFrame
function CreateFrame(kind, name, parent, template)
    local f = baseCreate(kind, name, parent)
    f.name, f.template = name, template
    if parent ~= nil then
        f.createdParent = parent
    end
    if kind == "CheckButton" then
        f.checked = false
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
                self.entries[#self.entries + 1] =
                    { text = text, selected = isSelected(), setSelected = setSelected, data = data }
            end
            self.menuRoot = root
            if self.menuGen then
                self.menuGen(self, root)
            end
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
    "SetJustifyH", "SetWordWrap", "SetHitRectInsets", "SetSpacing", "SetColorTexture", "SetFontObject", "SetOrientation", "SetThumbTexture",
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
    "StartMoving", "StopMovingAndSizing", "RegisterForClicks", "SetAutoFocus", "SetMaxLetters" }) do
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
    local fn = f.scripts.OnEnter
    if fn then
        fn(f)
    end
end
function stub.unhover(f)
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

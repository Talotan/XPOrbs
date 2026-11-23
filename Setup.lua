-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- "Find your XP bar" window: a small movable dialog that opens by itself when the addon can't find an XP bar (orbs
-- would fly to the bottom centre) and on /xporbs setup. It lets the player pick the bar, choose the glow shape and the
-- landing offset, and fire a test burst. Every control writes ns.db directly and the options panel is kept in sync.
-- Only reads other frames (through Target); the window itself is ours, unnamed and built on first use.

local Setup = {}
ns.Setup = Setup

local Target = ns.Target
local OrbMath = ns.OrbMath

local ENTRY_DELAY = 5 -- seconds after PLAYER_ENTERING_WORLD before the first look (UI suites build their bars late)
local TEST_PERCENT = "10" -- /xporbs test argument: a burst worth 10% of a level
local WINDOW_W, WINDOW_H = 320, 332
local PAD = 16
local CONTENT_W = WINDOW_W - 2 * PAD
local SLIDER_X, SLIDER_W, VALUE_X = 84, 150, 246
local RADIO_SIZE = 20
local RADIO_SPACING = 100
local GREY = 0.70
local BACKDROP = {
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true,
    tileSize = 16,
    edgeSize = 16,
    insets = { left = 4, right = 4, top = 4, bottom = 4 },
}

local SHAPES = { "bar", "vertical", "round" }
local SHAPE_NAME = { bar = "Horizontal", vertical = "Vertical", round = "Circular" }
local OFFSETS = {
    { key = "glowOffsetX", label = "Offset X", y = -214 },
    { key = "glowOffsetY", label = "Offset Y", y = -242 },
}

local window -- the dialog, built on first Open
local eventFrame -- PLAYER_ENTERING_WORLD always; PLAYER_REGEN_ENABLED only while waiting for combat to end
local pickWatcher -- frame whose OnUpdate exists only while the window is hidden for a pick
local shownThisSession = false
local entryPending = false -- a C_Timer.After callback is in flight
local waitingForCombat = false
local refreshing = false -- true while controls are being set from the db (their handlers must not write back)

Setup.controls = {} -- name -> widget, for tests and for the options panel's sake
Setup.statusText = nil -- the "Using: ..." line

-- ---------------------------------------------------------------- when to offer it

-- All the reasons to open the window by itself: enabled, not dismissed, not shown yet, not aiming at the portrait, and
-- Target really finds no bar right now. The cheap checks come first, so a dismissed player costs a few comparisons.
local function wanted()
    local saved = ns.db
    if not saved or saved.enabled == false or saved.setupDismissed == true or shownThisSession then
        return false
    end
    local okPortrait, portrait = pcall(Target.PortraitMode, Target)
    if okPortrait and portrait == true then
        return false
    end
    local okDestination, _, _, found = pcall(Target.GetDestination, Target)
    return okDestination and found == false
end

local function offerWindow()
    if shownThisSession or waitingForCombat then
        return
    end
    if InCombatLockdown and InCombatLockdown() then
        waitingForCombat = true
        pcall(eventFrame.RegisterEvent, eventFrame, "PLAYER_REGEN_ENABLED")
        return
    end
    if wanted() then
        Setup:Open()
    end
end

-- The first burst whose destination came back not-found (Orbs.lua calls this; once the window has been shown, or while
-- it waits for combat to end, it returns at once). Never throws.
function Setup:NoBarFound()
    pcall(offerWindow)
end

local function onEntryDelay()
    entryPending = false
    pcall(offerWindow)
end

local function scheduleEntryCheck()
    if shownThisSession or entryPending or not (C_Timer and C_Timer.After) then
        return
    end
    entryPending = true
    if not pcall(C_Timer.After, ENTRY_DELAY, onEntryDelay) then
        entryPending = false
    end
end

local function onCombatEnd()
    waitingForCombat = false
    pcall(eventFrame.UnregisterEvent, eventFrame, "PLAYER_REGEN_ENABLED")
    offerWindow()
end

local function onEvent(_, event)
    if event == "PLAYER_ENTERING_WORLD" then
        pcall(scheduleEntryCheck)
    elseif event == "PLAYER_REGEN_ENABLED" then
        pcall(onCombatEnd)
    end
end

eventFrame = CreateFrame("Frame")
Setup.eventFrame = eventFrame
eventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
eventFrame:SetScript("OnEvent", onEvent)

-- ---------------------------------------------------------------- the window

local function syncOptionsPanel()
    if ns.Options and ns.Options.Refresh then
        pcall(ns.Options.Refresh, ns.Options)
    end
end

-- "Using: <bar>" when Target finds one, else "Still not found".
local function currentStatus()
    local okDestination, _, _, found = pcall(Target.GetDestination, Target)
    if okDestination and found then
        return "Using: " .. tostring(Target.lastSourceLabel or Target.lastName)
    end
    return "Still not found"
end

local function refreshWindow()
    if not window or not ns.db then
        return
    end
    refreshing = true
    local controls = Setup.controls
    for _, shape in ipairs(SHAPES) do
        controls["shape_" .. shape]:SetChecked(ns.db.glowShape == shape)
    end
    for _, offset in ipairs(OFFSETS) do
        local value = ns.db[offset.key]
        if type(value) == "number" then
            controls[offset.key]:SetValue(value)
            controls[offset.key .. "_value"]:SetText(string.format("%d px", value))
        end
    end
    controls.dismiss:SetChecked(ns.db.setupDismissed == true)
    Setup.statusText:SetText(currentStatus())
    refreshing = false
end

local function addText(parent, template, str, x, y, width)
    local text = parent:CreateFontString(nil, "ARTWORK", template)
    text:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    text:SetJustifyH("LEFT")
    if width then
        text:SetWidth(width)
        text:SetWordWrap(true)
    end
    text:SetText(str)
    return text
end

local function hideTemplateText(button)
    for _, key in ipairs({ "Text", "text" }) do
        local text = button[key]
        if type(text) == "table" and text.Hide then
            if text.SetText then
                text:SetText("")
            end
            text:Hide()
        end
    end
end

-- A CheckButton from the first template that exists (the client always has them; a plain button is the last resort).
local function addCheckButton(parent, templates, x, y)
    local button
    for _, template in ipairs(templates) do
        local created, made = pcall(CreateFrame, "CheckButton", nil, parent, template)
        if created and made then
            button = made
            break
        end
    end
    button = button or CreateFrame("CheckButton", nil, parent)
    button:SetSize(RADIO_SIZE, RADIO_SIZE)
    button:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    hideTemplateText(button)
    return button
end

local function addPushButton(parent, str, x, y, width, onClick)
    local created, button = pcall(CreateFrame, "Button", nil, parent, "UIPanelButtonTemplate")
    if not (created and button) then
        button = CreateFrame("Button", nil, parent)
        local caption = button:CreateFontString(nil, "ARTWORK", "GameFontNormal")
        caption:SetPoint("CENTER", button, "CENTER", 0, 0)
        caption:SetText(str)
    end
    button:SetSize(width, 22)
    button:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    pcall(button.SetText, button, str)
    button:SetScript("OnClick", function()
        pcall(onClick)
    end)
    return button
end

local function addSlider(parent, key, x, y)
    local low, high, step = ns.ranges[key][1], ns.ranges[key][2], ns.ranges[key][3]
    local created, slider = pcall(CreateFrame, "Slider", nil, parent, "OptionsSliderTemplate")
    if created and slider then
        for _, part in ipairs({ "Text", "Low", "High" }) do
            if slider[part] and slider[part].Hide then
                slider[part]:Hide()
            end
        end
    else
        slider = CreateFrame("Slider", nil, parent)
        slider:SetOrientation("HORIZONTAL")
        slider:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
        local track = slider:CreateTexture(nil, "BACKGROUND")
        track:SetColorTexture(0, 0, 0, 0.5)
        track:SetAllPoints(slider)
    end
    slider:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    slider:SetSize(SLIDER_W, 16)
    slider:SetMinMaxValues(low, high)
    slider:SetValueStep(step)
    if slider.SetObeyStepOnDrag then
        slider:SetObeyStepOnDrag(true)
    end
    local valueText = addText(parent, "GameFontNormal", "", VALUE_X, y + 1)
    slider:SetScript("OnValueChanged", function(_, value)
        value = OrbMath.Snap(value, low, high, step)
        if not value then
            return
        end
        valueText:SetText(string.format("%d px", value))
        if not refreshing then
            ns.db[key] = value
            syncOptionsPanel()
        end
    end)
    Setup.controls[key] = slider
    Setup.controls[key .. "_value"] = valueText
    return slider
end

local function closeWindow()
    if window then
        window:Hide()
    end
end

-- Pick XP bar: hide the window so the bar is clickable, arm the picker, and show the window again when picking ends
-- (click, right-click or timeout). The watcher's OnUpdate removes itself the moment the picker is no longer armed.
local function onPickWatch()
    if Target:IsPicking() then
        return
    end
    pickWatcher:SetScript("OnUpdate", nil)
    if window then
        window:Show()
        refreshWindow()
    end
end

local function startPick()
    if window then
        window:Hide()
    end
    pcall(ns.commands.pick, "")
    if not Target:IsPicking() then
        if window then
            window:Show()
            refreshWindow()
        end
        return
    end
    if not pickWatcher then
        pickWatcher = CreateFrame("Frame")
        Setup.pickWatcher = pickWatcher
    end
    pickWatcher:SetScript("OnUpdate", onPickWatch)
end

local function addBackground(frame)
    local styled = frame.SetBackdrop and pcall(frame.SetBackdrop, frame, BACKDROP)
    if styled then
        pcall(frame.SetBackdropColor, frame, 0.07, 0.07, 0.10, 0.95)
        pcall(frame.SetBackdropBorderColor, frame, 0.6, 0.6, 0.7, 1)
    else
        local fill = frame:CreateTexture(nil, "BACKGROUND")
        fill:SetAllPoints(frame)
        fill:SetColorTexture(0.07, 0.07, 0.10, 0.95)
    end
end

local function addShapeRadios(frame)
    for i, shape in ipairs(SHAPES) do
        local x = PAD + (i - 1) * RADIO_SPACING
        local radio = addCheckButton(frame, { "UIRadioButtonTemplate", "UICheckButtonTemplate" }, x - 2, -176)
        local caption = addText(frame, "GameFontHighlight", SHAPE_NAME[shape], x + 24, -180)
        local okWidth, width = pcall(caption.GetStringWidth, caption)
        if not (okWidth and type(width) == "number") then
            width = RADIO_SPACING - RADIO_SIZE
        end
        if radio.SetHitRectInsets then
            pcall(radio.SetHitRectInsets, radio, 0, -(width + 8), -4, -4)
        end
        radio:SetScript("OnClick", function()
            ns.db.glowShape = shape
            refreshWindow()
            syncOptionsPanel()
        end)
        Setup.controls["shape_" .. shape] = radio
    end
end

local function buildWindow()
    local created, frame = pcall(CreateFrame, "Frame", nil, UIParent, "BackdropTemplate")
    if not (created and frame) then
        frame = CreateFrame("Frame", nil, UIParent)
    end
    frame:SetSize(WINDOW_W, WINDOW_H)
    frame:SetPoint("CENTER", UIParent, "CENTER", 0, 120)
    frame:SetFrameStrata("DIALOG")
    frame:EnableMouse(true)
    frame:SetMovable(true)
    pcall(frame.SetClampedToScreen, frame, true)
    pcall(frame.RegisterForDrag, frame, "LeftButton")
    frame:SetScript("OnDragStart", function(self)
        pcall(self.StartMoving, self)
    end)
    frame:SetScript("OnDragStop", function(self)
        pcall(self.StopMovingOrSizing, self)
    end)
    addBackground(frame)

    addText(frame, "GameFontNormalLarge", "XP Orbs", PAD, -14)
    addText(frame, "GameFontHighlight", "Couldn't find your XP bar. Pick it so the orbs know where to fly.", PAD, -40,
        CONTENT_W)

    Setup.controls.pick = addPushButton(frame, "Pick XP bar", PAD, -80, 120, startPick)
    Setup.statusText = addText(frame, "GameFontHighlight", "", PAD, -108, CONTENT_W)
    Setup.statusText:SetTextColor(GREY, GREY, GREY)

    addText(frame, "GameFontNormal", "Glow shape", PAD, -150)
    addShapeRadios(frame)
    for _, offset in ipairs(OFFSETS) do
        addText(frame, "GameFontHighlight", offset.label, PAD, offset.y)
        addSlider(frame, offset.key, SLIDER_X, offset.y - 1)
    end

    Setup.controls.test = addPushButton(frame, "Test", PAD, -272, 100, function()
        ns.commands.test(TEST_PERCENT)
    end)
    local dismiss = addCheckButton(frame, { "UICheckButtonTemplate" }, PAD - 4, -298)
    dismiss:SetSize(24, 24)
    addText(frame, "GameFontHighlight", "Don't ask again", PAD + 22, -302)
    dismiss:SetScript("OnClick", function(self)
        if not refreshing then
            ns.db.setupDismissed = self:GetChecked() and true or false
        end
    end)
    Setup.controls.dismiss = dismiss
    Setup.controls.done = addPushButton(frame, "Done", WINDOW_W - PAD - 90, -298, 90, closeWindow)

    -- Esc closes it without needing a global frame name: keys pass through to the game except Escape
    pcall(frame.EnableKeyboard, frame, true)
    frame:SetScript("OnKeyDown", function(self, key)
        pcall(self.SetPropagateKeyboardInput, self, key ~= "ESCAPE")
    end)
    frame:SetScript("OnKeyUp", function(self, key)
        if key == "ESCAPE" then
            self:Hide()
        end
    end)
    frame:SetScript("OnShow", function()
        refreshWindow()
    end)
    return frame
end

-- Opens the window (building it the first time). Never throws; returns true when it is showing.
function Setup:Open()
    if not ns.db then
        return false
    end
    shownThisSession = true
    if not window then
        local built, frame = pcall(buildWindow)
        if not (built and frame) then
            ns:Log("SETUP_ERR %s", string.sub(tostring(frame), 1, 120))
            return false
        end
        window = frame
        Setup.window = frame
    end
    window:Show()
    refreshWindow()
    return true
end

function Setup:Close()
    closeWindow()
end

-- /xporbs setup: open it any time (ignores "Don't ask again").
function ns.commands.setup()
    if not Setup:Open() then
        ns.Print("setup: the window couldn't be opened")
    end
end

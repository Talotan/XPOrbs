-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- The /xporbs status window: the status report in a read-only box that opens with everything selected, so a player
-- presses Ctrl+C and pastes it into a bug report. Built like the copy window other Forever addons use (Blizzard's
-- ButtonFrameTemplate around a ScrollingEditBoxTemplate). A client missing either template gets the chat output.

local StatusWindow = {}
ns.StatusWindow = StatusWindow

local FRAME_NAME = "XPOrbsStatusFrame" -- named so UISpecialFrames can close it with Esc
local WIDTH, HEIGHT = 560, 460
local PAD = 8 -- inside the inset, around the text box
local HINT_H = 38 -- the hint under the text box: room for two lines of the normal-size font
local BAR_W, BAR_GAP = 8, 14 -- the scroll bar's width, and how far it pushes the text box's right edge in
local TITLE_H = 24 -- the strip you drag the window by
local CLOSE_W = 26 -- the close button's corner, left clear of the drag strip
local GREY = 0.7
local TITLE = "XP Orbs status"
local HINT = "The report is selected: press Ctrl+C to copy it, then paste it into your bug report."

local frame, box
local buildFailed = false
local currentText = ""

-- Esc closes the window by its name; added once, and only after the window built.
local function registerSpecialFrame()
    if type(UISpecialFrames) ~= "table" then
        return
    end
    for _, name in ipairs(UISpecialFrames) do
        if name == FRAME_NAME then
            return
        end
    end
    table.insert(UISpecialFrames, FRAME_NAME)
end

local function build()
    local f = CreateFrame("Frame", FRAME_NAME, UIParent, "ButtonFrameTemplate")
    f:Hide() -- a half-built window must never be left showing
    local made, scroll = pcall(CreateFrame, "Frame", nil, f, "ScrollingEditBoxTemplate")
    local editBox = made and scroll.GetEditBox and scroll:GetEditBox()
    if not (editBox and scroll.SetText) then
        error(made and "no usable text box" or scroll)
    end

    f:SetSize(WIDTH, HEIGHT)
    f:SetPoint("CENTER", UIParent, "CENTER", 0, 40)
    f:SetFrameStrata("DIALOG")
    f:EnableMouse(true)
    f:SetMovable(true)
    pcall(f.SetClampedToScreen, f, true)
    if ButtonFrameTemplate_HidePortrait then
        pcall(ButtonFrameTemplate_HidePortrait, f)
    end
    if ButtonFrameTemplate_HideButtonBar then
        pcall(ButtonFrameTemplate_HideButtonBar, f)
    end
    if ButtonFrameTemplate_HideAttic then
        pcall(ButtonFrameTemplate_HideAttic, f) -- moves the inset up under the title
    end
    if f.SetTitle then
        pcall(f.SetTitle, f, TITLE)
    elseif f.TitleText then
        f.TitleText:SetText(TITLE)
    end

    -- move it by the title strip (the close button's corner stays clickable)
    local bar = CreateFrame("Frame", nil, f)
    bar:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
    bar:SetPoint("TOPRIGHT", f, "TOPRIGHT", -CLOSE_W, 0)
    bar:SetHeight(TITLE_H)
    bar:EnableMouse(true)
    pcall(bar.RegisterForDrag, bar, "LeftButton")
    bar:SetScript("OnDragStart", function()
        pcall(f.StartMoving, f)
    end)
    bar:SetScript("OnDragStop", function()
        pcall(f.StopMovingOrSizing, f)
    end)

    -- the text fills the inset (the frame itself when a template lacks one), with the hint under it
    local inset = f.Inset or f
    local rightGap = PAD
    -- a scroll bar inside the inset's right edge, when this client has the pieces; without them the wheel still scrolls
    if ScrollUtil and ScrollUtil.RegisterScrollBoxWithScrollBar and scroll.GetScrollBox then
        local madeBar, scrollBar = pcall(CreateFrame, "EventFrame", nil, f, "MinimalScrollBar")
        if madeBar and scrollBar then
            scrollBar:SetPoint("TOPRIGHT", inset, "TOPRIGHT", -PAD / 2, -PAD)
            scrollBar:SetPoint("BOTTOMRIGHT", inset, "BOTTOMRIGHT", -PAD / 2, PAD + HINT_H)
            pcall(scrollBar.SetWidth, scrollBar, BAR_W)
            if pcall(ScrollUtil.RegisterScrollBoxWithScrollBar, scroll:GetScrollBox(), scrollBar) then
                rightGap = PAD + BAR_GAP
            else
                pcall(scrollBar.Hide, scrollBar)
            end
        end
    end
    scroll:SetPoint("TOPLEFT", inset, "TOPLEFT", PAD, -PAD)
    scroll:SetPoint("BOTTOMRIGHT", inset, "BOTTOMRIGHT", -rightGap, PAD + HINT_H)
    local hint = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    hint:SetPoint("BOTTOMLEFT", inset, "BOTTOMLEFT", PAD + 2, PAD)
    hint:SetWidth(WIDTH - 4 * PAD - 8)
    hint:SetJustifyH("LEFT")
    hint:SetWordWrap(true)
    hint:SetTextColor(GREY, GREY, GREY)
    hint:SetText(HINT)

    -- read-only: whatever the player types or pastes is put straight back, and the report stays selected for copying
    editBox:HookScript("OnTextChanged", function(_, userInput)
        if userInput then
            scroll:SetText(currentText)
            editBox:HighlightText()
        end
    end)
    editBox:HookScript("OnEditFocusGained", function()
        editBox:HighlightText()
    end)
    editBox:HookScript("OnMouseUp", function()
        editBox:HighlightText()
    end)

    registerSpecialFrame()
    frame, box = f, scroll
end

-- Opens the window with a fresh report (building it the first time), everything selected for copying. A client that
-- can't build it gets the report in chat. Returns true when the window is showing.
function StatusWindow:Show()
    if not frame and not buildFailed then
        local ok, err = pcall(build)
        if not ok then
            buildFailed = true
            ns:Log("STATUS_WINDOW_ERR %s", string.sub(tostring(err), 1, 120))
        end
    end
    if not frame then
        ns.commands.status("chat")
        return false
    end
    currentText = table.concat(ns.StatusLines(), "\n")
    box:SetText(currentText)
    frame:Show()
    -- focus and select a frame later: the box lays its text out first, and the selection needs that
    local function selectAll()
        if frame:IsShown() then
            local editBox = box:GetEditBox()
            editBox:SetFocus()
            editBox:HighlightText(0, #currentText)
        end
    end
    if C_Timer and C_Timer.After then
        C_Timer.After(0, selectAll)
    else
        selectAll()
    end
    return true
end

function StatusWindow:Hide()
    if frame then
        frame:Hide()
    end
end

function StatusWindow:Toggle()
    if frame and frame:IsShown() then
        self:Hide()
    else
        self:Show()
    end
end

-- exposed for tests
function StatusWindow:Frame()
    return frame
end

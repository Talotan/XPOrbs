-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Where non-kill XP comes from. Watches the events that travel with a quest turn-in or an exploration discovery and
-- hands the kill matcher a "source hint" (what the XP was, and the screen point its orbs should start from). The
-- matcher pairs the hint with the XP delta (logic/KillMatcher.lua). Read-only: only frame geometry and the cursor are
-- read, every foreign value through pcall and the secret-value guard. Never throws; no OnUpdate of its own.

local Sources = {}
ns.Sources = Sources

-- Origins as fractions of the screen (UIParent) width and height.
local QUEST_DEFAULT_X, QUEST_DEFAULT_Y = 0.30, 0.60 -- where the quest window usually is
local EXPLORE_DEFAULT_X, EXPLORE_DEFAULT_Y = 0.50, 0.75 -- top-centre, under where the zone name shows
local DIALOG_CACHE_TTL = 120 -- seconds a remembered quest-window centre stays usable
local DIALOG_OPEN_EXPECT = 30 -- seconds an open quest dialog makes a late hint plausible
-- named windows of known quest-dialog replacements, tried before Blizzard's QuestFrame
local FRAME_QUEST_REPLACEMENTS = { "DaylightUINpc" }
local ZONE_TEXT_FRAMES = { "SubZoneTextFrame", "ZoneTextFrame" } -- a discovery shows the subzone name first

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function num(v)
    return type(v) == "number" and readable(v)
end

local function screenSize()
    local okWidth, width = pcall(UIParent.GetWidth, UIParent)
    local okHeight, height = pcall(UIParent.GetHeight, UIParent)
    if okWidth and okHeight and num(width) and num(height) and width > 0 and height > 0 then
        return width, height
    end
    return nil, nil
end

-- A point at (fractionX, fractionY) of the screen, or nil, nil.
local function screenPoint(fractionX, fractionY)
    local width, height = screenSize()
    if width then
        return width * fractionX, height * fractionY
    end
    return nil, nil
end

local function isVisible(frame)
    if type(frame) ~= "table" or not readable(frame) then
        return false
    end
    local ok, visible = pcall(frame.IsVisible, frame)
    return ok and readable(visible) and visible == true
end

-- Centre of a frame in UIParent units, or nil, nil (not a frame, not visible, unreadable, or off the screen: a window
-- another addon parked out of sight must not become an origin).
local function visibleCentre(frame)
    if not isVisible(frame) then
        return nil, nil
    end
    local okCentre, centreX, centreY = pcall(frame.GetCenter, frame)
    local okFrameScale, frameScale = pcall(frame.GetEffectiveScale, frame)
    local okScale, parentScale = pcall(UIParent.GetEffectiveScale, UIParent)
    if not (okCentre and okFrameScale and okScale and num(centreX) and num(centreY) and num(frameScale)
        and num(parentScale) and parentScale > 0) then
        return nil, nil
    end
    local x, y = centreX * frameScale / parentScale, centreY * frameScale / parentScale
    local width, height = screenSize()
    if width and (x < 0 or y < 0 or x > width or y > height) then
        return nil, nil
    end
    return x, y
end

local function globalFrame(name)
    local frame = _G[name]
    return type(frame) == "table" and frame or nil
end

-- The frame under the cursor (GetMouseFoci on current clients, GetMouseFocus on older ones).
local function mouseFocus()
    if GetMouseFoci then
        local ok, list = pcall(GetMouseFoci)
        if ok and type(list) == "table" then
            return list[1]
        end
    end
    if GetMouseFocus then
        local ok, frame = pcall(GetMouseFocus)
        if ok then
            return frame
        end
    end
    return nil
end

-- Cursor position when the pointer is over a visible UI frame (not the 3D world): the player just clicked a button.
local function clickPoint()
    local focus = mouseFocus()
    if type(focus) ~= "table" or not readable(focus) or focus == _G.WorldFrame or focus == UIParent then
        return nil, nil
    end
    if not isVisible(focus) then
        return nil, nil
    end
    return ns.Mouseover.CursorPosition()
end

-- Quest window centre, remembered at QUEST_COMPLETE / QUEST_PROGRESS / QUEST_FINISHED (the window is gone by the time
-- the turn-in is paid). A known replacement window wins over Blizzard's QuestFrame, which such addons park out of
-- sight.
local dialogX, dialogY, dialogTime

local function readDialogCentre()
    for _, name in ipairs(FRAME_QUEST_REPLACEMENTS) do
        local x, y = visibleCentre(globalFrame(name))
        if x then
            return x, y
        end
    end
    return visibleCentre(globalFrame("QuestFrame"))
end

local function cacheDialog()
    local x, y = readDialogCentre()
    if x then
        dialogX, dialogY, dialogTime = x, y, GetTime()
    end
end

local function cachedDialogCentre()
    if dialogX and GetTime() - dialogTime <= DIALOG_CACHE_TTL then
        return dialogX, dialogY
    end
    return nil, nil
end

-- Origin for a quest turn-in: where the player clicked, else the quest window, else the usual quest window spot.
function Sources.QuestOrigin()
    local x, y = clickPoint()
    if x then
        return x, y, "cursor"
    end
    x, y = readDialogCentre()
    if not x then
        x, y = cachedDialogCentre()
    end
    if x then
        return x, y, "questwindow"
    end
    x, y = screenPoint(QUEST_DEFAULT_X, QUEST_DEFAULT_Y)
    return x, y, "questdefault"
end

-- Origin for an exploration discovery: the zone name on screen, else top-centre. Read when the XP lands, not when the
-- chat line arrives (the banner may be fading in).
function Sources.ExploreOrigin()
    for _, name in ipairs(ZONE_TEXT_FRAMES) do
        local x, y = visibleCentre(globalFrame(name))
        if x then
            return x, y, "zonetext"
        end
    end
    local x, y = screenPoint(EXPLORE_DEFAULT_X, EXPLORE_DEFAULT_Y)
    return x, y, "exploredefault"
end

local function matcher()
    return ns.Kills and ns.Kills.matcher
end

local exploreReader -- msg -> XP amount, built from the client's ERR_ZONE_EXPLORED_XP once it exists

local handlers = {}

function handlers.QUEST_COMPLETE()
    cacheDialog()
    local quests = matcher()
    if quests then
        quests:ExpectSource(DIALOG_OPEN_EXPECT)
    end
end

handlers.QUEST_PROGRESS = handlers.QUEST_COMPLETE

function handlers.QUEST_FINISHED()
    cacheDialog()
end

-- QUEST_TURNED_IN(questID, xpReward, moneyReward). The reward is the XP amount to look for; unreadable or zero means
-- "the nearest XP delta".
function handlers.QUEST_TURNED_IN(_, xpReward)
    local quests = matcher()
    if not quests then
        return
    end
    local amount = num(xpReward) and xpReward > 0 and xpReward or nil
    local x, y, label = Sources.QuestOrigin()
    quests:AddSourceHint({ source = "quest", amount = amount, x = x, y = y, label = label })
    ns.Kills:EnsurePoll()
end

function handlers.CHAT_MSG_SYSTEM(msg)
    if type(msg) ~= "string" or not readable(msg) then
        return
    end
    if not exploreReader and type(_G.ERR_ZONE_EXPLORED_XP) == "string" then
        exploreReader = ns.XPParse.AmountReader(_G.ERR_ZONE_EXPLORED_XP)
    end
    local amount = exploreReader and exploreReader(msg)
    local quests = matcher()
    if not (amount and quests) then
        return
    end
    quests:AddSourceHint({ source = "explore", amount = amount, locate = Sources.ExploreOrigin })
    ns.Kills:EnsurePoll()
end

local frame = CreateFrame("Frame")
Sources.frame = frame
Sources.registered = {}
for event in pairs({
    QUEST_TURNED_IN = true,
    QUEST_COMPLETE = true,
    QUEST_PROGRESS = true,
    QUEST_FINISHED = true,
    CHAT_MSG_SYSTEM = true,
}) do
    Sources.registered[event] = pcall(frame.RegisterEvent, frame, event) and true or false
end
frame:SetScript("OnEvent", function(_, event, ...)
    local fn = handlers[event]
    if not fn then
        return
    end
    local ok, err = pcall(fn, ...)
    if not ok then
        ns:Log("Sources error %s: %s", tostring(event), tostring(err))
    end
end)

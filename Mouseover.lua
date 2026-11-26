-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Mouseover sampler: while the cursor is over a hostile unit it remembers (GUID -> cursor position), which is the best
-- on-screen clue we get to where a mob is (plates can't be measured). Kills ask for an estimate when a mob dies.
-- Separate from Plates.lua because it is about the cursor, not nameplates, and owns the shared MobEstimate instance.
-- The OnUpdate poll exists only while a unit is moused over. Never throws, never logs a GUID.

local Mouseover = {}
ns.Mouseover = Mouseover

local POLL_INTERVAL = 0.1

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local mobEstimate = ns.MobEstimate.New({ now = GetTime })
Mouseover.est = mobEstimate

local function num(v)
    return type(v) == "number" and readable(v)
end

-- Cursor position in UIParent units, or nil, nil.
local function cursor()
    local okCursor, cursorX, cursorY = pcall(GetCursorPosition)
    local okScale, scale = pcall(UIParent.GetEffectiveScale, UIParent)
    if okCursor and okScale and num(cursorX) and num(cursorY) and num(scale) and scale > 0 then
        return cursorX / scale, cursorY / scale
    end
    return nil, nil
end

Mouseover.CursorPosition = cursor -- shared with Sources.lua (where a quest turn-in was clicked)

local function screen()
    local okWidth, width = pcall(UIParent.GetWidth, UIParent)
    local okHeight, height = pcall(UIParent.GetHeight, UIParent)
    if okWidth and okHeight and num(width) and num(height) and width > 0 and height > 0 then
        return width, height
    end
    return nil, nil
end

local function mouseoverExists()
    local ok, exists = pcall(UnitExists, "mouseover")
    return ok and readable(exists) and exists and true or false
end

-- One sample attempt. Returns whether a unit is moused over (the sample itself is skipped when the GUID is secret or
-- the unit is not hostile).
local function takeSample()
    if not mouseoverExists() then
        return false
    end
    local okGuid, guid = pcall(UnitGUID, "mouseover")
    if not (okGuid and readable(guid) and type(guid) == "string") then
        return true
    end
    local okCanAttack, canAttack = pcall(UnitCanAttack, "player", "mouseover")
    if not (okCanAttack and readable(canAttack) and canAttack == true) then
        return true
    end
    local cursorX, cursorY = cursor()
    if cursorX then
        mobEstimate:AddSample(guid, cursorX, cursorY)
    end
    return true
end

local frame = CreateFrame("Frame")
Mouseover.frame = frame
local pollElapsed = 0

local function onPoll(_, elapsed)
    pollElapsed = pollElapsed + (elapsed or 0)
    if pollElapsed < POLL_INTERVAL then
        return
    end
    pollElapsed = 0
    local ok, exists = pcall(takeSample)
    if not (ok and exists) then
        frame:SetScript("OnUpdate", nil)
    end
end

function Mouseover:PollActive()
    return frame:GetScript("OnUpdate") ~= nil
end

-- (x, y, source, weight) for the mob with this guid (nil = unknown) right now. Never throws; x is nil only when the
-- screen size is unavailable.
function Mouseover:Estimate(guid)
    local okScreen, screenW, screenH = pcall(screen)
    if not okScreen then
        return nil, nil, "default", 0
    end
    local okCursor, cursorX, cursorY = pcall(cursor)
    if not okCursor then
        cursorX, cursorY = nil, nil
    end
    -- the zoom anchor puts orbs on the body, so the hovered point needs no lift towards the plate; only when the zoom
    -- is readable (Orbs.lua's zoomAnchorY otherwise leaves the frames at the head)
    local lift = ns.db and ns.db.zoomAnchor and ns.Orbs.ReadZoom() ~= nil and ns.MobEstimate.BODY_OFFSET or nil
    local ok, x, y, source, weight =
        pcall(mobEstimate.Estimate, mobEstimate, guid, cursorX, cursorY, screenW, screenH, lift)
    if not ok then
        return nil, nil, "default", 0
    end
    return x, y, source, weight
end

Mouseover.registered = pcall(frame.RegisterEvent, frame, "UPDATE_MOUSEOVER_UNIT") and true or false
frame:SetScript("OnEvent", function(_, event)
    if event ~= "UPDATE_MOUSEOVER_UNIT" then
        return
    end
    local ok, exists = pcall(takeSample)
    if not ok then
        ns:Log("Mouseover error %s", tostring(exists))
        exists = false
    end
    if exists then
        if not frame:GetScript("OnUpdate") then
            pollElapsed = 0
            frame:SetScript("OnUpdate", onPoll)
        end
    elseif frame:GetScript("OnUpdate") then
        frame:SetScript("OnUpdate", nil)
    end
end)

table.insert(ns.statusProviders, function()
    return string.format("mouseover: samples=%d event=%s poll=%s", mobEstimate:Count(),
        Mouseover.registered and "yes" or "no", Mouseover:PollActive() and "active" or "idle")
end)

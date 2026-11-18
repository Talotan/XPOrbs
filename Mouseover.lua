-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

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

local est = ns.MobEstimate.New({ now = GetTime })
Mouseover.est = est

local function num(v)
    return type(v) == "number" and readable(v)
end

-- Cursor position in UIParent units, or nil, nil.
local function cursor()
    local okc, cx, cy = pcall(GetCursorPosition)
    local oks, sc = pcall(UIParent.GetEffectiveScale, UIParent)
    if okc and oks and num(cx) and num(cy) and num(sc) and sc > 0 then
        return cx / sc, cy / sc
    end
    return nil, nil
end

local function screen()
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    local okh, h = pcall(UIParent.GetHeight, UIParent)
    if okw and okh and num(w) and num(h) and w > 0 and h > 0 then
        return w, h
    end
    return nil, nil
end

local function mouseoverExists()
    local ok, e = pcall(UnitExists, "mouseover")
    return ok and readable(e) and e and true or false
end

-- One sample attempt. Returns whether a unit is moused over (the sample itself is skipped when the GUID is secret or
-- the unit is not hostile).
local function takeSample()
    if not mouseoverExists() then
        return false
    end
    local okG, guid = pcall(UnitGUID, "mouseover")
    if not (okG and readable(guid) and type(guid) == "string") then
        return true
    end
    local okA, canAttack = pcall(UnitCanAttack, "player", "mouseover")
    if not (okA and readable(canAttack) and canAttack == true) then
        return true
    end
    local cx, cy = cursor()
    if cx then
        est:AddSample(guid, cx, cy)
    end
    return true
end

local frame = CreateFrame("Frame")
Mouseover.frame = frame
local acc = 0

local function onPoll(_, elapsed)
    acc = acc + (elapsed or 0)
    if acc < POLL_INTERVAL then
        return
    end
    acc = 0
    local ok, exists = pcall(takeSample)
    if not (ok and exists) then
        frame:SetScript("OnUpdate", nil)
    end
end

function Mouseover:PollActive()
    return frame:GetScript("OnUpdate") ~= nil
end

-- (x, y, source, w_m) for the mob with this guid (nil = unknown) right now. Never throws; x is nil only when the
-- screen size is unavailable.
function Mouseover:Estimate(guid)
    local okS, w, h = pcall(screen)
    if not okS then
        return nil, nil, "default", 0
    end
    local okC, cx, cy = pcall(cursor)
    if not okC then
        cx, cy = nil, nil
    end
    -- the zoom anchor puts orbs on the body, so the hovered point needs no lift towards the plate
    local lift = ns.db and ns.db.zoomAnchor and ns.MobEstimate.BODY_OFFSET or nil
    local ok, x, y, source, wm = pcall(est.Estimate, est, guid, cx, cy, w, h, lift)
    if not ok then
        return nil, nil, "default", 0
    end
    return x, y, source, wm
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
            acc = 0
            frame:SetScript("OnUpdate", onPoll)
        end
    elseif frame:GetScript("OnUpdate") then
        frame:SetScript("OnUpdate", nil)
    end
end)

table.insert(ns.statusProviders, function()
    return string.format("mouseover: samples=%d event=%s poll=%s", est:Count(), Mouseover.registered and "yes" or "no",
        Mouseover:PollActive() and "active" or "idle")
end)

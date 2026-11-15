-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Nameplate tracker. Remembers which hostile plates exist (unit token -> GUID, name, hostile) so a kill can be
-- matched to its plate after the plate is gone, and keeps the plate frame as an anchor parent for Orbs.lua.
-- Nameplates are restricted regions on Forever: NOTHING here (or anywhere else) may measure one. Every read of a
-- unit/GUID/name goes through readable() + pcall; it never throws.

local Plates = {}
ns.Plates = Plates

local RETRY_INTERVAL = 0.25 -- how often a hostile plate with an unreadable GUID is asked again
local HELD_TTL = 2.0

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local entries = {} -- unit token -> entry { unit, plate, guid, name, hostile }
local held = {} -- array of removed entries, each with .expires

Plates.entries = entries
Plates.held = held
Plates.onRemoved = nil -- Kills.lua hook: function(entry)

local function readString(fn, unit)
    local ok, v = pcall(fn, unit)
    if ok and readable(v) and type(v) == "string" then
        return v
    end
    return nil
end

local function prune()
    local now = GetTime()
    local i = 1
    while i <= #held do
        if now >= held[i].expires then
            table.remove(held, i)
        else
            i = i + 1
        end
    end
end

local retry = CreateFrame("Frame")
Plates.retryFrame = retry
local acc = 0

local onRetry

-- GUIDs can become readable once combat ends, so a hostile plate without one is asked again until it has one.
local function needsRetry()
    for _, e in pairs(entries) do
        if e.hostile and e.guid == nil then
            return true
        end
    end
    return false
end

function onRetry(_, elapsed)
    acc = acc + (elapsed or 0)
    if acc < RETRY_INTERVAL then
        return
    end
    acc = 0
    for _, e in pairs(entries) do
        if e.hostile and e.guid == nil then
            e.guid = readString(UnitGUID, e.unit)
            if not e.plate and C_NamePlate and C_NamePlate.GetNamePlateForUnit then
                local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, e.unit) -- the plate can arrive late
                if ok and p and readable(p) then
                    e.plate = p
                end
            end
        end
    end
    if not needsRetry() then
        retry:SetScript("OnUpdate", nil)
    end
end

local function updateRetry()
    if needsRetry() then
        if not retry:GetScript("OnUpdate") then
            acc = 0
            retry:SetScript("OnUpdate", onRetry)
        end
    elseif retry:GetScript("OnUpdate") then
        retry:SetScript("OnUpdate", nil)
    end
end

function Plates:RetryActive()
    return retry:GetScript("OnUpdate") ~= nil
end

function Plates:TrackedCount()
    local n = 0
    for _ in pairs(entries) do
        n = n + 1
    end
    return n
end

function Plates:HeldCount()
    prune()
    return #held
end

local function onAdded(unit)
    if type(unit) ~= "string" then
        return
    end
    local plate
    if C_NamePlate and C_NamePlate.GetNamePlateForUnit then
        local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, unit)
        if ok and readable(p) then
            plate = p
        end
    end
    local hostile = true -- unknown counts as hostile
    local okH, canAttack = pcall(UnitCanAttack, "player", unit)
    if okH and readable(canAttack) then
        hostile = canAttack and true or false
    end
    if plate and ns.Orbs and ns.Orbs.PlateReused then
        local okR, errR = pcall(ns.Orbs.PlateReused, ns.Orbs, plate)
        if not okR then
            ns:Log("PlateReused error %s", tostring(errR))
        end
    end
    local entry = {
        unit = unit,
        plate = plate,
        guid = readString(UnitGUID, unit),
        name = readString(UnitName, unit),
        hostile = hostile,
    }
    entries[unit] = entry
    ns:Log("PLATE_ADDED hostile=%s guidReadable=%s nameReadable=%s", tostring(hostile), tostring(entry.guid ~= nil),
        tostring(entry.name ~= nil))
    prune()
    updateRetry()
end

local function onRemoved(unit)
    local entry = entries[unit]
    if not entry then
        return
    end
    entries[unit] = nil
    local dead, deadKnown = false, false
    local ok1, isDead = pcall(UnitIsDead, unit)
    if ok1 and readable(isDead) and type(isDead) == "boolean" then
        deadKnown = true
        dead = isDead
    end
    if not dead then
        local ok2, hp = pcall(UnitHealth, unit)
        if ok2 and readable(hp) and type(hp) == "number" then
            deadKnown = true
            dead = hp == 0
        end
    end
    entry.deadAtRemoval = dead
    entry.deadKnown = deadKnown
    entry.held = true
    entry.expires = GetTime() + HELD_TTL
    held[#held + 1] = entry
    ns:Log("PLATE_REMOVED deadReadable=%s deadAtRemoval=%s hostile=%s", tostring(deadKnown), tostring(dead),
        tostring(entry.hostile))
    prune()
    updateRetry()
    if Plates.onRemoved then
        local ok, err = pcall(Plates.onRemoved, entry)
        if not ok then
            ns:Log("onRemoved error %s", tostring(err))
        end
    end
end

-- guid must be readable. Searches live plates, then recently removed ones (not expired).
function Plates:FindByGUID(guid)
    if not readable(guid) or type(guid) ~= "string" then
        return nil
    end
    for _, e in pairs(entries) do
        if e.guid ~= nil and e.guid == guid then
            return e
        end
    end
    prune()
    for _, e in ipairs(held) do
        if e.guid ~= nil and e.guid == guid then
            return e
        end
    end
    return nil
end

local events = CreateFrame("Frame")
Plates.eventFrame = events
events:RegisterEvent("NAME_PLATE_UNIT_ADDED")
events:RegisterEvent("NAME_PLATE_UNIT_REMOVED")
events:SetScript("OnEvent", function(_, event, unit)
    local ok, err = pcall(function()
        if event == "NAME_PLATE_UNIT_ADDED" then
            onAdded(unit)
        elseif event == "NAME_PLATE_UNIT_REMOVED" then
            onRemoved(unit)
        end
    end)
    if not ok then
        ns:Log("Plates error %s: %s", tostring(event), tostring(err))
    end
end)

table.insert(ns.statusProviders, function()
    return string.format("plates: tracked=%d held=%d retry=%s", Plates:TrackedCount(), Plates:HeldCount(),
        Plates:RetryActive() and "active" or "idle")
end)

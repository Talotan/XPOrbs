-- M3 stub extensions: nameplates, unit APIs, secret values, OnUpdate driver. Load after wowstub.lua, before the addon.
local ns = ...
local stub = ns.stub

stub.SECRET = { secret = true } -- sentinel: issecretvalue(SECRET) is true
stub.secretAll = false -- when true every value reads as secret
stub.units = {} -- unit token -> { guid, name, dead, hp, canAttack, exists, isTarget }
stub.plates = {} -- unit token -> plate frame
stub.failEvents = {} -- event name -> true makes RegisterEvent raise

function issecretvalue(v)
    return stub.secretAll or rawequal(v, stub.SECRET)
end

-- Camera zoom: stub.zoom is what GetCameraZoom returns (a number, or stub.SECRET to emulate a secret value). Tests
-- make the API absent with _G.GetCameraZoom = nil or make it raise with stub.zoomError = true.
stub.zoom = 15
function GetCameraZoom()
    if stub.zoomError then
        error("GetCameraZoom unavailable")
    end
    return stub.zoom
end

local frameMethods = getmetatable(UIParent)
local baseRegister = frameMethods.RegisterEvent
function frameMethods:RegisterEvent(event)
    if stub.failEvents[event] then
        error("event not allowed: " .. tostring(event))
    end
    return baseRegister(self, event)
end
function frameMethods:GetHeight()
    return self.height
end
UIParent:SetSize(1920, 1080)

C_NamePlate = {
    GetNamePlateForUnit = function(unit)
        return stub.plates[unit]
    end,
    GetNamePlates = function()
        local out = {}
        for _, p in pairs(stub.plates) do
            out[#out + 1] = p
        end
        return out
    end,
}

local function field(unit, key, default)
    local u = stub.units[unit]
    if u == nil or u[key] == nil then
        return default
    end
    return u[key]
end

function UnitGUID(unit)
    return field(unit, "guid", nil)
end
function UnitName(unit)
    return field(unit, "name", nil)
end
function UnitIsDead(unit)
    return field(unit, "dead", false)
end
function UnitHealth(unit)
    return field(unit, "hp", 100)
end
function UnitCanAttack(_, unit)
    return field(unit, "canAttack", true)
end
-- Threat on a unit: units[unit].threat = a number 0..3, stub.SECRET, or nil (not on the threat list).
function UnitThreatSituation(_, unit)
    return field(unit, "threat", nil)
end
-- PlaySoundFile records every call in stub.sounds ({ path, channel }). stub.soundMode: nil = plays, "false" = the
-- client says it won't play (returns false), "error" = raises.
stub.sounds = {}
function PlaySoundFile(path, channel)
    stub.sounds[#stub.sounds + 1] = { path, channel }
    if stub.soundMode == "error" then
        error("PlaySoundFile unavailable")
    end
    return stub.soundMode ~= "false", 1
end
function UnitExists(unit)
    return field(unit, "exists", true)
end
function UnitIsUnit(a, b)
    if a == "target" then
        return field(b, "isTarget", false)
    end
    return a == b
end

-- Create a plate + unit and fire NAME_PLATE_UNIT_ADDED. opts: guid, name, cx, cy, scale, canAttack.
function stub.addPlate(unit, opts)
    opts = opts or {}
    local plate = CreateFrame("Frame")
    plate.cx, plate.cy, plate.scale = opts.cx or 960, opts.cy or 540, opts.scale or 1
    stub.plates[unit] = plate
    stub.units[unit] = {
        guid = opts.guid,
        name = opts.name,
        canAttack = opts.canAttack ~= false,
        dead = false,
        hp = 100,
        isTarget = opts.isTarget or false,
    }
    ns.fire("NAME_PLATE_UNIT_ADDED", unit)
    return plate
end

-- Fire NAME_PLATE_UNIT_REMOVED; dead=true marks the unit dead first.
function stub.removePlate(unit, dead)
    if dead ~= nil then
        stub.units[unit].dead = dead
        stub.units[unit].hp = dead and 0 or 100
    end
    ns.fire("NAME_PLATE_UNIT_REMOVED", unit)
end

-- Advance time by dt and run every frame's OnUpdate with dt.
function stub.tick(dt)
    stub.time = stub.time + dt
    local snapshot = {}
    for i, f in ipairs(stub.frames) do
        snapshot[i] = f
    end
    for _, f in ipairs(snapshot) do
        local fn = f.scripts.OnUpdate
        if fn then
            fn(f, dt)
        end
    end
end

-- Number of frames that currently have an OnUpdate script.
function stub.updaters()
    local n = 0
    for _, f in ipairs(stub.frames) do
        if f.scripts.OnUpdate then
            n = n + 1
        end
    end
    return n
end

-- Set stub XP and fire PLAYER_XP_UPDATE.
function stub.setXP(xp, xpMax)
    stub.xp = xp
    if xpMax then
        stub.xpMax = xpMax
    end
    ns.fire("PLAYER_XP_UPDATE", "player")
end

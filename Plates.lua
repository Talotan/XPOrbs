local ADDON, ns = ...

-- Nameplate tracker. Remembers where hostile plates were (UIParent coordinates) so a kill can be located after
-- the plate is gone. Every read of a unit/GUID/name/geometry goes through readable() + pcall; it never throws.

local Plates = {}
ns.Plates = Plates

local SAMPLE_INTERVAL = 1 / 30
local HELD_TTL = 2.0

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local entries = {} -- unit token -> entry
local held = {} -- array of removed entries, each with .expires
-- okGeom/secretGeom: samples stored / rejected as secret. The rest count why a sample failed, per method
-- (A = the plate's own GetCenter, B = our proxy frame anchored to the plate).
local stats = {
    secretGeom = 0,
    okGeom = 0,
    okA = 0,
    okB = 0,
    noPlate = 0,
    forbidden = 0,
    errA = 0,
    errB = 0,
    nilA = 0,
    nilB = 0,
}
local loggedErr = {} -- method -> true once its first error message has been logged
local lastTarget -- { x, y, t }
local targetUnit -- unit token of the plate that is our target (best effort)

Plates.stats = stats
Plates.entries = entries
Plates.held = held
Plates.onRemoved = nil -- Kills.lua hook: function(entry)

local function log(...)
    ns:Log(...)
end

local function readString(fn, unit)
    local ok, v = pcall(fn, unit)
    if ok and readable(v) and type(v) == "string" then
        return v
    end
    return nil
end

-- Pool of 1x1 proxy frames (children of UIParent) anchored to plates, read when the plate itself can't be measured.
local proxyPool = {}

local function acquireProxy(entry, plate)
    if entry.proxy then
        return entry.proxy
    end
    local f = table.remove(proxyPool)
    if not f then
        local ok, nf = pcall(CreateFrame, "Frame", nil, UIParent)
        if not ok or not nf then
            return nil
        end
        f = nf
        pcall(f.SetSize, f, 1, 1)
    end
    local ok = pcall(function()
        f:ClearAllPoints()
        f:SetPoint("CENTER", plate, "CENTER", 0, 0)
        f:Show()
    end)
    if not ok then
        proxyPool[#proxyPool + 1] = f
        return nil
    end
    entry.proxy = f
    return f
end

local function releaseProxy(entry)
    local f = entry.proxy
    if not f then
        return
    end
    entry.proxy = nil
    pcall(function()
        f:ClearAllPoints()
        f:Hide()
    end)
    proxyPool[#proxyPool + 1] = f
end

local function noteErr(method, err)
    stats["err" .. method] = stats["err" .. method] + 1
    if not loggedErr[method] then
        loggedErr[method] = true
        ns:Log("GEOM_ERR method=%s err=%s", method, tostring(err))
    end
end

-- Measures one region: returns x, y in UIParent space, or nil plus a reason ("err", "secret", "nil").
local function measure(region, method)
    local ok, cx, cy = pcall(region.GetCenter, region)
    if not ok then
        noteErr(method, cx)
        return nil, "err"
    end
    if not readable(cx) or not readable(cy) then
        return nil, "secret"
    end
    if type(cx) ~= "number" or type(cy) ~= "number" then
        stats["nil" .. method] = stats["nil" .. method] + 1
        return nil, "nil"
    end
    local ok2, scale = pcall(region.GetEffectiveScale, region)
    local ok3, pscale = pcall(UIParent.GetEffectiveScale, UIParent)
    if not (ok2 and ok3) then
        noteErr(method, ok2 and pscale or scale)
        return nil, "err"
    end
    if not readable(scale) or not readable(pscale) then
        return nil, "secret"
    end
    if type(scale) ~= "number" or type(pscale) ~= "number" or pscale == 0 then
        stats["nil" .. method] = stats["nil" .. method] + 1
        return nil, "nil"
    end
    local x, y = ns.OrbMath.ToUIParent(cx, cy, scale, pscale)
    return x, y
end

local function isForbidden(plate)
    if not plate.IsForbidden then
        return false
    end
    local ok, forbidden = pcall(plate.IsForbidden, plate)
    return not ok or (readable(forbidden) and forbidden == true)
end

-- Reads the plate centre into entry.x/y (UIParent space). Returns true when a readable sample was stored.
local function sample(entry)
    local plate = entry.plate
    if not plate and entry.unit and not entry.held and C_NamePlate and C_NamePlate.GetNamePlateForUnit then
        local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, entry.unit) -- the plate can arrive late
        if ok and p and readable(p) then
            plate = p
            entry.plate = p
        end
    end
    if not plate then
        stats.noPlate = stats.noPlate + 1
        return false
    end
    if isForbidden(plate) then
        stats.forbidden = stats.forbidden + 1
        return false
    end
    local x, y = measure(plate, "A")
    local why = y
    if x then
        stats.okA = stats.okA + 1
    elseif why ~= "secret" then
        -- The proxy dodges measurement restrictions; a secret plate position would propagate to it anyway.
        local proxy = acquireProxy(entry, plate)
        if proxy then
            x, y = measure(proxy, "B")
            if x then
                stats.okB = stats.okB + 1
            elseif y == "secret" then
                why = "secret"
            end
        end
    end
    if not x then
        if why == "secret" then
            stats.secretGeom = stats.secretGeom + 1
        end
        return false
    end
    entry.x, entry.y = x, y
    entry.t = GetTime()
    stats.okGeom = stats.okGeom + 1
    if entry.unit == targetUnit then
        lastTarget = { x = entry.x, y = entry.y, t = entry.t }
    end
    return true
end

local function hostileCount()
    local n = 0
    for _, e in pairs(entries) do
        if e.hostile then
            n = n + 1
        end
    end
    return n
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

local sampler = CreateFrame("Frame")
Plates.samplerFrame = sampler
local acc = 0

local function onSample(_, elapsed)
    acc = acc + (elapsed or 0)
    if acc < SAMPLE_INTERVAL then
        return
    end
    acc = 0
    for _, e in pairs(entries) do
        if e.hostile then
            sample(e)
            if e.guid == nil then
                e.guid = readString(UnitGUID, e.unit) -- GUIDs can become readable once combat ends
            end
        end
    end
end

local function updateSampler()
    if hostileCount() > 0 then
        if not sampler:GetScript("OnUpdate") then
            acc = 0
            sampler:SetScript("OnUpdate", onSample)
        end
    elseif sampler:GetScript("OnUpdate") then
        sampler:SetScript("OnUpdate", nil)
    end
end

function Plates:SamplerActive()
    return sampler:GetScript("OnUpdate") ~= nil
end

function Plates:Sample(entry)
    return sample(entry)
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
    local hostile = true -- unknown counts as hostile: sampling a friendly plate is harmless
    local okH, canAttack = pcall(UnitCanAttack, "player", unit)
    if okH and readable(canAttack) then
        hostile = canAttack and true or false
    end
    local entry = {
        unit = unit,
        plate = plate,
        guid = readString(UnitGUID, unit),
        name = readString(UnitName, unit),
        hostile = hostile,
    }
    entries[unit] = entry
    sample(entry)
    ns:Log("PLATE_ADDED hostile=%s guidReadable=%s nameReadable=%s hadPos=%s", tostring(hostile),
        tostring(entry.guid ~= nil), tostring(entry.name ~= nil), tostring(entry.x ~= nil))
    prune()
    updateSampler()
end

local function onRemoved(unit)
    local entry = entries[unit]
    if not entry then
        return
    end
    entries[unit] = nil
    sample(entry) -- final sample; the plate may already be invalid, which is fine
    releaseProxy(entry)
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
    if unit == targetUnit then
        targetUnit = nil
    end
    ns:Log("PLATE_REMOVED deadReadable=%s deadAtRemoval=%s hadPos=%s hostile=%s geomOK=%d geomSecret=%d",
        tostring(deadKnown), tostring(dead), tostring(entry.x ~= nil), tostring(entry.hostile), stats.okGeom,
        stats.secretGeom)
    ns:Log("GEOM okA=%d okB=%d noPlate=%d forbidden=%d errA=%d errB=%d nilA=%d nilB=%d", stats.okA, stats.okB,
        stats.noPlate, stats.forbidden, stats.errA, stats.errB, stats.nilA, stats.nilB)
    prune()
    updateSampler()
    if Plates.onRemoved then
        local ok, err = pcall(Plates.onRemoved, entry)
        if not ok then
            ns:Log("onRemoved error %s", tostring(err))
        end
    end
end

local function unitIsTarget(unit)
    local ok, same = pcall(UnitIsUnit, "target", unit)
    return ok and readable(same) and same == true
end

local function onTargetChanged()
    targetUnit = nil
    for unit, e in pairs(entries) do
        if unitIsTarget(unit) then
            targetUnit = unit
            sample(e)
            if e.x then
                lastTarget = { x = e.x, y = e.y, t = e.t }
            end
            break
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

-- { x, y } of the current target (live plate, else the cached last target position), or nil.
function Plates:TargetEntry()
    for unit, e in pairs(entries) do
        if unitIsTarget(unit) then
            sample(e)
            if type(e.x) == "number" and type(e.y) == "number" then
                targetUnit = unit
                lastTarget = { x = e.x, y = e.y, t = e.t }
                return { x = e.x, y = e.y, unit = unit }
            end
        end
    end
    if lastTarget and type(lastTarget.x) == "number" and type(lastTarget.y) == "number" then
        return { x = lastTarget.x, y = lastTarget.y }
    end
    return nil
end

local events = CreateFrame("Frame")
Plates.eventFrame = events
events:RegisterEvent("NAME_PLATE_UNIT_ADDED")
events:RegisterEvent("NAME_PLATE_UNIT_REMOVED")
events:RegisterEvent("PLAYER_TARGET_CHANGED")
events:SetScript("OnEvent", function(_, event, unit)
    local ok, err = pcall(function()
        if event == "NAME_PLATE_UNIT_ADDED" then
            onAdded(unit)
        elseif event == "NAME_PLATE_UNIT_REMOVED" then
            onRemoved(unit)
        elseif event == "PLAYER_TARGET_CHANGED" then
            onTargetChanged()
        end
    end)
    if not ok then
        ns:Log("Plates error %s: %s", tostring(event), tostring(err))
    end
end)

table.insert(ns.statusProviders, function()
    return string.format("plates: tracked=%d held=%d secretGeom=%d okGeom=%d sampler=%s", Plates:TrackedCount(),
        Plates:HeldCount(), stats.secretGeom, stats.okGeom, Plates:SamplerActive() and "active" or "idle")
end)
table.insert(ns.statusProviders, function()
    return string.format("geom: okA=%d okB=%d noPlate=%d forbidden=%d errA=%d errB=%d nilA=%d nilB=%d", stats.okA,
        stats.okB, stats.noPlate, stats.forbidden, stats.errA, stats.errB, stats.nilA, stats.nilB)
end)

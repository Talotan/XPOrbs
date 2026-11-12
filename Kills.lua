local ADDON, ns = ...

-- Kill pipeline: wires UNIT_DIED / plate removal / chat XP / XP deltas into one KillMatcher and turns its bursts into
-- ns.Orbs:Burst calls. With db.probe on (M3 default) bursts are only logged. Never throws.

local Kills = {}
ns.Kills = Kills

local AMOUNT_WINDOW = 1.0 -- chat amount and PLAYER_XP_UPDATE delta are compared when within this many seconds

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local Plates = ns.Plates
local OrbMath = ns.OrbMath
local matcher = ns.KillMatcher.New({ now = GetTime })
local parser = ns.XPParse.Build(_G)
Kills.matcher = matcher

local xpCache = { xp = nil, max = nil }
local leveled = false
local unitDiedRegistered = false
local pendingChat, pendingDelta -- { amount, t, kind } awaiting their counterpart for AMOUNTCHECK
local lastDropped = 0

local function log(...)
    ns:Log(...)
end

local function isProbe()
    local db = ns.db
    return db == nil or db.probe
end

local function num(v)
    if readable(v) and type(v) == "number" then
        return v
    end
    return nil
end

local function refreshXP()
    local okx, xp = pcall(UnitXP, "player")
    local okm, mx = pcall(UnitXPMax, "player")
    if okx and num(xp) then
        xpCache.xp = xp
    end
    if okm and num(mx) then
        xpCache.max = mx
    end
end

-- Poller: runs only while the matcher has something queued.
local poller = CreateFrame("Frame")
Kills.pollFrame = poller

local function screenCentre()
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    local okh, h = pcall(UIParent.GetHeight, UIParent)
    if okw and okh and num(w) and num(h) and w > 0 and h > 0 then
        return w / 2, h * 0.65
    end
    return nil, nil
end

local function emitBurst(b)
    local x, y = b.x, b.y
    local hadXY = x ~= nil and y ~= nil
    local origin = "plate"
    if not hadXY then
        x, y, origin = nil, nil, "none"
        if b.kind == "kill" then
            local te = Plates:TargetEntry()
            if te then
                x, y, origin = te.x, te.y, "target"
            end
        end
        if x == nil then
            x, y = screenCentre()
            origin = x and "centre" or "none"
        end
    end
    local probe = isProbe()
    ns:Log("BURST tier=%d kind=%s amount=%s rested=%s hadXY=%s origin=%s probe=%s", b.tier, tostring(b.kind),
        tostring(b.amount), tostring(b.rested), tostring(hadXY), origin, tostring(probe))
    if probe or x == nil then
        return
    end
    local orbs = ns.Orbs
    if not (orbs and orbs.Burst) then
        return
    end
    local db = ns.db
    local n, scale = OrbMath.Count(b.amount, xpCache.max, db.density, db.cap)
    if n <= 0 then
        return
    end
    local nPurple = 0
    if db.restedTint and b.rested then
        local _, p = OrbMath.RestedSplit(n, b.amount, b.rested)
        nPurple = p
    end
    local ok, err = pcall(orbs.Burst, orbs, { x = x, y = y, n = n, scale = scale, nPurple = nPurple, kind = b.kind })
    if not ok then
        ns:Log("Orbs:Burst error %s", tostring(err))
    end
end

local function onPoll()
    local ok, err = pcall(function()
        local bursts = matcher:Poll()
        for _, b in ipairs(bursts) do
            emitBurst(b)
        end
        local s = matcher:Stats()
        if #bursts > 0 or s.dropped ~= lastDropped then
            lastDropped = s.dropped
            ns:Log("STATS tier1=%d tier2=%d tier3=%d tier4=%d dropped=%d other=%d pending=%d", s.tier1, s.tier2,
                s.tier3, s.tier4, s.dropped, s.other, matcher:Pending())
        end
    end)
    if not ok then
        ns:Log("poll error %s", tostring(err))
    end
    if matcher:Pending() == 0 then
        poller:SetScript("OnUpdate", nil)
    end
end

local function ensurePoll()
    if matcher:Pending() > 0 and not poller:GetScript("OnUpdate") then
        poller:SetScript("OnUpdate", onPoll)
    end
end

function Kills:PollActive()
    return poller:GetScript("OnUpdate") ~= nil
end

local function addDeath(entry, tier)
    entry.deathAdded = true
    local hasPos = type(entry.x) == "number" and type(entry.y) == "number"
    matcher:AddDeath({ x = hasPos and entry.x or nil, y = hasPos and entry.y or nil, tier = tier, name = entry.name })
    ensurePoll()
end

local function checkAmounts(chat, delta)
    local equal = chat.amount == delta.amount
    ns:Log("AMOUNTCHECK chat=%s delta=%s equal=%s kind=%s rested=%s penalty=%s", tostring(chat.amount),
        tostring(delta.amount), tostring(equal), tostring(chat.kind), tostring(chat.rested), tostring(chat.penalty))
end

local function noteChat(res)
    local now = GetTime()
    local c = { amount = res.amount, t = now, kind = res.kind, rested = res.rested, penalty = res.penalty }
    if pendingDelta and now - pendingDelta.t <= AMOUNT_WINDOW then
        checkAmounts(c, pendingDelta)
        pendingDelta = nil
    else
        pendingChat = c
    end
end

local function noteDelta(amount)
    local now = GetTime()
    local d = { amount = amount, t = now }
    if pendingChat and now - pendingChat.t <= AMOUNT_WINDOW then
        checkAmounts(pendingChat, d)
        pendingChat = nil
    else
        pendingDelta = d
    end
end

local handlers = {}

function handlers.UNIT_DIED(guid)
    local isReadable = readable(guid)
    local entry = isReadable and Plates:FindByGUID(guid) or nil
    ns:Log("UNIT_DIED guidReadable=%s matched=%s held=%s", tostring(isReadable), tostring(entry ~= nil),
        tostring(entry ~= nil and entry.held == true))
    if not entry then
        return
    end
    if entry.deathAdded then
        ns:Log("UNIT_DIED duplicate for an entry that already has a death; ignored")
        return
    end
    if not entry.held then
        Plates:Sample(entry)
    end
    addDeath(entry, 1)
end

function handlers.CHAT_MSG_COMBAT_XP_GAIN(msg)
    local isReadable = readable(msg)
    local res = isReadable and parser:Parse(msg, readable) or nil
    local r = res or {}
    ns:Log("CHAT msgReadable=%s kind=%s amount=%s rested=%s penalty=%s", tostring(isReadable),
        tostring(r.kind or "none"),
        tostring(r.amount), tostring(r.rested), tostring(r.penalty))
    if not res then
        return
    end
    noteChat(res)
    if res.kind == "kill" then
        matcher:AddKillXP({ amount = res.amount, mob = res.mob, rested = res.rested })
        ensurePoll()
    end
end

function handlers.PLAYER_XP_UPDATE(unit)
    if unit ~= nil and unit ~= "player" then
        return
    end
    local okx, xp = pcall(UnitXP, "player")
    local okm, mx = pcall(UnitXPMax, "player")
    if not (okx and okm and num(xp) and num(mx)) then
        ns:Log("XPUPDATE xpReadable=false")
        return
    end
    local wasLeveled = leveled
    leveled = false
    if xpCache.xp == nil or xpCache.max == nil then
        ns:Log("XPUPDATE no cache yet; cache primed")
        xpCache.xp, xpCache.max = xp, mx
        return
    end
    local delta = OrbMath.XPDelta(xpCache.xp, xpCache.max, xp, mx, wasLeveled)
    xpCache.xp, xpCache.max = xp, mx
    ns:Log("XPUPDATE delta=%s leveled=%s xp=%s max=%s", tostring(delta), tostring(wasLeveled), tostring(xp),
        tostring(mx))
    if delta > 0 then
        noteDelta(delta)
        matcher:AddDelta(delta)
        ensurePoll()
    end
end

function handlers.PLAYER_LEVEL_UP()
    leveled = true
    ns:Log("PLAYER_LEVEL_UP")
end

function handlers.PLAYER_ENTERING_WORLD()
    refreshXP()
    ns:Log("PLAYER_ENTERING_WORLD xp cached=%s", tostring(xpCache.xp ~= nil and xpCache.max ~= nil))
end

-- Plate removed while dead and no UNIT_DIED seen for it: tier 2.
Plates.onRemoved = function(entry)
    if not entry.hostile then
        return
    end
    if entry.deadAtRemoval and not entry.deathAdded then
        addDeath(entry, 2)
        ns:Log("DEATH tier=2 hadPos=%s", tostring(type(entry.x) == "number"))
    end
end

local frame = CreateFrame("Frame")
Kills.frame = frame
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("CHAT_MSG_COMBAT_XP_GAIN")
frame:RegisterEvent("PLAYER_XP_UPDATE")
frame:RegisterEvent("PLAYER_LEVEL_UP")
unitDiedRegistered = pcall(frame.RegisterEvent, frame, "UNIT_DIED") and true or false
Kills.unitDiedRegistered = unitDiedRegistered
frame:SetScript("OnEvent", function(_, event, ...)
    local fn = handlers[event]
    if not fn then
        return
    end
    local ok, err = pcall(fn, ...)
    if not ok then
        ns:Log("Kills error %s: %s", tostring(event), tostring(err))
    end
end)

refreshXP()

table.insert(ns.statusProviders, function()
    local s = matcher:Stats()
    return string.format("kills: tier1=%d tier2=%d tier3=%d tier4=%d dropped=%d other=%d probe=%s UNIT_DIED=%s poll=%s",
        s.tier1, s.tier2, s.tier3, s.tier4, s.dropped, s.other, isProbe() and "on" or "off",
        unitDiedRegistered and "yes" or "no", Kills:PollActive() and "active" or "idle")
end)

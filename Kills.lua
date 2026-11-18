-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Kill pipeline: wires UNIT_DIED / plate removal / chat XP / XP deltas into one KillMatcher and turns its bursts into
-- ns.Orbs:Burst calls. Deaths carry no position (plates can't be measured); the origin is estimated. Never throws.

local Kills = {}
ns.Kills = Kills

local AMOUNT_WINDOW = 1.0 -- chat amount and PLAYER_XP_UPDATE delta are compared when within this many seconds

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local Plates = ns.Plates
local OrbMath = ns.OrbMath
local matcher = ns.KillMatcher.New({ now = GetTime })
local engaged = ns.Engaged.New({ now = GetTime, window = 10, cap = 40 }) -- GUIDs the player was fighting (max level)
Kills.engaged = engaged
local parser = ns.XPParse.Build(_G)
Kills.matcher = matcher

local xpCache = { xp = nil, max = nil }
local xpStale = false -- the last PLAYER_XP_UPDATE was unreadable: the cache can't be trusted until it is re-primed
local unitDiedRegistered = false
local pendingChat, pendingDelta -- { amount, t, kind } awaiting their counterpart for AMOUNTCHECK
local lastDropped = 0

-- Rested pool tracking (fallback rested detection when chat carries no "(+N exp Rested bonus)"). exhCur is the last
-- known pool (nil = unknown); every observed decrease is a drop. A drop is attached to the XP update it arrived with
-- (UPDATE_EXHAUSTION may land just before or just after PLAYER_XP_UPDATE) and later claimed by the kill burst whose
-- amount equals that update, so it is counted once. See emitBurst.
local DROP_TTL = 2.0 -- a recorded XP update stays claimable by a kill this long
local ACCUM_TTL = 1.0 -- a drop seen before any XP update is attached to the next one within this long
local LATE_WINDOW = 0.5 -- UPDATE_EXHAUSTION after an XP update still belongs to it within this long
local exhCur
local accumDrop, accumT = 0, 0
local xpEntries = {} -- { amount, drop, t } one per positive XP delta not yet claimed by a burst
local awaiting = {} -- { amount, t } kill bursts emitted before their XP update arrived (it must not be kept)
local lastOtherChat -- { amount, rested, t } most recent non-kill chat XP with a rested bonus

local function log(...)
    ns:Log(...)
end

local function num(v)
    if readable(v) and type(v) == "number" then
        return v
    end
    return nil
end

-- Re-reads the cache. Returns true when both values were readable.
local function refreshXP()
    local okx, xp = pcall(UnitXP, "player")
    local okm, mx = pcall(UnitXPMax, "player")
    local gotX = okx and num(xp) ~= nil
    local gotM = okm and num(mx) ~= nil
    if gotX then
        xpCache.xp = xp
    end
    if gotM then
        xpCache.max = mx
    end
    return gotX and gotM
end

-- Returns raw, state: raw = the API value for logging (nil when not rested or unreadable); state = the pool for
-- tracking (nil API value while readable = empty pool = 0; errors and secret values = unknown nil).
local function readExh()
    local ok, v = pcall(GetXPExhaustion)
    if not ok then
        return nil, nil
    end
    if v == nil then
        return nil, 0
    end
    if num(v) then
        return v, v
    end
    return nil, nil
end

-- Folds a new pool reading into exhCur and returns how much it dropped (0 when not known to have dropped).
local function observeExh(state)
    local drop = 0
    if exhCur and state and state < exhCur then
        drop = exhCur - state
    end
    exhCur = state
    return drop
end

local function pruneExh(now)
    for i = #xpEntries, 1, -1 do
        if now - xpEntries[i].t > DROP_TTL then
            table.remove(xpEntries, i)
        end
    end
    for i = #awaiting, 1, -1 do
        if now - awaiting[i].t > DROP_TTL then
            table.remove(awaiting, i)
        end
    end
end

-- Takes the XP update recorded for a kill of this amount, FIFO. Returns its drop (nil if none recorded yet).
local function claimDrop(amount, now)
    pruneExh(now)
    for i, e in ipairs(xpEntries) do
        if e.amount == amount then
            table.remove(xpEntries, i)
            return e.drop
        end
    end
    awaiting[#awaiting + 1] = { amount = amount, t = now }
    return nil
end

-- Poller: runs only while the matcher has something queued.
local poller = CreateFrame("Frame")
Kills.pollFrame = poller

local NON_KILL_Y = 0.65 -- non-kill XP (quests etc.) streams from the screen centre, at this fraction of its height

local function screenCentre(frac)
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    local okh, h = pcall(UIParent.GetHeight, UIParent)
    if okw and okh and num(w) and num(h) and w > 0 and h > 0 then
        return w / 2, h * (frac or 0.65)
    end
    return nil, nil
end

-- Stream origin. Non-kill XP (quests etc.) always streams from the screen centre (NON_KILL_Y). Kills: popstream and
-- crossfade start at the estimate P-hat when there is one (crossfade flies from P-hat, so the label says so); popstream
-- falls back to the portrait without one; the stream style uses the target frame (kept from its last good
-- measurement). Fallback: the screen centre. (ex, ey) = the kill's estimate. Returns x, y, label.
local function chooseOrigin(b, ex, ey)
    if b.kind == "kill" then
        local style = ns.db.style
        if style == "popstream" then
            local x, y, label = ns.Target:StreamOrigin(ex, ey)
            if x then
                return x, y, label
            end
        elseif style == "crossfade" and type(ex) == "number" and type(ey) == "number" then
            return ex, ey, "estimate"
        else
            local fx, fy = ns.Target:TargetFrameOrigin()
            if fx then
                return fx, fy, "targetframe"
            end
        end
        local cx, cy = screenCentre()
        return cx, cy, "centre"
    end
    local cx, cy = screenCentre(NON_KILL_Y)
    return cx, cy, "centre"
end

-- True when a different live plate entry is anchored to this very plate frame: Blizzard reuses plate frames, so the
-- dead mob's plate may already belong to another mob and a pop there would land on the wrong one. Identity compare only
-- (the plate is never measured). `entry` is the dead unit's own record: it never counts as "another".
local function plateReused(plate, entry)
    for _, e in pairs(Plates.entries) do
        if e ~= entry and e.plate == plate then
            return true
        end
    end
    return false
end

-- The fallback plate (the current target's) is only trusted when the target is known to be dead.
local function targetIsDead()
    local ok, dead = pcall(UnitIsDead, "target")
    return ok and readable(dead) and dead == true
end

local MAXLEVEL_ORBS = 6 -- orbs in the burst an engaged kill sends to the portrait at max level

-- A burst is { tier, kind, guid, plate, entry, amount, rested } from the matcher, or (max level) a fixed orb count
-- { tier, kind = "kill", maxlevel = true, n = N, guid, plate, entry } that has no XP behind it: no rested split, the
-- orb count is n and the log line says kind=maxlevel amount=0.
local function emitBurst(b)
    local db = ns.db
    local ex, ey, est, wm
    if b.secret then
        ns:Log("SECRETPAIR tier=%d amount=%s", b.tier, tostring(b.amount))
    end
    if b.kind == "kill" then
        ex, ey, est, wm = ns.Mouseover:Estimate(b.guid) -- once per burst; b.guid is never logged
    end
    local now = GetTime()
    local chatRested, exhDrop = b.rested, nil
    local restedAmt, restedSrc
    if b.n then
        restedAmt, restedSrc = nil, "none"
    elseif b.kind == "kill" then
        exhDrop = claimDrop(b.amount, now)
        local rawNow = readExh()
        restedAmt, restedSrc = OrbMath.RestedFallback(b.amount, chatRested, exhDrop, rawNow)
    else
        if lastOtherChat and lastOtherChat.amount == b.amount and now - lastOtherChat.t <= 1.5 then
            chatRested = lastOtherChat.rested -- quests etc.: only a chat-reported bonus counts, never the pool
            lastOtherChat = nil
        end
        restedAmt, restedSrc = OrbMath.RestedFallback(b.amount, chatRested, nil, nil)
    end
    b.rested = restedAmt
    local x, y, origin = chooseOrigin(b, ex, ey)
    local plate
    if b.kind == "kill" and db.style ~= "stream" then
        if b.plate ~= nil then
            if not plateReused(b.plate, b.entry) then
                plate = b.plate
            end
        elseif targetIsDead() then
            plate = ns.Target:TargetPlate()
        end
    end
    ns:Log("BURST tier=%d kind=%s amount=%s rested=%s origin=%s plate=%s est=%s w=%.2f restedSrc=%s", b.tier,
        b.maxlevel and "maxlevel" or tostring(b.kind), tostring(b.amount or 0), tostring(b.rested), origin,
        plate and "yes" or "no", est or "none", wm or 0, restedSrc)
    if not db.enabled or x == nil then
        return
    end
    if b.kind ~= "kill" and not db.questBursts then
        return
    end
    local orbs = ns.Orbs
    if not (orbs and orbs.Burst) then
        return
    end
    local n, scale
    if b.n then
        n, scale = b.n, 1
    else
        n, scale = OrbMath.Count(b.amount, xpCache.max, db.density, db.cap)
    end
    if n <= 0 then
        return
    end
    local nPurple = 0
    if not b.n and db.restedTint and b.rested then
        local _, p = OrbMath.RestedSplit(n, b.amount, b.rested)
        nPurple = p
    end
    local ok, err = pcall(orbs.Burst, orbs, {
        x = x,
        y = y,
        plate = plate,
        n = n,
        scale = scale,
        nPurple = nPurple,
        kind = b.kind,
        ex = ex,
        ey = ey,
        est = est,
        estW = wm,
    })
    if not ok then
        ns:Log("Orbs:Burst error %s", tostring(err))
    end
end

-- Hoisted so the poll creates no closure per frame. Reads the matcher's counters directly: Stats() builds a table.
local function pollBody()
    local bursts = matcher:Poll()
    for _, b in ipairs(bursts) do
        emitBurst(b)
    end
    local s = matcher.stats
    if #bursts > 0 or s.dropped ~= lastDropped then
        lastDropped = s.dropped
        if ns.db and ns.db.debug then
            ns:Log("STATS tier1=%d tier2=%d tier4=%d dropped=%d other=%d secret=%d pending=%d", s.tier1,
                s.tier2, s.tier4, s.dropped, s.other, s.secret, matcher:Pending())
        end
    end
end

local function onPoll()
    local ok, err = pcall(pollBody)
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

-- Sizes of the unclaimed-XP-update and early-burst queues (for tests; both are pruned by age).
function Kills:XPQueueSizes()
    return #xpEntries, #awaiting
end

function Kills:PollActive()
    return poller:GetScript("OnUpdate") ~= nil
end

-- True when the dead unit is the current hostile target (a long fight outlives the 10 s engaged window).
local function isHostileTarget(guid)
    local okg, tg = pcall(UnitGUID, "target")
    if not (okg and readable(tg) and tg == guid) then
        return false
    end
    local okc, can = pcall(UnitCanAttack, "player", "target")
    return okc and readable(can) and can == true
end

-- At max level the game pays no XP, so a kill can't be paired with chat: an engaged hostile's death sends a small
-- burst straight out (never through the matcher, where it would wait for XP forever and count as dropped).
local function maxLevelDeath(entry, tier, guid)
    if not (readable(guid) and type(guid) == "string") then
        return
    end
    if not (engaged:IsEngaged(guid) or isHostileTarget(guid)) then
        return
    end
    emitBurst({
        tier = tier,
        kind = "kill",
        maxlevel = true,
        n = MAXLEVEL_ORBS,
        plate = entry.plate,
        guid = guid,
        entry = entry,
    })
end

local function addDeath(entry, tier, guid)
    entry.deathAdded = true
    guid = guid or entry.guid -- opaque: only used to look up estimates and the engaged set, never logged
    local db = ns.db
    if db and db.showAtMax and ns.AtMaxLevel() then
        local ok, err = pcall(maxLevelDeath, entry, tier, guid)
        if not ok then
            ns:Log("Kills error maxlevel: %s", tostring(err))
        end
        return
    end
    matcher:AddDeath({
        tier = tier,
        name = entry.name,
        plate = entry.plate,
        guid = guid,
        entry = entry, -- opaque: lets emitBurst tell "my plate" from "a plate another mob has taken over"
    })
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
    addDeath(entry, 1, guid)
end

-- Engaged-set feeders (max level only: they return at once while the option is off). Every read is guarded and no GUID
-- is ever logged.
function handlers.PLAYER_TARGET_CHANGED()
    if not (ns.db and ns.db.showAtMax) then
        return
    end
    local okc, can = pcall(UnitCanAttack, "player", "target")
    if not (okc and readable(can) and can == true) then
        return
    end
    local okg, guid = pcall(UnitGUID, "target")
    if okg and readable(guid) then
        engaged:Mark(guid)
    end
end

function handlers.UNIT_THREAT_LIST_UPDATE(unit)
    if not (ns.db and ns.db.showAtMax) then
        return
    end
    if not (readable(unit) and type(unit) == "string" and string.sub(unit, 1, 9) == "nameplate") then
        return
    end
    local ok, threat = pcall(UnitThreatSituation, "player", unit)
    if not (ok and threat ~= nil and readable(threat)) then
        return -- not on the threat list, or a secret value: skip
    end
    local okg, guid = pcall(UnitGUID, unit)
    if okg and readable(guid) then
        engaged:Mark(guid)
    end
end

function handlers.CHAT_MSG_COMBAT_XP_GAIN(msg)
    local isReadable = readable(msg)
    local res = isReadable and parser:Parse(msg, readable) or nil
    local r = res or {}
    -- tail: what follows the first "experience." (no mob name in it), to see whether a bonus suffix exists
    local tail = ""
    if isReadable and type(msg) == "string" then
        local _, e = string.find(msg, "experience.", 1, true)
        if e then
            tail = string.sub(msg, e + 1, e + 60)
        end
    end
    ns:Log("CHAT msgReadable=%s kind=%s amount=%s rested=%s penalty=%s%s", tostring(isReadable),
        tostring(r.kind or "none"), tostring(r.amount), tostring(r.rested), tostring(r.penalty),
        isReadable and string.format(' tail="%s"', tail) or "")
    if not isReadable then
        -- Instances: no amount or name, but one kill's XP delta follows. Mark it so it is not quest XP.
        matcher:AddSecretChat()
        ensurePoll()
    end
    if not res then
        return
    end
    noteChat(res)
    if res.kind == "other" and res.rested then
        lastOtherChat = { amount = res.amount, rested = res.rested, t = GetTime() }
    end
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
        xpStale = true -- whatever XP arrives meanwhile is unknown: the next readable update re-primes the cache
        ns:Log("XPUPDATE xpReadable=false")
        return
    end
    if xpCache.xp == nil or xpCache.max == nil then
        ns:Log("XPUPDATE no cache yet; cache primed")
        xpCache.xp, xpCache.max = xp, mx
        xpStale = false
        return
    end
    if xpStale then
        -- a delta across unreadable updates would merge several gains into one phantom burst
        ns:Log("XPUPDATE stale; cache primed")
        xpCache.xp, xpCache.max = xp, mx
        xpStale = false
        return
    end
    local wasLeveled = OrbMath.LeveledUp(xpCache.xp, xpCache.max, xp, mx)
    local delta = OrbMath.XPDelta(xpCache.xp, xpCache.max, xp, mx)
    xpCache.xp, xpCache.max = xp, mx
    local now = GetTime()
    pruneExh(now) -- the queues must not grow while no kill claims their entries
    local rawExh, stateExh = readExh()
    local drop = observeExh(stateExh)
    if accumDrop > 0 and now - accumT <= ACCUM_TTL then
        drop = drop + accumDrop
    end
    accumDrop = 0
    ns:Log("XPUPDATE delta=%s leveled=%s xp=%s max=%s exh=%s exhDrop=%s", tostring(delta), tostring(wasLeveled),
        tostring(xp), tostring(mx), tostring(rawExh), tostring(drop > 0 and drop or nil))
    if delta > 0 then
        local claimed = false
        for i, a in ipairs(awaiting) do -- the burst was emitted before this update: it can no longer use the drop
            if a.amount == delta and now - a.t <= DROP_TTL then
                table.remove(awaiting, i)
                claimed = true
                break
            end
        end
        if not claimed then
            xpEntries[#xpEntries + 1] = { amount = delta, drop = drop, t = now }
        end
        noteDelta(delta)
        matcher:AddDelta(delta)
        ensurePoll()
    end
end

function handlers.UPDATE_EXHAUSTION()
    local rawExh, stateExh = readExh()
    local drop = observeExh(stateExh)
    ns:Log("EXH exh=%s drop=%s", tostring(rawExh), tostring(drop > 0 and drop or nil))
    if drop <= 0 then
        return
    end
    local now = GetTime()
    local last = xpEntries[#xpEntries]
    if last and last.drop == 0 and now - last.t <= LATE_WINDOW then
        last.drop = drop -- arrived just after its XP update
    else
        accumDrop, accumT = accumDrop + drop, now -- arrived first: the next XP update takes it
    end
end

-- Only logs: the level-up wrap is read from the XP numbers themselves (OrbMath.LeveledUp), so it can't depend on
-- whether this event arrives before or after PLAYER_XP_UPDATE.
function handlers.PLAYER_LEVEL_UP()
    ns:Log("PLAYER_LEVEL_UP")
end

function handlers.PLAYER_ENTERING_WORLD()
    if refreshXP() then
        xpStale = false
    end
    local _, stateExh = readExh()
    exhCur, accumDrop = stateExh, 0 -- re-baseline: a zone change is not a drop
    ns:Log("PLAYER_ENTERING_WORLD xp cached=%s", tostring(xpCache.xp ~= nil and xpCache.max ~= nil))
end

-- Plate removed while dead and no UNIT_DIED seen for it: tier 2.
Plates.onRemoved = function(entry)
    if not entry.hostile then
        return
    end
    if entry.deadAtRemoval and not entry.deathAdded then
        addDeath(entry, 2)
        ns:Log("DEATH tier=2")
    end
end

local frame = CreateFrame("Frame")
Kills.frame = frame
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("CHAT_MSG_COMBAT_XP_GAIN")
frame:RegisterEvent("PLAYER_XP_UPDATE")
frame:RegisterEvent("PLAYER_LEVEL_UP")
frame:RegisterEvent("PLAYER_TARGET_CHANGED")
Kills.threatRegistered = pcall(frame.RegisterEvent, frame, "UNIT_THREAT_LIST_UPDATE") and true or false
unitDiedRegistered = pcall(frame.RegisterEvent, frame, "UNIT_DIED") and true or false
Kills.unitDiedRegistered = unitDiedRegistered
Kills.exhaustionRegistered = pcall(frame.RegisterEvent, frame, "UPDATE_EXHAUSTION") and true or false
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
exhCur = select(2, readExh())

table.insert(ns.statusProviders, function()
    local s = matcher:Stats()
    return string.format("kills: tier1=%d tier2=%d tier4=%d dropped=%d other=%d UNIT_DIED=%s poll=%s",
        s.tier1, s.tier2, s.tier4, s.dropped, s.other, unitDiedRegistered and "yes" or "no",
        Kills:PollActive() and "active" or "idle")
end)

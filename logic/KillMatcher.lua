-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Pure logic: pairs deaths (position) with chat kill-XP and XP deltas into bursts. Touches no WoW globals.
-- Tiers: 1 = UNIT_DIED match, 2 = plate removed while dead, 4 = no death matched (caller falls back). Tier 3 (a target
-- fallback that needed a death position) was retired with the plate measuring in v0.17; the number stays unused so log
-- lines keep their meaning.
-- When the chat line is a secret value (instances) there is no amount or name to match on. The caller then registers a
-- marker (AddSecretChat); a marker pairs the oldest queued death within secretTTL of it with the oldest unclaimed
-- XP delta, FIFO, as a kill.
-- Without a marker an unclaimed delta is still "other" (a quest turn-in near a grey-mob death must not become a kill).
-- An "other" burst can carry a source ("quest" | "explore") and an origin point. The caller registers a source hint
-- (AddSourceHint) from the event that comes with the XP (QUEST_TURNED_IN, the exploration chat line); an unclaimed
-- delta that matches a hint by amount and time takes its source and origin. Kills never look at hints.

local KillMatcher = {}
ns.KillMatcher = KillMatcher
KillMatcher.__index = KillMatcher

function KillMatcher.New(cfg)
    cfg = cfg or {}
    local self = setmetatable({}, KillMatcher)
    self.cfg = {
        deathTTL = cfg.deathTTL or 1.5,
        chatWait = cfg.chatWait or 0.5,
        deltaWait = cfg.deltaWait or 0.4,
        owedTTL = cfg.owedTTL or 1.0, -- how long an emitted kill waits for its (late) XP delta
        secretTTL = cfg.secretTTL or 1.0, -- how long a secret-chat marker waits for its death and delta
        hintTTL = cfg.hintTTL or 2.0, -- how long a source hint waits for its delta
        hintWindow = cfg.hintWindow or 1.0, -- a hint with an amount matches a delta this close in time (either order)
        nearestWindow = cfg.nearestWindow or 0.5, -- a hint takes a delta of another amount this close in time
        sourceWait = cfg.sourceWait or 0.3, -- extra wait for a delta while a source hint is expected (ExpectSource)
        now = cfg.now,
    }
    self.deaths = {}
    self.kills = {}
    self.deltas = {}
    self.owed = {}
    self.secret = {}
    self.hints = {}
    self.expectUntil = nil
    self.stats = { tier1 = 0, tier2 = 0, tier4 = 0, dropped = 0, other = 0, secret = 0 }
    return self
end

-- death = { tier, name|nil, plate|nil, guid|nil, entry|nil }; guid and entry are opaque (passed through to the burst,
-- never logged; entry is the plate tracker's record of the dead unit)
function KillMatcher:AddDeath(death)
    self.deaths[#self.deaths + 1] = {
        tier = death.tier or 1,
        name = death.name,
        plate = death.plate,
        guid = death.guid,
        entry = death.entry,
        t = self.cfg.now(),
    }
end

-- kill = { amount, mob|nil, rested|nil }; from chat, kind="kill" only.
function KillMatcher:AddKillXP(kill)
    self.kills[#self.kills + 1] = { amount = kill.amount, mob = kill.mob, rested = kill.rested, t = self.cfg.now() }
end

function KillMatcher:AddDelta(amount)
    self.deltas[#self.deltas + 1] = { amount = amount, t = self.cfg.now() }
end

-- A kill-XP chat line arrived but was unreadable (secret): remember that one kill's worth of XP is on its way.
function KillMatcher:AddSecretChat()
    self.secret[#self.secret + 1] = { t = self.cfg.now() }
end

-- hint = { source = "quest"|"explore", amount|nil, x|nil, y|nil, label|nil, locate|nil }. amount nil means "the nearest
-- unclaimed delta". The origin is x, y (UIParent units) or, when given, locate() -> x, y, label which is called only
-- when a delta takes the hint (so it can read the screen as late as possible).
function KillMatcher:AddSourceHint(hint)
    self.hints[#self.hints + 1] = {
        source = hint.source,
        amount = hint.amount,
        x = hint.x,
        y = hint.y,
        label = hint.label,
        locate = hint.locate,
        t = self.cfg.now(),
    }
end

-- A source hint is likely on its way (a quest dialog is open): for the next `seconds`, an unclaimed delta waits
-- sourceWait longer before it is emitted as plain "other", so a hint that arrives just after it can still claim it.
function KillMatcher:ExpectSource(seconds)
    self.expectUntil = self.cfg.now() + seconds
end

-- Anything queued? Lets the caller stop its OnUpdate when idle.
function KillMatcher:Pending()
    return #self.deaths + #self.kills + #self.deltas + #self.owed + #self.secret + #self.hints
end

function KillMatcher:Stats()
    local stats = self.stats
    return {
        tier1 = stats.tier1,
        tier2 = stats.tier2,
        tier4 = stats.tier4,
        dropped = stats.dropped,
        other = stats.other,
        secret = stats.secret,
    }
end

-- Each delta claims one equal-amount kill (still pending, or already emitted and owed a delta), FIFO.
function KillMatcher:_claim()
    local i = 1
    while i <= #self.deltas do
        local delta = self.deltas[i]
        local matched
        for j, owedKill in ipairs(self.owed) do
            if owedKill.amount == delta.amount then
                table.remove(self.owed, j)
                matched = true
                break
            end
        end
        if not matched then
            for _, kill in ipairs(self.kills) do
                if not kill.claimed and kill.amount == delta.amount then
                    kill.claimed = true
                    matched = true
                    break
                end
            end
        end
        if matched then
            table.remove(self.deltas, i)
        else
            i = i + 1
        end
    end
end

-- Could a pending death or secret-chat marker still turn this delta into a kill? Poll pairs a marker with a death
-- within secretTTL of each other and takes the oldest unclaimed delta, so an unpaired marker or death that close in
-- time may yet own the delta. Expired ones were removed earlier in Poll, so anything left is inside its claim window.
function KillMatcher:_couldBeKill(delta)
    local window = self.cfg.secretTTL
    for _, marker in ipairs(self.secret) do
        if math.abs(marker.t - delta.t) <= window then
            return true
        end
    end
    for _, death in ipairs(self.deaths) do
        if math.abs(death.t - delta.t) <= window then
            return true
        end
    end
    return false
end

-- The hint for an unclaimed delta, as an index or nil:
--   1. the closest-in-time hint with the same amount within hintWindow;
--   2. else the closest-in-time hint of any amount within nearestWindow. A reported quest reward can differ from the XP
--      actually paid (XP boosts or food, a reward clipped at the level cap), so an exact match must not be required.
--      An amount-less hint is only eligible here while a source is expected (an open quest dialog covers the delta)
--      and no pending death or secret-chat marker could still claim the delta: otherwise it would steal a kill's XP.
function KillMatcher:_findHint(delta)
    local cfg = self.cfg
    local bestIndex, bestGap
    for i, hint in ipairs(self.hints) do
        local gap = math.abs(hint.t - delta.t)
        if hint.amount == delta.amount and gap <= cfg.hintWindow and (not bestGap or gap < bestGap) then
            bestIndex, bestGap = i, gap
        end
    end
    if bestIndex then
        return bestIndex
    end
    -- a pending kill could still claim this delta: no hint may take it on timing alone
    if self:_couldBeKill(delta) then
        return nil
    end
    local amountlessAllowed = self.expectUntil ~= nil and delta.t <= self.expectUntil
    for i, hint in ipairs(self.hints) do
        local gap = math.abs(hint.t - delta.t)
        local eligible = hint.amount ~= nil or amountlessAllowed
        if eligible and gap <= cfg.nearestWindow and (not bestGap or gap < bestGap) then
            bestIndex, bestGap = i, gap
        end
    end
    return bestIndex
end

-- Fills in the origin a hint carries. Never throws: a failing locate() just leaves the origin unset.
local function applyHint(burst, hint)
    burst.source = hint.source
    local x, y, label = hint.x, hint.y, hint.label
    if hint.locate then
        local ok, locatedX, locatedY, locatedLabel = pcall(hint.locate)
        if ok then
            x, y, label = locatedX, locatedY, locatedLabel
        end
    end
    burst.x, burst.y, burst.label = x, y, label
end

-- With a readable mob name: the oldest death of the same name, else the oldest death whose name is unknown. A death
-- with a different readable name is never taken (it belongs to another kill). Without a mob name: the oldest death.
local function findDeath(deaths, mob)
    if mob ~= nil then
        for i, death in ipairs(deaths) do
            if death.name ~= nil and death.name == mob then
                return i
            end
        end
        for i, death in ipairs(deaths) do
            if death.name == nil then
                return i
            end
        end
        return nil
    end
    if #deaths > 0 then
        return 1
    end
    return nil
end

-- Returns a list of bursts { plate|nil, guid|nil, entry|nil, amount, rested, tier, kind = "kill"|"other", secret|nil };
-- an "other" burst may also carry source, x, y, label from a matching source hint.
-- Order: claim deltas, emit readable kills, expire stale secret markers, pair markers with (oldest death, oldest
-- unclaimed delta), then expire deaths and deltas. Pairing precedes expiry so a pair is never split by the clock.
function KillMatcher:Poll()
    local cfg, now, out = self.cfg, self.cfg.now(), {}
    self:_claim()

    local i = 1
    while i <= #self.kills do
        local kill = self.kills[i]
        local deathIndex = findDeath(self.deaths, kill.mob)
        local burst
        if deathIndex then
            local death = table.remove(self.deaths, deathIndex)
            burst = {
                plate = death.plate,
                guid = death.guid,
                entry = death.entry,
                amount = kill.amount,
                rested = kill.rested,
                tier = death.tier,
                kind = "kill",
            }
        elseif now - kill.t >= cfg.chatWait then
            burst = { amount = kill.amount, rested = kill.rested, tier = 4, kind = "kill" }
        end
        if burst then
            table.remove(self.kills, i)
            if not kill.claimed then
                self.owed[#self.owed + 1] = { amount = kill.amount, t = now }
            end
            local key = "tier" .. burst.tier
            self.stats[key] = (self.stats[key] or 0) + 1
            out[#out + 1] = burst
        else
            i = i + 1
        end
    end

    i = 1
    while i <= #self.secret do
        if now - self.secret[i].t >= cfg.secretTTL then
            table.remove(self.secret, i)
        else
            i = i + 1
        end
    end
    -- A marker only pairs with a death within secretTTL of it (either direction): an unrelated secret line next to a
    -- grey or tapped mob's death must not turn that death into a kill. Unpaired deaths expire below, deltas become
    -- "other".
    local markerIndex = 1
    while #self.deltas > 0 and markerIndex <= #self.secret do
        local markerTime, deathIndex = self.secret[markerIndex].t, nil
        for j, queued in ipairs(self.deaths) do
            if math.abs(queued.t - markerTime) <= cfg.secretTTL then
                deathIndex = j
                break
            end
        end
        if deathIndex then
            local delta = table.remove(self.deltas, 1)
            table.remove(self.secret, markerIndex)
            local death = table.remove(self.deaths, deathIndex) -- no name to match on: the oldest death in the window
            out[#out + 1] = {
                plate = death.plate,
                guid = death.guid,
                entry = death.entry,
                amount = delta.amount,
                rested = nil,
                tier = death.tier,
                kind = "kill",
                secret = true,
            }
            local key = "tier" .. death.tier
            self.stats[key] = (self.stats[key] or 0) + 1
            self.stats.secret = self.stats.secret + 1
        else
            markerIndex = markerIndex + 1
        end
    end

    -- Deaths nobody paid XP for (grey mob, tapped by others) expire silently.
    i = 1
    while i <= #self.deaths do
        if now - self.deaths[i].t >= cfg.deathTTL then
            table.remove(self.deaths, i)
            self.stats.dropped = self.stats.dropped + 1
        else
            i = i + 1
        end
    end

    -- Deltas nobody claimed are non-kill XP (quest, exploration...). One that matches a source hint takes its source
    -- and origin. While a hint is expected a delta without one waits sourceWait longer.
    i = 1
    while i <= #self.deltas do
        local delta = self.deltas[i]
        local age = now - delta.t
        local hintIndex = age >= cfg.deltaWait and self:_findHint(delta) or nil
        local expecting = self.expectUntil ~= nil and delta.t <= self.expectUntil
        if hintIndex or (age >= cfg.deltaWait + (expecting and cfg.sourceWait or 0)) then
            table.remove(self.deltas, i)
            self.stats.other = self.stats.other + 1
            local burst = { amount = delta.amount, rested = nil, tier = 4, kind = "other" }
            if hintIndex then
                applyHint(burst, table.remove(self.hints, hintIndex))
            end
            out[#out + 1] = burst
        else
            i = i + 1
        end
    end

    i = 1
    while i <= #self.hints do
        if now - self.hints[i].t >= cfg.hintTTL then
            table.remove(self.hints, i)
        else
            i = i + 1
        end
    end

    i = 1
    while i <= #self.owed do
        if now - self.owed[i].t >= cfg.owedTTL then
            table.remove(self.owed, i)
        else
            i = i + 1
        end
    end
    return out
end

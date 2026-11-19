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
        now = cfg.now,
    }
    self.deaths = {}
    self.kills = {}
    self.deltas = {}
    self.owed = {}
    self.secret = {}
    self.stats = { tier1 = 0, tier2 = 0, tier4 = 0, dropped = 0, other = 0, secret = 0 }
    return self
end

-- d = { tier, name|nil, plate|nil, guid|nil, entry|nil }; guid and entry are opaque (passed through to the burst, never
-- logged; entry is the plate tracker's record of the dead unit)
function KillMatcher:AddDeath(d)
    self.deaths[#self.deaths + 1] = {
        tier = d.tier or 1,
        name = d.name,
        plate = d.plate,
        guid = d.guid,
        entry = d.entry,
        t = self.cfg.now(),
    }
end

-- k = { amount, mob|nil, rested|nil }; from chat, kind="kill" only.
function KillMatcher:AddKillXP(k)
    self.kills[#self.kills + 1] = { amount = k.amount, mob = k.mob, rested = k.rested, t = self.cfg.now() }
end

function KillMatcher:AddDelta(amount)
    self.deltas[#self.deltas + 1] = { amount = amount, t = self.cfg.now() }
end

-- A kill-XP chat line arrived but was unreadable (secret): remember that one kill's worth of XP is on its way.
function KillMatcher:AddSecretChat()
    self.secret[#self.secret + 1] = { t = self.cfg.now() }
end

-- Anything queued? Lets the caller stop its OnUpdate when idle.
function KillMatcher:Pending()
    return #self.deaths + #self.kills + #self.deltas + #self.owed + #self.secret
end

function KillMatcher:Stats()
    local s = self.stats
    return {
        tier1 = s.tier1, tier2 = s.tier2, tier4 = s.tier4, dropped = s.dropped, other = s.other, secret = s.secret,
    }
end

-- Each delta claims one equal-amount kill (still pending, or already emitted and owed a delta), FIFO.
function KillMatcher:_claim()
    local i = 1
    while i <= #self.deltas do
        local d = self.deltas[i]
        local hit
        for j, o in ipairs(self.owed) do
            if o.amount == d.amount then
                table.remove(self.owed, j)
                hit = true
                break
            end
        end
        if not hit then
            for _, k in ipairs(self.kills) do
                if not k.claimed and k.amount == d.amount then
                    k.claimed = true
                    hit = true
                    break
                end
            end
        end
        if hit then
            table.remove(self.deltas, i)
        else
            i = i + 1
        end
    end
end

-- With a readable mob name: the oldest death of the same name, else the oldest death whose name is unknown. A death
-- with a different readable name is never taken (it belongs to another kill). Without a mob name: the oldest death.
local function findDeath(deaths, mob)
    if mob ~= nil then
        for i, d in ipairs(deaths) do
            if d.name ~= nil and d.name == mob then
                return i
            end
        end
        for i, d in ipairs(deaths) do
            if d.name == nil then
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

-- Returns a list of bursts { plate|nil, guid|nil, entry|nil, amount, rested, tier, kind = "kill"|"other", secret|nil }.
-- Order: claim deltas, emit readable kills, expire stale secret markers, pair markers with (oldest death, oldest
-- unclaimed delta), then expire deaths and deltas. Pairing precedes expiry so a pair is never split by the clock.
function KillMatcher:Poll()
    local cfg, now, out = self.cfg, self.cfg.now(), {}
    self:_claim()

    local i = 1
    while i <= #self.kills do
        local k = self.kills[i]
        local di = findDeath(self.deaths, k.mob)
        local burst
        if di then
            local d = table.remove(self.deaths, di)
            burst = {
                plate = d.plate,
                guid = d.guid,
                entry = d.entry,
                amount = k.amount,
                rested = k.rested,
                tier = d.tier,
                kind = "kill",
            }
        elseif now - k.t >= cfg.chatWait then
            burst = { amount = k.amount, rested = k.rested, tier = 4, kind = "kill" }
        end
        if burst then
            table.remove(self.kills, i)
            if not k.claimed then
                self.owed[#self.owed + 1] = { amount = k.amount, t = now }
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
    local mi = 1
    while #self.deltas > 0 and mi <= #self.secret do
        local mt, di = self.secret[mi].t, nil
        for j, dd in ipairs(self.deaths) do
            if math.abs(dd.t - mt) <= cfg.secretTTL then
                di = j
                break
            end
        end
        if di then
            local delta = table.remove(self.deltas, 1)
            table.remove(self.secret, mi)
            local d = table.remove(self.deaths, di) -- no name to match on: the oldest death in the window
            out[#out + 1] = {
                plate = d.plate,
                guid = d.guid,
                entry = d.entry,
                amount = delta.amount,
                rested = nil,
                tier = d.tier,
                kind = "kill",
                secret = true,
            }
            local key = "tier" .. d.tier
            self.stats[key] = (self.stats[key] or 0) + 1
            self.stats.secret = self.stats.secret + 1
        else
            mi = mi + 1
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

    -- Deltas nobody claimed are non-kill XP (quest, exploration...).
    i = 1
    while i <= #self.deltas do
        local d = self.deltas[i]
        if now - d.t >= cfg.deltaWait then
            table.remove(self.deltas, i)
            self.stats.other = self.stats.other + 1
            out[#out + 1] = { amount = d.amount, rested = nil, tier = 4, kind = "other" }
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

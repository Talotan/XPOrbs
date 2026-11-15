local ADDON, ns = ...

-- Pure logic: pairs deaths (position) with chat kill-XP and XP deltas into bursts. Touches no WoW globals.
-- Tiers: 1 = UNIT_DIED match, 2 = plate removed while dead, 3 = target fallback, 4 = no origin (caller falls back).

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
        now = cfg.now,
    }
    self.deaths = {}
    self.kills = {}
    self.deltas = {}
    self.owed = {}
    self.stats = { tier1 = 0, tier2 = 0, tier3 = 0, tier4 = 0, dropped = 0, other = 0 }
    return self
end

-- d = { x, y, tier, name|nil, plate|nil, guid|nil }; guid is opaque (passed through to the burst, never logged)
function KillMatcher:AddDeath(d)
    self.deaths[#self.deaths + 1] = {
        x = d.x,
        y = d.y,
        tier = d.tier or 1,
        name = d.name,
        plate = d.plate,
        guid = d.guid,
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

-- Anything queued? Lets the caller stop its OnUpdate when idle.
function KillMatcher:Pending()
    return #self.deaths + #self.kills + #self.deltas + #self.owed
end

function KillMatcher:Stats()
    local s = self.stats
    return { tier1 = s.tier1, tier2 = s.tier2, tier3 = s.tier3, tier4 = s.tier4, dropped = s.dropped, other = s.other }
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

-- Same readable name wins, else the oldest queued death.
local function findDeath(deaths, mob)
    if mob ~= nil then
        for i, d in ipairs(deaths) do
            if d.name ~= nil and d.name == mob then
                return i
            end
        end
    end
    if #deaths > 0 then
        return 1
    end
    return nil
end

-- Returns a list of bursts { x|nil, y|nil, plate|nil, guid|nil, amount, rested, tier, kind = "kill"|"other" }.
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
                x = d.x,
                y = d.y,
                plate = d.plate,
                guid = d.guid,
                amount = k.amount,
                rested = k.rested,
                tier = d.tier,
                kind = "kill",
            }
        elseif now - k.t >= cfg.chatWait then
            burst = { x = nil, y = nil, amount = k.amount, rested = k.rested, tier = 4, kind = "kill" }
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
            out[#out + 1] = { x = nil, y = nil, amount = d.amount, rested = nil, tier = 4, kind = "other" }
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

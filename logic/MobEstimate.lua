-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Pure logic: estimates where a dying mob is on screen (plates can't be measured on Forever). Mouseover samples are
-- the cursor position seen while hovering a hostile GUID; an estimate blends a fresh sample with the cursor and a
-- fixed default point. Touches no WoW globals: the caller injects the clock, cursor and screen size.

local MobEstimate = {}
ns.MobEstimate = MobEstimate
MobEstimate.__index = MobEstimate

-- default mob height as a fraction of screen height (target plates sat at 0.55-0.62); the only place this is defined
MobEstimate.ASSUMED_MOB_Y = 0.58
MobEstimate.HEAD_OFFSET = 40 -- a hovered mob's cursor sits on the body; the plate/head is about this far above (px)
MobEstimate.BODY_OFFSET = 0 -- with the zoom anchor the orbs aim at the body itself, which is where the cursor sits

local DEFAULTS = {
    cap = 20, -- max remembered GUIDs (oldest evicted)
    prune = 5, -- samples older than this many seconds are dropped
    full = 1, -- sample weight is 1 up to this age (s)
    zero = 3, -- ... falls linearly to 0 at this age
    cursorWeight = 0, -- weight of the plain cursor when there is no usable sample (an idle cursor says nothing)
}

-- The default mob point for a screen of w x h.
function MobEstimate.Default(w, h, assumedY)
    return w / 2, h * (assumedY or MobEstimate.ASSUMED_MOB_Y)
end

-- Which point the popstream stream starts from: the estimate P-hat whenever there is one (the pop sits at the mob, so
-- the stream starts there too), else the target frame portrait (nil if never measured). (estX, estY) = the estimate,
-- (frameX, frameY) = portrait centre. Returns x, y, "estimate"|"targetframe", or nil when neither applies (the caller
-- falls back to the screen centre).
function MobEstimate.PickOrigin(estX, estY, frameX, frameY)
    if type(estX) == "number" and type(estY) == "number" then
        return estX, estY, "estimate"
    end
    if type(frameX) == "number" and type(frameY) == "number" then
        return frameX, frameY, "targetframe"
    end
    return nil
end

-- cfg = { now = function() -> seconds, plus optional overrides of DEFAULTS }
function MobEstimate.New(cfg)
    cfg = cfg or {}
    local self = setmetatable({}, MobEstimate)
    self.cfg = { now = cfg.now }
    for k, v in pairs(DEFAULTS) do
        self.cfg[k] = cfg[k] or v
    end
    self.samples = {} -- guid -> { x, y, t }
    self.n = 0
    return self
end

function MobEstimate:Count()
    return self.n
end

function MobEstimate:_prune()
    local now, limit = self.cfg.now(), self.cfg.prune
    for guid, sample in pairs(self.samples) do
        if now - sample.t > limit then
            self.samples[guid] = nil
            self.n = self.n - 1
        end
    end
end

-- Records the cursor position (x, y) seen while hovering guid. The caller has already checked the unit is hostile
-- and the values readable; anything that isn't a string guid + two numbers is ignored. Returns true when stored.
function MobEstimate:AddSample(guid, x, y)
    if type(guid) ~= "string" or type(x) ~= "number" or type(y) ~= "number" then
        return false
    end
    self:_prune()
    local sample = self.samples[guid]
    if sample then
        sample.x, sample.y, sample.t = x, y, self.cfg.now()
        return true
    end
    if self.n >= self.cfg.cap then
        local oldest, oldestTime
        for candidateGuid, candidate in pairs(self.samples) do
            if oldestTime == nil or candidate.t < oldestTime then
                oldest, oldestTime = candidateGuid, candidate.t
            end
        end
        if oldest ~= nil then
            self.samples[oldest] = nil
            self.n = self.n - 1
        end
    end
    self.samples[guid] = { x = x, y = y, t = self.cfg.now() }
    self.n = self.n + 1
    return true
end

-- Sample weight for an age in seconds: 1 up to cfg.full, linear to 0 at cfg.zero.
function MobEstimate:Weight(age)
    local full, zero = self.cfg.full, self.cfg.zero
    if age <= full then
        return 1
    elseif age >= zero then
        return 0
    end
    return (zero - age) / (zero - full)
end

-- Estimated screen point of the mob with this guid. (cursorX, cursorY) may be nil; (w, h) is the screen size in the
-- same units. Returns x, y, source, sampleWeight with source "mouseover" (sampleWeight > 0) | "cursor" | "default"
-- (nil, nil without a usable screen size). In the formula below w_m is sampleWeight:
--   P = w_m * (sample + (0, headOffset)) + (1 - w_m) * (cursorWeight * cursor + (1 - cursorWeight) * default)
-- headOffset defaults to HEAD_OFFSET (aim at the plate); the zoom anchor passes BODY_OFFSET (aim at the body).
function MobEstimate:Estimate(guid, cursorX, cursorY, w, h, headOffset)
    if type(w) ~= "number" or type(h) ~= "number" or w <= 0 or h <= 0 then
        return nil, nil, "default", 0
    end
    self:_prune()
    local defaultX, defaultY = MobEstimate.Default(w, h)
    local baseX, baseY, source = defaultX, defaultY, "default"
    local cursorWeight = self.cfg.cursorWeight
    if cursorWeight > 0 and type(cursorX) == "number" and type(cursorY) == "number" then
        baseX = cursorWeight * cursorX + (1 - cursorWeight) * defaultX
        baseY = cursorWeight * cursorY + (1 - cursorWeight) * defaultY
        source = "cursor"
    end
    if type(headOffset) ~= "number" then
        headOffset = MobEstimate.HEAD_OFFSET
    end
    local sample = type(guid) == "string" and self.samples[guid] or nil
    local sampleWeight = sample and self:Weight(self.cfg.now() - sample.t) or 0
    if sampleWeight > 0 then
        local x = sampleWeight * sample.x + (1 - sampleWeight) * baseX
        local y = sampleWeight * (sample.y + headOffset) + (1 - sampleWeight) * baseY
        return x, y, "mouseover", sampleWeight
    end
    return baseX, baseY, source, 0
end

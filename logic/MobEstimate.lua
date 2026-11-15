local ADDON, ns = ...

-- Pure logic: estimates where a dying mob is on screen (plates can't be measured on Forever). Mouseover samples are
-- the cursor position seen while hovering a hostile GUID; an estimate blends a fresh sample with the cursor and a
-- fixed default point. Touches no WoW globals: the caller injects the clock, cursor and screen size.

local MobEstimate = {}
ns.MobEstimate = MobEstimate
MobEstimate.__index = MobEstimate

-- default mob height as a fraction of screen height (target plates sat at 0.55-0.62); the only place this is defined
MobEstimate.ASSUMED_MOB_Y = 0.58
MobEstimate.HEAD_OFFSET = 40 -- a hovered mob's cursor sits on the body; the plate/head is about this far above (px)

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
-- the stream starts there too), else the target frame portrait (nil if never measured). (ex, ey) = the estimate,
-- (fx, fy) = portrait centre. Returns x, y, "estimate"|"targetframe", or nil when neither applies (the caller falls
-- back to the screen centre).
function MobEstimate.PickOrigin(ex, ey, fx, fy)
    if type(ex) == "number" and type(ey) == "number" then
        return ex, ey, "estimate"
    end
    if type(fx) == "number" and type(fy) == "number" then
        return fx, fy, "targetframe"
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
    for guid, s in pairs(self.samples) do
        if now - s.t > limit then
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
    local s = self.samples[guid]
    if s then
        s.x, s.y, s.t = x, y, self.cfg.now()
        return true
    end
    if self.n >= self.cfg.cap then
        local oldest, ot
        for g, o in pairs(self.samples) do
            if ot == nil or o.t < ot then
                oldest, ot = g, o.t
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
-- same units. Returns x, y, source, w_m with source "mouseover" (w_m > 0) | "cursor" | "default" (nil, nil without a
-- usable screen size).
--   P = w_m * (sample + (0, HEAD_OFFSET)) + (1 - w_m) * (cursorWeight * cursor + (1 - cursorWeight) * default)
function MobEstimate:Estimate(guid, cursorX, cursorY, w, h)
    if type(w) ~= "number" or type(h) ~= "number" or w <= 0 or h <= 0 then
        return nil, nil, "default", 0
    end
    self:_prune()
    local dx, dy = MobEstimate.Default(w, h)
    local bx, by, source = dx, dy, "default"
    local cw = self.cfg.cursorWeight
    if cw > 0 and type(cursorX) == "number" and type(cursorY) == "number" then
        bx, by, source = cw * cursorX + (1 - cw) * dx, cw * cursorY + (1 - cw) * dy, "cursor"
    end
    local s = type(guid) == "string" and self.samples[guid] or nil
    local wm = s and self:Weight(self.cfg.now() - s.t) or 0
    if wm > 0 then
        return wm * s.x + (1 - wm) * bx, wm * (s.y + MobEstimate.HEAD_OFFSET) + (1 - wm) * by, "mouseover", wm
    end
    return bx, by, source, 0
end

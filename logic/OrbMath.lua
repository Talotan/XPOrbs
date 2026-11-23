-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Pure logic: orb counts, curves and coordinate maths. Touches no WoW globals.

local OrbMath = {}
ns.OrbMath = OrbMath

local floor, sqrt, min, max = math.floor, math.sqrt, math.min, math.max

local function clamp(v, lo, hi)
    if v < lo then
        return lo
    elseif v > hi then
        return hi
    end
    return v
end

-- Orb count and size scale for a gain. 0, 1 when there is nothing to show.
-- density is an orb multiplier in percent (100 = normal). Square-root curve so small kills still read.
function OrbMath.Count(gain, xpMax, density, cap)
    if type(gain) ~= "number" or type(xpMax) ~= "number" or type(density) ~= "number" or type(cap) ~= "number" then
        return 0, 1
    end
    if gain <= 0 or xpMax <= 0 or cap < 1 then
        return 0, 1
    end
    local percentOfLevel = gain / xpMax * 100
    local raw = (3 + 5 * sqrt(percentOfLevel)) * density / 100
    local count = clamp(floor(raw + 0.5), 1, cap)
    local scale = 1
    if raw > cap then
        scale = min(1.5, sqrt(raw / cap))
    end
    return count, scale
end

-- Split n orbs into blue and purple by the rested share of the gain (rested = the bonus XP, amount = the whole gain).
-- Returns nBlue, nPurple.
function OrbMath.RestedSplit(n, amount, rested)
    if type(rested) ~= "number" or type(amount) ~= "number" or amount <= 0 then
        return n, 0
    end
    local nPurple = clamp(floor(n * rested / amount + 0.5), 0, n)
    return n - nPurple, nPurple
end

-- Where a burst's rested bonus comes from. Chat wins; else a fresh exhaustion-pool drop for this kill; else an estimate
-- from the current pool; else nothing.
-- Forever drains the pool by the FULL gain of a kill, not just the bonus (in-game log, 2026-11-15: exhDrop == delta on
-- all seven kills), and rested doubles kill XP, so the bonus is half of the XP the pool covered: bonus = covered / 2.
--   pool:     covered = min(drop, amount)
--   estimate: covered = min(amount, pool now)  (no drop seen: assume the whole gain was rested, capped by the pool)
-- Both round half up. Returns rested|nil, source = "chat" | "pool" | "estimate" | "none".
function OrbMath.RestedFallback(amount, chatRested, exhDrop, exhNow)
    if type(chatRested) == "number" then
        return chatRested, "chat"
    end
    if type(amount) ~= "number" or amount <= 0 then
        return nil, "none"
    end
    if type(exhDrop) == "number" and exhDrop > 0 then
        return floor(min(exhDrop, amount) / 2 + 0.5), "pool"
    end
    if type(exhNow) == "number" and exhNow > 0 then
        return floor(min(amount, exhNow) / 2 + 0.5), "estimate"
    end
    return nil, "none"
end

-- Pop control point for orb i of n: stratified angle, radius 45..100, pushed out 2.2x and biased upward (y is up).
-- (x0, y0) is the burst origin, rand() a random source in [0, 1). Optional spread scales the radius (default 1) and
-- lift is the upward bias (default 0.35); the stream that follows a corpse pop uses a tight spread and little lift.
-- Returns c1x, c1y (the first Bezier control point) and the radius.
function OrbMath.PopControl(i, n, x0, y0, rand, spread, lift)
    spread = spread or 1
    lift = lift or 0.35
    local angle = ((i - 1) + rand() * 0.8) / n * 2 * math.pi
    local radius = (45 + rand() * 55) * spread
    return x0 + math.cos(angle) * radius * 2.2, y0 + (0.8 * math.sin(angle) + lift) * radius * 2.2, radius
end

-- Unit direction the pop orbs exit along: from the estimated pop point (px, py) towards the stream origin (sx, sy).
-- When those are closer than minDist (default 20) the stream starts at the pop, so use the direction from the pop
-- towards the destination (tx, ty). Fully degenerate -> straight up (0, 1).
function OrbMath.ExitVector(sx, sy, px, py, tx, ty, minDist)
    minDist = minDist or 20
    local vx, vy = sx - px, sy - py
    local distance = sqrt(vx * vx + vy * vy)
    if distance >= minDist and distance > 0 then
        return vx / distance, vy / distance
    end
    vx, vy = tx - px, ty - py
    distance = sqrt(vx * vx + vy * vy)
    if distance > 1e-6 then
        return vx / distance, vy / distance
    end
    return 0, 1
end

-- Second control point of the pop-then-home curve: hugs the destination's x, sits 0.30 * dist0 above it. (c1x, c1y) is
-- the first control point, (dx, dy) the destination, dist0 the pop-to-destination distance.
function OrbMath.HomeControl(c1x, c1y, dx, dy, dist0)
    return dx + (c1x - dx) * 0.15, dy + 0.30 * dist0
end

-- Pop ease: fast start (ease-out half, weight w) blended with a slow-in finish (ease-in half, weight 1 - w).
-- p is progress 0..1 (clamped). w defaults to 0.5 (launch slope 1.5); crossfade uses a smaller w for a gentler launch.
function OrbMath.PopEase(p, w)
    p = clamp(p, 0, 1)
    w = w or 0.5
    return w * (1 - (1 - p) ^ 3) + (1 - w) * p ^ 2.2
end

-- Corpse-pop ring angle (radians) of orb i of n: golden-ratio interleave plus jitter, so the first k orbs (the rested
-- ones) are spread around the whole ring instead of taking one half. rand() is in [0, 1).
function OrbMath.RingAngle(i, n, rand)
    return ((((i - 1) * 0.618034) % 1) + rand() * 0.8 / n) * 2 * math.pi
end

-- Cubic Bezier point at t (0..1) through control points (x0, y0) .. (x3, y3); w0..w3 are the Bernstein weights.
function OrbMath.Cubic(t, x0, y0, x1, y1, x2, y2, x3, y3)
    local u = 1 - t
    local w0, w1, w2, w3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return w0 * x0 + w1 * x1 + w2 * x2 + w3 * x3, w0 * y0 + w1 * y1 + w2 * y2 + w3 * y3
end

-- Screen-space point (frame effective scale) -> UIParent space.
function OrbMath.ToUIParent(x, y, frameScale, parentScale)
    local ratio = frameScale / parentScale
    return x * ratio, y * ratio
end

-- Point on the XP bar's fill edge: x at the xp fraction, y at the vertical middle.
function OrbMath.FillEdge(left, bottom, width, height, xp, xpMax)
    local frac = 0
    if type(xpMax) == "number" and xpMax > 0 and type(xp) == "number" then
        frac = clamp(xp / xpMax, 0, 1)
    end
    return left + width * frac, bottom + height / 2
end

-- Landing point on a StatusBar fill edge, whichever way it fills. frac (0..1, clamped) is how full the bar is.
-- Horizontal: x = left + w * frac (right - w * frac when reversed), y at the vertical middle.
-- Vertical: y = bottom + h * frac (top - h * frac when reversed), x at the horizontal middle.
function OrbMath.StatusFill(left, bottom, width, height, frac, vertical, reverse)
    frac = clamp(frac, 0, 1)
    if vertical then
        local y = reverse and (bottom + height - height * frac) or (bottom + height * frac)
        return left + width / 2, y
    end
    local x = reverse and (left + width - width * frac) or (left + width * frac)
    return x, bottom + height / 2
end

-- Did the bar wrap between two readings? A level-up leaves less XP than before, or changes the maximum while the XP
-- moved. Reading it from the numbers means the answer doesn't depend on whether PLAYER_LEVEL_UP arrived before or after
-- the update. A new maximum with the same XP is the second half of a split level-up update (the wrap was already
-- counted), not another level.
function OrbMath.LeveledUp(oldXP, oldMax, newXP, newMax)
    return newXP < oldXP or (newMax ~= oldMax and newXP ~= oldXP)
end

-- XP gained between two PLAYER_XP_UPDATE readings; wraps across a level-up. Never negative.
function OrbMath.XPDelta(oldXP, oldMax, newXP, newMax)
    local delta
    if OrbMath.LeveledUp(oldXP, oldMax, newXP, newMax) then
        delta = (oldMax - oldXP) + newXP
    else
        delta = newXP - oldXP
    end
    return max(0, delta)
end

-- Nearest permitted slider value: clamped to [lo, hi], snapped to the step grid that starts at lo, float dust removed.
-- Returns nil for anything that is not a finite number (so callers can ignore bad input).
function OrbMath.Snap(v, lo, hi, step)
    if type(v) ~= "number" or v ~= v or v == math.huge or v == -math.huge then
        return nil
    end
    v = clamp(v, lo, hi)
    if type(step) == "number" and step > 0 then
        v = lo + floor((v - lo) / step + 0.5) * step
        v = tonumber(string.format("%.4f", v)) -- no float dust (0.15000000000000002)
    end
    return clamp(v, lo, hi)
end

-- Text typed into a value box -> number, or nil. Tolerates spaces and a trailing %, "px" or "s" unit.
function OrbMath.ParseNumber(text)
    if type(text) ~= "string" then
        return nil
    end
    text = text:gsub("%s+", ""):gsub("px$", ""):gsub("[%%s]+$", "")
    return tonumber(text)
end

-- Does value differ from its default? Numbers within 1e-4, colour tables per channel within 0.005, nil only equals
-- nil (so an unset default, like targetFrame, differs whenever a value is set).
function OrbMath.Differs(value, default)
    if value == nil or default == nil then
        return value ~= default
    end
    if type(value) == "number" and type(default) == "number" then
        return math.abs(value - default) > 1e-4
    end
    if type(value) == "table" and type(default) == "table" then
        for i = 1, max(#value, #default) do
            local valueChannel, defaultChannel = value[i], default[i]
            local bad = type(valueChannel) ~= "number" or type(defaultChannel) ~= "number"
            if bad or math.abs(valueChannel - defaultChannel) > 0.005 then
                return true
            end
        end
        return false
    end
    return value ~= default
end

-- Diameter of the round arrival glow: 1.3 x the smaller side of the destination frame, clamped to [32, 160]; without
-- a usable frame size, 6 x the orb size.
function OrbMath.GlowDiameter(w, h, orbSize)
    if type(w) == "number" and type(h) == "number" and w > 0 and h > 0 then
        return clamp(min(w, h) * 1.3, 32, 160)
    end
    return (type(orbSize) == "number" and orbSize or 14) * 6
end

-- Arrival glow intensity. percent (25-200, default 100) -> alpha multiplier k = percent / 100 and size multiplier
-- 0.8 + 0.2k. Anything that is not a finite number counts as 100%; the percent is clamped to [25, 200].
function OrbMath.GlowIntensity(percent)
    local k = 1
    if type(percent) == "number" and percent == percent and percent ~= math.huge and percent ~= -math.huge then
        k = clamp(percent, 25, 200) / 100
    end
    return k, 0.8 + 0.2 * k
end

-- Landing point plus the user's offset (UIParent px). Non-numeric offsets count as 0.
local function finiteOr0(v)
    if type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge then
        return v
    end
    return 0
end

function OrbMath.ApplyOffset(x, y, ox, oy)
    return x + finiteOr0(ox), y + finiteOr0(oy)
end

-- Zoom-aware mob anchor. A mob's body sits below its nameplate by a distance that shrinks as the camera zooms out, so
-- the offset (px below the plate's BOTTOM) is modelled as a + b / zoom, with zoom floored at zMin so a camera pushed
-- into first person can't send the anchor off to infinity. nil when any input is not a finite number.
local function finite(v)
    return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

function OrbMath.ZoomOffset(z, a, b, zMin)
    if not (finite(z) and finite(a) and finite(b) and finite(zMin)) then
        return nil
    end
    return a + b / max(z, zMin)
end

-- Least-squares fit of off = a + b * x with x = 1 / max(z, zMin) over calibration points { z = , off = } (entries
-- that aren't two finite numbers with z > 0 are skipped). Returns a, b, or nil with fewer than two usable points or
-- when every point shares one x (nothing to fit a slope to). A negative slope (zooming out would push the anchor
-- further down) is noise, so it falls back to the flat mean with b = 0.
function OrbMath.FitZoom(points, zMin)
    -- Running sums for the least-squares fit: n points, sx = sum x, sy = sum off, sxx = sum x^2, sxy = sum x * off.
    if type(points) ~= "table" or not finite(zMin) or zMin <= 0 then
        return nil
    end
    local n, sx, sy, sxx, sxy = 0, 0, 0, 0, 0
    local xs = {}
    for _, point in ipairs(points) do
        if type(point) == "table" and finite(point.z) and finite(point.off) and point.z > 0 then
            local x = 1 / max(point.z, zMin)
            n = n + 1
            xs[n] = x
            sx, sy, sxx, sxy = sx + x, sy + point.off, sxx + x * x, sxy + x * point.off
        end
    end
    if n < 2 then
        return nil
    end
    local det = n * sxx - sx * sx
    local lo, hi = xs[1], xs[1]
    for i = 2, n do
        lo, hi = min(lo, xs[i]), max(hi, xs[i])
    end
    if hi - lo < 1e-9 then
        return nil
    end
    local b = (n * sxy - sx * sy) / det
    if b < 0 then
        return sy / n, 0
    end
    return (sy - b * sx) / n, b
end

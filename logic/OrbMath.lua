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
    local pct = gain / xpMax * 100
    local raw = (3 + 5 * sqrt(pct)) * density / 100
    local n = clamp(floor(raw + 0.5), 1, cap)
    local scale = 1
    if raw > cap then
        scale = min(1.5, sqrt(raw / cap))
    end
    return n, scale
end

-- Split n orbs into blue and purple by the rested share of the gain. Returns nBlue, nPurple.
function OrbMath.RestedSplit(n, amount, rested)
    if type(rested) ~= "number" or type(amount) ~= "number" or amount <= 0 then
        return n, 0
    end
    local nPurple = clamp(floor(n * rested / amount + 0.5), 0, n)
    return n - nPurple, nPurple
end

-- Quadratic Bezier point at t.
function OrbMath.Bezier(t, x0, y0, cx, cy, x1, y1)
    local u = 1 - t
    local a, b, c = u * u, 2 * u * t, t * t
    return a * x0 + b * cx + c * x1, a * y0 + b * cy + c * y1
end

-- Cubic ease in/out, t clamped to [0, 1].
function OrbMath.EaseInOut(t)
    t = clamp(t, 0, 1)
    if t < 0.5 then
        return 4 * t * t * t
    end
    local v = -2 * t + 2
    return 1 - v * v * v / 2
end

-- Control point: midpoint + perpendicular jitter ((rand() - 0.5) * 0.6 * dist) + upward lift (0.25 * dist).
function OrbMath.ControlPoint(x0, y0, x1, y1, rand)
    local mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    local dx, dy = x1 - x0, y1 - y0
    local dist = sqrt(dx * dx + dy * dy)
    if dist == 0 then
        return mx, my
    end
    local off = (rand() - 0.5) * 0.6 * dist
    return mx + (-dy / dist) * off, my + (dx / dist) * off + 0.25 * dist
end

-- Pop control point for orb i of n: stratified angle, radius 45..100, pushed out 2.2x and biased upward (y is up).
-- Returns c1x, c1y, R.
function OrbMath.PopControl(i, n, x0, y0, rand)
    local ang = ((i - 1) + rand() * 0.8) / n * 2 * math.pi
    local r = 45 + rand() * 55
    return x0 + math.cos(ang) * r * 2.2, y0 + (0.8 * math.sin(ang) + 0.35) * r * 2.2, r
end

-- Second control point of the pop-then-home curve: hugs the destination's x, sits 0.30 * dist0 above it.
function OrbMath.HomeControl(c1x, c1y, dx, dy, dist0)
    return dx + (c1x - dx) * 0.15, dy + 0.30 * dist0
end

-- Pop ease: fast start (ease-out half) blended with a slow-in finish (ease-in half). p clamped to [0, 1].
function OrbMath.PopEase(p)
    p = clamp(p, 0, 1)
    return 0.5 * (1 - (1 - p) ^ 3) + 0.5 * p ^ 2.2
end

-- Anchored flight: the plate centre P is unknown (anchor-only), so write the cubic Bezier as B = a * P + k where
-- P0 = P + s, C1 = P + o, C2 = D + 0.15 * (C1 - D) + (0, L) and e is the eased parameter. Scalars in and out so the
-- hot loop allocates nothing. Returns a, kx, ky.
local HOME_PULL = 0.15
function OrbMath.AnchoredWeights(e, sx, sy, ox, oy, dx, dy, L)
    local u = 1 - e
    local b0, b1, b2, b3 = u * u * u, 3 * u * u * e, 3 * u * e * e, e * e * e
    local hx = (1 - HOME_PULL) * dx + HOME_PULL * ox
    local hy = (1 - HOME_PULL) * dy + HOME_PULL * oy + L
    return b0 + b1 + b2 * HOME_PULL, b0 * sx + b1 * ox + b2 * hx + b3 * dx, b0 * sy + b1 * oy + b2 * hy + b3 * dy
end

-- Cubic Bezier point at t.
function OrbMath.Cubic(t, x0, y0, x1, y1, x2, y2, x3, y3)
    local u = 1 - t
    local a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3
end

-- Screen-space point (frame effective scale) -> UIParent space.
function OrbMath.ToUIParent(x, y, frameScale, parentScale)
    local k = frameScale / parentScale
    return x * k, y * k
end

-- Point on the XP bar's fill edge: x at the xp fraction, y at the vertical middle.
function OrbMath.FillEdge(left, bottom, width, height, xp, xpMax)
    local frac = 0
    if type(xpMax) == "number" and xpMax > 0 and type(xp) == "number" then
        frac = clamp(xp / xpMax, 0, 1)
    end
    return left + width * frac, bottom + height / 2
end

-- XP gained between two PLAYER_XP_UPDATE readings; wraps across a level-up. Never negative.
function OrbMath.XPDelta(oldXP, oldMax, newXP, newMax, leveled)
    local delta
    if leveled or newXP < oldXP then
        delta = (oldMax - oldXP) + newXP
    else
        delta = newXP - oldXP
    end
    return max(0, delta)
end

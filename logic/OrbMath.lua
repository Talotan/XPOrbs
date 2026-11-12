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
function OrbMath.Count(gain, xpMax, density, cap)
    if type(gain) ~= "number" or type(xpMax) ~= "number" or type(density) ~= "number" or type(cap) ~= "number" then
        return 0, 1
    end
    if gain <= 0 or xpMax <= 0 or cap < 1 then
        return 0, 1
    end
    local raw = gain / xpMax * density
    local n = clamp(floor(raw + 0.5), 1, cap)
    local scale = 1
    if raw > cap then
        scale = min(2, sqrt(raw / cap))
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

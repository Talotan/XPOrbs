local ADDON, ns = ...

-- Orb renderer: one overlay frame, a hand-rolled texture pool and a single OnUpdate driver that only runs
-- while orbs or the arrival flash are alive. Frames are created lazily on the first burst.

local Orbs = {}
ns.Orbs = Orbs

local OrbMath = ns.OrbMath
local Target = ns.Target

local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local FLASH_TEX = "Interface\\AddOns\\XPOrbs\\media\\flash"

local TWO_PI = math.pi * 2
local random = math.random
local floor, min, sqrt, cos, sin = math.floor, math.min, math.sqrt, math.cos, math.sin

local EXTRAS = 3 -- ceiling formula: cap * (1 + EXTRAS) + 8. Per orb: sparkle + 2 trail ghosts beyond the orb itself
local GLOW = 1.8 -- the orb art fades to nothing at its rim, so draw it larger than db.size
local SPARKLE = 2.4
local STAGGER = 0.25 -- max start delay
local START_RADIUS = 12
local SHRINK_FROM = 0.8 -- shrink to 60% over the last 20% of the flight
local FADE_IN = 0.1
local GHOST_STEP = 0.04
local FLASH_TIME = 0.3

local overlay, driver, flash
local freeTex, texCreated, texInUse = {}, 0, 0
local live, nLive = {}, 0
local freeRec = {}
local active = false
local arrivedRecently, flashAge, flashOn = 0, 0, false

local function db()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function ceiling()
    return db().cap * (1 + EXTRAS) + 8
end

local function ensureFrames()
    if overlay then
        return
    end
    overlay = CreateFrame("Frame", nil, UIParent)
    overlay:SetAllPoints(UIParent)
    overlay:SetFrameStrata("HIGH")
    overlay:EnableMouse(false)
    overlay:Show()
    driver = CreateFrame("Frame")
    Orbs.driver = driver
    flash = overlay:CreateTexture(nil, "OVERLAY")
    flash:SetTexture(FLASH_TEX)
    flash:SetBlendMode("ADD")
    flash:Hide()
    texCreated = 1 -- the flash counts towards the ceiling
end

local function acquire(path, sub, r, g, b)
    local tex = freeTex[#freeTex]
    if tex then
        freeTex[#freeTex] = nil
    else
        tex = overlay:CreateTexture(nil, "ARTWORK")
        tex:SetBlendMode("ADD")
        texCreated = texCreated + 1
    end
    texInUse = texInUse + 1
    tex:SetTexture(path)
    tex:SetDrawLayer("ARTWORK", sub)
    tex:SetVertexColor(r, g, b)
    tex:SetAlpha(0)
    tex:Hide()
    tex.xoShown = false
    return tex
end

local function release(tex)
    tex:Hide()
    tex:ClearAllPoints()
    tex.xoShown = false
    freeTex[#freeTex + 1] = tex
    texInUse = texInUse - 1
end

local function place(tex, x, y, size, alpha)
    if not tex.xoShown then
        tex:Show()
        tex.xoShown = true
    end
    tex:ClearAllPoints()
    tex:SetPoint("CENTER", overlay, "BOTTOMLEFT", x, y)
    tex:SetSize(size, size)
    tex:SetAlpha(alpha)
end

local function hideTex(tex)
    if tex.xoShown then
        tex:Hide()
        tex.xoShown = false
    end
end

local function newRec()
    local n = #freeRec
    if n > 0 then
        local r = freeRec[n]
        freeRec[n] = nil
        return r
    end
    return {}
end

local function freeOrb(o)
    release(o.orb)
    release(o.spark)
    if o.g1 then
        release(o.g1)
        release(o.g2)
    end
    o.orb, o.spark, o.g1, o.g2 = nil, nil, nil, nil
    freeRec[#freeRec + 1] = o
end

local function drawOrb(o, p, dx, dy)
    local ex, ey = OrbMath.Bezier(OrbMath.EaseInOut(p), o.x0, o.y0, o.cx, o.cy, dx, dy)
    local s = o.size
    if p > SHRINK_FROM then
        s = s * (1 - 0.4 * (p - SHRINK_FROM) / (1 - SHRINK_FROM))
    end
    local a = p < FADE_IN and p / FADE_IN or 1
    place(o.orb, ex, ey, s * GLOW, a)
    place(o.spark, ex, ey, s * SPARKLE, a * 0.8)
    o.spark:SetRotation(o.rot0 + TWO_PI * (o.el - o.delay))
    if o.g1 then
        local pk = p - GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Bezier(OrbMath.EaseInOut(pk), o.x0, o.y0, o.cx, o.cy, dx, dy)
            place(o.g1, gx, gy, s * GLOW, a * 0.5)
        else
            hideTex(o.g1)
        end
        pk = p - 2 * GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Bezier(OrbMath.EaseInOut(pk), o.x0, o.y0, o.cx, o.cy, dx, dy)
            place(o.g2, gx, gy, s * GLOW, a * 0.25)
        else
            hideTex(o.g2)
        end
    end
end

local function onUpdate(self, dt)
    local dx, dy = Target:GetDestination()
    local i = 1
    while i <= nLive do
        local o = live[i]
        o.el = o.el + dt
        local t = o.el - o.delay
        if t < 0 then
            i = i + 1
        else
            local p = t / o.dur
            if p >= 1 then
                arrivedRecently = arrivedRecently + 1
                flashAge, flashOn = 0, true
                freeOrb(o)
                live[i] = live[nLive]
                live[nLive] = nil
                nLive = nLive - 1
            else
                drawOrb(o, p, dx, dy)
                i = i + 1
            end
        end
    end

    if flashOn then
        flashAge = flashAge + dt
        if flashAge >= FLASH_TIME then
            flashOn, arrivedRecently = false, 0
            flash:Hide()
        else
            local c = ns.db.color
            local a = min(1, 0.35 + 0.05 * arrivedRecently) * (1 - flashAge / FLASH_TIME)
            local w = ns.db.size * 8
            flash:SetVertexColor(c[1], c[2], c[3])
            flash:ClearAllPoints()
            flash:SetPoint("CENTER", overlay, "BOTTOMLEFT", dx, dy)
            flash:SetSize(w, w / 4)
            flash:SetAlpha(a)
            flash:Show()
        end
    end

    if nLive == 0 and not flashOn then
        active = false
        self:SetScript("OnUpdate", nil)
    end
end

local function lighten(c)
    return c + (1 - c) * 0.5
end

-- Burst{ x=, y= (UIParent coords), n=, scale= (default 1), nPurple= (default 0), kind= }. n <= 0 is a no-op.
function Orbs:Burst(p)
    if type(p) ~= "table" or type(p.n) ~= "number" or p.n < 1 then
        return
    end
    local d = db()
    ensureFrames()
    local n = floor(p.n)
    local scale = type(p.scale) == "number" and p.scale or 1
    local nPurple = type(p.nPurple) == "number" and p.nPurple or 0
    if not d.restedTint then
        nPurple = 0
    end
    local x, y = p.x, p.y
    if type(x) ~= "number" or type(y) ~= "number" then
        x, y = UIParent:GetWidth() / 2, UIParent:GetHeight() * 0.65
    end
    local dx, dy = Target:GetDestination()
    local trail = d.trail
    local need = trail and 1 + EXTRAS or 2 -- orb + sparkle (+ 2 ghosts)
    local limit = ceiling() - 1 -- the arrival flash holds one slot

    for i = 1, n do
        if texInUse + need > limit then
            break
        end
        local c = (i <= nPurple) and d.restedColor or d.color
        local r, g, b = c[1], c[2], c[3]
        local o = newRec()
        local ang, rad = random() * TWO_PI, START_RADIUS * sqrt(random())
        o.x0, o.y0 = x + cos(ang) * rad, y + sin(ang) * rad
        o.cx, o.cy = OrbMath.ControlPoint(o.x0, o.y0, dx, dy, random)
        o.delay = random() * STAGGER
        o.dur = d.flightTime * (0.85 + random() * 0.3)
        o.el = 0
        o.size = d.size * scale
        o.rot0 = random() * TWO_PI
        o.orb = acquire(ORB_TEX, 1, r, g, b)
        o.spark = acquire(SPARKLE_TEX, 2, lighten(r), lighten(g), lighten(b))
        if trail then
            o.g1 = acquire(ORB_TEX, 0, r, g, b)
            o.g2 = acquire(ORB_TEX, 0, r, g, b)
        end
        nLive = nLive + 1
        live[nLive] = o
    end

    if nLive > 0 and not active then
        active = true
        driver:SetScript("OnUpdate", onUpdate)
    end
end

-- active, texturesInUse, texturesCreated, ceiling
function Orbs:Info()
    return active, texInUse, texCreated, ceiling()
end

local function testOrigin()
    local ok, e = pcall(function()
        return ns.Plates and ns.Plates.TargetEntry and ns.Plates:TargetEntry()
    end)
    if ok and type(e) == "table" and type(e.x) == "number" and type(e.y) == "number" then
        return e.x, e.y
    end
    local okc, cx, cy = pcall(GetCursorPosition)
    local oks, s = pcall(UIParent.GetEffectiveScale, UIParent)
    if okc and oks and type(cx) == "number" and type(cy) == "number" and type(s) == "number" and s > 0 then
        return cx / s, cy / s
    end
    return UIParent:GetWidth() / 2, UIParent:GetHeight() / 2
end

-- /xporbs test [pct] [rested]
function ns.commands.test(arg)
    local d = db()
    local pct, rested = 5, false
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        else
            local v = tonumber(tok)
            if v and v > 0 then
                pct = min(v, 1000)
            end
        end
    end
    local okm, xpMax = pcall(UnitXPMax, "player")
    if not okm or type(xpMax) ~= "number" or xpMax <= 0 then
        xpMax = 1000 -- max level or no data: any positive number gives the same orb count
    end
    local gain = pct / 100 * xpMax
    local n, scale = OrbMath.Count(gain, xpMax, d.density, d.cap)
    local nPurple = 0
    if rested then
        local _
        _, nPurple = OrbMath.RestedSplit(n, gain, gain / 2)
    end
    local x, y = testOrigin()
    Orbs:Burst({ x = x, y = y, n = n, scale = scale, nPurple = nPurple, kind = "test" })
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f", pct, n, nPurple, scale))
end

table.insert(ns.statusProviders, function()
    Target:GetDestination()
    return string.format(
        "orbs: driver=%s, live textures=%d, pool=%d/%d, dest=%s, fallback=%s",
        active and "active" or "idle",
        texInUse,
        texCreated,
        ceiling(),
        tostring(Target.lastName),
        Target.lastOk and "no" or "yes"
    )
end)

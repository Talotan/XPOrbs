-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Orb renderer: one overlay frame, a hand-rolled texture pool and a single OnUpdate driver that only runs
-- while orbs or the arrival flash are alive. Frames are created lazily on the first burst.

local Orbs = {}
ns.Orbs = Orbs

local OrbMath = ns.OrbMath
local Target = ns.Target

local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
Orbs.ORB_TEX = ORB_TEX -- Calib.lua draws its marker with the same art
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local FLASH_TEX = "Interface\\AddOns\\XPOrbs\\media\\flash"
-- the six notes of each chime voice (built once: nothing is concatenated while orbs fly)
local VOICE_PATHS = { coin = {}, glass = {} }
for voice, paths in pairs(VOICE_PATHS) do
    for i = 1, 6 do
        paths[i] = "Interface\\AddOns\\XPOrbs\\media\\" .. voice .. i .. ".ogg"
    end
end

local TWO_PI = math.pi * 2
local HALF_PI = math.pi / 2
local random = math.random
local floor, min, max, sqrt, cos, sin = math.floor, math.min, math.max, math.sqrt, math.cos, math.sin

-- Tunables (retune here).
local EXTRAS = 4 -- ceiling formula: cap * (1 + EXTRAS) * 2 + 8. Per orb: orb + underlay + sparkle + 2 trail ghosts
local MIN_DUR = 0.05 -- shortest allowed flight, so a bad flightTime can never strand an orb
local STRESS_TIME = 2.0 -- /xporbs test stress spreads its bursts over this many seconds
local STRESS_DEFAULT, STRESS_MAX = 20, 100
local GLOW = 2.0 -- the orb art fades to nothing at its rim, so draw it larger than db.size
local SPARKLE = 1.9
local SPARKLE_ALPHA = 0.6
local SPARKLE_WHITE = 0.15 -- sparkle tint = lerp(colour, white, this)
local STAGGER = 0.15 -- max start delay
local STAGGER_POP = 0.08 -- ... when the stream follows a corpse pop (it reads as one continuous effect)
local RESTED_DELAY = 0.12 -- extra start delay for rested orbs
local RESTED_SIZE = 1.15
local START_RADIUS = 6
local SHRINK_FROM = 0.8 -- shrink to 60% over the last 20% of the flight
local FADE_IN = 0.1
local FADE_IN_POP = 0.15 -- ... after a pop
-- PopControl radius multiplier / upward bias for the stream after a pop (defaults 1 / 0.35)
local POP_STREAM_SPREAD, POP_STREAM_LIFT = 0.45, 0.10
local GHOST_STEP = 0.015 -- in p, before easing
local GHOST1_ALPHA, GHOST1_SIZE = 0.55, 0.85
local GHOST2_ALPHA, GHOST2_SIZE = 0.30, 0.70
local UNDER_K = 0.25 -- dark underlay = this fraction of the orb's own colour, so bright orbs keep their hue
local UNDER_ALPHA, UNDER_SIZE = 0.45, 1.25
local FLASH_TIME = 0.4
local FLASH_WHITE = 0.45 -- arrival flash tint = lerp(colour, white, this)
local FLASH_ALPHA, FLASH_STEP = 0.6, 0.08 -- arrival flash base alpha, added per recent arrival
local FLASH_W, FLASH_ASPECT = 12, 7 -- width = size * FLASH_W, height = width / FLASH_ASPECT
-- Corpse pop (a burst of orbs at the dead mob's nameplate, drawn relative to a tiny frame anchored ONLY to the plate).
local POP_MAX = 12 -- orbs per pop
local POP_FRAMES = 8 -- concurrent pops (one pooled frame each)
local POP_TIME = 0.55
local POP_Y = -20 -- offset of the pop frame from the plate centre (between the name and the head)
local POP_R_MIN, POP_R_MAX = 30, 55 -- final radius
local POP_DRIFT = 12 -- extra upward drift, px
local POP_SIZE = 1.2 -- start size multiplier
local POP_UNDER_ALPHA = 0.35 -- underlay alpha of pop orbs (smudges on mid-tone grass at 0.45)
local POP_SHRINK_FROM = 0.75 -- size shrinks to 0 over p in [0.75, 1]
local POP_FADE_FROM = 0.7 -- alpha 1 -> 0 over p in [0.7, 1]
local POP_EXIT_FROM = 0.45 -- from here the pop orbs launch along the exit vector towards the stream
local POP_EXIT_DIST = 140 -- px travelled at p = 1 (grows with q^2)
local POP_GATHER = 0.5 -- the radial offset shrinks by this fraction at p = 1 (gather, then launch)
local POP_FADE_OUT = 0.1 -- seconds a pop fades when its plate is reused for another unit
local STREAM_DELAY = 0.30 -- extra start delay of the stream when a pop happened, so the pop reads first
-- Crossfade style: orbs fly from an ESTIMATED mob position P-hat (plates can't be measured; see logic/MobEstimate.lua,
-- which owns the default point). Copy A is drawn relative to the plate's BOTTOM (exact if the estimate is right),
-- copy B in screen space. Each orb first blooms at the plate as copy A only (the hold), then flies; A fades out and B
-- fades in (equal power) over flight p in [XF_START, XF_END], measured after the hold.
local XF_START, XF_END = 0.12, 0.30
local XF_HOLD = 0.22 -- s: bloom at the plate (copy A only) before the flight timeline starts
local XF_BLOOM_R = 18 -- px: ring radius reached (ease-out cubic) by the end of the hold
local XF_BLOOM_SIZE = 1.5 -- start-size multiplier during the hold, easing to 1.0 by its end
local XF_FADE_IN = 0.06 -- s: alpha fade-in at birth
local XF_FLIGHT = 1.2 -- multiplier on flightTime for crossfade orbs
local XF_EASE_OUT = 0.25 -- ease-out weight of the crossfade launch (PopEase default 0.5 = launch slope 1.5)
-- Per-orb profiles of the plate-copy machinery (o.prof), static tables built once so nothing allocates per frame.
-- s0/s1: flight p range of the A -> B crossfade; bloom: seconds the bloom from P-hat to the ring point takes;
-- bsize: start-size multiplier of the bloom; fadeIn: alpha fade-in seconds; flight: flightTime multiplier;
-- ease: ease-out weight of the launch.
-- hold: base seconds before the flight; rmin/rmax/drift: ring radius range and extra upward drift of the ring point.
local XF_PROFILE = { s0 = XF_START, s1 = XF_END, bloom = XF_HOLD, bsize = XF_BLOOM_SIZE, fadeIn = XF_FADE_IN,
    flight = XF_FLIGHT, ease = XF_EASE_OUT, hold = XF_HOLD, rmin = XF_BLOOM_R, rmax = XF_BLOOM_R, drift = 0 }
-- Mob style: one burst of orbs at the mob (like the pop, all born within MOB_BORN), each launching after
-- MOB_HOLD + up to STAGGER_POP seconds, so it reads as one pop and then a stream. The ring radius (POP_R_MIN..MAX plus
-- POP_DRIFT) is per orb; the bloom ends at MOB_HOLD and the orb idles on its ring point until its own launch. The
-- crossfade is early and quick (flight p 0.04..0.20) so a good P-hat makes the hand-off invisible.
local MOB_HOLD = 0.35
local MOB_BORN = 0.04
local MOB_PROFILE = { s0 = 0.04, s1 = 0.20, bloom = MOB_HOLD, bsize = 1.4, fadeIn = 0.06, flight = 1.1, ease = 0.35,
    hold = MOB_HOLD, rmin = POP_R_MIN, rmax = POP_R_MAX, drift = POP_DRIFT }

local overlay, driver, flash, flashShape
local freeTex, texCreated, texInUse = {}, 0, 0
local live, nLive = {}, 0
local freeRec = {}
local active = false
local arrivedRecently, flashAge, flashOn, flashRested = 0, 0, false, false
local freePop, popsCreated = {}, 0
local pops, nPops = {}, 0
local popErrSeen = false
local xfs, nXf = {}, 0 -- crossfade pop frames alive (their orbs are driven from the stream loop)
local portraitMode = false -- decided once per Burst (Target:PortraitMode): orbs aim at the portrait centre, round flash
local chime = ns.Chime.New({ now = GetTime, gap = 0.07, perBurst = 6 })
local soundDead = false -- the first sound failure switches the chime off for the session
Orbs.chime = chime -- exposed for tests
local burstSeq = 0 -- burst key counter; every orb carries its burst's key (o.bk)
local burstLeft = {} -- burst key -> orbs of that burst still alive (the chime forgets a burst when it hits 0)

local function db()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

-- Room for two full-cap bursts, so a pull that kills several mobs at once doesn't leave the later kills without orbs.
local function ceiling()
    return db().cap * (1 + EXTRAS) * 2 + 8
end

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function num(v)
    return type(v) == "number" and readable(v)
end

-- Zoom anchor. The camera zoom as a readable number, or nil (API missing, errors, secret, not a number).
function Orbs.ReadZoom()
    if type(GetCameraZoom) ~= "function" then
        return nil
    end
    local ok, z = pcall(GetCameraZoom)
    if ok and num(z) and z == z then
        return z
    end
    return nil
end

-- Decided once per burst, never per frame: the y offset (negative, px below the plate's BOTTOM) of the body anchor, or
-- nil when the option is off or the zoom can't be read (every frame then keeps its own default anchor). Also keeps
-- the last zoom/offset for /xporbs status.
local function zoomAnchorY(d)
    if not d.zoomAnchor then
        return nil
    end
    local z = Orbs.ReadZoom()
    local off = z and OrbMath.ZoomOffset(z, d.zoomA, d.zoomB, d.zoomMin)
    if not off then
        return nil
    end
    Orbs.lastZoom, Orbs.lastOffset = z, off
    return -off
end

-- (relPoint, y) of a plate-anchored frame's single anchor: the body anchor when zy is set, else the caller's default.
-- Shared by the pop, the crossfade copy and any later style that hangs a frame off a plate.
local function plateAnchor(zy, relPoint, y)
    if zy then
        return "BOTTOM", zy
    end
    return relPoint, y
end

-- The orb colour for the next burst: the player's class colour when db.classColor is on and the API answers, else
-- db.color. One reusable table, filled in once per burst (never per frame); the arrival flash reads it too.
local normalC = { 0.2, 0.5, 1 }

local function classRGB()
    if not UnitClass then
        return nil
    end
    local ok, r, g, b = pcall(function()
        local _, classFile = UnitClass("player")
        if type(classFile) ~= "string" then
            return nil
        end
        local c = nil
        if C_ClassColor and C_ClassColor.GetClassColor then
            c = C_ClassColor.GetClassColor(classFile)
        end
        if not c and RAID_CLASS_COLORS then
            c = RAID_CLASS_COLORS[classFile]
        end
        if c then
            return c.r, c.g, c.b
        end
        return nil
    end)
    if ok and type(r) == "number" and type(g) == "number" and type(b) == "number" and readable(r) then
        return r, g, b
    end
    return nil
end

local function resolveNormal(d)
    local c = d.color
    local r, g, b = c[1], c[2], c[3]
    if d.classColor then
        local cr, cg, cb = classRGB()
        if cr then
            r, g, b = cr, cg, cb
        end
    end
    normalC[1], normalC[2], normalC[3] = r, g, b
    return normalC
end

-- Circular shape = the destination is a round frame (a portrait): the orbs aim at its centre, not the XP fill edge.
-- Independent of Show glow (v0.14): the shape describes the target frame, not just the flash.
local function aimCentre(d)
    return portraitMode or d.glowShape == "round"
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
    Orbs.overlay = overlay
    driver = CreateFrame("Frame")
    Orbs.driver = driver
    flash = overlay:CreateTexture(nil, "OVERLAY")
    flash:SetTexture(FLASH_TEX)
    flashShape = "bar"
    flash:SetBlendMode("ADD")
    flash:Hide()
    texCreated = 1 -- the flash counts towards the ceiling
end

local function acquire(path, sub, r, g, b, blend)
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
    tex:SetBlendMode(blend or "ADD")
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

-- Pop textures are positioned relative to their pop frame only (never measured, never anchored to anything else).
local function placeRel(tex, rel, x, y, size, alpha)
    if not tex.xoShown then
        tex:Show()
        tex.xoShown = true
    end
    tex:ClearAllPoints()
    tex:SetPoint("CENTER", rel, "CENTER", x, y)
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

local releasePop, dropXf -- defined with the pop code below

-- Gives an orb record and everything it holds back to the pools. Tolerates a half-built record (Burst failed midway).
local function freeOrb(o)
    local bk = o.bk
    if bk then
        o.bk = nil
        local left = (burstLeft[bk] or 1) - 1
        if left > 0 then
            burstLeft[bk] = left
        else
            burstLeft[bk] = nil
            chime:Done(bk)
        end
    end
    if o.under then
        release(o.under)
    end
    if o.orb then
        release(o.orb)
    end
    if o.spark then
        release(o.spark)
    end
    if o.g1 then
        release(o.g1)
    end
    if o.g2 then
        release(o.g2)
    end
    o.under, o.orb, o.spark, o.g1, o.g2 = nil, nil, nil, nil, nil
    if o.g then
        local g = o.g
        o.g = nil
        for j = 1, 3 do
            hideTex(g.tex[o.k + j])
        end
        g.refs = g.refs - 1
        if g.refs <= 0 then
            dropXf(g)
            releasePop(g)
        end
    end
    freeRec[#freeRec + 1] = o
end

local function smoothstep(p, prof)
    local t = (p - prof.s0) / (prof.s1 - prof.s0)
    if t <= 0 then
        return 0
    elseif t >= 1 then
        return 1
    end
    return t * t * (3 - 2 * t)
end

-- Crossfade copy A: this orb's textures on the plate-anchored frame, offset by (B - P-hat). Under pcall.
local function drawA(o, g, ex, ey, s, alpha)
    local tex, k = g.tex, o.k
    if alpha <= 0 then
        hideTex(tex[k + 1])
        hideTex(tex[k + 2])
        hideTex(tex[k + 3])
        return
    end
    local f, ox, oy = g.f, ex - o.px, ey - o.py
    placeRel(tex[k + 1], f, ox, oy, s * GLOW * UNDER_SIZE, alpha * UNDER_ALPHA)
    placeRel(tex[k + 2], f, ox, oy, s * GLOW, alpha)
    local sp = tex[k + 3]
    placeRel(sp, f, ox, oy, s * SPARKLE, alpha * SPARKLE_ALPHA)
    sp:SetRotation(o.rot0 + TWO_PI * (o.el - o.delay))
end

-- drawA under pcall; the first failure silences copy A for the whole burst frame and is logged once.
local function safeA(o, g, ex, ey, s, alpha)
    local ok, err = pcall(drawA, o, g, ex, ey, s, alpha)
    if not ok then
        g.fm = 0
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR crossfade %s", string.sub(tostring(err), 1, 120))
        end
    end
end

local function hideB(o)
    hideTex(o.under)
    hideTex(o.orb)
    hideTex(o.spark)
    if o.g1 then
        hideTex(o.g1)
        hideTex(o.g2)
    end
end

-- Crossfade hold: t seconds after the orb's birth. Copy A only, blooming from P-hat out to the ring start (o.x0, o.y0)
-- with a size boost that eases off. Copy B (screen space) stays hidden.
local function drawHold(o, t)
    local prof = o.prof
    local h = t / prof.bloom
    if h > 1 then
        h = 1
    end
    local e = 1 - (1 - h) * (1 - h) * (1 - h)
    local a = t < prof.fadeIn and t / prof.fadeIn or 1
    local g = o.g
    hideB(o)
    safeA(o, g, o.px + (o.x0 - o.px) * e, o.py + (o.y0 - o.py) * e, o.size * (1 + (prof.bsize - 1) * (1 - e)),
        a * g.fm)
end

local function drawOrb(o, p, dx, dy)
    local x0, y0, c1x, c1y = o.x0, o.y0, o.c1x, o.c1y
    local c2x, c2y = OrbMath.HomeControl(c1x, c1y, dx, dy, o.dist0)
    local ew = o.ew
    local ex, ey = OrbMath.Cubic(OrbMath.PopEase(p, ew), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
    local s = o.size
    if p > SHRINK_FROM then
        s = s * (1 - 0.4 * (p - SHRINK_FROM) / (1 - SHRINK_FROM))
    end
    local fi = o.fadeIn
    local a = p < fi and p / fi or 1
    local g = o.g
    if g then
        local w = smoothstep(p, o.prof) -- position of the crossfade; equal power keeps the sum of the two copies steady
        safeA(o, g, ex, ey, s, w >= 1 and 0 or a * cos(w * HALF_PI) * g.fm) -- cos(pi/2) is not exactly 0
        if w <= 0 then
            hideB(o)
            return
        end
        a = a * sin(w * HALF_PI)
    end
    place(o.under, ex, ey, s * GLOW * UNDER_SIZE, a * UNDER_ALPHA)
    place(o.orb, ex, ey, s * GLOW, a)
    place(o.spark, ex, ey, s * SPARKLE, a * SPARKLE_ALPHA)
    o.spark:SetRotation(o.rot0 + TWO_PI * (o.el - o.delay))
    if o.g1 then
        local pk = p - GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Cubic(OrbMath.PopEase(pk, ew), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
            place(o.g1, gx, gy, s * GLOW * GHOST1_SIZE, a * GHOST1_ALPHA)
        else
            hideTex(o.g1)
        end
        pk = p - 2 * GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Cubic(OrbMath.PopEase(pk, ew), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
            place(o.g2, gx, gy, s * GLOW * GHOST2_SIZE, a * GHOST2_ALPHA)
        else
            hideTex(o.g2)
        end
    end
end

-- ---------------------------------------------------------------- corpse pop

-- A pooled pop: g.f is a 1x1 frame whose ONLY anchor is the nameplate; g.tex holds up to POP_MAX * 3 textures
-- (underlay, orb, sparkle per orb) created lazily and parented to g.f; per-orb parameters live in g.dx/dy/size/rot.
local function newPop()
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetSize(1, 1)
    f:SetFrameStrata("HIGH")
    f:EnableMouse(false)
    f:Hide()
    return { f = f, tex = {}, dx = {}, dy = {}, drift = {}, size = {}, rot = {}, n = 0, used = 0 }
end

function releasePop(g)
    if g.free then
        return -- already back in the pool (a second release would hand the frame out twice)
    end
    g.free = true
    local tex = g.tex
    for i = 1, g.used do
        local t = tex[i]
        t:Hide()
        t.xoShown = false
    end
    g.used, g.plate, g.xf, g.refs = 0, nil, false, 0
    pcall(g.f.ClearAllPoints, g.f)
    pcall(g.f.Hide, g.f)
    freePop[#freePop + 1] = g
end

-- Fills g for m orbs (rested: the first nP). Anchors g.f to the plate with a single point. Errors propagate (pcall'd).
local function setupPop(g, plate, m, scale, nP, rc, bc, ux, uy, zy)
    local d = ns.db
    local f, tex = g.f, g.tex
    f:ClearAllPoints()
    local rel, y = plateAnchor(zy, "CENTER", POP_Y)
    f:SetPoint("CENTER", plate, rel, 0, y)
    f:Show()
    for i = 1, m * 3 do
        if not tex[i] then
            tex[i] = f:CreateTexture(nil, "ARTWORK")
        end
    end
    for i = 1, m do
        local rested = i <= nP
        local c = rested and rc or bc
        local r, gg, b = c[1], c[2], c[3]
        local k = (i - 1) * 3
        local u, o, s = tex[k + 1], tex[k + 2], tex[k + 3]
        u:SetTexture(ORB_TEX)
        u:SetBlendMode("BLEND")
        u:SetDrawLayer("ARTWORK", -1)
        u:SetVertexColor(r * UNDER_K, gg * UNDER_K, b * UNDER_K)
        o:SetTexture(ORB_TEX)
        o:SetBlendMode("ADD")
        o:SetDrawLayer("ARTWORK", 0)
        o:SetVertexColor(r, gg, b)
        s:SetTexture(SPARKLE_TEX)
        s:SetBlendMode("ADD")
        s:SetDrawLayer("ARTWORK", 1)
        s:SetVertexColor(r + (1 - r) * SPARKLE_WHITE, gg + (1 - gg) * SPARKLE_WHITE, b + (1 - b) * SPARKLE_WHITE)
        for j = 1, 3 do
            local t = tex[k + j]
            t:SetAlpha(0)
            t:Hide()
            t.xoShown = false
        end
        local ang = OrbMath.RingAngle(i, m, random)
        local rad = POP_R_MIN + random() * (POP_R_MAX - POP_R_MIN)
        g.dx[i], g.dy[i] = cos(ang) * rad, sin(ang) * rad
        g.drift[i] = random() * POP_DRIFT
        g.size[i] = d.size * scale * (rested and RESTED_SIZE or 1)
        g.rot[i] = random() * TWO_PI
    end
    g.used = m * 3
    g.n = m
    g.ux, g.uy = ux, uy
end

-- Takes a pooled pop frame (or creates one under the POP_FRAMES cap). nil when none is free.
local function takePopFrame()
    local g = freePop[#freePop]
    if g then
        freePop[#freePop] = nil
        g.free = false
        return g
    end
    if popsCreated < POP_FRAMES then
        local ok, ng = pcall(newPop)
        if ok then
            popsCreated = popsCreated + 1
            return ng
        end
    end
    return nil
end

-- Returns true when a pop was started. Never throws; every failure just means "no pop".
local function startPop(plate, n, scale, nPurple, ux, uy, zy)
    if type(plate) ~= "table" or not readable(plate) then
        return false
    end
    local g = takePopFrame()
    if not g then
        return false
    end
    local d = ns.db
    local m = min(n, POP_MAX)
    local nP = nPurple > 0 and floor(nPurple * m / n + 0.5) or 0
    local ok, err = pcall(setupPop, g, plate, m, scale, nP, d.restedColor, normalC, ux, uy, zy)
    if not ok then
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR setup %s", string.sub(tostring(err), 1, 120))
        end
        releasePop(g)
        return false
    end
    g.plate, g.el, g.fading, g.fadeEl, g.xf = plate, 0, false, 0, false
    nPops = nPops + 1
    pops[nPops] = g
    return true
end

-- Crossfade: a pop frame anchored to the plate's BOTTOM that will carry copy A of every orb. Returns the frame or nil.
local function startXf(plate, zy)
    if type(plate) ~= "table" or not readable(plate) then
        return nil
    end
    local g = takePopFrame()
    if not g then
        return nil
    end
    local f = g.f
    local ok, err = pcall(function()
        f:ClearAllPoints()
        local rel, y = plateAnchor(zy, "BOTTOM", 0)
        f:SetPoint("CENTER", plate, rel, 0, y)
        f:Show()
    end)
    if not ok then
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR crossfade setup %s", string.sub(tostring(err), 1, 120))
        end
        releasePop(g)
        return nil
    end
    g.plate, g.xf, g.refs, g.fm, g.fading, g.fadeEl = plate, true, 0, 1, false, 0
    nXf = nXf + 1
    xfs[nXf] = g
    return g
end

function dropXf(g)
    for i = 1, nXf do
        if xfs[i] == g then
            xfs[i] = xfs[nXf]
            xfs[nXf] = nil
            nXf = nXf - 1
            break
        end
    end
end

-- Creates/configures the 3 textures of orb slot k+1..k+3 on the crossfade frame. Errors propagate (pcall'd).
local function xfTextures(g, k, r, gg, b)
    local tex, f = g.tex, g.f
    for j = 1, 3 do
        if not tex[k + j] then
            tex[k + j] = f:CreateTexture(nil, "ARTWORK")
        end
    end
    local u, o, s = tex[k + 1], tex[k + 2], tex[k + 3]
    u:SetTexture(ORB_TEX)
    u:SetBlendMode("BLEND")
    u:SetDrawLayer("ARTWORK", -1)
    u:SetVertexColor(r * UNDER_K, gg * UNDER_K, b * UNDER_K)
    o:SetTexture(ORB_TEX)
    o:SetBlendMode("ADD")
    o:SetDrawLayer("ARTWORK", 0)
    o:SetVertexColor(r, gg, b)
    s:SetTexture(SPARKLE_TEX)
    s:SetBlendMode("ADD")
    s:SetDrawLayer("ARTWORK", 1)
    s:SetVertexColor(r + (1 - r) * SPARKLE_WHITE, gg + (1 - gg) * SPARKLE_WHITE, b + (1 - b) * SPARKLE_WHITE)
    for j = 1, 3 do
        local t = tex[k + j]
        t:SetAlpha(0)
        t:Hide()
        t.xoShown = false
    end
    if k + 3 > g.used then
        g.used = k + 3
    end
end

-- Positions every pop orb. Called under pcall from the driver; allocates nothing.
local function drawPop(g)
    local p = g.el / POP_TIME
    if p > 1 then
        p = 1
    end
    local e = 1 - (1 - p) * (1 - p) * (1 - p)
    local sc = p > POP_SHRINK_FROM and 1 - (p - POP_SHRINK_FROM) / (1 - POP_SHRINK_FROM) or 1
    local a = p > POP_FADE_FROM and 1 - (p - POP_FADE_FROM) / (1 - POP_FADE_FROM) or 1
    if g.fading then
        a = a * (1 - g.fadeEl / POP_FADE_OUT)
    end
    local q = p > POP_EXIT_FROM and (p - POP_EXIT_FROM) / (1 - POP_EXIT_FROM) or 0
    local gather = 1 - POP_GATHER * q
    local exit = POP_EXIT_DIST * q * q
    local exx, exy = g.ux * exit, g.uy * exit
    local f, tex = g.f, g.tex
    local spin = TWO_PI * g.el
    for i = 1, g.n do
        local ox = g.dx[i] * e * gather + exx
        local oy = (g.dy[i] + g.drift[i]) * e * gather + exy
        local s = g.size[i] * GLOW * POP_SIZE * sc
        local k = (i - 1) * 3
        placeRel(tex[k + 1], f, ox, oy, s * UNDER_SIZE, a * POP_UNDER_ALPHA)
        placeRel(tex[k + 2], f, ox, oy, s, a)
        local sp = tex[k + 3]
        placeRel(sp, f, ox, oy, s * SPARKLE, a * SPARKLE_ALPHA)
        sp:SetRotation(g.rot[i] + spin)
    end
end

local function updatePops(dt)
    local i = 1
    while i <= nPops do
        local g = pops[i]
        g.el = g.el + dt
        local drop = false
        if g.fading then
            g.fadeEl = g.fadeEl + dt
            drop = g.fadeEl >= POP_FADE_OUT
        end
        if g.el >= POP_TIME then
            drop = true
        end
        if not drop then
            local ok, err = pcall(drawPop, g)
            if not ok then
                drop = true
                if not popErrSeen then
                    popErrSeen = true
                    ns:Log("POP_ERR draw %s", string.sub(tostring(err), 1, 120))
                end
            end
        end
        if drop then
            releasePop(g)
            pops[i] = pops[nPops]
            pops[nPops] = nil
            nPops = nPops - 1
        else
            i = i + 1
        end
    end
end

-- An orb arrived: asks the chime for a note and plays it. The first failure (an error, or the client saying the file
-- won't play) logs SOUND_ERR once and silences the chime for the session. Allocates nothing.
local function playChime(key)
    local n = chime:Arrive(key)
    if not n then
        return
    end
    local ok, willPlay = pcall(PlaySoundFile, (VOICE_PATHS[ns.db.soundVoice] or VOICE_PATHS.glass)[n], "SFX")
    if not ok or willPlay == false then
        soundDead = true
        ns:Log("SOUND_ERR %s", ok and "the client won't play the file" or string.sub(tostring(willPlay), 1, 120))
    end
end

-- Perf counters for /xporbs perf: frames the driver ran, their summed and worst time in ms.
local perfFrames, perfTotal, perfMax = 0, 0, 0
local driverErrSeen = false

-- One driver frame. Runs under pcall (see onUpdate) and allocates nothing.
local function drive(self, dt)
    if nPops > 0 then
        updatePops(dt)
    end
    for i = 1, nXf do
        local g = xfs[i]
        if g.fading then
            g.fadeEl = g.fadeEl + dt
            g.fm = g.fadeEl >= POP_FADE_OUT and 0 or 1 - g.fadeEl / POP_FADE_OUT
        end
    end
    local dx, dy = Target:GetDestination(aimCentre(ns.db), portraitMode)
    local i = 1
    while i <= nLive do
        local o = live[i]
        o.el = o.el + dt
        local t = o.el - o.delay
        local drop = false
        if t >= 0 then
            local ft = t - o.hold -- flight time; negative during the crossfade hold
            if ft < 0 then
                drawHold(o, t)
            else
                local p = ft / o.dur
                if p >= 1 then
                    if ns.db.sound and not soundDead then
                        playChime(o.bk)
                    end
                    if ns.db.glow ~= false then
                        arrivedRecently = arrivedRecently + 1
                        flashAge, flashOn, flashRested = 0, true, o.rested
                    end
                    drop = true
                else
                    drawOrb(o, p, dx, dy)
                end
            end
        end
        if drop then
            freeOrb(o)
            live[i] = live[nLive]
            live[nLive] = nil
            nLive = nLive - 1
        else
            i = i + 1
        end
    end

    if flashOn then
        flashAge = flashAge + dt
        if flashAge >= FLASH_TIME or ns.db.glow == false then
            flashOn, arrivedRecently = false, 0
            flash:Hide()
        else
            local c = flashRested and ns.db.restedColor or normalC
            local kA, kS = OrbMath.GlowIntensity(ns.db.glowIntensity)
            local a = min(1, min(1, FLASH_ALPHA + FLASH_STEP * arrivedRecently) * (1 - flashAge / FLASH_TIME) * kA)
            -- the bar-shaped flash is horizontal, so a vertical StatusBar destination gets the round glow instead
            local shape = (portraitMode or ns.db.glowShape == "round" or Target.lastVertical) and "round" or "bar"
            if shape ~= flashShape then
                flashShape = shape
                flash:SetTexture(shape == "round" and ORB_TEX or FLASH_TEX) -- orb.tga is a radial gradient
            end
            flash:SetVertexColor(c[1] + (1 - c[1]) * FLASH_WHITE, c[2] + (1 - c[2]) * FLASH_WHITE,
                c[3] + (1 - c[3]) * FLASH_WHITE)
            flash:ClearAllPoints()
            flash:SetPoint("CENTER", overlay, "BOTTOMLEFT", dx, dy)
            if shape == "round" then
                local dia = OrbMath.GlowDiameter(Target.lastW, Target.lastH, ns.db.size)
                flash:SetSize(dia * kS, dia * kS)
            else
                local w = ns.db.size * FLASH_W * kS
                flash:SetSize(w, w / FLASH_ASPECT)
            end
            flash:SetAlpha(a)
            flash:Show()
        end
    end

    if nLive == 0 and nPops == 0 and not flashOn then
        active = false
        self:SetScript("OnUpdate", nil)
    end
end

-- The driver failed: give every orb, pop and crossfade frame back to its pool, hide the flash and stop, so one bad
-- frame can never leave orbs hanging on screen with an OnUpdate that throws forever. Logged once per session.
local function abortDriver(err)
    if not driverErrSeen then
        driverErrSeen = true
        ns:Log("DRIVER_ERR %s", string.sub(tostring(err), 1, 120))
    end
    for i = nLive, 1, -1 do
        pcall(freeOrb, live[i])
        live[i] = nil
    end
    nLive = 0
    for i = nPops, 1, -1 do
        pcall(releasePop, pops[i])
        pops[i] = nil
    end
    nPops = 0
    for i = nXf, 1, -1 do
        pcall(releasePop, xfs[i])
        xfs[i] = nil
    end
    nXf = 0
    flashOn, arrivedRecently = false, 0
    if flash then
        pcall(flash.Hide, flash)
    end
    active = false
    if driver then
        driver:SetScript("OnUpdate", nil)
    end
end

-- The OnUpdate script. Hoisted (no closure per frame); times each frame when debugprofilestop exists.
local function onUpdate(self, dt)
    local prof = debugprofilestop
    local t0 = prof and prof()
    local ok, err = pcall(drive, self, dt)
    if t0 then
        local ms = prof() - t0
        perfFrames = perfFrames + 1
        perfTotal = perfTotal + ms
        if ms > perfMax then
            perfMax = ms
        end
    end
    if not ok then
        abortDriver(err)
    end
end

local function lighten(c)
    return c + (1 - c) * SPARKLE_WHITE
end

local function styleOf(v)
    if v == "crossfade" or v == "stream" or v == "popstream" or v == "mob" then
        return v
    end
    return "popstream"
end

-- Burst{ x=, y= (stream origin, UIParent coords; nil -> screen centre), n=, scale= (default 1), nPurple= (default 0),
-- kind=, plate= (optional nameplate of the dead mob), style= (optional override of db.style),
-- ex=, ey= (P-hat, the estimated mob position in UIParent coords; default = MobEstimate.Default), est=, estW= (source
-- label and mouseover weight, informational) }. n < 1 is a no-op.
-- Returns "pop+stream" | "crossfade" | "mob" | "stream".
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
    local style = styleOf(p.style or d.style)
    if p.kind == "other" then
        style = "stream" -- quest and other XP: no pop (Kills passes the origin; the centre is the default)
    end
    if type(x) ~= "number" or type(y) ~= "number" then
        x, y = UIParent:GetWidth() / 2, UIParent:GetHeight() * 0.65
    end
    portraitMode = Target:PortraitMode() == true -- once per burst, never per frame
    local dx, dy = Target:GetDestination(aimCentre(d), portraitMode)
    local normal = resolveNormal(d)
    -- P-hat: our best guess of where the mob is on screen (Kills passes the mouseover/cursor estimate)
    local px, py = p.ex, p.ey
    if type(px) ~= "number" or type(py) ~= "number" then
        px, py = ns.MobEstimate.Default(UIParent:GetWidth(), UIParent:GetHeight())
    end
    local popped, xg = false, nil
    local zy = p.plate ~= nil and zoomAnchorY(d) or nil
    if p.plate ~= nil and style == "popstream" then
        local ux, uy = OrbMath.ExitVector(x, y, px, py, dx, dy)
        popped = startPop(p.plate, n, scale, nPurple, ux, uy, zy)
    elseif p.plate ~= nil and (style == "crossfade" or style == "mob") then
        xg = startXf(p.plate, zy)
    end
    if xg then
        x, y = px, py
    end
    -- Budget the texture pool. A full burst with trails needs 5 textures per orb; when that doesn't fit, the burst
    -- drops its trail ghosts (3 per orb), then draws fewer orbs. Every burst still gets min(n, 3) orbs while 9
    -- textures are free, so the later kills of an AoE pull are never starved by the earlier ones.
    local trail = d.trail and true or false
    local need = trail and 1 + EXTRAS or 3 -- orb + underlay + sparkle (+ 2 ghosts)
    local limit = ceiling() - 1 -- the arrival flash holds one slot
    local free = limit - texInUse
    if trail and n * need > free then
        trail, need = false, 3
    end
    local fit = floor(free / need)
    if fit < 0 then
        fit = 0
    end
    if fit < n then
        nPurple = floor(nPurple * fit / n + 0.5)
        n = fit
    end
    local mob = xg ~= nil and style == "mob"
    local prof = mob and MOB_PROFILE or XF_PROFILE
    local extra = popped and STREAM_DELAY or 0
    local stagger = (popped or xg) and STAGGER_POP or STAGGER
    if mob then
        stagger = MOB_BORN -- born together; the launch is what gets staggered (o.hold)
    end
    local spread, lift = nil, nil -- PopControl defaults
    if popped or xg then
        spread, lift = POP_STREAM_SPREAD, POP_STREAM_LIFT
    end
    local fadeIn = popped and FADE_IN_POP or FADE_IN
    local flight = xg and prof.flight or 1
    local xfCount = 0
    local cur, curLive = nil, false -- the orb being built, and whether it is in `live` yet
    burstSeq = burstSeq + 1
    local bk = burstSeq

    local ok, err = pcall(function()
        for i = 1, n do
            if texInUse + need > limit then
                break
            end
            local rested = i <= nPurple
            local c = rested and d.restedColor or normal
            local r, g, bl = c[1], c[2], c[3]
            local o = newRec()
            cur, curLive = o, false
            o.g, o.hold, o.ew, o.prof = nil, 0, nil, nil
            if xg then
                local k = xfCount * 3
                if pcall(xfTextures, xg, k, r, g, bl) then
                    xfCount = xfCount + 1
                    o.g, o.k, o.px, o.py = xg, k, px, py
                    o.hold, o.ew, o.prof = mob and prof.hold + random() * STAGGER_POP or prof.hold, prof.ease, prof
                    xg.refs = xg.refs + 1
                end
            end
            if o.g then
                -- the flight starts where the bloom ends: on the ring around P-hat
                local ang = OrbMath.RingAngle(i, n, random)
                if mob then
                    local rad = prof.rmin + random() * (prof.rmax - prof.rmin)
                    o.x0, o.y0 = x + cos(ang) * rad, y + sin(ang) * rad + random() * prof.drift
                else
                    o.x0, o.y0 = x + cos(ang) * prof.rmin, y + sin(ang) * prof.rmin
                end
            else
                local ang, rad = random() * TWO_PI, START_RADIUS * sqrt(random())
                o.x0, o.y0 = x + cos(ang) * rad, y + sin(ang) * rad
            end
            o.c1x, o.c1y = OrbMath.PopControl(i, n, o.x0, o.y0, random, spread, lift)
            local ddx, ddy = dx - o.x0, dy - o.y0
            o.dist0 = sqrt(ddx * ddx + ddy * ddy)
            o.delay = random() * stagger + (rested and not mob and RESTED_DELAY or 0) + extra
            if mob and rested then
                o.hold = o.hold + RESTED_DELAY -- keep the purple orbs behind the others without delaying their birth
            end
            o.dur = max(MIN_DUR, d.flightTime * (o.g and flight or 1) * (0.85 + random() * 0.3))
            o.el = 0
            o.fadeIn = o.g and 0 or fadeIn -- plate-copy orbs fade in during the hold (prof.fadeIn)
            o.rested = rested
            o.size = d.size * scale * (rested and RESTED_SIZE or 1)
            o.rot0 = random() * TWO_PI
            o.under = acquire(ORB_TEX, -1, r * UNDER_K, g * UNDER_K, bl * UNDER_K, "BLEND")
            o.orb = acquire(ORB_TEX, 0, r, g, bl)
            o.spark = acquire(SPARKLE_TEX, 1, lighten(r), lighten(g), lighten(bl))
            if trail then
                o.g1 = acquire(ORB_TEX, 0, r, g, bl)
                o.g2 = acquire(ORB_TEX, 0, r, g, bl)
            end
            nLive = nLive + 1
            live[nLive] = o
            o.bk = bk
            burstLeft[bk] = (burstLeft[bk] or 0) + 1
            curLive = true
        end
    end)
    if not ok then
        -- Undo what this burst started, so nothing is left holding a pool slot: the half-built orb, every orb that
        -- shares the crossfade frame, and the pop frame (the newest entry of `pops`).
        if cur and not curLive then
            pcall(freeOrb, cur)
        end
        if xg then
            local i = 1
            while i <= nLive do
                local o = live[i]
                if o.g == xg then
                    pcall(freeOrb, o)
                    live[i] = live[nLive]
                    live[nLive] = nil
                    nLive = nLive - 1
                else
                    i = i + 1
                end
            end
        end
        if popped and nPops > 0 then
            local g = pops[nPops]
            pops[nPops] = nil
            nPops = nPops - 1
            releasePop(g)
        end
    end
    if xg and (not ok or xg.refs <= 0) and xg.xf then
        -- no orb got a plate-space copy (or the burst failed): give the frame back
        dropXf(xg)
        releasePop(xg)
    end
    if not ok then
        xg = nil
    elseif xg and not xg.xf then
        xg = nil
    end

    if (nLive > 0 or nPops > 0) and not active then
        active = true
        driver:SetScript("OnUpdate", onUpdate)
    end
    if not ok then
        error(err, 0) -- Kills logs it; everything above is already back in its pool
    end
    if xg then
        return mob and "mob" or "crossfade"
    end
    return popped and "pop+stream" or "stream"
end

-- A plate frame we may be anchored to was assigned to a new unit: fade its pop out (0.1 s) and release it.
function Orbs:PlateReused(plate)
    for i = 1, nPops do
        local g = pops[i]
        if g.plate == plate and not g.fading then
            g.fading, g.fadeEl = true, 0
        end
    end
    for i = 1, nXf do
        local g = xfs[i]
        if g.plate == plate and not g.fading then
            g.fading, g.fadeEl = true, 0
        end
    end
end

-- active, texturesInUse, texturesCreated, ceiling
function Orbs:Info()
    return active, texInUse, texCreated, ceiling()
end

-- popsInUse, popFramesCreated, popFrameCap
function Orbs:PopInfo()
    return nPops, popsCreated, POP_FRAMES
end

-- freePop, popFramesCreated, popsAlive, crossfadeFramesAlive: pool bookkeeping (idle = freePop == popFramesCreated and
-- the other two 0; a released frame always has refs 0).
function Orbs:PoolInfo()
    return #freePop, popsCreated, nPops, nXf
end

-- Stream origin for /xporbs test. popstream follows the kill rule (Target:StreamOrigin: the estimate P-hat, the
-- portrait only without one); otherwise target frame, else the cursor, else the screen centre. Every read is
-- checked for secrecy and pcall'd. Returns x, y, label (x, y nil only when even the screen size is unreadable).
local function testOrigin(popstream, ex, ey)
    if popstream then
        local sx, sy, sl = Target:StreamOrigin(ex, ey)
        if sx then
            return sx, sy, sl
        end
    end
    local fx, fy = Target:TargetFrameOrigin()
    if fx then
        return fx, fy, "targetframe"
    end
    local okc, cx, cy = pcall(GetCursorPosition)
    local oks, sc = pcall(UIParent.GetEffectiveScale, UIParent)
    if okc and oks and num(cx) and num(cy) and num(sc) and sc > 0 then
        return cx / sc, cy / sc, "cursor"
    end
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    local okh, h = pcall(UIParent.GetHeight, UIParent)
    if okw and okh and num(w) and num(h) then
        return w / 2, h / 2, "centre"
    end
    return nil, nil, "centre"
end

-- Fires one test burst of pct % of a level. Returns the numbers the /xporbs test report prints.
local function fireTest(pct, rested, force)
    local d = db()
    local okm, xpMax = pcall(UnitXPMax, "player")
    if not okm or not num(xpMax) or xpMax <= 0 then
        xpMax = 1000 -- max level, no data or a secret value: any positive number gives the same orb count
    end
    local gain = pct / 100 * xpMax
    local n, scale = OrbMath.Count(gain, xpMax, d.density, d.cap)
    local nPurple = 0
    if rested then
        local _
        _, nPurple = OrbMath.RestedSplit(n, gain, gain / 2)
    end
    -- the target's estimate (its GUID, when readable, finds a mouseover sample); no target = a keyboard-style estimate
    local guid
    local okg, tg = pcall(UnitGUID, "target")
    if okg and readable(tg) and type(tg) == "string" then
        guid = tg
    end
    local ex, ey, est, estW = ns.Mouseover:Estimate(guid)
    local x, y, label = testOrigin(styleOf(force or d.style) == "popstream", ex, ey)
    local mode = Orbs:Burst({
        x = x,
        y = y,
        plate = Target:TargetPlate(),
        n = n,
        scale = scale,
        nPurple = nPurple,
        kind = "test",
        style = force,
        ex = ex,
        ey = ey,
        est = est,
        estW = estW,
    })
    return n, scale, nPurple, est, estW, mode, label
end

-- /xporbs test stress [n]: n test bursts (1-15 % of a level each) spread over STRESS_TIME seconds, from one short-lived
-- OnUpdate frame that removes its own script when the last burst has fired.
local stressFrame
local stressN, stressFired, stressEl = 0, 0, 0

local function stressStop()
    if stressFrame then
        stressFrame:SetScript("OnUpdate", nil)
    end
end

local function stressTick(_, dt)
    stressEl = stressEl + (num(dt) and dt or 0)
    while stressFired < stressN and stressEl >= stressFired * STRESS_TIME / stressN do
        stressFired = stressFired + 1
        local ok, err = pcall(fireTest, 1 + floor(random() * 15), false, nil)
        if not ok then
            ns:Log("stress error %s", tostring(err))
            stressStop()
            return
        end
    end
    if stressFired >= stressN then
        stressStop()
    end
end

local function startStress(arg)
    local n = floor(tonumber(arg) or STRESS_DEFAULT)
    n = max(1, min(STRESS_MAX, n))
    if not stressFrame then
        stressFrame = CreateFrame("Frame")
        Orbs.stressFrame = stressFrame
    end
    stressN, stressFired, stressEl = n, 0, 0
    stressFrame:SetScript("OnUpdate", stressTick)
    ns.Print(string.format("stress: %d test bursts over about %g s", n, STRESS_TIME))
end

-- /xporbs test [pct] [rested] [popstream|crossfade|stream|mob]  (the old "frame" / "plate" words are ignored)
-- /xporbs test stress [n]
function ns.commands.test(arg)
    local first, count = string.match(arg or "", "^%s*(%S+)%s*(%S*)")
    if first == "stress" then
        startStress(count)
        return
    end
    local d = db()
    local pct, rested, force = 5, false, nil
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        elseif tok == "popstream" or tok == "crossfade" or tok == "stream" or tok == "mob" then
            force = tok
        elseif tok ~= "frame" and tok ~= "plate" then
            local v = tonumber(tok)
            if v and v > 0 then
                pct = min(v, 1000)
            end
        end
    end
    local n, scale, nPurple, est, estW, mode, label = fireTest(pct, rested, force)
    local used = mode == "pop+stream" and "popstream" or mode
    if mode == "crossfade" or mode == "mob" then
        label = "estimated"
    end
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f, est=%s w=%.2f pop=%s stream=%s"
        .. " style=%s", pct, n, nPurple, scale, est or "none", estW or 0, mode == "pop+stream" and "yes" or "no",
        label, used))
end

-- /xporbs perf [reset]: addon memory, driver frame time, pool usage.
function ns.commands.perf(arg)
    if arg == "reset" then
        perfFrames, perfTotal, perfMax = 0, 0, 0
        ns.Print("perf counters reset")
        return
    end
    local mem = "n/a"
    if UpdateAddOnMemoryUsage and GetAddOnMemoryUsage then
        local ok1 = pcall(UpdateAddOnMemoryUsage)
        local ok2, kb = pcall(GetAddOnMemoryUsage, ADDON)
        if ok1 and ok2 and num(kb) then
            mem = string.format("%.1f KB", kb)
        end
    end
    ns.Print("perf: memory " .. mem)
    if perfFrames == 0 and not debugprofilestop then
        ns.Print("perf: driver timing n/a")
    else
        ns.Print(string.format("perf: driver frames=%d avg=%.3f ms max=%.3f ms", perfFrames,
            perfFrames > 0 and perfTotal / perfFrames or 0, perfMax))
    end
    ns.Print(string.format("perf: textures created=%d in use=%d ceiling=%d", texCreated, texInUse, ceiling()))
    ns.Print(string.format("perf: pop frames created=%d (cap %d)", popsCreated, POP_FRAMES))
    ns.Print(string.format("perf: live orbs=%d", nLive))
end

local function refreshPanel()
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
end

-- /xporbs sound on|off|coin|glass: the arrival chime. Turning it on also clears a SOUND_ERR shutdown, so it can be
-- retried. coin and glass pick the sound (and turn the chime on).
function ns.commands.sound(arg)
    local w = string.match(arg or "", "%S+")
    if w == "on" or w == "coin" or w == "glass" then
        db().sound = true
        if w ~= "on" then
            db().soundVoice = w
        end
        soundDead = false
        refreshPanel()
    elseif w == "off" then
        db().sound = false
        refreshPanel()
    elseif w ~= nil then
        ns.Print("sound: use on, off, coin or glass")
        return
    end
    local note = soundDead and " (switched off this session: the client wouldn't play the file)" or ""
    ns.Print("chime: " .. (db().sound and "on" or "off") .. ", " .. tostring(db().soundVoice) .. note)
end

-- Plays one note of a voice so the options panel can preview it (even with the chime off). One pcall, no state.
function Orbs:PreviewSound(voice)
    local paths = VOICE_PATHS[voice]
    if paths and PlaySoundFile then
        pcall(PlaySoundFile, paths[random(6)], "SFX")
    end
end

-- true once a sound failure has switched the chime off for this session
function Orbs:SoundDisabled()
    return soundDead
end

-- /xporbs style popstream|crossfade|stream|mob  (/xporbs pop on|off = alias for popstream|stream)
function ns.commands.style(arg)
    local w = string.match(arg or "", "%S+")
    if w == "popstream" or w == "crossfade" or w == "stream" or w == "mob" then
        db().style = w
        refreshPanel()
    elseif w ~= nil then
        ns.Print("style: use popstream, crossfade, stream or mob")
        return
    end
    ns.Print("kill style: " .. styleOf(db().style))
end

function ns.commands.pop(arg)
    local w = string.match(arg or "", "%S+")
    if w == "on" then
        db().style = "popstream"
        refreshPanel()
    elseif w == "off" then
        db().style = "stream"
        refreshPanel()
    elseif w ~= nil then
        ns.Print("pop: use on or off")
        return
    end
    ns.Print("kill style: " .. styleOf(db().style))
end

table.insert(ns.statusProviders, function()
    Target:GetDestination()
    return string.format(
        "orbs: driver=%s, live textures=%d, pool=%d/%d, dest=%s, fallback=%s, style=%s, pops=%d (frames %d/%d)",
        active and "active" or "idle",
        texInUse,
        texCreated,
        ceiling(),
        tostring(Target.lastName),
        Target.lastOk and "no" or "yes",
        styleOf(db().style),
        nPops,
        popsCreated,
        POP_FRAMES
    )
end)

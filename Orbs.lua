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

-- Tunables (retune here).
local EXTRAS = 4 -- ceiling formula: cap * (1 + EXTRAS) + 8. Per orb: underlay + sparkle + 2 trail ghosts
local GLOW = 2.0 -- the orb art fades to nothing at its rim, so draw it larger than db.size
local SPARKLE = 1.9
local SPARKLE_ALPHA = 0.6
local SPARKLE_WHITE = 0.25 -- sparkle tint = lerp(colour, white, this)
local STAGGER = 0.15 -- max start delay
local RESTED_DELAY = 0.12 -- extra start delay for rested orbs
local RESTED_SIZE = 1.15
local START_RADIUS = 6
local SHRINK_FROM = 0.8 -- shrink to 60% over the last 20% of the flight
local FADE_IN = 0.1
local GHOST_STEP = 0.015 -- in p, before easing
local GHOST1_ALPHA, GHOST1_SIZE = 0.55, 0.85
local GHOST2_ALPHA, GHOST2_SIZE = 0.30, 0.70
local UNDER_R, UNDER_G, UNDER_B = 0.02, 0.08, 0.30 -- dark underlay so bright orbs keep their hue
local UNDER_ALPHA, UNDER_SIZE = 0.45, 1.25
local FLASH_TIME = 0.3
-- Corpse pop (a burst of orbs at the dead mob's nameplate, drawn relative to a tiny frame anchored ONLY to the plate).
local POP_MAX = 12 -- orbs per pop
local POP_FRAMES = 8 -- concurrent pops (one pooled frame each)
local POP_TIME = 0.45
local POP_Y = 0 -- offset of the pop frame from the plate centre
local POP_R_MIN, POP_R_MAX = 30, 70 -- final radius
local POP_DRIFT = 40 -- extra upward drift, px
local POP_SIZE = 1.1 -- start size multiplier
local POP_SHRINK_FROM = 0.5 -- size shrinks to 0 over p in [0.5, 1]
local POP_FADE_FROM = 0.6 -- alpha 1 -> 0 over p in [0.6, 1]
local POP_FADE_OUT = 0.1 -- seconds a pop fades when its plate is reused for another unit
local STREAM_DELAY = 0.12 -- extra start delay of the stream when a pop happened, so the pop reads first
-- Crossfade style: orbs fly from an ESTIMATED mob position (plates can't be measured). Copy A is drawn relative to
-- the plate (exact if the estimate is right), copy B in screen space; A fades out and B fades in over
-- p in [XF_START, XF_END].
local ASSUMED_MOB_Y = 0.58 -- estimated mob height as a fraction of screen height (target plates sat at 0.55-0.62)
local XF_START, XF_END = 0.25, 0.60

local overlay, driver, flash
local freeTex, texCreated, texInUse = {}, 0, 0
local live, nLive = {}, 0
local freeRec = {}
local active = false
local arrivedRecently, flashAge, flashOn, flashRested = 0, 0, false, false
local freePop, popsCreated = {}, 0
local pops, nPops = {}, 0
local popErrSeen = false
local xfs, nXf = {}, 0 -- crossfade pop frames alive (their orbs are driven from the stream loop)

local function db()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

local function ceiling()
    return db().cap * (1 + EXTRAS) + 8
end

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
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

local function freeOrb(o)
    release(o.under)
    release(o.orb)
    release(o.spark)
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

local function smoothstep(p)
    local t = (p - XF_START) / (XF_END - XF_START)
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

local function hideB(o)
    hideTex(o.under)
    hideTex(o.orb)
    hideTex(o.spark)
    if o.g1 then
        hideTex(o.g1)
        hideTex(o.g2)
    end
end

local function drawOrb(o, p, dx, dy)
    local x0, y0, c1x, c1y = o.x0, o.y0, o.c1x, o.c1y
    local c2x, c2y = OrbMath.HomeControl(c1x, c1y, dx, dy, o.dist0)
    local ex, ey = OrbMath.Cubic(OrbMath.PopEase(p), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
    local s = o.size
    if p > SHRINK_FROM then
        s = s * (1 - 0.4 * (p - SHRINK_FROM) / (1 - SHRINK_FROM))
    end
    local a = p < FADE_IN and p / FADE_IN or 1
    local g = o.g
    if g then
        local w = smoothstep(p) -- weight of the screen-space copy B
        local ok, err = pcall(drawA, o, g, ex, ey, s, a * (1 - w) * g.fm)
        if not ok then
            g.fm = 0
            if not popErrSeen then
                popErrSeen = true
                ns:Log("POP_ERR crossfade %s", string.sub(tostring(err), 1, 120))
            end
        end
        if w <= 0 then
            hideB(o)
            return
        end
        a = a * w
    end
    place(o.under, ex, ey, s * GLOW * UNDER_SIZE, a * UNDER_ALPHA)
    place(o.orb, ex, ey, s * GLOW, a)
    place(o.spark, ex, ey, s * SPARKLE, a * SPARKLE_ALPHA)
    o.spark:SetRotation(o.rot0 + TWO_PI * (o.el - o.delay))
    if o.g1 then
        local pk = p - GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Cubic(OrbMath.PopEase(pk), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
            place(o.g1, gx, gy, s * GLOW * GHOST1_SIZE, a * GHOST1_ALPHA)
        else
            hideTex(o.g1)
        end
        pk = p - 2 * GHOST_STEP
        if pk > 0 then
            local gx, gy = OrbMath.Cubic(OrbMath.PopEase(pk), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
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
local function setupPop(g, plate, m, scale, nP, rc, bc)
    local d = ns.db
    local f, tex = g.f, g.tex
    f:ClearAllPoints()
    f:SetPoint("CENTER", plate, "CENTER", 0, POP_Y)
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
        u:SetVertexColor(UNDER_R, UNDER_G, UNDER_B)
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
        local ang = ((i - 1) + random() * 0.8) / m * TWO_PI
        local rad = POP_R_MIN + random() * (POP_R_MAX - POP_R_MIN)
        g.dx[i], g.dy[i] = cos(ang) * rad, sin(ang) * rad
        g.drift[i] = random() * POP_DRIFT
        g.size[i] = d.size * scale * (rested and RESTED_SIZE or 1)
        g.rot[i] = random() * TWO_PI
    end
    g.used = m * 3
    g.n = m
end

-- Takes a pooled pop frame (or creates one under the POP_FRAMES cap). nil when none is free.
local function takePopFrame()
    local g = freePop[#freePop]
    if g then
        freePop[#freePop] = nil
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
local function startPop(plate, n, scale, nPurple)
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
    local ok, err = pcall(setupPop, g, plate, m, scale, nP, d.restedColor, d.color)
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

-- Crossfade: a pop frame anchored to the plate that will carry copy A of every orb. Returns the frame or nil.
local function startXf(plate)
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
        f:SetPoint("CENTER", plate, "CENTER", 0, 0)
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
    u:SetVertexColor(UNDER_R, UNDER_G, UNDER_B)
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
    local f, tex = g.f, g.tex
    local spin = TWO_PI * g.el
    for i = 1, g.n do
        local ox, oy = g.dx[i] * e, g.dy[i] * e + g.drift[i] * e
        local s = g.size[i] * GLOW * POP_SIZE * sc
        local k = (i - 1) * 3
        placeRel(tex[k + 1], f, ox, oy, s * UNDER_SIZE, a * UNDER_ALPHA)
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

local function onUpdate(self, dt)
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
    local dx, dy = Target:GetDestination()
    local i = 1
    while i <= nLive do
        local o = live[i]
        o.el = o.el + dt
        local t = o.el - o.delay
        local drop = false
        if t >= 0 then
            local p = t / o.dur
            if p >= 1 then
                arrivedRecently = arrivedRecently + 1
                flashAge, flashOn, flashRested = 0, true, o.rested
                drop = true
            else
                drawOrb(o, p, dx, dy)
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
        if flashAge >= FLASH_TIME then
            flashOn, arrivedRecently = false, 0
            flash:Hide()
        else
            local c = flashRested and ns.db.restedColor or ns.db.color
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

    if nLive == 0 and nPops == 0 and not flashOn then
        active = false
        self:SetScript("OnUpdate", nil)
    end
end

local function lighten(c)
    return c + (1 - c) * SPARKLE_WHITE
end

local function styleOf(v)
    if v == "crossfade" or v == "stream" or v == "popstream" then
        return v
    end
    return "popstream"
end

-- Burst{ x=, y= (stream origin, UIParent coords; nil -> screen centre), n=, scale= (default 1), nPurple= (default 0),
-- kind=, plate= (optional nameplate of the dead mob), style= (optional override of db.style) }. n < 1 is a no-op.
-- Returns "pop+stream" | "crossfade" | "stream".
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
        x, y = nil, nil -- quest and other XP: always from the screen centre, no pop
        style = "stream"
    end
    if type(x) ~= "number" or type(y) ~= "number" then
        x, y = UIParent:GetWidth() / 2, UIParent:GetHeight() * 0.65
    end
    local popped, xg = false, nil
    if p.plate ~= nil and style == "popstream" then
        popped = startPop(p.plate, n, scale, nPurple)
    elseif p.plate ~= nil and style == "crossfade" then
        xg = startXf(p.plate)
    end
    local px, py
    if xg then
        px, py = UIParent:GetWidth() * 0.5, UIParent:GetHeight() * ASSUMED_MOB_Y
        x, y = px, py
    end
    local dx, dy = Target:GetDestination()
    local trail = d.trail
    local need = trail and 1 + EXTRAS or 3 -- orb + underlay + sparkle (+ 2 ghosts)
    local limit = ceiling() - 1 -- the arrival flash holds one slot
    local extra = popped and STREAM_DELAY or 0
    local xfCount = 0

    for i = 1, n do
        if texInUse + need > limit then
            break
        end
        local rested = i <= nPurple
        local c = rested and d.restedColor or d.color
        local r, g, bl = c[1], c[2], c[3]
        local o = newRec()
        local ang, rad = random() * TWO_PI, START_RADIUS * sqrt(random())
        o.x0, o.y0 = x + cos(ang) * rad, y + sin(ang) * rad
        o.c1x, o.c1y = OrbMath.PopControl(i, n, o.x0, o.y0, random)
        local ddx, ddy = dx - o.x0, dy - o.y0
        o.dist0 = sqrt(ddx * ddx + ddy * ddy)
        o.delay = random() * STAGGER + (rested and RESTED_DELAY or 0) + extra
        o.dur = d.flightTime * (0.85 + random() * 0.3)
        o.el = 0
        o.rested = rested
        o.size = d.size * scale * (rested and RESTED_SIZE or 1)
        o.rot0 = random() * TWO_PI
        o.g = nil
        if xg then
            local k = xfCount * 3
            if pcall(xfTextures, xg, k, r, g, bl) then
                xfCount = xfCount + 1
                o.g, o.k, o.px, o.py = xg, k, px, py
                xg.refs = xg.refs + 1
            end
        end
        o.under = acquire(ORB_TEX, -1, UNDER_R, UNDER_G, UNDER_B, "BLEND")
        o.orb = acquire(ORB_TEX, 0, r, g, bl)
        o.spark = acquire(SPARKLE_TEX, 1, lighten(r), lighten(g), lighten(bl))
        if trail then
            o.g1 = acquire(ORB_TEX, 0, r, g, bl)
            o.g2 = acquire(ORB_TEX, 0, r, g, bl)
        end
        nLive = nLive + 1
        live[nLive] = o
    end
    if xg and xg.refs <= 0 then
        -- no orb got a plate-space copy: give the frame back
        dropXf(xg)
        releasePop(xg)
        xg = nil
    end

    if (nLive > 0 or nPops > 0) and not active then
        active = true
        driver:SetScript("OnUpdate", onUpdate)
    end
    if xg then
        return "crossfade"
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

-- Stream origin for /xporbs test: target frame, else the cursor, else the screen centre. Returns x, y, label.
local function testOrigin()
    local fx, fy = Target:TargetFrameOrigin()
    if fx then
        return fx, fy, "targetframe"
    end
    local okc, cx, cy = pcall(GetCursorPosition)
    local oks, sc = pcall(UIParent.GetEffectiveScale, UIParent)
    if okc and oks and type(cx) == "number" and type(cy) == "number" and type(sc) == "number" and sc > 0 then
        return cx / sc, cy / sc, "cursor"
    end
    return UIParent:GetWidth() / 2, UIParent:GetHeight() / 2, "centre"
end

-- /xporbs test [pct] [rested] [popstream|crossfade|stream]  (the old "frame" / "plate" words are ignored)
function ns.commands.test(arg)
    local d = db()
    local pct, rested, force = 5, false, nil
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        elseif tok == "popstream" or tok == "crossfade" or tok == "stream" then
            force = tok
        elseif tok ~= "frame" and tok ~= "plate" then
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
    local x, y, label = testOrigin()
    local mode = Orbs:Burst({
        x = x,
        y = y,
        plate = Target:TargetPlate(),
        n = n,
        scale = scale,
        nPurple = nPurple,
        kind = "test",
        style = force,
    })
    local used = mode == "pop+stream" and "popstream" or mode
    if mode == "crossfade" then
        label = "estimated"
    end
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f, pop=%s stream=%s style=%s", pct,
        n, nPurple, scale, mode == "pop+stream" and "yes" or "no", label, used))
end

-- /xporbs style popstream|crossfade|stream  (/xporbs pop on|off = alias for popstream|stream)
function ns.commands.style(arg)
    local w = string.match(arg or "", "%S+")
    if w == "popstream" or w == "crossfade" or w == "stream" then
        db().style = w
    elseif w ~= nil then
        ns.Print("style: use popstream, crossfade or stream")
        return
    end
    ns.Print("kill style: " .. styleOf(db().style))
end

function ns.commands.pop(arg)
    local w = string.match(arg or "", "%S+")
    if w == "on" then
        db().style = "popstream"
    elseif w == "off" then
        db().style = "stream"
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

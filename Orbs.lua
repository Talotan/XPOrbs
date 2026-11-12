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
-- Anchored mode (origin = a nameplate we may not measure): see HANDOFF "M2.2 anchored origin".
local GHOSTS_ANCHORED = 1 -- trail ghosts per orb in anchored bursts (numeric bursts keep 2); each costs a chain
local ASSUMED_MOB_Y = 0.55 -- assumed mob height as a fraction of screen height, used to size the home-curve lift
local LIFT = 0.30 -- lift of the home control point, as a fraction of the assumed travel distance
local MIN_TRAVEL = 150 -- px floor for that assumed distance
local A_MIN = 0.002 -- below this plate weight the chain is skipped and textures anchor to UIParent directly
local FADE_OUT = 0.15 -- seconds an orb fades when its plate is reused for another unit
local R_CEIL = 16 -- anchored bursts alive at once
local WHITE = "Interface\\Buttons\\WHITE8X8"

local overlay, driver, flash
local freeTex, texCreated, texInUse = {}, 0, 0
local live, nLive = {}, 0
local freeRec = {}
local active = false
local freeChain, chainsCreated, chainsInUse = {}, 0, 0
local freeR, rCreated, rInUse = {}, 0, 0
local drawErrLogged = false
local arrivedRecently, flashAge, flashOn, flashRested = 0, 0, false, false

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

local function chainCeiling()
    return floor((ceiling() - 1) / (3 + GHOSTS_ANCHORED)) * (1 + GHOSTS_ANCHORED)
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

local function hideTex(tex)
    if tex.xoShown then
        tex:Hide()
        tex.xoShown = false
    end
end

local function setupBar(bar, orientation)
    bar:SetOrientation(orientation)
    bar:SetMinMaxValues(0, 1)
    bar:SetStatusBarTexture(WHITE)
    bar:SetStatusBarColor(0, 0, 0, 0) -- invisible but still laid out
    bar:SetValue(0)
end

-- Chain of 3 regions whose hBar fill TOPRIGHT sits at (a*Px, a*Py) for the burst frame R spanning (0,0)-(Px,Py).
local function acquireChain(R)
    local ch = freeChain[#freeChain]
    local reused = ch ~= nil
    local ok = pcall(function()
        if reused then
            ch.v:SetParent(R)
            ch.m:SetParent(R)
            ch.h:SetParent(R)
        else
            local v = CreateFrame("StatusBar", nil, R)
            local m = CreateFrame("Frame", nil, R)
            local h = CreateFrame("StatusBar", nil, R)
            setupBar(v, "VERTICAL")
            setupBar(h, "HORIZONTAL")
            ch = { v = v, m = m, h = h, vfill = v:GetStatusBarTexture(), fill = h:GetStatusBarTexture() }
        end
        ch.v:ClearAllPoints()
        ch.v:SetAllPoints(R)
        ch.m:ClearAllPoints()
        ch.m:SetPoint("BOTTOMLEFT", R, "BOTTOMLEFT")
        ch.m:SetPoint("TOPRIGHT", ch.vfill, "TOPRIGHT")
        ch.h:ClearAllPoints()
        ch.h:SetAllPoints(ch.m)
        ch.v:Show()
        ch.m:Show()
        ch.h:Show()
    end)
    if not ok or not ch or not ch.fill then
        return nil
    end
    if reused then
        freeChain[#freeChain] = nil
    else
        chainsCreated = chainsCreated + 1
    end
    chainsInUse = chainsInUse + 1
    return ch
end

local function releaseChain(ch)
    pcall(function()
        ch.v:Hide()
        ch.m:Hide()
        ch.h:Hide()
        ch.m:ClearAllPoints()
    end)
    freeChain[#freeChain + 1] = ch
    chainsInUse = chainsInUse - 1
end

-- Burst record: R spans UIParent BOTTOMLEFT (0,0) to the plate centre P. Shared by the burst's orbs and ghosts.
local function acquireBurst(plate)
    local R = freeR[#freeR]
    if not R and rCreated >= R_CEIL then
        return nil
    end
    if R then
        freeR[#freeR] = nil
    else
        local ok, f = pcall(CreateFrame, "Frame", nil, UIParent)
        if not ok or not f then
            return nil
        end
        R = f
        rCreated = rCreated + 1
    end
    local ok = pcall(function()
        R:ClearAllPoints()
        R:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
        R:SetPoint("TOPRIGHT", plate, "CENTER", 0, 0)
        R:Show()
    end)
    if not ok then
        freeR[#freeR + 1] = R
        return nil
    end
    rInUse = rInUse + 1
    return { R = R, plate = plate, n = 0 }
end

local function releaseBurst(b)
    local R = b.R
    b.R = nil
    pcall(function()
        R:Hide()
        R:ClearAllPoints()
    end)
    freeR[#freeR + 1] = R
    rInUse = rInUse - 1
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
    release(o.under)
    release(o.orb)
    release(o.spark)
    if o.g1 then
        release(o.g1)
    end
    if o.g2 then
        release(o.g2)
    end
    if o.anch then
        releaseChain(o.ch)
        if o.gch then
            releaseChain(o.gch)
        end
        local b = o.burst
        b.n = b.n - 1
        if b.n <= 0 and b.R then
            releaseBurst(b)
        end
        o.ch, o.gch, o.burst = nil, nil, nil
    end
    o.under, o.orb, o.spark, o.g1, o.g2 = nil, nil, nil, nil, nil
    freeRec[#freeRec + 1] = o
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

local function placeA(tex, fill, w, kx, ky, size, alpha)
    if not tex.xoShown then
        tex:Show()
        tex.xoShown = true
    end
    tex:ClearAllPoints()
    if w < A_MIN then
        tex:SetPoint("CENTER", UIParent, "BOTTOMLEFT", kx, ky)
    else
        tex:SetPoint("CENTER", fill, "TOPRIGHT", kx, ky)
    end
    tex:SetSize(size, size)
    tex:SetAlpha(alpha)
end

-- Anchored orb: never measures anything; positions are weight * P (via the chain) + a known offset.
local function drawOrbA(o, p, dx, dy)
    local sx, sy, ox, oy, L = o.sx, o.sy, o.ox, o.oy, o.L
    local w, kx, ky = OrbMath.AnchoredWeights(OrbMath.PopEase(p), sx, sy, ox, oy, dx, dy, L)
    local ch = o.ch
    ch.v:SetValue(w)
    ch.h:SetValue(w)
    local s = o.size
    if p > SHRINK_FROM then
        s = s * (1 - 0.4 * (p - SHRINK_FROM) / (1 - SHRINK_FROM))
    end
    local a = (p < FADE_IN and p / FADE_IN or 1) * o.fm
    local fill = ch.fill
    placeA(o.under, fill, w, kx, ky, s * GLOW * UNDER_SIZE, a * UNDER_ALPHA)
    placeA(o.orb, fill, w, kx, ky, s * GLOW, a)
    placeA(o.spark, fill, w, kx, ky, s * SPARKLE, a * SPARKLE_ALPHA)
    o.spark:SetRotation(o.rot0 + TWO_PI * (o.el - o.delay))
    if o.g1 then
        local pk = p - GHOST_STEP
        if pk > 0 then
            local gch = o.gch
            w, kx, ky = OrbMath.AnchoredWeights(OrbMath.PopEase(pk), sx, sy, ox, oy, dx, dy, L)
            gch.v:SetValue(w)
            gch.h:SetValue(w)
            placeA(o.g1, gch.fill, w, kx, ky, s * GLOW * GHOST1_SIZE, a * GHOST1_ALPHA)
        else
            hideTex(o.g1)
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
        local drop = false
        if o.fading then
            o.fadeEl = o.fadeEl + dt
            if t < 0 or o.fadeEl >= FADE_OUT then
                drop = true
            else
                o.fm = 1 - o.fadeEl / FADE_OUT
            end
        end
        if not drop and t >= 0 then
            local p = t / o.dur
            if p >= 1 then
                arrivedRecently = arrivedRecently + 1
                flashAge, flashOn, flashRested = 0, true, o.rested
                drop = true
            elseif o.anch then
                local ok, err = pcall(drawOrbA, o, p, dx, dy)
                if not ok then
                    drop = true
                    if not drawErrLogged then
                        drawErrLogged = true
                        ns:Log("anchored draw error: %s", tostring(err))
                    end
                end
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

    if nLive == 0 and not flashOn then
        active = false
        self:SetScript("OnUpdate", nil)
    end
end

local function lighten(c)
    return c + (1 - c) * SPARKLE_WHITE
end

-- Burst{ x=, y= (UIParent coords) | plate= (nameplate frame, anchored mode), n=, scale= (default 1),
-- nPurple= (default 0), kind= }. n <= 0 is a no-op.
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
    local b
    if p.plate ~= nil then
        b = acquireBurst(p.plate)
        if not b then
            x, y = nil, nil -- the plate can't be anchored to: fall back to the screen centre
        end
    end
    if not b and (type(x) ~= "number" or type(y) ~= "number") then
        x, y = UIParent:GetWidth() / 2, UIParent:GetHeight() * 0.65
    end
    local dx, dy = Target:GetDestination()
    local trail = d.trail
    local need, chainNeed -- orb + underlay + sparkle (+ ghosts)
    if b then
        need, chainNeed = trail and 3 + GHOSTS_ANCHORED or 3, trail and 1 + GHOSTS_ANCHORED or 1
    else
        need = trail and 1 + EXTRAS or 3
    end
    local limit = ceiling() - 1 -- the arrival flash holds one slot
    local lift = LIFT * math.max(MIN_TRAVEL, UIParent:GetHeight() * ASSUMED_MOB_Y - dy)

    for i = 1, n do
        if texInUse + need > limit or (b and chainsInUse + chainNeed > chainCeiling()) then
            break
        end
        local ch, gch
        if b then
            ch = acquireChain(b.R)
            if not ch then
                break
            end
            if trail then
                gch = acquireChain(b.R)
                if not gch then
                    releaseChain(ch)
                    break
                end
            end
        end
        local rested = i <= nPurple
        local c = rested and d.restedColor or d.color
        local r, g, bl = c[1], c[2], c[3]
        local o = newRec()
        local ang, rad = random() * TWO_PI, START_RADIUS * sqrt(random())
        o.anch, o.fading, o.fadeEl, o.fm = b ~= nil, false, 0, 1
        if b then
            o.sx, o.sy = cos(ang) * rad, sin(ang) * rad
            o.ox, o.oy = OrbMath.PopControl(i, n, 0, 0, random) -- pop offset relative to the plate centre
            o.L = lift
            o.ch, o.gch, o.burst = ch, gch, b
            b.n = b.n + 1
        else
            o.x0, o.y0 = x + cos(ang) * rad, y + sin(ang) * rad
            o.c1x, o.c1y = OrbMath.PopControl(i, n, o.x0, o.y0, random)
            local ddx, ddy = dx - o.x0, dy - o.y0
            o.dist0 = sqrt(ddx * ddx + ddy * ddy)
        end
        o.delay = random() * STAGGER + (rested and RESTED_DELAY or 0)
        o.dur = d.flightTime * (0.85 + random() * 0.3)
        o.el = 0
        o.rested = rested
        o.size = d.size * scale * (rested and RESTED_SIZE or 1)
        o.rot0 = random() * TWO_PI
        o.under = acquire(ORB_TEX, -1, UNDER_R, UNDER_G, UNDER_B, "BLEND")
        o.orb = acquire(ORB_TEX, 0, r, g, bl)
        o.spark = acquire(SPARKLE_TEX, 1, lighten(r), lighten(g), lighten(bl))
        if trail then
            o.g1 = acquire(ORB_TEX, 0, r, g, bl)
            if not o.anch then
                o.g2 = acquire(ORB_TEX, 0, r, g, bl)
            end
        end
        nLive = nLive + 1
        live[nLive] = o
    end
    if b and b.n == 0 then
        releaseBurst(b)
    end

    if nLive > 0 and not active then
        active = true
        driver:SetScript("OnUpdate", onUpdate)
    end
end

-- A plate frame we may be anchored to was assigned to a new unit: fade its orbs out (0.15 s) and release them.
function Orbs:PlateReused(plate)
    for i = 1, nLive do
        local o = live[i]
        if o.anch and o.burst.plate == plate and not o.fading then
            o.fading, o.fadeEl = true, 0
        end
    end
end

-- chainsInUse, chainsCreated, chainCeiling, burstFramesInUse, burstFramesCreated
function Orbs:AnchorInfo()
    return chainsInUse, chainsCreated, chainCeiling(), rInUse, rCreated
end

-- active, texturesInUse, texturesCreated, ceiling
function Orbs:Info()
    return active, texInUse, texCreated, ceiling()
end

local function targetPlate()
    if not (C_NamePlate and C_NamePlate.GetNamePlateForUnit) then
        return nil
    end
    local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, "target")
    if ok and p and readable(p) and type(p) == "table" then
        return p
    end
    return nil
end

-- Returns x, y, plate, label. force: nil (follow db.origin) | "frame" | "plate".
local function testOrigin(force)
    local frameFirst = force == "frame" or (force == nil and db().origin == "targetframe")
    if frameFirst then
        local fx, fy = Target:TargetFrameOrigin()
        if fx then
            return fx, fy, nil, "target frame"
        end
    end
    local plate = targetPlate()
    if plate then
        return nil, nil, plate, "target plate"
    end
    local ok, e = pcall(function()
        return ns.Plates and ns.Plates.TargetEntry and ns.Plates:TargetEntry()
    end)
    if ok and type(e) == "table" and type(e.x) == "number" and type(e.y) == "number" then
        return e.x, e.y, nil, "target plate"
    end
    if not frameFirst and force == nil then
        local fx, fy = Target:TargetFrameOrigin()
        if fx then
            return fx, fy, nil, "target frame"
        end
    end
    local okc, cx, cy = pcall(GetCursorPosition)
    local oks, sc = pcall(UIParent.GetEffectiveScale, UIParent)
    if okc and oks and type(cx) == "number" and type(cy) == "number" and type(sc) == "number" and sc > 0 then
        return cx / sc, cy / sc, nil, "cursor"
    end
    return UIParent:GetWidth() / 2, UIParent:GetHeight() / 2, nil, "cursor"
end

-- /xporbs test [pct] [rested] [frame|plate]
function ns.commands.test(arg)
    local d = db()
    local pct, rested, force = 5, false, nil
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        elseif tok == "frame" or tok == "plate" then
            force = tok
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
    local x, y, plate, label = testOrigin(force)
    Orbs:Burst({ x = x, y = y, plate = plate, n = n, scale = scale, nPurple = nPurple, kind = "test" })
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f, origin=%s", pct, n, nPurple,
        scale, label))
end

-- /xporbs origin plate|frame
function ns.commands.origin(arg)
    local w = string.match(arg or "", "%S+")
    if w == "plate" then
        db().origin = "plate"
    elseif w == "frame" or w == "targetframe" then
        db().origin = "targetframe"
    elseif w ~= nil then
        ns.Print("origin: use plate or frame")
        return
    end
    ns.Print("origin: " .. (db().origin == "targetframe" and "frame (target unit frame)" or "plate (anchored)"))
end

table.insert(ns.statusProviders, function()
    Target:GetDestination()
    return string.format(
        "orbs: driver=%s, live textures=%d, pool=%d/%d, dest=%s, fallback=%s, origin=%s",
        active and "active" or "idle",
        texInUse,
        texCreated,
        ceiling(),
        tostring(Target.lastName),
        Target.lastOk and "no" or "yes",
        db().origin == "targetframe" and "targetframe" or "plate"
    )
end)
table.insert(ns.statusProviders, function()
    return string.format("anchor: chains=%d/%d (ceiling %d) burstFrames=%d/%d", chainsInUse, chainsCreated,
        chainCeiling(), rInUse, rCreated)
end)

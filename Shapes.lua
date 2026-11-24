-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- The orb shapes other than Starlight (db.orbShape): Retro, Wisp and Power. Starlight is the original drawing in
-- Orbs.lua; this file registers the other three in ns.OrbShapes.by (see the SHAPES comment in Orbs.lua for what a shape
-- table must offer) and borrows the pooled-texture and placement helpers of Orbs.lua through ns.OrbShapes.host.
--
-- Nothing here is touched by an orb that was started as Starlight, and an orb keeps the shape it was started with
-- (orb.shape, set per burst), so changing the setting mid-flight never swaps art on orbs already in the air.
--
-- Per orb, a shape draws with the 3 textures of a slot (underlay, body, third) and, for a flying orb, up to 4 more
-- (ghost1..ghost4, the trail). The third is the sparkle of Starlight: Retro's twinkle, Power's bolt layer, unused by
-- Wisp. The state that varies per orb (blink phase, bolt timer, breathing phase, cell size) lives in `st`: the orb
-- record, or a per-slot table of a pop group.

local SHAPES = ns.OrbShapes
local host, k = SHAPES.host, SHAPES.k
local take, putAt, place, hideTex, flightPoint = host.take, host.putAt, host.place, host.hide, host.flightPoint

local random = math.random
local floor, ceil, max, min, sin = math.floor, math.ceil, math.max, math.min, math.sin
local TWO_PI = math.pi * 2

local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local RETRO_TEX = "Interface\\AddOns\\XPOrbs\\media\\retro" -- 64x64: the 8 x 8 cell octagon, 8 px per cell
local RETRO_UNDER_TEX = "Interface\\AddOns\\XPOrbs\\media\\retro_under" -- 128x128: 10 x 10 cell art, top left
local RETRO_TWINKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\retro_twinkle" -- 32x32: 3 x 3 cell "+", top left
local WISP_TEX = "Interface\\AddOns\\XPOrbs\\media\\wisp"
local WISP_UNDER_TEX = "Interface\\AddOns\\XPOrbs\\media\\wisp_under"
local POWER_CORE_TEX = "Interface\\AddOns\\XPOrbs\\media\\power_core"
-- the four bolt frames, built once so nothing is concatenated while orbs fly
local BOLT_TEX = {
    "Interface\\AddOns\\XPOrbs\\media\\bolt1",
    "Interface\\AddOns\\XPOrbs\\media\\bolt2",
    "Interface\\AddOns\\XPOrbs\\media\\bolt3",
    "Interface\\AddOns\\XPOrbs\\media\\bolt4",
}

local UNDER_K = k.underK
local GLOW = k.glow
local GHOST_KEY = { "ghost1", "ghost2", "ghost3", "ghost4" }

-- Retro: the art is 8 x 8 "pixels" (cells). RETRO_K makes db.size 14 (the default) a 24 px orb, 3 px per cell.
local RETRO_K = 24 / 14
local RETRO_CELLS_MIN = 2 -- px per cell at the smallest
local RETRO_UNDER_ALPHA = 0.9
local RETRO_UNDER_UV = 80 / 128 -- the 10-cell art in the 128 px texture
local RETRO_TWINKLE_UV = 24 / 32 -- the 3-cell art in the 32 px texture
local RETRO_TWINKLE_WHITE = 0.5 -- twinkle tint = lerp(colour, white, this)
local RETRO_BLINK = 0.25 -- seconds on, then seconds off
local RETRO_TWINKLE_OFF = 2.5 -- cells from the orb centre (x left, y up): the middle of art cell (1, 1)
local RETRO_TRAIL_BIG = { gap = 6, cells = 2, alpha = 0.70 } -- a 2 x 2 cell square, 0.75 x the body behind the orb
local RETRO_TRAIL_SMALL = { gap = 10, cells = 1, alpha = 0.40 } -- a 1 cell square, body + 2 cells behind

-- Wisp
local WISP_COUNT, WISP_SIZE, WISP_TIME = 0.5, 1.6, 1.35 -- multipliers on the player's own settings
local WISP_BODY = 1.5 -- drawn size = size * this (the art has a solid rim, so no GLOW)
local WISP_UNDER_ALPHA = 0.80
local WISP_BREATH, WISP_RATE = 0.06, 2.5 -- size x (1 + WISP_BREATH * sin(2 pi WISP_RATE t + phase))
local WISP_GAP = { 10, 20, 30, 40 } -- px of trail between the orb and each ghost
local WISP_GHOST_ALPHA = { 0.52, 0.36, 0.22, 0.12 }
local WISP_GHOST_SIZE = { 0.87, 0.75, 0.65, 0.55 }

-- Power
local POWER_CORE = 0.9 -- core size = body * this (body = size * GLOW as Starlight)
local POWER_BOLT = 1.5 -- bolt layer size = body * this
local POWER_BOLT_WHITE = 0.15
local POWER_UNDER, POWER_UNDER_ALPHA = 1.6, 0.58
local POWER_TICK_MIN, POWER_TICK_SPAN = 0.07, 0.02 -- each orb's bolt changes every 70-90 ms
local POWER_TURN_MIN = math.pi / 3 -- the bolt turns at least 60 degrees at every change
local POWER_ALPHA_MIN = 0.7 -- bolt alpha U(0.7, 1.0)

-- ---------------------------------------------------------------- helpers

local nearestOk -- nil until tried, then whether SetTexture took the "NEAREST" filter argument
-- SetTexture with nearest-neighbour filtering (crisp pixels); a client that rejects the argument gets the plain call
-- from then on. The outcome is logged once.
local function setNearest(tex, path)
    if nearestOk ~= false then
        local ok = pcall(tex.SetTexture, tex, path, nil, nil, "NEAREST")
        if nearestOk == nil then
            nearestOk = ok
            ns:Log("SHAPE nearest filter %s", ok and "ok" or "unavailable, using the plain filter")
        end
        if ok then
            return
        end
    end
    tex:SetTexture(path)
end

local function style(tex, subLayer, blend, red, green, blue)
    tex:SetBlendMode(blend)
    tex:SetDrawLayer("ARTWORK", subLayer)
    tex:SetVertexColor(red, green, blue)
end

-- A freshly taken or configured texture starts hidden, like Orbs.lua's acquire.
local function ready(tex)
    tex:SetAlpha(0)
    tex:Hide()
    tex.xoShown = false
end

local function lerp(channel, toward, amount)
    return channel + (toward - channel) * amount
end

local function identity(n, nPurple, scale)
    return n, nPurple, scale
end

-- The position of the trail point `gap` px behind the orb along its flight, plus that point's size and alpha
-- multipliers; nil while the orb has not flown that far. A crossfade orb fading in has no path behind it yet: its
-- trail sits along -u (towards where it implicitly came from).
local function behind(orb, progress, gap, dx, dy, control2X, control2Y, orbX, orbY)
    if orb.group and progress < orb.fadeIn then
        return orbX - orb.ux * gap, orbY - orb.uy * gap, 1, 1
    end
    local earlier = progress - gap / max(orb.flightDist, 60)
    if earlier <= 0 then
        return nil
    end
    return flightPoint(orb, earlier, dx, dy, control2X, control2Y)
end

-- Builds a flying orb of `shape`: the 3 slot textures (the third only when withThird), configured by shape.setup.
local function buildSlots(shape, orb, red, green, blue, withThird)
    orb.under, orb.body = take(), take()
    if withThird then
        orb.spark = take()
    end
    shape.setup(orb.under, orb.body, orb.spark, orb, red, green, blue)
    ready(orb.under)
    ready(orb.body)
    if withThird then
        ready(orb.spark)
    end
end

-- ---------------------------------------------------------------- Retro

local RETRO = { needTrail = 5, needPlain = 3, timeMul = 1, adjust = identity }

function RETRO.setup(under, body, spark, st, red, green, blue)
    setNearest(under, RETRO_UNDER_TEX)
    under:SetTexCoord(0, RETRO_UNDER_UV, 0, RETRO_UNDER_UV)
    under.xoDirty = true
    style(under, -1, "BLEND", red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    setNearest(body, RETRO_TEX)
    style(body, 0, "ADD", red, green, blue)
    setNearest(spark, RETRO_TWINKLE_TEX)
    spark:SetTexCoord(0, RETRO_TWINKLE_UV, 0, RETRO_TWINKLE_UV)
    spark.xoDirty = true
    style(spark, 1, "ADD", lerp(red, 1, RETRO_TWINKLE_WHITE), lerp(green, 1, RETRO_TWINKLE_WHITE),
        lerp(blue, 1, RETRO_TWINKLE_WHITE))
    st.phase = random() * 2 * RETRO_BLINK -- where in the on / off blink this orb starts
end

-- A trail square: a colour texture (no art), ADD, tinted by the orb colour.
local function newSquare(red, green, blue)
    local tex = take()
    tex:SetColorTexture(red, green, blue, 1)
    style(tex, 0, "ADD", 1, 1, 1)
    ready(tex)
    return tex
end

function RETRO.build(orb, trail, red, green, blue)
    buildSlots(RETRO, orb, red, green, blue, true)
    if trail then
        orb.ghost1 = newSquare(red, green, blue)
        orb.ghost2 = newSquare(red, green, blue)
    end
end

-- The 8 x 8 cell body (size px, whole cells of at least 2 px) on a grid of cells, so it moves in chunky steps; the
-- underlay is the octagon grown by one cell all round; the twinkle is a 3-cell "+" on the top left cut corner that
-- blinks.
function RETRO.draw(st, t, rel, under, body, spark, x, y, size, alpha)
    local cell = max(RETRO_CELLS_MIN, floor(size * RETRO_K / 8 + 0.5))
    st.cell = cell
    local gridX, gridY = floor(x / cell + 0.5) * cell, floor(y / cell + 0.5) * cell
    putAt(under, rel, gridX, gridY, 10 * cell, alpha * RETRO_UNDER_ALPHA)
    putAt(body, rel, gridX, gridY, 8 * cell, alpha)
    if (t + st.phase) % (2 * RETRO_BLINK) < RETRO_BLINK then
        putAt(spark, rel, gridX - RETRO_TWINKLE_OFF * cell, gridY + RETRO_TWINKLE_OFF * cell, 3 * cell, alpha)
    else
        hideTex(spark)
    end
end

-- One trail square `part.gap` cells behind the orb, snapped so its edges sit on the cell grid (an even number of cells
-- is centred on a grid line, an odd one in the middle of a cell).
local function trailSquare(orb, tex, part, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
    local cell = orb.cell
    local x, y = behind(orb, progress, part.gap * cell, dx, dy, control2X, control2Y, orbX, orbY)
    if not x then
        hideTex(tex)
        return
    end
    if part.cells % 2 == 0 then
        x, y = floor(x / cell + 0.5) * cell, floor(y / cell + 0.5) * cell
    else
        x, y = (floor(x / cell) + 0.5) * cell, (floor(y / cell) + 0.5) * cell
    end
    place(tex, x, y, part.cells * cell, alpha * part.alpha)
end

function RETRO.trail(orb, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
    trailSquare(orb, orb.ghost1, RETRO_TRAIL_BIG, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
    trailSquare(orb, orb.ghost2, RETRO_TRAIL_SMALL, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
end

-- ---------------------------------------------------------------- Wisp

local WISP = { needTrail = 6, needPlain = 2, timeMul = WISP_TIME }

-- Half the orbs (at least one; the rested share scaled to match), 1.6 x the size (and 1.35 x the flight time).
function WISP.adjust(n, nPurple, scale)
    local count = max(1, ceil(n * WISP_COUNT))
    return count, nPurple > 0 and floor(nPurple * count / n + 0.5) or 0, scale * WISP_SIZE
end

function WISP.setup(under, body, spark, st, red, green, blue)
    under:SetTexture(WISP_UNDER_TEX)
    style(under, -1, "BLEND", red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    body:SetTexture(WISP_TEX)
    style(body, 0, "ADD", red, green, blue)
    if spark then -- no sparkle: the slot just stays hidden
        spark:Hide()
        spark.xoShown = false
    end
    st.phase = random() * TWO_PI
end

function WISP.build(orb, trail, red, green, blue)
    buildSlots(WISP, orb, red, green, blue, false)
    if trail then
        for i = 1, 4 do
            local tex = take()
            tex:SetTexture(WISP_TEX)
            style(tex, 0, "ADD", red, green, blue)
            ready(tex)
            orb[GHOST_KEY[i]] = tex
        end
    end
end

-- A solid ball with a faint dark disc under it, breathing slowly.
function WISP.draw(st, t, rel, under, body, spark, x, y, size, alpha)
    local drawn = size * WISP_BODY * (1 + WISP_BREATH * sin(TWO_PI * WISP_RATE * t + st.phase))
    st.bodySize = drawn
    putAt(under, rel, x, y, drawn, alpha * WISP_UNDER_ALPHA)
    putAt(body, rel, x, y, drawn, alpha)
end

-- Four ghosts at fixed gaps behind the orb, each smaller and fainter.
function WISP.trail(orb, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
    for i = 1, 4 do
        local tex = orb[GHOST_KEY[i]]
        local x, y, sizeMul, alphaMul = behind(orb, progress, WISP_GAP[i], dx, dy, control2X, control2Y, orbX, orbY)
        if x then
            place(tex, x, y, orb.bodySize * sizeMul * WISP_GHOST_SIZE[i], alpha * alphaMul * WISP_GHOST_ALPHA[i])
        else
            hideTex(tex)
        end
    end
end

-- ---------------------------------------------------------------- Power

local POWER = { needTrail = 5, needPlain = 3, timeMul = 1, adjust = identity }

-- Gives the bolt layer a frame different from the last, turned at least 60 degrees, at a new brightness.
local function nextBolt(st, spark, t)
    st.boltAt = t + st.boltEvery
    local frame = floor(random() * 3) + 1 -- one of the three that is not the current frame
    if frame >= st.boltFrame then
        frame = frame + 1
    end
    st.boltFrame = frame
    st.boltTurn = (st.boltTurn + POWER_TURN_MIN + random() * (TWO_PI - 2 * POWER_TURN_MIN)) % TWO_PI
    st.boltAlpha = POWER_ALPHA_MIN + random() * (1 - POWER_ALPHA_MIN)
    spark:SetTexture(BOLT_TEX[frame])
    spark:SetRotation(st.boltTurn)
end

function POWER.setup(under, body, spark, st, red, green, blue)
    under:SetTexture(ORB_TEX)
    style(under, -1, "BLEND", red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    body:SetTexture(POWER_CORE_TEX)
    style(body, 0, "ADD", red, green, blue)
    st.boltEvery = POWER_TICK_MIN + random() * POWER_TICK_SPAN
    st.boltAt = random() * st.boltEvery -- a random phase, so a burst's bolts don't change in step
    st.boltFrame = floor(random() * 4) + 1
    st.boltTurn = random() * TWO_PI
    st.boltAlpha = POWER_ALPHA_MIN + random() * (1 - POWER_ALPHA_MIN)
    spark:SetTexture(BOLT_TEX[st.boltFrame])
    spark:SetRotation(st.boltTurn)
    spark.xoDirty = true
    style(spark, 1, "ADD", lerp(red, 1, POWER_BOLT_WHITE), lerp(green, 1, POWER_BOLT_WHITE),
        lerp(blue, 1, POWER_BOLT_WHITE))
end

function POWER.build(orb, trail, red, green, blue)
    buildSlots(POWER, orb, red, green, blue, true)
    if trail then
        for i = 1, 2 do
            local tex = take()
            tex:SetTexture(POWER_CORE_TEX)
            style(tex, 0, "ADD", red, green, blue)
            ready(tex)
            orb[GHOST_KEY[i]] = tex
        end
    end
end

-- A steady core in a dark bed, wrapped in a bolt layer that jumps to another frame, angle and brightness every 70-90
-- ms. (The ghosts are drawn by Orbs.lua, as for Starlight.)
function POWER.draw(st, t, rel, under, body, spark, x, y, size, alpha)
    local bodySize = size * GLOW
    if t >= st.boltAt then
        nextBolt(st, spark, t)
    end
    putAt(under, rel, x, y, bodySize * POWER_UNDER, alpha * POWER_UNDER_ALPHA)
    putAt(body, rel, x, y, bodySize * POWER_CORE, alpha)
    putAt(spark, rel, x, y, bodySize * POWER_BOLT, alpha * st.boltAlpha)
end

SHAPES.by.retro, SHAPES.by.wisp, SHAPES.by.power = RETRO, WISP, POWER
SHAPES.nearestOk = function()
    return nearestOk
end

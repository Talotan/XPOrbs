-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- The orb shapes other than Starlight (db.orbShape): Retro, Globe and Crackle. Starlight is the original drawing in
-- Orbs.lua; this file registers the other three in ns.OrbShapes.by (see the SHAPES comment in Orbs.lua for what a shape
-- table must offer) and borrows the pooled-texture and placement helpers of Orbs.lua through ns.OrbShapes.host.
--
-- Nothing here is touched by an orb that was started as Starlight, and an orb keeps the shape it was started with
-- (orb.shape, set per burst), so changing the setting mid-flight never swaps art on orbs already in the air.
--
-- Per orb, a shape draws with the 3 textures of a slot (underlay, body, third) and, for a flying orb, up to 4 more
-- (ghost1..ghost4, the trail). The third is the sparkle of Starlight: Retro's twinkle, Crackle's bolt layer,
-- Globe's glint. The state that varies per orb (blink phase, bolt timer, breathing phase, cell size) lives in `st`:
-- the orb record, or a per-slot table of a pop group.

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
local GLOBE_TEX = "Interface\\AddOns\\XPOrbs\\media\\globe"
local GLOBE_UNDER_TEX = "Interface\\AddOns\\XPOrbs\\media\\globe_under"
local GLOBE_GLINT_TEX = "Interface\\AddOns\\XPOrbs\\media\\globe_glint"
local CRACKLE_CORE_TEX = "Interface\\AddOns\\XPOrbs\\media\\crackle_core"
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

-- Retro: the art is 8 x 8 "pixels" (cells). RETRO_K makes db.size 14 a 24 px orb, 3 px per cell. One cell size serves
-- a whole burst (from db.size x the burst's scale, st.base: no rested or pop multiplier), so every orb of it has the
-- same pixels.
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
-- A pop or bloom draws Retro at RETRO_GROW_FROM of the flight cell, growing to the full cell over the first
-- RETRO_GROW_SPAN of the pop, in whole pixels: it pops in in steps and never gets bigger than in flight.
local RETRO_GROW_FROM, RETRO_GROW_SPAN = 0.4, 0.4

-- Globe (the size, count and flight time are the player's own: no multipliers)
local GLOBE_BODY = 1.5 -- drawn size = size * this (the art has a solid rim, so no GLOW)
local GLOBE_UNDER_ALPHA = 0.80
local GLOBE_BREATH, GLOBE_RATE = 0.06, 2.5 -- size x (1 + GLOBE_BREATH * sin(2 pi GLOBE_RATE t + phase)), if db.pulse
local GLOBE_GAP = { 10, 20, 30, 40 } -- px of trail between the orb and each ghost
local GLOBE_GHOST_ALPHA = { 0.52, 0.36, 0.22, 0.12 }
local GLOBE_GHOST_SIZE = { 0.87, 0.75, 0.65, 0.55 }
-- the glint, a small highlight up and to the left of the centre that makes it read as a sphere: quad = body * SIZE,
-- centred (X, Y) bodies from the centre (y up), tinted lerp(colour, white, WHITE)
local GLOBE_GLINT_SIZE, GLOBE_GLINT_X, GLOBE_GLINT_Y = 0.30, -0.20, 0.20
local GLOBE_GLINT_ALPHA, GLOBE_GLINT_WHITE = 0.55, 0.75

-- Crackle
local CRACKLE_CORE = 1.15 -- core size = body * this (body = size * GLOW as Starlight)
local CRACKLE_BOLT = 1.30 -- bolt layer size = body * this: its arcs sit on the core's rim
local CRACKLE_BOLT_WHITE = 0.15
local CRACKLE_UNDER, CRACKLE_UNDER_ALPHA = 1.6, 0.58
local CRACKLE_TICK_MIN, CRACKLE_TICK_SPAN = 0.07, 0.02 -- each orb's bolt changes every 70-90 ms
local CRACKLE_TURN_MIN = math.pi / 3 -- the bolt turns at least 60 degrees at every change
local CRACKLE_ALPHA_MIN = 0.7 -- bolt alpha U(0.7, 1.0)

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

-- Where a pop or bloom is `progress` (0..1, of the pop) between RETRO_GROW_FROM and 1 of the flight size. Called by
-- Orbs.lua for every shape (only Retro uses what it gets).
function SHAPES.grow(progress)
    if progress >= RETRO_GROW_SPAN then
        return 1
    end
    return RETRO_GROW_FROM + (1 - RETRO_GROW_FROM) * max(0, progress) / RETRO_GROW_SPAN
end

-- px per cell of a burst whose orbs are `base` (db.size x scale) before any rested or pop multiplier.
local function retroCell(base)
    return max(RETRO_CELLS_MIN, floor(base * RETRO_K / 8 + 0.5))
end

function RETRO.setup(under, body, spark, st, red, green, blue)
    st.flightCell = retroCell(st.base or ns.db.size)
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

-- The 8 x 8 cell body on a grid of cells, so it moves in chunky steps. The cell is the burst's own (whole pixels, at
-- least 2), whatever `size` is (rested orbs and pops are drawn at the same cell); a pop or bloom (`grow` below 1)
-- draws smaller whole pixels. The underlay is the octagon grown by one cell all round; the twinkle is a 3-cell "+" on
-- the top left cut corner that blinks.
function RETRO.draw(st, t, rel, under, body, spark, x, y, size, alpha, grow)
    local cell = st.flightCell or retroCell(size)
    if grow and grow < 1 then
        cell = max(1, floor(cell * grow + 0.5))
    end
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

-- ---------------------------------------------------------------- Globe

local GLOBE = { needTrail = 7, needPlain = 3, timeMul = 1, adjust = identity }

function GLOBE.setup(under, body, spark, st, red, green, blue)
    under:SetTexture(GLOBE_UNDER_TEX)
    style(under, -1, "BLEND", red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    body:SetTexture(GLOBE_TEX)
    style(body, 0, "ADD", red, green, blue)
    spark:SetTexture(GLOBE_GLINT_TEX)
    style(spark, 1, "ADD", lerp(red, 1, GLOBE_GLINT_WHITE), lerp(green, 1, GLOBE_GLINT_WHITE),
        lerp(blue, 1, GLOBE_GLINT_WHITE))
    st.phase = random() * TWO_PI
end

function GLOBE.build(orb, trail, red, green, blue)
    buildSlots(GLOBE, orb, red, green, blue, true)
    if trail then
        for i = 1, 4 do
            local tex = take()
            tex:SetTexture(GLOBE_TEX)
            style(tex, 0, "ADD", red, green, blue)
            ready(tex)
            orb[GHOST_KEY[i]] = tex
        end
    end
end

-- A solid ball with a faint dark disc under it and a small glint up and to the left, breathing slowly (unless
-- db.pulse is off). The glint breathes with the body.
function GLOBE.draw(st, t, rel, under, body, spark, x, y, size, alpha)
    local drawn = size * GLOBE_BODY
    if ns.db.pulse ~= false then
        drawn = drawn * (1 + GLOBE_BREATH * sin(TWO_PI * GLOBE_RATE * t + st.phase))
    end
    st.bodySize = drawn
    putAt(under, rel, x, y, drawn, alpha * GLOBE_UNDER_ALPHA)
    putAt(body, rel, x, y, drawn, alpha)
    putAt(spark, rel, x + GLOBE_GLINT_X * drawn, y + GLOBE_GLINT_Y * drawn, drawn * GLOBE_GLINT_SIZE,
        alpha * GLOBE_GLINT_ALPHA)
end

-- Four ghosts at fixed gaps behind the orb, each smaller and fainter.
function GLOBE.trail(orb, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha)
    for i = 1, 4 do
        local tex = orb[GHOST_KEY[i]]
        local x, y, sizeMul, alphaMul = behind(orb, progress, GLOBE_GAP[i], dx, dy, control2X, control2Y, orbX, orbY)
        if x then
            place(tex, x, y, orb.bodySize * sizeMul * GLOBE_GHOST_SIZE[i], alpha * alphaMul * GLOBE_GHOST_ALPHA[i])
        else
            hideTex(tex)
        end
    end
end

-- ---------------------------------------------------------------- Crackle

local CRACKLE = { needTrail = 5, needPlain = 3, timeMul = 1, adjust = identity }

-- Gives the bolt layer a frame different from the last, turned at least 60 degrees, at a new brightness.
local function nextBolt(st, spark, t)
    st.boltAt = t + st.boltEvery
    local frame = floor(random() * 3) + 1 -- one of the three that is not the current frame
    if frame >= st.boltFrame then
        frame = frame + 1
    end
    st.boltFrame = frame
    st.boltTurn = (st.boltTurn + CRACKLE_TURN_MIN + random() * (TWO_PI - 2 * CRACKLE_TURN_MIN)) % TWO_PI
    st.boltAlpha = CRACKLE_ALPHA_MIN + random() * (1 - CRACKLE_ALPHA_MIN)
    spark:SetTexture(BOLT_TEX[frame])
    spark:SetRotation(st.boltTurn)
end

function CRACKLE.setup(under, body, spark, st, red, green, blue)
    under:SetTexture(ORB_TEX)
    style(under, -1, "BLEND", red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    body:SetTexture(CRACKLE_CORE_TEX)
    style(body, 0, "ADD", red, green, blue)
    st.boltEvery = CRACKLE_TICK_MIN + random() * CRACKLE_TICK_SPAN
    st.boltAt = random() * st.boltEvery -- a random phase, so a burst's bolts don't change in step
    st.boltFrame = floor(random() * 4) + 1
    st.boltTurn = random() * TWO_PI
    st.boltAlpha = CRACKLE_ALPHA_MIN + random() * (1 - CRACKLE_ALPHA_MIN)
    spark:SetTexture(BOLT_TEX[st.boltFrame])
    spark:SetRotation(st.boltTurn)
    spark.xoDirty = true
    style(spark, 1, "ADD", lerp(red, 1, CRACKLE_BOLT_WHITE), lerp(green, 1, CRACKLE_BOLT_WHITE),
        lerp(blue, 1, CRACKLE_BOLT_WHITE))
end

function CRACKLE.build(orb, trail, red, green, blue)
    buildSlots(CRACKLE, orb, red, green, blue, true)
    if trail then
        for i = 1, 2 do
            local tex = take()
            tex:SetTexture(CRACKLE_CORE_TEX)
            style(tex, 0, "ADD", red, green, blue)
            ready(tex)
            orb[GHOST_KEY[i]] = tex
        end
    end
end

-- A steady core in a dark bed, wrapped in a bolt layer that jumps to another frame, angle and brightness every 70-90
-- ms. (The ghosts are drawn by Orbs.lua, as for Starlight.)
function CRACKLE.draw(st, t, rel, under, body, spark, x, y, size, alpha)
    local bodySize = size * GLOW
    if t >= st.boltAt then
        nextBolt(st, spark, t)
    end
    putAt(under, rel, x, y, bodySize * CRACKLE_UNDER, alpha * CRACKLE_UNDER_ALPHA)
    putAt(body, rel, x, y, bodySize * CRACKLE_CORE, alpha)
    putAt(spark, rel, x, y, bodySize * CRACKLE_BOLT, alpha * st.boltAlpha)
end

SHAPES.by.retro, SHAPES.by.globe, SHAPES.by.crackle = RETRO, GLOBE, CRACKLE
SHAPES.nearestOk = function()
    return nearestOk
end

-- /xporbs status: whether Retro's crisp-pixel filter took (shown once Retro is the shape or has been drawn).
table.insert(ns.statusProviders, function()
    if nearestOk == nil and not (ns.db and ns.db.orbShape == "retro") then
        return nil
    end
    local state = "not tried yet"
    if nearestOk ~= nil then
        state = nearestOk and "nearest" or "smoothed (nearest unavailable)"
    end
    return "retro pixel filter: " .. state
end)

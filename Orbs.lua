-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Orb renderer: one overlay frame, a hand-rolled texture pool and a single OnUpdate driver that only runs
-- while orbs or the arrival flash are alive. Frames are created lazily on the first burst.
--
-- How it fits together: Kills.lua (and /xporbs test) call Orbs:Burst, which builds one "orb" record per orb in `live`
-- (start point, control point, flight time, textures) and hands them to the driver. The driver (`drive`) moves every
-- orb each frame along a cubic curve from OrbMath towards the XP bar (Target:GetDestination) and plays the arrival
-- chime (Sound.lua) and flash. A corpse pop or crossfade shares one pooled "group" (a small frame anchored to the
-- nameplate plus its textures) between its orbs. Orb record fields: x0/y0 stream start, control1X/Y first control
-- point, px/py P-hat (the estimated mob position), ux/uy unit vector from P-hat towards the bar, ringX/Y ring point
-- (pop and crossfade copy A), hold seconds spent in that ring before the flight, dur flight time, delay start delay,
-- pathKind / pathAmp / pathFreq1-3 / pathPhase1-3 the flight path (db.flightPath at spawn) and its random parameters.

local Orbs = {}
ns.Orbs = Orbs

local OrbMath = ns.OrbMath
local Target = ns.Target

local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
Orbs.ORB_TEX = ORB_TEX -- Calib.lua draws its marker with the same art
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local FLASH_TEX = "Interface\\AddOns\\XPOrbs\\media\\flash"
local FLASH_TEX_VERTICAL = "Interface\\AddOns\\XPOrbs\\media\\flash_v" -- the flash transposed (32x128)
-- arrival flash art per shape (orb.tga is a radial gradient); one table so the driver holds one upvalue, not three
local FLASH_SHAPE_TEX = { bar = FLASH_TEX, vertical = FLASH_TEX_VERTICAL, round = ORB_TEX }
local TWO_PI = math.pi * 2
local random = math.random
local floor, min, max, sqrt, cos, sin = math.floor, math.min, math.max, math.sqrt, math.cos, math.sin

-- Tunables (retune here).
local EXTRAS = 5 -- ceiling formula: cap * (1 + EXTRAS) * 2 + 8. Per orb: orb + underlay + sparkle + 3 trail ghosts
local MIN_DUR = 0.05 -- shortest allowed flight, so a bad flightTime can never strand an orb
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
-- Flight speed mode (db.flightMode "speed"): px per second at flightSpeed 100 % (1300 px/s: calibrated in game so 100 %
-- feels like the old 1 s flight time over a typical mob-to-bar flight). Lives in SHAPES.k (refSpeed) so Burst reads it.
-- The trail ghosts are spaced in px along the path, ghostGapK x the drawn diameter apart (SHAPES.k), whatever the
-- speed, so they always overlap into a smear; orb.pxToProgress (1 / path length, set at spawn) turns px into progress.
local REF_SPEED = 1300
local GHOST1_ALPHA, GHOST1_SIZE = 0.55, 0.85
local GHOST2_ALPHA, GHOST2_SIZE = 0.30, 0.70
local GHOST3_ALPHA, GHOST3_SIZE = 0.15, 0.55
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
-- Crossfade style: the orbs leave the corpse and reappear just above the bar; most of the trip is implied, not drawn.
-- Copy A is drawn relative to the plate's BOTTOM (exact, whatever P-hat is): it blooms to a ring (XF_HOLD), then
-- accelerates away along u (the unit vector from P-hat towards the bar) for leaveDist px, fading out. Copy B (screen
-- space) appears only after A is gone and a short gap with nothing drawn: it starts about D = clamp(min(0.30 * screen
-- height, 0.60 * L), 80, 320) (L = P-hat to bar) px short of the bar (along -u, within a bSpread px disc) and
-- flies the last stretch.
local XF_HOLD = 0.24 -- s: the small pop at the plate (copy A only)
local XF_BLOOM_R = 24 -- px: smallest ring radius reached (ease-out cubic) by the end of the pop (rmax 36)
local XF_BLOOM_SIZE = 1.6 -- start-size multiplier during the bloom, easing to 1.0 by its end
local XF_FADE_IN = 0.06 -- s: alpha fade-in at birth
local XF_EASE_OUT = 0.70 -- ease-out weight of copy B's launch (PopEase default 0.5): fast entry, slowing into the bar
-- Profile of the crossfade plate-copy machinery (orb.profile), a static table built once so nothing allocates per
-- frame.
-- bloom: seconds the bloom from P-hat to the ring point takes; bsize: start-size multiplier of the bloom; fadeIn:
-- alpha fade-in seconds; flight: flightTime multiplier;
-- ease: ease-out weight of the launch; hold: base seconds before the flight; rmin/rmax/drift: ring radius range and
-- extra upward drift of the ring point.
-- leave = true (crossfade) switches on the leave / reappear behaviour: leaveDist px along u over leaveTime s with
-- ease-in (progress^2), alpha 1 - progress^2, size 1 -> 0.8; each orb's leave starts a random 0..leaveStagger s after
-- the bloom; B's flight starts gap s after A is gone (so hold = bloom + stagger + leaveTime + gap); B fades in over
-- bFade s, starts at (bDistMin..bDistMax, min(bScreenFrac * screen height, bLengthFrac * L)) px from the bar and
-- flies flightTime * flight * (jitterLow..jitterLow + jitterSpan); ctrlAhead / ctrlJitter put its first control
-- point ctrlAhead * dist ahead along u, jittered sideways by +-ctrlJitter * dist (no lift); its trail
-- ghosts sit behind it (along -u) during the fade-in, SHAPES.k.ghostGapK drawn diameters apart.
-- ux, uy, bCentreX, bCentreY, leaveDistClamped are per-burst scratch (see XF_PROFILE.plan). The arcs of every style
-- share more of it (Burst has no upvalue to spare, so it lives here): screenW, screenH, bowSide (1 or -1, the side the
-- arcs bow to) and edgeMargin = edgeFraction * screen height, the base inset of the control points.
local XF_PROFILE = { bloom = XF_HOLD, bsize = XF_BLOOM_SIZE, fadeIn = XF_FADE_IN,
    flight = 0.40, ease = XF_EASE_OUT, hold = XF_HOLD, rmin = XF_BLOOM_R, rmax = 36, drift = 8, born = 0.04,
    leave = true, leaveDist = 180, leaveTime = 0.26, leaveStagger = 0.15, gap = 0.10, bFade = 0.08, bSpread = 14,
    bDistMin = 80, bDistMax = 320, bScreenFrac = 0.30, bLengthFrac = 0.60, jitterLow = 0.94, jitterSpan = 0.12,
    ctrlAhead = 0.4, ctrlJitter = 0.1,
    ux = 0, uy = 1, bCentreX = 0, bCentreY = 0,
    edgeFraction = 0.04, screenW = 0, screenH = 0, bowSide = 1, edgeMargin = 0 }
-- db.unknownOrigin for the "mob position unknown" case (est == "default"): "wide" (the default) starts the stream
-- (Popstream (Nameplate), Direct Stream) or the pop (Popstream (Direct)) somewhere over an ellipse (semi-axes
-- rx * screen width, ry * screen height at camera zoom zRef) instead of one point; "off" keeps the
-- single point. The ellipse scales by clamp((zRef + zK) / (zoom + zK), fMin, fMax): wider zoomed in (the mob is
-- bigger on screen), narrower zoomed out. One table keeps Burst's upvalues down.
-- The same zoom factor scales the spawn spread of located orbs when db.zoomSpread is on (UNKNOWN.factor).
-- Popstream (Direct) does not move its pop around the ellipse: the pop stays at the estimate and its ring is stretched
-- horizontally by popWiden (a wider ring reads as "somewhere about here" without the origin jumping).
-- The Helix starts from a short horizontal line instead of a disc or the ellipse (all in px, UIParent units): helixLine
-- is the half-width at a detected origin, helixLineUnknown at an unknown one, helixLineJitter the half-height of both;
-- popWiden stretches Popstream (Direct)'s ring horizontally at an unknown origin (the same for every path).
local UNKNOWN = { rx = 0.064, ry = 0.04, zRef = 15, zK = 5, fMin = 0.5, fMax = 2, level = { off = 0, wide = 1 },
    popWiden = 1.6, helixLine = 8, helixLineUnknown = 18, helixLineJitter = 2 }

-- clamp((zRef + zK) / (zoom + zK), fMin, fMax) for the current camera zoom: 1 at zoom 15, 2 zoomed in, 0.5 zoomed out;
-- 1 when the zoom can't be read. A field of UNKNOWN, so Burst (near Lua 5.1's upvalue cap) needs no new upvalue.
function UNKNOWN.factor()
    local zoom = Orbs.ReadZoom()
    if zoom and zoom > -UNKNOWN.zK then
        return max(UNKNOWN.fMin, min(UNKNOWN.fMax, (UNKNOWN.zRef + UNKNOWN.zK) / (zoom + UNKNOWN.zK)))
    end
    return 1
end

-- Popstream (Direct) (render style "streampop": db.style "popstream", popMode "direct"): screen space only, no plate
-- frame. Every orb is born at the start point within `born` s and pops out to a ring point (RingAngle, size bsize -> 1,
-- alpha fade-in over fadeIn s); the orb launches the moment ITS OWN bloom ends, flying the normal stream path straight
-- on from the ring point, so the time between the kill and the launch is all pop, never a wait. Each orb has its own
-- bloom duration (orb.bloom, bloomMin..bloomMin + bloomSpan s), shortest for the orb whose ring point is nearest to the
-- bar, so the launches are staggered nearest-first; a rested orb's bloom lasts restedDelay longer (it trails slightly,
-- still moving outward). The bloom eases out only partly (easeOut: 0 = linear, 1 = cubic ease-out) so it still has
-- speed when the flight takes over; the first control point leaves along the ring angle blended (ctrlBlend of it, the
-- rest towards the bar), so the outward bloom motion carries on into the flight.
-- Size derived from the Popstream (Nameplate) pop (POP_R_MIN/MAX 30/55, POP_DRIFT 12, POP_SIZE 1.2, POP_EXIT_FROM
-- 0.45): its pop frame is a child of UIParent anchored to the plate, so its offsets are already UIParent px (a plate's
-- own scale only moves the anchor). The pop is on screen at radius * eased * gather, which peaks at about 0.84 of the
-- final radius (p = 0.5: eased 0.875, gather 0.955) before the orbs launch. So rmin/rmax = 0.84 * 30/55 = 25 / 46 px.
-- The upward drift (0..12 px, mean 6 * 0.84 = 5 px) is left out: the start point is the mob's estimated position, not
-- the plate. bsize makes the mean size over the bloom equal POP_SIZE: mean(1 - eased) is 0.375 for easeOut = 0.5, so
-- bsize = 1 + 0.2 / 0.375 = 1.55. widthCap bounds the horizontal ring radius when it is widened.
-- centreX/centreY (ring centre: the start point), ringAngle, ringX/ringY (ring point), blooms (per-orb bloom seconds),
-- dist and idx (launch order) are per-burst scratch arrays (see plan).
local SP_PROFILE = { born = 0.03, bloomMin = 0.20, bloomSpan = 0.06, bsize = 1.55, fadeIn = 0.05, rmin = 25, rmax = 46,
    easeOut = 0.5, restedDelay = 0.06, widthCap = 64, ranks = {}, jitterLow = 0.94, jitterSpan = 0.12, ctrlBlend = 0.6,
    centreX = {}, centreY = {}, ringAngle = {}, ringX = {}, ringY = {}, blooms = {}, dist = {}, idx = {} }
XF_PROFILE.sp = SP_PROFILE -- reached through XF_PROFILE from Burst, which cannot take another upvalue

-- Orb shapes (db.orbShape). "starlight" is the original drawing in this file: orb.shape is nil for it, so every branch
-- below that handles a shape is skipped and Starlight runs exactly the code it always did. Retro, Bubble and Crackle
-- live in Shapes.lua (loaded right after this file): it fills `by` (name -> shape table) and uses `host` (the helpers
-- of this file: pooled textures, placement, the flight path) and `k` (the shared tunables). One table, reached through
-- XF_PROFILE from Burst, which cannot take another upvalue.
-- Every orb also carries orb.opacity (db.opacity / 100, taken per burst): the alpha computed once per orb is multiplied
-- by it, so every texture of every shape follows (a pop group has group.opacity). orb.trailK (db.trailOpacity / 100,
-- also per burst) scales the alpha of every trail ghost, whatever the shape. orb.base is db.size x the burst's
-- scale, before the rested multiplier: Retro's one cell size per burst comes from it.
-- A shape table has: needTrail / needPlain (pool textures per flying orb with / without the trail), build(orb, trail,
-- red, green, blue) (the textures of a flying orb), setup(under, body, spark, st, red, green, blue) (the 3 textures
-- of a pop or copy-A slot; also the first three of a flying orb), draw(st, t, rel, under, body, spark, x, y, size,
-- alpha) (the 3 textures of one orb, no trail; size is db.size scaled, never GLOW; grow, when given (a pop or
-- bloom), is 0.4..1 of the flight size, see SHAPES.grow) and optionally trail(...), see Shapes.lua. `st` is the
-- table holding the orb's shape state: the orb record, or a per-slot table of a pop group.
local SHAPES = { by = {}, host = {}, k = { glow = GLOW, ghostStep = GHOST_STEP, refSpeed = REF_SPEED,
    ghostGapK = 0.3, ghost1Alpha = GHOST1_ALPHA,
    ghost1Size = GHOST1_SIZE, ghost2Alpha = GHOST2_ALPHA, ghost2Size = GHOST2_SIZE, ghost3Alpha = GHOST3_ALPHA,
    ghost3Size = GHOST3_SIZE, underK = UNDER_K, darkTrailLum = 0.25,
    darkTrailShade = 0.45,
    sparkleWhite = SPARKLE_WHITE, extras = EXTRAS, underSize = UNDER_SIZE, underAlpha = UNDER_ALPHA,
    sparkle = SPARKLE, sparkleAlpha = SPARKLE_ALPHA, restedSize = RESTED_SIZE } }
ns.OrbShapes = SHAPES
XF_PROFILE.shapes = SHAPES

-- Where the pop has put the orb `age` seconds after its birth (screen space; allocates nothing): out from the ring
-- centre to the ring point over orb.bloom s, on a partial ease-out (a blend of linear and cubic, so it ends with some
-- speed). Returns x, y and the bloom's eased progress (0..1). Shared by the bloom drawing and by Burst (the flight
-- starts at the bloom's end), so the hand-over has no seam.
function SP_PROFILE.bloomPoint(orb, age)
    local profile = SP_PROFILE
    local progress = age / orb.bloom
    if progress > 1 then
        progress = 1
    end
    local cubic = 1 - (1 - progress) * (1 - progress) * (1 - progress)
    local eased = progress + (cubic - progress) * profile.easeOut
    return orb.px + (orb.ringX - orb.px) * eased, orb.py + (orb.ringY - orb.py) * eased, eased
end

-- table.sort comparator over SP_PROFILE.idx: nearest ring point first (dist), ties by index. File-level so a burst
-- allocates no closure.
local function byRingDist(a, b)
    local dist = SP_PROFILE.dist
    if dist[a] ~= dist[b] then
        return dist[a] < dist[b]
    end
    return a < b
end

-- Per-burst plan of n orbs around (x, y): the ring centre (always (x, y): the origin stays put), ring points (radius x
-- spreadFactor, the zoom-scaled spread, the same for every path; the x radius also x UNKNOWN.popWiden when the
-- origin is unknown (unknownLevel > 0), never wider than widthCap) and bloom durations ordered by distance from the
-- ring point to (dx, dy): the
-- nearest gets bloomMin, the farthest bloomMin + bloomSpan (the launch is the end of the bloom); ranks[i] is orb i's
-- place in that launch order.
function SP_PROFILE.plan(n, x, y, dx, dy, unknownLevel, spreadFactor)
    local profile = SP_PROFILE
    local dist, idx = profile.dist, profile.idx
    for i = #idx, n + 1, -1 do -- table.sort sorts #idx slots: drop what a larger earlier burst left behind
        idx[i] = nil
    end
    local centreX, centreY = x, y
    local widen = 1
    if unknownLevel > 0 then
        widen = UNKNOWN.popWiden
    end
    for i = 1, n do
        local ringAngle = OrbMath.RingAngle(i, n, random)
        local ringRadius = (profile.rmin + random() * (profile.rmax - profile.rmin)) * spreadFactor
        local ringWidth = min(ringRadius * widen, max(ringRadius, profile.widthCap * spreadFactor)) -- x radius, capped
        local ringX, ringY = centreX + cos(ringAngle) * ringWidth, centreY + sin(ringAngle) * ringRadius
        profile.centreX[i], profile.centreY[i], profile.ringAngle[i] = centreX, centreY, ringAngle
        profile.ringX[i], profile.ringY[i] = ringX, ringY
        dist[i], idx[i] = (dx - ringX) * (dx - ringX) + (dy - ringY) * (dy - ringY), i
    end
    table.sort(idx, byRingDist)
    local span = max(n - 1, 1)
    for rank = 0, n - 1 do
        profile.blooms[idx[rank + 1]] = profile.bloomMin + profile.bloomSpan * rank / span
        profile.ranks[idx[rank + 1]] = rank + 1
    end
end

local overlay, driver, flash, flashShape
local freeTex, texCreated, texInUse = {}, 0, 0
local live, nLive = {}, 0
local freeRec = {}
local active = false
local arrivedRecently, flashAge, flashOn, flashRested = 0, 0, false, false
local freePop, popsCreated = {}, 0
local pops, nPops = {}, 0
local popErrSeen = false
local crossfadeGroups, nCrossfade = {}, 0 -- crossfade pop frames alive (their orbs are driven from the stream loop)
local portraitMode = false -- decided once per Burst (Target:PortraitMode): orbs aim at the portrait centre, round flash
-- Sound.lua (loaded before this file) owns the chime; the driver's two calls are cached here so an arrival costs one
-- direct call and no table lookup.
local soundArrive, soundDone = ns.Sound.Arrive, ns.Sound.Done
Orbs.chime = ns.Sound.chime -- exposed for tests
Orbs.sampleOffsets = ns.Sound.sampleOffsets -- ... and the sample's drawn arrival times
local burstSeq = 0 -- burst key counter; every orb carries its burst's key (orb.burstKey)
local burstLeft = {} -- burst key -> orbs of that burst still alive (the chime forgets a burst when it hits 0)

local function settings()
    if not ns.db then
        ns:InitDB()
    end
    return ns.db
end

-- Room for two full-cap bursts, so a pull that kills several mobs at once doesn't leave the later kills without orbs.
-- (the per-orb need is the largest of the current shape's and the Starlight 1 + EXTRAS)
local function ceiling()
    local shape = SHAPES.by[settings().orbShape]
    local perOrb = shape and max(1 + EXTRAS, shape.needTrail + (shape.extra and shape.extra() and 1 or 0)) or 1 + EXTRAS
    return settings().cap * perOrb * 2 + 8
end

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function isNumber(v)
    return type(v) == "number" and readable(v)
end

-- Zoom anchor. The camera zoom as a readable number, or nil (API missing, errors, secret, not a number).
function Orbs.ReadZoom()
    if type(GetCameraZoom) ~= "function" then
        return nil
    end
    local ok, zoom = pcall(GetCameraZoom)
    if ok and isNumber(zoom) and zoom == zoom then
        return zoom
    end
    return nil
end

-- Decided once per burst, never per frame: the y offset (negative, px below the plate's BOTTOM) of the body anchor, or
-- nil when the option is off or the zoom can't be read (every frame then keeps its own default anchor). Also keeps
-- the last zoom/offset for /xporbs status.
local function zoomAnchorY(config)
    if not config.zoomAnchor then
        return nil
    end
    local zoom = Orbs.ReadZoom()
    local offset = zoom and OrbMath.ZoomOffset(zoom, config.zoomA, config.zoomB, config.zoomMin)
    if not offset then
        return nil
    end
    Orbs.lastZoom, Orbs.lastOffset = zoom, offset
    return -offset
end

-- (relPoint, y) of a plate-anchored frame's single anchor: the body anchor when bodyAnchorY is set, else the
-- caller's default. Shared by the pop, the crossfade copy and any later style that hangs a frame off a plate.
local function plateAnchor(bodyAnchorY, relPoint, y)
    if bodyAnchorY then
        return "BOTTOM", bodyAnchorY
    end
    return relPoint, y
end

-- The orb colour for the next burst: the player's class colour when db.classColor is on and the API answers, else
-- db.color. One reusable table, filled in once per burst (never per frame); the arrival flash reads it too.
local normalColour = { 0.2, 0.5, 1 }

local function classRGB()
    if not UnitClass then
        return nil
    end
    local ok, red, green, blue = pcall(function()
        local _, classFile = UnitClass("player")
        if type(classFile) ~= "string" then
            return nil
        end
        local colour = nil
        if C_ClassColor and C_ClassColor.GetClassColor then
            colour = C_ClassColor.GetClassColor(classFile)
        end
        if not colour and RAID_CLASS_COLORS then
            colour = RAID_CLASS_COLORS[classFile]
        end
        if colour then
            return colour.r, colour.g, colour.b
        end
        return nil
    end)
    if ok and type(red) == "number" and type(green) == "number" and type(blue) == "number" and readable(red) then
        return red, green, blue
    end
    return nil
end

-- Fills normalColour for this burst (class colour or the saved colour) and returns it.
local function resolveNormal(config)
    local colour = config.color
    local red, green, blue = colour[1], colour[2], colour[3]
    if config.classColor then
        local classRed, classGreen, classBlue = classRGB()
        if classRed then
            red, green, blue = classRed, classGreen, classBlue
        end
    end
    normalColour[1], normalColour[2], normalColour[3] = red, green, blue
    return normalColour
end

-- The same normal-orb colour as r, g, b without touching the burst's table (the options preview asks for it).
function Orbs.NormalRGB(config)
    local colour = config.color
    local red, green, blue = colour[1], colour[2], colour[3]
    if config.classColor then
        local classRed, classGreen, classBlue = classRGB()
        if classRed then
            red, green, blue = classRed, classGreen, classBlue
        end
    end
    return red, green, blue
end

-- Circular shape = the destination is a round frame (a portrait): the orbs aim at its centre, not the XP fill edge.
-- Independent of Show glow (v0.14): the shape describes the target frame, not just the flash.
local function aimCentre(config)
    return portraitMode or config.glowShape == "round"
end

local function ensureFrames()
    if overlay then
        return
    end
    overlay = CreateFrame("Frame", nil, UIParent)
    overlay:SetAllPoints(UIParent)
    overlay:SetFrameStrata(Orbs.Strata()) -- FULLSCREEN_DIALOG by default: above the test target and preview windows
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

-- A texture from the pool (or a new one under the ceiling check the caller made), unconfigured. A texture that carried
-- a rotation or a texcoord window (xoDirty) gets the full image back first.
local function take()
    local tex = freeTex[#freeTex]
    if tex then
        freeTex[#freeTex] = nil
    else
        tex = overlay:CreateTexture(nil, "ARTWORK")
        tex:SetBlendMode("ADD")
        texCreated = texCreated + 1
    end
    texInUse = texInUse + 1
    if tex.xoDirty then
        tex:SetTexCoord(0, 1, 0, 1)
        tex.xoDirty = false
    end
    return tex
end

-- The same for the permanent textures of a pop group.
local function clean(tex)
    if tex.xoDirty then
        tex:SetTexCoord(0, 1, 0, 1)
        tex.xoDirty = false
    end
end

local function acquire(path, subLayer, red, green, blue, blendMode)
    local tex = take()
    tex:SetTexture(path)
    tex:SetBlendMode(blendMode or "ADD")
    tex:SetDrawLayer("ARTWORK", subLayer)
    tex:SetVertexColor(red, green, blue)
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
    local count = #freeRec
    if count > 0 then
        local rec = freeRec[count]
        freeRec[count] = nil
        return rec
    end
    return {}
end

local releasePop, dropCrossfade -- defined with the pop code below

-- Gives an orb record and everything it holds back to the pools. Tolerates a half-built record (Burst failed midway).
local function freeOrb(orb)
    local burstKey = orb.burstKey
    if burstKey then
        orb.burstKey = nil
        local left = (burstLeft[burstKey] or 1) - 1
        if left > 0 then
            burstLeft[burstKey] = left
        else
            burstLeft[burstKey] = nil
            soundDone(burstKey)
        end
    end
    if orb.under then
        release(orb.under)
    end
    if orb.body then
        release(orb.body)
    end
    if orb.spark then
        release(orb.spark)
    end
    if orb.shine then -- Retro Solid's shine overlay
        release(orb.shine)
        orb.shine = nil
    end
    if orb.ghost1 then
        release(orb.ghost1)
    end
    if orb.ghost2 then
        release(orb.ghost2)
    end
    if orb.ghost3 then -- Starlight's and Crackle's third ghost, Bubble's longer trail
        release(orb.ghost3)
    end
    if orb.ghost4 then
        release(orb.ghost4)
    end
    orb.under, orb.body, orb.spark, orb.ghost1, orb.ghost2 = nil, nil, nil, nil, nil
    orb.ghost3, orb.ghost4 = nil, nil
    if orb.group then
        local group = orb.group
        orb.group = nil
        for j = 1, 3 do
            hideTex(group.tex[orb.slotBase + j])
        end
        local shine = group.tex[orb.slotBase + 2].xoShine
        if shine then
            hideTex(shine)
        end
        group.refs = group.refs - 1
        if group.refs <= 0 then
            dropCrossfade(group)
            releasePop(group)
        end
    end
    freeRec[#freeRec + 1] = orb
end

-- Crossfade copy A: this orb's textures on the plate-anchored frame, offset by (B - P-hat). Under pcall.
local function drawA(orb, group, posX, posY, size, alpha, grow)
    local tex, slotBase = group.tex, orb.slotBase
    alpha = alpha * (orb.opacity or 1)
    if alpha <= 0 then
        hideTex(tex[slotBase + 1])
        hideTex(tex[slotBase + 2])
        hideTex(tex[slotBase + 3])
        if tex[slotBase + 2].xoShine then
            hideTex(tex[slotBase + 2].xoShine)
        end
        return
    end
    local frame, ox, oy = group.frame, posX - orb.px, posY - orb.py
    local shape = orb.shape
    if shape then
        shape.draw(orb, orb.elapsed, frame, tex[slotBase + 1], tex[slotBase + 2], tex[slotBase + 3], ox, oy, size,
            alpha, grow)
        return
    end
    placeRel(tex[slotBase + 1], frame, ox, oy, size * GLOW * UNDER_SIZE, alpha * UNDER_ALPHA)
    placeRel(tex[slotBase + 2], frame, ox, oy, size * GLOW, alpha)
    local sparkle = tex[slotBase + 3]
    placeRel(sparkle, frame, ox, oy, size * SPARKLE, alpha * SPARKLE_ALPHA)
    sparkle:SetRotation(orb.startRotation + TWO_PI * (orb.elapsed - orb.delay))
end

-- drawA under pcall; the first failure silences copy A for the whole burst frame and is logged once.
local function safeA(orb, group, posX, posY, size, alpha, grow)
    local ok, err = pcall(drawA, orb, group, posX, posY, size, alpha, grow)
    if not ok then
        group.fadeMultiplier = 0
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR crossfade %s", string.sub(tostring(err), 1, 120))
        end
    end
end

local function hideB(orb)
    hideTex(orb.under)
    hideTex(orb.body)
    if orb.spark then
        hideTex(orb.spark)
    end
    if orb.shine then
        hideTex(orb.shine)
    end
    if orb.ghost1 then
        hideTex(orb.ghost1)
        hideTex(orb.ghost2)
    end
    if orb.ghost3 then
        hideTex(orb.ghost3)
    end
    if orb.ghost4 then
        hideTex(orb.ghost4)
    end
end

-- Crossfade hold: `age` seconds after the orb's birth. Copy A only, blooming from P-hat out to its ring point
-- (orb.ringX, orb.ringY) with a size boost that eases off, then leaving along u. Copy B (screen space) stays hidden.
local function drawHold(orb, age)
    local profile = orb.profile
    local bloomProgress = age / profile.bloom
    local sinceBloom = age - profile.bloom
    if bloomProgress > 1 then
        bloomProgress = 1
    end
    local eased = 1 - (1 - bloomProgress) * (1 - bloomProgress) * (1 - bloomProgress)
    local alpha = age < profile.fadeIn and age / profile.fadeIn or 1
    local group = orb.group
    local grow = orb.shape and SHAPES.grow(bloomProgress) -- (a shape that draws a pop smaller at first)
    hideB(orb)
    local ringX, ringY = orb.ringX, orb.ringY -- x0, y0 is copy B's start near the bar; A rests on its own ring point
    local leaveProgress = (sinceBloom - orb.leaveStart) / profile.leaveTime
    if leaveProgress > 0 then
        -- leave: accelerate away along u, fading out; leaveProgress >= 1 draws nothing (the gap before B appears)
        if leaveProgress >= 1 then
            safeA(orb, group, ringX, ringY, 0, 0, grow)
        else
            local leaveOffset = orb.leaveDist * leaveProgress * leaveProgress
            safeA(orb, group, ringX + orb.ux * leaveOffset, ringY + orb.uy * leaveOffset,
                orb.size * (1 - 0.2 * leaveProgress), (1 - leaveProgress * leaveProgress) * group.fadeMultiplier, grow)
        end
        return
    end
    safeA(orb, group, orb.px + (ringX - orb.px) * eased, orb.py + (ringY - orb.py) * eased,
        orb.size * (1 + (profile.bsize - 1) * (1 - eased)), alpha * group.fadeMultiplier, grow)
end

-- Stream pop bloom: `age` seconds after the orb's birth, before its launch. Screen space: SP_PROFILE.bloomPoint (size
-- boost easing off, alpha fade-in). Allocates nothing.
local function drawSpHold(orb, age)
    local profile = SP_PROFILE
    local x, y, eased = SP_PROFILE.bloomPoint(orb, age)
    local alpha = (age < profile.fadeIn and age / profile.fadeIn or 1) * (orb.opacity or 1)
    local size = orb.size * (1 + (profile.bsize - 1) * (1 - eased))
    local shape = orb.shape
    if shape then
        shape.draw(orb, orb.elapsed, nil, orb.under, orb.body, orb.spark, x, y, size, alpha,
            SHAPES.grow(age / orb.bloom), orb.shine)
        return
    end
    place(orb.under, x, y, size * GLOW * UNDER_SIZE, alpha * UNDER_ALPHA)
    place(orb.body, x, y, size * GLOW, alpha)
    place(orb.spark, x, y, size * SPARKLE, alpha * SPARKLE_ALPHA)
    orb.spark:SetRotation(orb.startRotation + TWO_PI * (orb.elapsed - orb.delay))
end

-- The orb's screen position at `progress` (0..1) of its flight, plus the size and alpha multipliers of the path's fake
-- depth. Smooth is the cubic curve itself (multipliers 1); Chaos and Helix (orb.pathKind, fixed at spawn) move the
-- point sideways of the straight start-to-destination line and, for Chaos, shift the progress (OrbMath.PathOffset).
local function flightPoint(orb, progress, dx, dy, control2X, control2Y)
    local x0, y0 = orb.x0, orb.y0
    local kind = orb.pathKind
    if kind ~= "chaos" and kind ~= "helix" then
        local pathX, pathY = OrbMath.Cubic(OrbMath.PopEase(progress, orb.easeWeight), x0, y0, orb.control1X,
            orb.control1Y, control2X, control2Y, dx, dy)
        return pathX, pathY, 1, 1
    end
    local sideways, warp, sizeMul, alphaMul = OrbMath.PathOffset(kind, progress, orb.pathAmp, orb.pathFreq1,
        orb.pathFreq2, orb.pathFreq3, orb.pathPhase1, orb.pathPhase2, orb.pathPhase3)
    local pathX, pathY = OrbMath.Cubic(OrbMath.PopEase(progress + warp, orb.easeWeight), x0, y0, orb.control1X,
        orb.control1Y, control2X, control2Y, dx, dy)
    local lineX, lineY = dx - x0, dy - y0
    local lineLength = sqrt(lineX * lineX + lineY * lineY)
    if lineLength > 1e-6 then
        pathX = pathX - lineY / lineLength * sideways
        pathY = pathY + lineX / lineLength * sideways
    end
    -- last resort: a near-level flight along the screen edge has no room for its sideways swing (the control points
    -- cannot help), so the drawn point itself is kept on screen
    pathX, pathY = OrbMath.ClampToScreen(pathX, pathY, orb.screenW, orb.screenH, 0)
    return pathX, pathY, sizeMul, alphaMul
end

-- place / placeRel in one call: rel nil places on the overlay (screen space), a frame places relative to it.
local function putAt(tex, rel, x, y, size, alpha)
    if rel then
        placeRel(tex, rel, x, y, size, alpha)
    else
        place(tex, x, y, size, alpha)
    end
end

-- What Shapes.lua may use of this file (see SHAPES).
SHAPES.host.take, SHAPES.host.putAt, SHAPES.host.place, SHAPES.host.hide = take, putAt, place, hideTex
SHAPES.host.flightPoint = flightPoint

-- One flying orb at `progress` (0..1) of its flight towards the destination (dx, dy): position on its flight path,
-- shrink near the end, fade-in, spark rotation and the two trail ghosts (the same path a little earlier in time).
local function drawOrb(orb, progress, dx, dy)
    local control2X, control2Y = OrbMath.HomeControl(orb.control1X, orb.control1Y, dx, dy, orb.flightDist, orb.bowX,
        orb.bowY)
    -- the destination can move, so the second control point is kept on screen every frame (arithmetic only)
    control2X, control2Y = OrbMath.ClampToScreen(control2X, control2Y, orb.screenW, orb.screenH, orb.clampMargin, dx,
        dy)
    local orbX, orbY, sizeMul, alphaMul = flightPoint(orb, progress, dx, dy, control2X, control2Y)
    local size = orb.size
    if progress > SHRINK_FROM then
        size = size * (1 - 0.4 * (progress - SHRINK_FROM) / (1 - SHRINK_FROM))
    end
    local fadeIn = orb.fadeIn
    local alpha = (progress < fadeIn and progress / fadeIn or 1) * (orb.opacity or 1)
    local group = orb.group
    local shape = orb.shape
    if shape then
        shape.draw(orb, orb.elapsed, nil, orb.under, orb.body, orb.spark, orbX, orbY, size * sizeMul, alpha * alphaMul,
            nil, orb.shine)
        if shape.trail then -- a trail of its own (Retro, Bubble); Crackle keeps the Starlight ghosts below
            if orb.ghost1 then
                shape.trail(orb, progress, dx, dy, control2X, control2Y, orbX, orbY,
                    alpha * alphaMul * (orb.trailK or 1))
            end
            return
        end
    else
        place(orb.under, orbX, orbY, size * sizeMul * GLOW * UNDER_SIZE, alpha * alphaMul * UNDER_ALPHA)
        place(orb.body, orbX, orbY, size * sizeMul * GLOW, alpha * alphaMul)
        place(orb.spark, orbX, orbY, size * sizeMul * SPARKLE, alpha * alphaMul * SPARKLE_ALPHA)
        orb.spark:SetRotation(orb.startRotation + TWO_PI * (orb.elapsed - orb.delay))
    end
    if orb.ghost1 then
        -- the ghosts sit ghostGapK drawn diameters apart (px along the path, so they overlap at any speed)
        local gap = SHAPES.k.ghostGapK * size * sizeMul * GLOW
        local ghostStep = orb.pxToProgress and gap * orb.pxToProgress or GHOST_STEP
        alpha = alpha * (orb.trailK or 1) -- the ghosts only (the orb above is drawn already)
        local ghostProgress = progress - ghostStep
        if group and progress < fadeIn then
            -- crossfade B fading in: the ghosts sit behind it along -u, so it arrives "from" the implied path
            place(orb.ghost1, orbX - orb.ux * gap, orbY - orb.uy * gap, size * sizeMul * GLOW * GHOST1_SIZE,
                alpha * alphaMul * GHOST1_ALPHA)
            place(orb.ghost2, orbX - orb.ux * 2 * gap, orbY - orb.uy * 2 * gap, size * sizeMul * GLOW * GHOST2_SIZE,
                alpha * alphaMul * GHOST2_ALPHA)
            place(orb.ghost3, orbX - orb.ux * 3 * gap, orbY - orb.uy * 3 * gap, size * sizeMul * GLOW * GHOST3_SIZE,
                alpha * alphaMul * GHOST3_ALPHA)
            return
        end
        if ghostProgress > 0 then
            local ghostX, ghostY, ghostSizeMul, ghostAlphaMul = flightPoint(orb, ghostProgress, dx, dy, control2X,
                control2Y)
            place(orb.ghost1, ghostX, ghostY, size * ghostSizeMul * GLOW * GHOST1_SIZE,
                alpha * ghostAlphaMul * GHOST1_ALPHA)
        else
            hideTex(orb.ghost1)
        end
        ghostProgress = progress - 2 * ghostStep
        if ghostProgress > 0 then
            local ghostX, ghostY, ghostSizeMul, ghostAlphaMul = flightPoint(orb, ghostProgress, dx, dy, control2X,
                control2Y)
            place(orb.ghost2, ghostX, ghostY, size * ghostSizeMul * GLOW * GHOST2_SIZE,
                alpha * ghostAlphaMul * GHOST2_ALPHA)
        else
            hideTex(orb.ghost2)
        end
        ghostProgress = progress - 3 * ghostStep
        if ghostProgress > 0 then
            local ghostX, ghostY, ghostSizeMul, ghostAlphaMul = flightPoint(orb, ghostProgress, dx, dy, control2X,
                control2Y)
            place(orb.ghost3, ghostX, ghostY, size * ghostSizeMul * GLOW * GHOST3_SIZE,
                alpha * ghostAlphaMul * GHOST3_ALPHA)
        else
            hideTex(orb.ghost3)
        end
    end
end

-- ---------------------------------------------------------------- corpse pop

-- The strata the overlay and every pop frame draw in (db.orbStrata, the Arrival tab's "Orb layer"); a missing or
-- unknown saved value gives the default. Kept as fields of Orbs, not locals, to stay under Lua's local limits.
Orbs.popFrames = {} -- every pop frame ever made (pooled or in use), so a strata change reaches them all
function Orbs.Strata()
    local saved = ns.db and ns.db.orbStrata
    if ns.STRATA_LABEL[saved] then
        return saved
    end
    return ns.defaults.orbStrata
end

-- Moves the overlay (which carries the flash) and all existing pop frames to the current strata. Frames made later
-- read it themselves.
function Orbs.ApplyStrata()
    local strata = Orbs.Strata()
    if overlay then
        overlay:SetFrameStrata(strata)
    end
    for _, frame in ipairs(Orbs.popFrames) do
        frame:SetFrameStrata(strata)
    end
end

-- A pooled pop ("group"): group.frame is a 1x1 frame whose ONLY anchor is the nameplate; group.tex holds up to
-- POP_MAX * 3 textures (underlay, orb, sparkle per orb) created lazily and parented to group.frame; per-orb parameters
-- live in the arrays group.offsetX/offsetY/drift/size/rotation.
local function newPop()
    local frame = CreateFrame("Frame", nil, UIParent)
    frame:SetSize(1, 1)
    frame:SetFrameStrata(Orbs.Strata())
    frame:EnableMouse(false)
    frame:Hide()
    Orbs.popFrames[#Orbs.popFrames + 1] = frame
    return { frame = frame, tex = {}, offsetX = {}, offsetY = {}, drift = {}, size = {}, rotation = {}, n = 0,
        used = 0, st = {} }
end

function releasePop(group)
    if group.free then
        return -- already back in the pool (a second release would hand the frame out twice)
    end
    group.free = true
    local tex = group.tex
    for i = 1, group.used do
        local texture = tex[i]
        texture:Hide()
        texture.xoShown = false
        if texture.xoShine then -- Retro Solid's overlay lives on the body texture
            texture.xoShine:Hide()
            texture.xoShine.xoShown = false
        end
    end
    group.used, group.plate, group.isCrossfade, group.refs, group.shape = 0, nil, false, 0, nil
    pcall(group.frame.ClearAllPoints, group.frame)
    pcall(group.frame.Hide, group.frame)
    freePop[#freePop + 1] = group
end

-- The 3 textures of a Starlight slot (the shape-less default): the dim underlay, the orb and the sparkle.
local function starlightSetup(underTex, orbTex, sparkleTex, red, green, blue)
    underTex:SetTexture(ORB_TEX)
    underTex:SetBlendMode("BLEND")
    underTex:SetDrawLayer("ARTWORK", -1)
    underTex:SetVertexColor(red * UNDER_K, green * UNDER_K, blue * UNDER_K)
    orbTex:SetTexture(ORB_TEX)
    orbTex:SetBlendMode("ADD")
    orbTex:SetDrawLayer("ARTWORK", 0)
    orbTex:SetVertexColor(red, green, blue)
    sparkleTex:SetTexture(SPARKLE_TEX)
    sparkleTex:SetBlendMode("ADD")
    sparkleTex:SetDrawLayer("ARTWORK", 1)
    sparkleTex:SetVertexColor(red + (1 - red) * SPARKLE_WHITE, green + (1 - green) * SPARKLE_WHITE,
        blue + (1 - blue) * SPARKLE_WHITE)
    sparkleTex.xoDirty = true -- it spins (SetRotation)
end
SHAPES.host.starlightSetup = starlightSetup -- the preview sets its Starlight orbs up the same way

-- Fills group for orbCount orbs (rested: the first restedCount). Anchors group.frame to the plate with a single point.
-- (ux, uy) is the exit vector the pop orbs launch along; spreadFactor scales the ring radius and drift (the
-- zoom-scaled spread, 1 = fixed). Errors propagate (pcall'd).
local function setupPop(group, plate, orbCount, scale, restedCount, restedColour, bodyColour, ux, uy, bodyAnchorY,
                        spreadFactor)
    local config = ns.db
    local shape = group.shape -- nil: Starlight
    group.opacity = config.opacity / 100
    local frame, tex = group.frame, group.tex
    frame:ClearAllPoints()
    local rel, y = plateAnchor(bodyAnchorY, "CENTER", POP_Y)
    frame:SetPoint("CENTER", plate, rel, 0, y)
    frame:Show()
    for i = 1, orbCount * 3 do
        if not tex[i] then
            tex[i] = frame:CreateTexture(nil, "ARTWORK")
        end
    end
    for i = 1, orbCount do
        local rested = i <= restedCount
        local colour = rested and restedColour or bodyColour
        local red, green, blue = colour[1], colour[2], colour[3]
        local slotBase = (i - 1) * 3
        local underTex, orbTex, sparkleTex = tex[slotBase + 1], tex[slotBase + 2], tex[slotBase + 3]
        clean(underTex)
        clean(orbTex)
        clean(sparkleTex)
        if shape then
            group.st[i] = group.st[i] or {}
            group.st[i].base = ns.OrbSize(config) * scale -- (Retro's one cell size per burst)
            shape.setup(underTex, orbTex, sparkleTex, group.st[i], red, green, blue)
        else
            starlightSetup(underTex, orbTex, sparkleTex, red, green, blue)
        end
        for j = 1, 3 do
            local texture = tex[slotBase + j]
            texture:SetAlpha(0)
            texture:Hide()
            texture.xoShown = false
        end
        local angle = OrbMath.RingAngle(i, orbCount, random)
        local radius = (POP_R_MIN + random() * (POP_R_MAX - POP_R_MIN)) * spreadFactor
        group.offsetX[i], group.offsetY[i] = cos(angle) * radius, sin(angle) * radius
        group.drift[i] = random() * POP_DRIFT * spreadFactor
        group.size[i] = ns.OrbSize(config) * scale * (rested and RESTED_SIZE or 1)
        group.rotation[i] = random() * TWO_PI
    end
    group.used = orbCount * 3
    group.n = orbCount
    group.ux, group.uy = ux, uy
end

-- Takes a pooled pop frame (or creates one under the POP_FRAMES cap). nil when none is free.
local function takePopFrame()
    local group = freePop[#freePop]
    if group then
        freePop[#freePop] = nil
        group.free = false
        return group
    end
    if popsCreated < POP_FRAMES then
        local ok, newGroup = pcall(newPop)
        if ok then
            popsCreated = popsCreated + 1
            return newGroup
        end
    end
    return nil
end

-- Returns true when a pop was started. Never throws; every failure just means "no pop".
local function startPop(plate, n, scale, nPurple, ux, uy, bodyAnchorY, spreadFactor, shape)
    if type(plate) ~= "table" or not readable(plate) then
        return false
    end
    local group = takePopFrame()
    if not group then
        return false
    end
    local config = ns.db
    group.shape = shape
    local count = min(n, POP_MAX)
    local restedCount = nPurple > 0 and floor(nPurple * count / n + 0.5) or 0
    local ok, err = pcall(setupPop, group, plate, count, scale, restedCount, config.restedColor, normalColour, ux, uy,
        bodyAnchorY, spreadFactor)
    if not ok then
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR setup %s", string.sub(tostring(err), 1, 120))
        end
        releasePop(group)
        return false
    end
    group.plate, group.elapsed, group.fading, group.fadeElapsed, group.isCrossfade = plate, 0, false, 0, false
    nPops = nPops + 1
    pops[nPops] = group
    return true
end

-- Crossfade: a pop frame that will carry copy A of every orb. With a readable plate it is anchored to the plate's
-- BOTTOM (exact, whatever P-hat is). Without one (a Test burst, or a kill whose mob was not located) it is anchored to
-- the screen at P-hat (screenX, screenY), so copy A blooms there instead; copy A's offsets are relative to P-hat either
-- way. Returns the frame or nil.
local function startCrossfade(plate, bodyAnchorY, screenX, screenY)
    local plated = type(plate) == "table" and readable(plate)
    if not plated and not (type(screenX) == "number" and type(screenY) == "number") then
        return nil
    end
    local group = takePopFrame()
    if not group then
        return nil
    end
    local frame = group.frame
    local ok, err = pcall(function()
        frame:ClearAllPoints()
        if plated then
            local rel, y = plateAnchor(bodyAnchorY, "BOTTOM", 0)
            frame:SetPoint("CENTER", plate, rel, 0, y)
        else
            frame:SetPoint("CENTER", UIParent, "BOTTOMLEFT", screenX, screenY)
        end
        frame:Show()
    end)
    if not ok then
        if not popErrSeen then
            popErrSeen = true
            ns:Log("POP_ERR crossfade setup %s", string.sub(tostring(err), 1, 120))
        end
        releasePop(group)
        return nil
    end
    group.plate, group.isCrossfade, group.refs = plated and plate or nil, true, 0
    group.fadeMultiplier, group.fading, group.fadeElapsed = 1, false, 0
    nCrossfade = nCrossfade + 1
    crossfadeGroups[nCrossfade] = group
    return group
end

function dropCrossfade(group)
    for i = 1, nCrossfade do
        if crossfadeGroups[i] == group then
            crossfadeGroups[i] = crossfadeGroups[nCrossfade]
            crossfadeGroups[nCrossfade] = nil
            nCrossfade = nCrossfade - 1
            break
        end
    end
end

-- Creates/configures the 3 textures of orb slot slotBase+1..slotBase+3 on the crossfade frame. Errors propagate
-- (pcall'd).
local function crossfadeTextures(group, slotBase, red, green, blue, shape, orb)
    local tex, frame = group.tex, group.frame
    for j = 1, 3 do
        if not tex[slotBase + j] then
            tex[slotBase + j] = frame:CreateTexture(nil, "ARTWORK")
        end
    end
    local underTex, orbTex, sparkleTex = tex[slotBase + 1], tex[slotBase + 2], tex[slotBase + 3]
    clean(underTex)
    clean(orbTex)
    clean(sparkleTex)
    if shape then
        shape.setup(underTex, orbTex, sparkleTex, orb, red, green, blue) -- the orb record holds copy A's shape state
    else
        starlightSetup(underTex, orbTex, sparkleTex, red, green, blue)
    end
    for j = 1, 3 do
        local texture = tex[slotBase + j]
        texture:SetAlpha(0)
        texture:Hide()
        texture.xoShown = false
    end
    if slotBase + 3 > group.used then
        group.used = slotBase + 3
    end
end

-- Positions every pop orb. Called under pcall from the driver; allocates nothing.
local function drawPop(group)
    local progress = group.elapsed / POP_TIME
    if progress > 1 then
        progress = 1
    end
    local eased = 1 - (1 - progress) * (1 - progress) * (1 - progress)
    local sizeScale = progress > POP_SHRINK_FROM and 1 - (progress - POP_SHRINK_FROM) / (1 - POP_SHRINK_FROM) or 1
    local alpha = (progress > POP_FADE_FROM and 1 - (progress - POP_FADE_FROM) / (1 - POP_FADE_FROM) or 1)
        * (group.opacity or 1)
    if group.fading then
        alpha = alpha * (1 - group.fadeElapsed / POP_FADE_OUT)
    end
    local exitProgress = progress > POP_EXIT_FROM and (progress - POP_EXIT_FROM) / (1 - POP_EXIT_FROM) or 0
    local gather = 1 - POP_GATHER * exitProgress
    local exit = POP_EXIT_DIST * exitProgress * exitProgress
    local exitX, exitY = group.ux * exit, group.uy * exit
    local frame, tex = group.frame, group.tex
    local spin = TWO_PI * group.elapsed
    local shape = group.shape
    local grow = shape and SHAPES.grow(progress) -- (a shape that draws a pop smaller at first)
    for i = 1, group.n do
        local ox = group.offsetX[i] * eased * gather + exitX
        local oy = (group.offsetY[i] + group.drift[i]) * eased * gather + exitY
        local slotBase = (i - 1) * 3
        if shape then
            shape.draw(group.st[i], group.elapsed, frame, tex[slotBase + 1], tex[slotBase + 2], tex[slotBase + 3], ox,
                oy, group.size[i] * POP_SIZE * sizeScale, alpha, grow)
        else
            local size = group.size[i] * GLOW * POP_SIZE * sizeScale
            placeRel(tex[slotBase + 1], frame, ox, oy, size * UNDER_SIZE, alpha * POP_UNDER_ALPHA)
            placeRel(tex[slotBase + 2], frame, ox, oy, size, alpha)
            local sparkle = tex[slotBase + 3]
            placeRel(sparkle, frame, ox, oy, size * SPARKLE, alpha * SPARKLE_ALPHA)
            sparkle:SetRotation(group.rotation[i] + spin)
        end
    end
end

local function updatePops(dt)
    local i = 1
    while i <= nPops do
        local group = pops[i]
        group.elapsed = group.elapsed + dt
        local drop = false
        if group.fading then
            group.fadeElapsed = group.fadeElapsed + dt
            drop = group.fadeElapsed >= POP_FADE_OUT
        end
        if group.elapsed >= POP_TIME then
            drop = true
        end
        if not drop then
            local ok, err = pcall(drawPop, group)
            if not ok then
                drop = true
                if not popErrSeen then
                    popErrSeen = true
                    ns:Log("POP_ERR draw %s", string.sub(tostring(err), 1, 120))
                end
            end
        end
        if drop then
            releasePop(group)
            pops[i] = pops[nPops]
            pops[nPops] = nil
            nPops = nPops - 1
        else
            i = i + 1
        end
    end
end

-- The chime's public methods live on Orbs (the options panel, /xporbs and the tests call them here); the work is in
-- Sound.lua. PlayChimeSample returns false when the chime is off or dead; the sample's frame is exposed for tests.
function Orbs:PlayChimeSample()
    local started = ns.Sound.PlayChimeSample()
    Orbs.sampleFrame = ns.Sound.sampleFrame
    return started
end

function Orbs:PreviewSound(voice)
    ns.Sound.PreviewSound(voice)
end

-- true once a sound failure has switched the chime off for this session
function Orbs:SoundDisabled()
    return ns.Sound.Disabled()
end

-- Perf counters for /xporbs perf: frames the driver ran, their summed and worst time in ms.
local perfFrames, perfTotal, perfMax = 0, 0, 0
local driverErrSeen = false

-- One driver frame. Runs under pcall (see onUpdate) and allocates nothing.
local function drive(self, dt)
    if nPops > 0 then
        updatePops(dt)
    end
    for i = 1, nCrossfade do
        local group = crossfadeGroups[i]
        if group.fading then
            group.fadeElapsed = group.fadeElapsed + dt
            group.fadeMultiplier = group.fadeElapsed >= POP_FADE_OUT and 0 or 1 - group.fadeElapsed / POP_FADE_OUT
        end
    end
    local dx, dy = Target:GetDestination(aimCentre(ns.db), portraitMode)
    local i = 1
    while i <= nLive do
        local orb = live[i]
        orb.elapsed = orb.elapsed + dt
        local age = orb.elapsed - orb.delay -- seconds since the orb's start delay ran out
        local drop = false
        if age >= 0 then
            local flightElapsed = age - orb.hold -- flight time; negative during the crossfade hold
            if flightElapsed < 0 then
                if orb.group then
                    drawHold(orb, age)
                else
                    drawSpHold(orb, age) -- stream pop: the hold of a screen-space orb
                end
            else
                local progress = flightElapsed / orb.dur
                if progress >= 1 then
                    soundArrive(orb.burstKey)
                    if ns.db.glow ~= false then
                        arrivedRecently = arrivedRecently + 1
                        flashAge, flashOn, flashRested = 0, true, orb.rested
                    end
                    drop = true
                else
                    drawOrb(orb, progress, dx, dy)
                end
            end
        end
        if drop then
            freeOrb(orb)
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
            local colour = flashRested and ns.db.restedColor or normalColour
            local glowAlphaFactor, glowSizeFactor = OrbMath.GlowIntensity(ns.db.glowIntensity)
            local alpha = min(1, min(1, FLASH_ALPHA + FLASH_STEP * arrivedRecently) * (1 - flashAge / FLASH_TIME)
                * glowAlphaFactor)
            -- round for a portrait or the Circular shape; upright for the Vertical shape, and under Horizontal for a
            -- destination that is a vertical bar; otherwise the horizontal flash
            local glowShape = ns.db.glowShape
            local shape = "bar"
            if portraitMode or glowShape == "round" then
                shape = "round"
            elseif glowShape == "vertical" or (glowShape == "bar" and Target.lastVertical) then
                shape = "vertical"
            end
            if shape ~= flashShape then
                flashShape = shape
                flash:SetTexture(FLASH_SHAPE_TEX[shape])
            end
            flash:SetVertexColor(colour[1] + (1 - colour[1]) * FLASH_WHITE, colour[2] + (1 - colour[2]) * FLASH_WHITE,
                colour[3] + (1 - colour[3]) * FLASH_WHITE)
            flash:ClearAllPoints()
            flash:SetPoint("CENTER", overlay, "BOTTOMLEFT", dx, dy)
            if shape == "round" then
                local diameter = OrbMath.GlowDiameter(Target.lastW, Target.lastH, ns.OrbSize(ns.db))
                flash:SetSize(diameter * glowSizeFactor, diameter * glowSizeFactor)
            elseif shape == "vertical" then
                local tall = ns.OrbSize(ns.db) * FLASH_W * glowSizeFactor
                flash:SetSize(tall / FLASH_ASPECT, tall)
            else
                local w = ns.OrbSize(ns.db) * FLASH_W * glowSizeFactor
                flash:SetSize(w, w / FLASH_ASPECT)
            end
            flash:SetAlpha(alpha)
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
    for i = nCrossfade, 1, -1 do
        pcall(releasePop, crossfadeGroups[i])
        crossfadeGroups[i] = nil
    end
    nCrossfade = 0
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
    local clock = debugprofilestop
    local startTime = clock and clock()
    local ok, err = pcall(drive, self, dt)
    if startTime then
        local ms = clock() - startTime
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

local function lighten(channel)
    return channel + (1 - channel) * SPARKLE_WHITE
end

-- The blend mode of an orb's trail ghosts, decided once at spawn from the orb's own colour: additive ghosts add nothing
-- over a black or very dark orb, so a dark colour (relative luminance under SHAPES.k.darkTrailLum) draws them with
-- plain alpha blending, a dark smear. Bright colours stay additive with the orb's own colour. The BLEND ghosts are
-- tinted darker than the orb (each channel x SHAPES.k.darkTrailShade) so the smear reads as a shadow behind it, not
-- the same colour as the ground. Returns the blend mode and the ghost tint.
function SHAPES.trailTint(red, green, blue)
    local k = SHAPES.k
    if 0.2126 * red + 0.7152 * green + 0.0722 * blue < k.darkTrailLum then
        local shade = k.darkTrailShade
        return "BLEND", red * shade, green * shade, blue * shade
    end
    return "ADD", red, green, blue
end

-- Gets the textures of one flying orb from the pool: the Starlight art here (underlay, orb, sparkle, 3 ghosts), or
-- the shape's own. Called through XF_PROFILE.shapes, because Burst has no upvalue to spare.
function SHAPES.build(orb, shape, trail, red, green, blue)
    if shape then
        return shape.build(orb, trail, red, green, blue)
    end
    orb.under = acquire(ORB_TEX, -1, red * UNDER_K, green * UNDER_K, blue * UNDER_K, "BLEND")
    orb.body = acquire(ORB_TEX, 0, red, green, blue)
    orb.spark = acquire(SPARKLE_TEX, 1, lighten(red), lighten(green), lighten(blue))
    orb.spark.xoDirty = true -- it spins (SetRotation)
    if trail then
        local blend, ghostRed, ghostGreen, ghostBlue = SHAPES.trailTint(red, green, blue)
        orb.ghost1 = acquire(ORB_TEX, 0, ghostRed, ghostGreen, ghostBlue, blend)
        orb.ghost2 = acquire(ORB_TEX, 0, ghostRed, ghostGreen, ghostBlue, blend)
        orb.ghost3 = acquire(ORB_TEX, 0, ghostRed, ghostGreen, ghostBlue, blend)
    end
end

-- Wide start of one stream orb: orb.x0, orb.y0 moves to a random point of the unknown-origin ellipse around (x, y)
-- (unknownLevel == 0: left alone). zoomFactor scales the ellipse (the camera-zoom factor, read once per burst).
-- A helix (pathKind == "helix") starts from a short line across the flight instead (the perpendicular of the way from
-- (x, y) to the destination (dx, dy), so it reads the same whichever way the bar lies): UNKNOWN.helixLine px either
-- side of (x, y) at a detected origin, UNKNOWN.helixLineUnknown when the origin is unknown (the ellipse is too loose
-- for its strands), and at most UNKNOWN.helixLineJitter px along the flight.
local function placeUnknown(orb, unknownLevel, x, y, zoomFactor, pathKind, dx, dy)
    if pathKind == "helix" then
        local halfWidth = unknownLevel > 0 and UNKNOWN.helixLineUnknown or UNKNOWN.helixLine
        local alongX, alongY = dx - x, dy - y
        local length = sqrt(alongX * alongX + alongY * alongY)
        if length > 1e-6 then
            alongX, alongY = alongX / length, alongY / length
        else
            alongX, alongY = 0, 1
        end
        local across, along = (random() * 2 - 1) * halfWidth, (random() * 2 - 1) * UNKNOWN.helixLineJitter
        orb.x0 = x - alongY * across + alongX * along
        orb.y0 = y + alongX * across + alongY * along
        return
    end
    if unknownLevel == 0 then
        return
    end
    -- sqrt: uniform over the ellipse, not clustered at the centre
    local angle, radius = random() * TWO_PI, sqrt(random())
    orb.x0 = x + cos(angle) * radius * UNKNOWN.rx * zoomFactor * UIParent:GetWidth()
    orb.y0 = y + sin(angle) * radius * UNKNOWN.ry * zoomFactor * UIParent:GetHeight()
end

-- Crossfade per-burst plan (scratch in XF_PROFILE, read while the orbs are built): u = unit vector from P-hat towards
-- the bar (straight up when they coincide), and the centre of copy B's start disc, startDist px short of the bar.
function XF_PROFILE.plan(px, py, dx, dy) -- a method of the profile: one upvalue fewer in Burst
    local profile = XF_PROFILE
    local vx, vy = dx - px, dy - py
    local len = sqrt(vx * vx + vy * vy)
    if len > 1e-6 then
        vx, vy = vx / len, vy / len
    else
        vx, vy = 0, 1
    end
    local startDist = max(profile.bDistMin,
        min(profile.bDistMax, profile.bScreenFrac * UIParent:GetHeight(), profile.bLengthFrac * len))
    -- short plate-to-bar distances: shorten the leave and keep B's start ahead of where A vanishes (per orb:
    -- orb.leaveDist)
    local leaveDist = max(60, min(profile.leaveDist, 0.40 * len))
    startDist = max(50, min(startDist, len - leaveDist))
    profile.leaveDistClamped = leaveDist
    profile.ux, profile.uy = vx, vy
    profile.bCentreX, profile.bCentreY = dx - vx * startDist, dy - vy * startDist
end

-- Burst{ x=, y= (stream origin, UIParent coords; nil -> screen centre), n=, scale= (default 1), nPurple= (default 0),
-- kind=, plate= (optional nameplate of the dead mob), style= (optional override of db.style: a style name or alias),
-- popMode= (optional override of db.popMode),
-- ex=, ey= (P-hat, the estimated mob position in UIParent coords; default = MobEstimate.Default), est=, estW= (source
-- label and mouseover weight, informational) }. n < 1 is a no-op.
-- Returns "pop+stream" | "crossfade" | "stream" | "streampop" (a plate is ignored by "streampop").
function Orbs:Burst(params)
    if type(params) ~= "table" or type(params.n) ~= "number" or params.n < 1 then
        return
    end
    local config = settings()
    ensureFrames()
    local n = floor(params.n)
    local scale = type(params.scale) == "number" and params.scale or 1
    local nPurple = type(params.nPurple) == "number" and params.nPurple or 0
    if not config.restedTint then
        nPurple = 0
    end
    -- the orb shape is the same for the whole burst (changing the setting mid-flight never swaps art in the air); nil =
    -- Starlight.
    local shape = XF_PROFILE.shapes.by[config.orbShape]
    local flightTime = config.flightTime
    -- speed mode: px per second for the whole burst (nil = fixed flight time)
    XF_PROFILE.flightSpeed = config.flightMode == "speed"
        and XF_PROFILE.shapes.k.refSpeed * config.flightSpeed / 100 or nil
    local x, y = params.x, params.y
    local style = ns.RenderStyle(params.style or config.style, params.popMode or config.popMode)
    if params.kind == "other" then
        style = "stream" -- quest and other XP: no pop (Kills passes the origin; the centre is the default)
    end
    if type(x) ~= "number" or type(y) ~= "number" then
        x, y = UIParent:GetWidth() / 2, UIParent:GetHeight() * 0.65
    end
    portraitMode = Target:PortraitMode() == true -- once per burst, never per frame
    local dx, dy, destFound = Target:GetDestination(aimCentre(config), portraitMode)
    if destFound == false and ns.Setup then
        ns.Setup:NoBarFound() -- once per session offers the "find your XP bar" window (Setup.lua); cheap after that
    end
    local baseColour = resolveNormal(config)
    -- P-hat: our best guess of where the mob is on screen (Kills passes the mouseover/cursor estimate)
    local px, py = params.ex, params.ey
    if type(px) ~= "number" or type(py) ~= "number" then
        px, py = ns.MobEstimate.Default(UIParent:GetWidth(), UIParent:GetHeight())
    end
    local popped, crossfadeGroup = false, nil
    local isStreamPop = style == "streampop" -- screen space only: never any plate frame
    local bodyAnchorY = params.plate ~= nil and not isStreamPop and zoomAnchorY(config) or nil
    -- unknown-origin spread: only when nobody hovered the mob, and either the plain stream (which starts at P-hat) or
    -- a plate-space pop or copy is really drawn
    local unknownLevel = 0
    -- (crossfade is exempt: its plate copy is exact and its screen copy starts near the bar)
    local plated = params.plate ~= nil and style ~= "crossfade"
    if params.est == "default" and params.kind ~= "other" and (style == "stream" or isStreamPop or plated) then
        unknownLevel = UNKNOWN.level[config.unknownOrigin] or 0
    end
    -- one zoom read per burst (unreadable -> 1): unknownZoomFactor scales the unknown-origin ellipse (always),
    -- spreadFactor the spawn spread of the pop rings and the stream's start disc (only with Zoom-scaled spread on and
    -- a located kill; 1 = the fixed spread)
    -- (params.zoomFactor, a number, replaces the camera read: the test stand-in sits in a fixed window)
    local unknownZoomFactor = type(params.zoomFactor) == "number" and params.zoomFactor or UNKNOWN.factor()
    local spreadFactor = config.zoomSpread and params.kind ~= "other" and unknownZoomFactor or 1
    if params.plate ~= nil and style == "popstream" then
        local ux, uy = OrbMath.ExitVector(x, y, px, py, dx, dy)
        popped = startPop(params.plate, n, scale, nPurple, ux, uy, bodyAnchorY, spreadFactor, shape)
    elseif style == "crossfade" then
        -- no readable plate: the group is anchored to the screen at P-hat instead
        crossfadeGroup = startCrossfade(params.plate, bodyAnchorY, px, py)
    end
    if crossfadeGroup then
        x, y = px, py
    end
    if not (popped or crossfadeGroup or isStreamPop or style == "stream") then
        unknownLevel = 0
    end
    Orbs.lastUnknown = unknownLevel > 0 and config.unknownOrigin or nil
    -- Budget the texture pool. A full burst with trails needs 6 textures per orb; when that doesn't fit, the burst
    -- drops its trail ghosts (3 per orb), then draws fewer orbs. Every burst still gets min(n, 3) orbs while 9
    -- textures are free, so the later kills of an AoE pull are never starved by the earlier ones.
    local trail = (config.trail and (config.trailOpacity or 100) > 0) and true or false -- 0 %: no ghosts at all
    local needTrail, needPlain = 1 + EXTRAS, 3 -- orb + underlay + sparkle (+ 3 ghosts)
    if shape then
        needTrail, needPlain = shape.needTrail, shape.needPlain
        if shape.extra and shape.extra() then -- one more texture per orb (Retro Solid's shine overlay)
            needTrail, needPlain = needTrail + 1, needPlain + 1
        end
    end
    local need = trail and needTrail or needPlain
    local limit = ceiling() - 1 -- the arrival flash holds one slot
    local free = limit - texInUse
    if trail and n * need > free then
        trail, need = false, needPlain
    end
    local fit = floor(free / need)
    if fit < 0 then
        fit = 0
    end
    if fit < n then
        nPurple = floor(nPurple * fit / n + 0.5)
        n = fit
    end
    local profile = isStreamPop and XF_PROFILE.sp or XF_PROFILE -- (Burst is near the upvalue limit)
    local extraDelay = popped and STREAM_DELAY or 0
    local stagger = (popped or crossfadeGroup) and STAGGER_POP or STAGGER
    if crossfadeGroup then
        stagger = XF_PROFILE.born -- crossfade: the pop is one quick burst
    elseif isStreamPop then
        stagger = profile.born -- stream pop: all born at the start point together
    end
    local spread, lift = nil, nil -- PopControl defaults
    if popped or crossfadeGroup then
        spread, lift = POP_STREAM_SPREAD, POP_STREAM_LIFT
    end
    local fadeIn = popped and FADE_IN_POP or FADE_IN
    local flightScale = crossfadeGroup and profile.flight or 1 -- crossfade copy B flies faster than the normal stream
    -- the flight path is the same for the whole burst (changing the setting mid-flight never bends an orb in the air)
    local burstPath = OrbMath.PathKind(params.path or config.flightPath)
    if popped and burstPath == "helix" then
        -- the stream of a helix after a nameplate pop is the Direct Stream helix (its favourite look): the same
        -- stagger, control spread / lift (defaults) and fade-in; only the pop and STREAM_DELAY stay
        stagger, spread, lift, fadeIn = STAGGER, nil, nil, FADE_IN
    end
    -- per-burst screen facts for the arcs (scratch fields of XF_PROFILE, Burst has no upvalue to spare): the screen
    -- size, which side every orb bows to (the side with more room, see OrbMath.BowVector) and the base margin that
    -- keeps the control points off the screen edge (each orb adds its path amplitude)
    XF_PROFILE.screenW, XF_PROFILE.screenH = UIParent:GetWidth(), UIParent:GetHeight()
    XF_PROFILE.bowSide = OrbMath.BowSide(crossfadeGroup and px or x, crossfadeGroup and py or y, dx, dy,
        XF_PROFILE.screenW, XF_PROFILE.screenH)
    XF_PROFILE.edgeMargin = XF_PROFILE.edgeFraction * XF_PROFILE.screenH
    local spiralSign = 1 -- a helix turns one way or the other, chosen once per burst
    if burstPath == "helix" and random() < 0.5 then
        spiralSign = -1
    end
    if crossfadeGroup then
        XF_PROFILE.plan(px, py, dx, dy)
    elseif isStreamPop then
        profile.plan(n, x, y, dx, dy, unknownLevel, spreadFactor)
    end
    local crossfadeCount = 0 -- orbs that got a plate-space copy A (each takes 3 texture slots on crossfadeGroup)
    local building, buildingLive = nil, false -- the orb being built, and whether it is in `live` yet
    burstSeq = burstSeq + 1
    local burstKey = burstSeq

    local ok, err = pcall(function()
        for i = 1, n do
            if texInUse + need > limit then
                break
            end
            local rested = i <= nPurple
            local colour = rested and config.restedColor or baseColour
            local red, green, blue = colour[1], colour[2], colour[3]
            local orb = newRec()
            orb.shape = shape
            orb.base, orb.opacity = ns.OrbSize(config) * scale, config.opacity / 100 -- (see SHAPES)
            orb.trailK = (config.trailOpacity or 100) / 100
            building, buildingLive = orb, false
            local controlScale, staggerScale, pathJitterLow, pathJitterSpan = OrbMath.PathShape(burstPath)
            orb.group, orb.hold, orb.easeWeight, orb.profile = nil, 0, nil, nil
            if crossfadeGroup then
                local slotBase = crossfadeCount * 3 -- first of this orb's 3 texture slots on the group
                if pcall(crossfadeTextures, crossfadeGroup, slotBase, red, green, blue, shape, orb) then
                    crossfadeCount = crossfadeCount + 1
                    orb.group, orb.slotBase, orb.px, orb.py = crossfadeGroup, slotBase, px, py
                    orb.hold, orb.easeWeight, orb.profile = profile.hold, profile.ease, profile
                    crossfadeGroup.refs = crossfadeGroup.refs + 1
                end
            end
            if isStreamPop then
                -- stream pop: the orb launches when its own bloom ends, from the ring point
                orb.bloom = profile.blooms[i] + (rested and profile.restedDelay or 0)
                orb.hold = orb.bloom
                orb.px, orb.py = profile.centreX[i], profile.centreY[i]
                orb.ringX, orb.ringY = profile.ringX[i], profile.ringY[i]
                orb.x0, orb.y0 = profile.bloomPoint(orb, orb.hold) -- the ring point itself
            elseif orb.group then
                -- crossfade: A blooms out to its ring point around P-hat and rests there; B starts near the bar, and
                -- A has left before B's flight begins
                local ringAngle = OrbMath.RingAngle(i, n, random)
                local radius = (profile.rmin + random() * (profile.rmax - profile.rmin)) * spreadFactor
                orb.ringX = x + cos(ringAngle) * radius
                orb.ringY = y + sin(ringAngle) * radius + random() * profile.drift * spreadFactor
                orb.ux, orb.uy = profile.ux, profile.uy
                orb.leaveDist = profile.leaveDistClamped
                orb.leaveStart = random() * profile.leaveStagger
                orb.hold = profile.bloom + orb.leaveStart + profile.leaveTime + profile.gap
                local spawnAngle, spawnRadius = random() * TWO_PI, profile.bSpread * sqrt(random())
                orb.x0 = profile.bCentreX + cos(spawnAngle) * spawnRadius
                orb.y0 = profile.bCentreY + sin(spawnAngle) * spawnRadius
            else
                local ringAngle, radius = random() * TWO_PI, START_RADIUS * spreadFactor * sqrt(random())
                orb.x0, orb.y0 = x + cos(ringAngle) * radius, y + sin(ringAngle) * radius
            end
            -- (Popstream (Direct) picked its shared ring centre in plan; unknownLevel is 0 for crossfade)
            placeUnknown(orb, isStreamPop and 0 or unknownLevel, x, y, unknownZoomFactor,
                not (isStreamPop or orb.group) and burstPath or nil, dx, dy)
            -- the arc bows along a direction that follows the flight (straight up for a bottom bar, see BowVector)
            local bowX, bowY = OrbMath.BowVector(orb.x0, orb.y0, dx, dy, XF_PROFILE.screenW, XF_PROFILE.screenH,
                XF_PROFILE.bowSide)
            orb.bowX, orb.bowY = bowX, bowY
            if isStreamPop then
                -- leave along the ring angle blended towards the bar (nobody flies back through the middle)
                local ringAngle, blend = profile.ringAngle[i], profile.ctrlBlend
                local vx, vy = dx - orb.x0, dy - orb.y0
                local vecLen = sqrt(vx * vx + vy * vy)
                if vecLen > 1e-6 then
                    vx, vy = vx / vecLen, vy / vecLen
                else
                    vx, vy = 0, 1
                end
                local reach = (45 + random() * 55) * POP_STREAM_SPREAD * 2.2 * controlScale
                orb.control1X = orb.x0 + (cos(ringAngle) * blend + vx * (1 - blend)) * reach
                orb.control1Y = orb.y0 + (sin(ringAngle) * blend + vy * (1 - blend)) * reach
            elseif orb.group then
                -- crossfade B: first control point ahead along u (towards the bar), jittered sideways, no lift
                local ddx, ddy = dx - orb.x0, dy - orb.y0
                local barDist = sqrt(ddx * ddx + ddy * ddy)
                local sideways = (random() * 2 - 1) * profile.ctrlJitter * barDist
                sideways = sideways * controlScale
                orb.control1X = orb.x0 + orb.ux * profile.ctrlAhead * barDist - orb.uy * sideways
                orb.control1Y = orb.y0 + orb.uy * profile.ctrlAhead * barDist + orb.ux * sideways
            else
                -- (a helix shrinks the control point's spread so its strands share one spine)
                local pathSpread = controlScale ~= 1 and (spread or 1) * controlScale or spread
                orb.control1X, orb.control1Y = OrbMath.PopControl(i, n, orb.x0, orb.y0, random, pathSpread, lift, bowX,
                    bowY)
            end
            local ddx, ddy = dx - orb.x0, dy - orb.y0
            orb.flightDist = sqrt(ddx * ddx + ddy * ddy)
            orb.pathKind = burstPath
            orb.pathAmp, orb.pathFreq1, orb.pathFreq2, orb.pathFreq3, orb.pathPhase1, orb.pathPhase2,
                orb.pathPhase3 = OrbMath.PathParams(burstPath, isStreamPop and profile.ranks[i] or i, orb.flightDist,
                    random, spiralSign)
            -- keep both control points on screen, inset by the margin plus this orb's sideways swing (the second
            -- control point is clamped every frame, see drawOrb)
            orb.screenW, orb.screenH = XF_PROFILE.screenW, XF_PROFILE.screenH
            orb.clampMargin = XF_PROFILE.edgeMargin + math.abs(orb.pathAmp)
            orb.control1X, orb.control1Y = OrbMath.ClampToScreen(orb.control1X, orb.control1Y, orb.screenW, orb.screenH,
                orb.clampMargin, dx, dy)
            local launchOrder = random()
            if staggerScale ~= 1 then
                -- a helix launches in pairs, in order, so the orbs follow each other along the two strands
                launchOrder = (floor((i - 1) / 2) + launchOrder * 0.2) / floor((n + 1) / 2)
            end
            orb.delay = launchOrder * stagger * staggerScale + (rested and not isStreamPop and RESTED_DELAY or 0)
                + extraDelay
            local jitterLow, jitterSpan = 0.85, 0.3
            if (orb.group or isStreamPop) and profile.jitterLow then
                jitterLow, jitterSpan = profile.jitterLow, profile.jitterSpan
            end
            if pathJitterLow then
                jitterLow, jitterSpan = pathJitterLow, pathJitterSpan -- a helix's strands keep their spacing
            end
            local flightSpeed, baseDur = XF_PROFILE.flightSpeed, flightTime
            local arcLen = OrbMath.ArcLength(orb.x0, orb.y0, orb.control1X, orb.control1Y, dx, dy, orb.flightDist, bowX,
                bowY, orb.screenW, orb.screenH, orb.clampMargin)
            if flightSpeed then
                baseDur = math.min(2.5, math.max(0.35, arcLen / flightSpeed)) -- B's short arc is already a short time
            else
                baseDur = baseDur * (orb.group and flightScale or 1)
            end
            orb.dur = max(MIN_DUR, baseDur * (jitterLow + random() * jitterSpan))
            if i == 1 then
                ns:Log("FLIGHT mode=%s dist=%d dur=%.2f", flightSpeed and "speed" or "time", floor((arcLen or 0) + 0.5),
                    baseDur)
            end
            -- the trail is spaced in px along the path (the same at any speed or distance): progress per px
            orb.pxToProgress = 1 / max(arcLen, 1)
            orb.elapsed = 0
            orb.fadeIn = fadeIn -- plate-copy orbs fade in during the hold (profile.fadeIn); crossfade's B over bFade
            if orb.group then
                orb.fadeIn = profile.bFade / orb.dur
            elseif isStreamPop then
                orb.fadeIn = 0 -- the pop already faded in
            end
            orb.rested = rested
            orb.size = ns.OrbSize(config) * scale * (rested and RESTED_SIZE or 1)
            orb.startRotation = random() * TWO_PI
            XF_PROFILE.shapes.build(orb, shape, trail, red, green, blue)
            nLive = nLive + 1
            live[nLive] = orb
            orb.burstKey = burstKey
            burstLeft[burstKey] = (burstLeft[burstKey] or 0) + 1
            buildingLive = true
        end
    end)
    if not ok then
        -- Undo what this burst started, so nothing is left holding a pool slot: the half-built orb, every orb that
        -- shares the crossfade frame, and the pop frame (the newest entry of `pops`).
        if building and not buildingLive then
            pcall(freeOrb, building)
        end
        if crossfadeGroup then
            local i = 1
            while i <= nLive do
                local orb = live[i]
                if orb.group == crossfadeGroup then
                    pcall(freeOrb, orb)
                    live[i] = live[nLive]
                    live[nLive] = nil
                    nLive = nLive - 1
                else
                    i = i + 1
                end
            end
        end
        if popped and nPops > 0 then
            local group = pops[nPops]
            pops[nPops] = nil
            nPops = nPops - 1
            releasePop(group)
        end
    end
    if crossfadeGroup and (not ok or crossfadeGroup.refs <= 0) and crossfadeGroup.isCrossfade then
        -- no orb got a plate-space copy (or the burst failed): give the frame back
        dropCrossfade(crossfadeGroup)
        releasePop(crossfadeGroup)
    end
    if not ok then
        crossfadeGroup = nil
    elseif crossfadeGroup and not crossfadeGroup.isCrossfade then
        crossfadeGroup = nil
    end

    if (nLive > 0 or nPops > 0) and not active then
        active = true
        driver:SetScript("OnUpdate", onUpdate)
    end
    if not ok then
        error(err, 0) -- Kills logs it; everything above is already back in its pool
    end
    if crossfadeGroup then
        return "crossfade"
    end
    if isStreamPop then
        return "streampop"
    end
    return popped and "pop+stream" or "stream"
end

-- A plate frame we may be anchored to was assigned to a new unit: fade its pop out (0.1 s) and release it.
function Orbs:PlateReused(plate)
    for i = 1, nPops do
        local group = pops[i]
        if group.plate == plate and not group.fading then
            group.fading, group.fadeElapsed = true, 0
        end
    end
    for i = 1, nCrossfade do
        local group = crossfadeGroups[i]
        if group.plate == plate and not group.fading then
            group.fading, group.fadeElapsed = true, 0
        end
    end
end

-- active, texturesInUse, texturesCreated, ceiling
function Orbs:Info()
    return active, texInUse, texCreated, ceiling()
end

-- liveOrbs, popsAlive, driverFrames, driverTotalMs, driverMaxMs: what the dev-only benchmark (dev/Bench.lua) and
-- /xporbs perf (OrbsCommands.lua) sample
function Orbs:BenchProbe()
    return nLive, nPops, perfFrames, perfTotal, perfMax
end

-- /xporbs perf reset: zeroes the driver's frame counters (the driver updates them as plain upvalues)
function Orbs:PerfReset()
    perfFrames, perfTotal, perfMax = 0, 0, 0
end

-- popsInUse, popFramesCreated, popFrameCap
function Orbs:PopInfo()
    return nPops, popsCreated, POP_FRAMES
end

-- freePop, popFramesCreated, popsAlive, crossfadeFramesAlive: pool bookkeeping (idle = freePop == popFramesCreated and
-- the other two 0; a released frame always has refs 0).
function Orbs:PoolInfo()
    return #freePop, popsCreated, nPops, nCrossfade
end

-- Shared with OrbsCommands.lua (loaded right after this file) so the test commands read the same values: the pop
-- frame's y offset, the unknown-origin levels (UNKNOWN.level) and the zoom anchor read.
Orbs.k = { POP_Y = POP_Y, UNKNOWN_LEVEL = UNKNOWN.level }
Orbs.ZoomAnchorY = zoomAnchorY

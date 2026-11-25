-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Orb renderer: one overlay frame, a hand-rolled texture pool and a single OnUpdate driver that only runs
-- while orbs or the arrival flash are alive. Frames are created lazily on the first burst.
--
-- How it fits together: Kills.lua (and /xporbs test) call Orbs:Burst, which builds one "orb" record per orb in `live`
-- (start point, control point, flight time, textures) and hands them to the driver. The driver (`drive`) moves every
-- orb each frame along a cubic curve from OrbMath towards the XP bar (Target:GetDestination) and plays the arrival
-- chime and flash. A corpse pop or crossfade shares one pooled "group" (a small frame anchored to the nameplate plus
-- its textures) between its orbs. Orb record fields: x0/y0 stream start, control1X/Y first control point, px/py
-- P-hat (the estimated mob position), ux/uy unit vector from P-hat towards the bar, ringX/Y ring point (pop and
-- crossfade copy A), hold seconds spent in that ring before the flight, dur flight time, delay start delay,
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
-- Every chime file, built once so nothing is concatenated while orbs fly: CHIME_PATHS[voice][volume][note]. The game
-- has no per-sound volume, so each volume level (ns.ranges.soundVolume, percent) is its own pre-rendered folder, made
-- by tools/make_sounds.py.
local CHIME_NOTES = 6
local CHIME_PATHS = { glass = {}, coin = {}, swish = {}, pixel = {} }
do
    local range = ns.ranges.soundVolume
    local lowest, highest, step = range[1], range[2], range[3]
    for voice, byVolume in pairs(CHIME_PATHS) do
        for volume = lowest, highest, step do
            local notePaths = {}
            for note = 1, CHIME_NOTES do
                notePaths[note] = "Interface\\AddOns\\XPOrbs\\media\\chime\\" .. volume .. "\\" .. voice
                    .. note .. ".ogg"
            end
            byVolume[volume] = notePaths
        end
    end
end
-- the six paths for a voice at the saved volume (a saved value that is off the grid falls back to the default level)
local function chimeNotePaths(voice)
    local byVolume = CHIME_PATHS[voice] or CHIME_PATHS.glass
    return byVolume[ns.db.soundVolume] or byVolume[ns.defaults.soundVolume]
end

local TWO_PI = math.pi * 2
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
-- point ctrlAhead * dist ahead along u, jittered sideways by +-ctrlJitter * dist (no lift); ghost1Gap / ghost2Gap are
-- the px its trail ghosts sit behind it (along -u) during the fade-in.
-- ux, uy, bCentreX, bCentreY, leaveDistClamped are per-burst scratch (see XF_PROFILE.plan). The arcs of every style
-- share more of it (Burst has no upvalue to spare, so it lives here): screenW, screenH, bowSide (1 or -1, the side the
-- arcs bow to) and edgeMargin = edgeFraction * screen height, the base inset of the control points.
local XF_PROFILE = { bloom = XF_HOLD, bsize = XF_BLOOM_SIZE, fadeIn = XF_FADE_IN,
    flight = 0.40, ease = XF_EASE_OUT, hold = XF_HOLD, rmin = XF_BLOOM_R, rmax = 36, drift = 8, born = 0.04,
    leave = true, leaveDist = 180, leaveTime = 0.26, leaveStagger = 0.15, gap = 0.10, bFade = 0.08, bSpread = 14,
    bDistMin = 80, bDistMax = 320, bScreenFrac = 0.30, bLengthFrac = 0.60, jitterLow = 0.94, jitterSpan = 0.12,
    ctrlAhead = 0.4, ctrlJitter = 0.1,
    ghost1Gap = 12, ghost2Gap = 24,
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
-- below that handles a shape is skipped and Starlight runs exactly the code it always did. Retro, Globe and Crackle
-- live in Shapes.lua (loaded right after this file): it fills `by` (name -> shape table) and uses `host` (the helpers
-- of this file: pooled textures, placement, the flight path) and `k` (the shared tunables). One table, reached through
-- XF_PROFILE from Burst, which cannot take another upvalue.
-- Every orb also carries orb.opacity (db.opacity / 100, taken per burst): the alpha computed once per orb is multiplied
-- by it, so every texture of every shape follows (a pop group has group.opacity). orb.base is db.size x the burst's
-- scale, before the rested multiplier: Retro's one cell size per burst comes from it.
-- A shape table has: needTrail / needPlain (pool textures per flying orb with / without the trail), adjust(n, nPurple,
-- scale) -> n, nPurple, scale (count and size multipliers), timeMul (flight time), build(orb, trail, red, green, blue)
-- (the textures of a flying orb), setup(under, body, spark, st, red, green, blue) (the 3 textures of a pop or copy-A
-- slot; also the first three of a flying orb), draw(st, t, rel, under, body, spark, x, y, size, alpha) (the 3 textures
-- of one orb, no trail; size is db.size scaled, never GLOW; grow, when given (a pop or bloom), is 0.4..1 of the flight
-- size, see SHAPES.grow) and optionally trail(...), see Shapes.lua. `st` is the
-- table holding the orb's shape state: the orb record, or a per-slot table of a pop group.
local SHAPES = { by = {}, host = {}, k = { glow = GLOW, ghostStep = GHOST_STEP, ghost1Alpha = GHOST1_ALPHA,
    ghost1Size = GHOST1_SIZE, ghost2Alpha = GHOST2_ALPHA, ghost2Size = GHOST2_SIZE, underK = UNDER_K,
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
local chime = ns.Chime.New({ now = GetTime, gap = 0.07, perBurst = 6 })
local soundDead = false -- the first sound failure switches the chime off for the session
Orbs.chime = chime -- exposed for tests
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
    local perOrb = shape and max(1 + EXTRAS, shape.needTrail) or 1 + EXTRAS
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
            chime:Done(burstKey)
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
    if orb.ghost1 then
        release(orb.ghost1)
    end
    if orb.ghost2 then
        release(orb.ghost2)
    end
    if orb.ghost3 then -- Globe's longer trail
        release(orb.ghost3)
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
    if orb.ghost1 then
        hideTex(orb.ghost1)
        hideTex(orb.ghost2)
    end
    if orb.ghost3 then
        hideTex(orb.ghost3)
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
            SHAPES.grow(age / orb.bloom))
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
        shape.draw(orb, orb.elapsed, nil, orb.under, orb.body, orb.spark, orbX, orbY, size * sizeMul, alpha * alphaMul)
        if shape.trail then -- a trail of its own (Retro, Globe); Crackle keeps the Starlight ghosts below
            if orb.ghost1 then
                shape.trail(orb, progress, dx, dy, control2X, control2Y, orbX, orbY, alpha * alphaMul)
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
        local ghostProgress = progress - GHOST_STEP
        if group and progress < fadeIn then
            -- crossfade B fading in: the ghosts sit behind it along -u, so it arrives "from" the implied path
            local profile = orb.profile
            place(orb.ghost1, orbX - orb.ux * profile.ghost1Gap, orbY - orb.uy * profile.ghost1Gap,
                size * sizeMul * GLOW * GHOST1_SIZE, alpha * alphaMul * GHOST1_ALPHA)
            place(orb.ghost2, orbX - orb.ux * profile.ghost2Gap, orbY - orb.uy * profile.ghost2Gap,
                size * sizeMul * GLOW * GHOST2_SIZE, alpha * alphaMul * GHOST2_ALPHA)
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
        ghostProgress = progress - 2 * GHOST_STEP
        if ghostProgress > 0 then
            local ghostX, ghostY, ghostSizeMul, ghostAlphaMul = flightPoint(orb, ghostProgress, dx, dy, control2X,
                control2Y)
            place(orb.ghost2, ghostX, ghostY, size * ghostSizeMul * GLOW * GHOST2_SIZE,
                alpha * ghostAlphaMul * GHOST2_ALPHA)
        else
            hideTex(orb.ghost2)
        end
    end
end

-- ---------------------------------------------------------------- corpse pop

-- A pooled pop ("group"): group.frame is a 1x1 frame whose ONLY anchor is the nameplate; group.tex holds up to
-- POP_MAX * 3 textures (underlay, orb, sparkle per orb) created lazily and parented to group.frame; per-orb parameters
-- live in the arrays group.offsetX/offsetY/drift/size/rotation.
local function newPop()
    local frame = CreateFrame("Frame", nil, UIParent)
    frame:SetSize(1, 1)
    frame:SetFrameStrata("HIGH")
    frame:EnableMouse(false)
    frame:Hide()
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
    end
    group.used, group.plate, group.isCrossfade, group.refs, group.shape = 0, nil, false, 0, nil
    pcall(group.frame.ClearAllPoints, group.frame)
    pcall(group.frame.Hide, group.frame)
    freePop[#freePop + 1] = group
end

-- Fills group for orbCount orbs (rested: the first restedCount). Anchors group.frame to the plate with a single point.
-- (ux, uy) is the exit vector the pop orbs launch along; spreadFactor scales the ring radius and drift (the
-- zoom-scaled spread, 1 = fixed). Errors propagate (pcall'd).
local function setupPop(group, plate, orbCount, scale, restedCount, restedColour, normalColour, ux, uy, bodyAnchorY,
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
        local colour = rested and restedColour or normalColour
        local red, green, blue = colour[1], colour[2], colour[3]
        local slotBase = (i - 1) * 3
        local underTex, orbTex, sparkleTex = tex[slotBase + 1], tex[slotBase + 2], tex[slotBase + 3]
        clean(underTex)
        clean(orbTex)
        clean(sparkleTex)
        if shape then
            group.st[i] = group.st[i] or {}
            group.st[i].base = config.size * scale -- (Retro's one cell size per burst)
            shape.setup(underTex, orbTex, sparkleTex, group.st[i], red, green, blue)
        else
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
        group.size[i] = config.size * scale * (rested and RESTED_SIZE or 1)
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
        sparkleTex.xoDirty = true
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

-- An orb arrived: asks the chime for a note and plays it. The first failure (an error, or the client saying the file
-- won't play) logs SOUND_ERR once and silences the chime for the session. Allocates nothing.
local function playChime(burstKey)
    local note = chime:Arrive(burstKey)
    if not note then
        return
    end
    local ok, willPlay = pcall(PlaySoundFile, chimeNotePaths(ns.db.soundVoice)[note], "SFX")
    if not ok or willPlay == false then
        soundDead = true
        ns:Log("SOUND_ERR %s", ok and "the client won't play the file" or string.sub(tostring(willPlay), 1, 120))
    end
end

-- Chime sample (the options panel's play button): the chime of a burst of SAMPLE_COUNT orbs arriving, through
-- playChime so the note progression and the per-note gap match real arrivals. A real burst's orbs land at slightly
-- different times, so each press draws fresh arrival times (seconds after the press) into one reused scratch table:
-- the first note at 0, the rest spread at random inside SAMPLE_SPAN, sorted, and never closer than SAMPLE_MIN_GAP
-- (the chime's own 70 ms rate limit, logic/Chime.lua, plus about one frame: notes play on frame ticks, so two notes
-- drawn just over 70 ms apart could land on frames under it and one would be dropped). The room beyond the
-- minimum gaps is SAMPLE_SPAN - (SAMPLE_COUNT - 1) * SAMPLE_MIN_GAP; sorted random draws share it out unevenly.
-- One short-lived OnUpdate that removes itself after the last note; a new press restarts it.
local SAMPLE_COUNT = 6
local SAMPLE_SPAN = 0.50
local SAMPLE_MIN_GAP = 0.085
local SAMPLE_OFFSETS = {}
for index = 1, SAMPLE_COUNT do
    SAMPLE_OFFSETS[index] = 0
end
Orbs.sampleOffsets = SAMPLE_OFFSETS -- exposed for tests

-- Fills SAMPLE_OFFSETS in place: insertion-sorted random shares of the spare time, plus the minimum gaps.
local function drawSampleOffsets()
    local spare = SAMPLE_SPAN - (SAMPLE_COUNT - 1) * SAMPLE_MIN_GAP
    SAMPLE_OFFSETS[1] = 0
    for index = 2, SAMPLE_COUNT do
        local share = random() * spare
        local slot = index
        while slot > 2 and SAMPLE_OFFSETS[slot - 1] > share do
            SAMPLE_OFFSETS[slot] = SAMPLE_OFFSETS[slot - 1]
            slot = slot - 1
        end
        SAMPLE_OFFSETS[slot] = share
    end
    for index = 2, SAMPLE_COUNT do
        SAMPLE_OFFSETS[index] = SAMPLE_OFFSETS[index] + (index - 1) * SAMPLE_MIN_GAP
    end
end
local SAMPLE_KEY = "chime-sample" -- its own burst key, so it never eats a real burst's six-note allowance
local sampleFrame
local sampleNext, sampleElapsed = 1, 0

local function sampleStop()
    if sampleFrame then
        sampleFrame:SetScript("OnUpdate", nil)
    end
    chime:Done(SAMPLE_KEY)
    sampleNext = #SAMPLE_OFFSETS + 1
end

local function sampleTick(_, dt)
    sampleElapsed = sampleElapsed + (isNumber(dt) and dt or 0)
    while sampleNext <= #SAMPLE_OFFSETS and sampleElapsed >= SAMPLE_OFFSETS[sampleNext] do
        sampleNext = sampleNext + 1
        if ns.db.sound and not soundDead then
            playChime(SAMPLE_KEY)
        end
    end
    if sampleNext > #SAMPLE_OFFSETS then
        sampleStop()
    end
end

-- Starts (or restarts) the sample. Returns false when the chime is off or switched off for the session.
function Orbs:PlayChimeSample()
    if not settings().sound or soundDead then
        return false
    end
    if not sampleFrame then
        sampleFrame = CreateFrame("Frame")
        Orbs.sampleFrame = sampleFrame
    end
    chime:Done(SAMPLE_KEY)
    drawSampleOffsets()
    sampleNext, sampleElapsed = 1, 0
    sampleFrame:SetScript("OnUpdate", sampleTick)
    return true
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
                    if ns.db.sound and not soundDead then
                        playChime(orb.burstKey)
                    end
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
                local diameter = OrbMath.GlowDiameter(Target.lastW, Target.lastH, ns.db.size)
                flash:SetSize(diameter * glowSizeFactor, diameter * glowSizeFactor)
            elseif shape == "vertical" then
                local tall = ns.db.size * FLASH_W * glowSizeFactor
                flash:SetSize(tall / FLASH_ASPECT, tall)
            else
                local w = ns.db.size * FLASH_W * glowSizeFactor
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

-- Gets the textures of one flying orb from the pool: the Starlight art here (underlay, orb, sparkle, 2 ghosts), or
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
        orb.ghost1 = acquire(ORB_TEX, 0, red, green, blue)
        orb.ghost2 = acquire(ORB_TEX, 0, red, green, blue)
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
    -- Starlight. A shape may scale the orb count, size and flight time (all multipliers on the player's own settings).
    local shape = XF_PROFILE.shapes.by[config.orbShape]
    local flightTime = config.flightTime
    if shape then
        n, nPurple, scale = shape.adjust(n, nPurple, scale)
        flightTime = flightTime * shape.timeMul
    end
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
    -- Budget the texture pool. A full burst with trails needs 5 textures per orb; when that doesn't fit, the burst
    -- drops its trail ghosts (3 per orb), then draws fewer orbs. Every burst still gets min(n, 3) orbs while 9
    -- textures are free, so the later kills of an AoE pull are never starved by the earlier ones.
    local trail = config.trail and true or false
    local needTrail, needPlain = 1 + EXTRAS, 3 -- orb + underlay + sparkle (+ 2 ghosts)
    if shape then
        needTrail, needPlain = shape.needTrail, shape.needPlain
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
            orb.base, orb.opacity = config.size * scale, config.opacity / 100 -- (see SHAPES)
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
            orb.dur = max(MIN_DUR,
                flightTime * (orb.group and flightScale or 1) * (jitterLow + random() * jitterSpan))
            orb.elapsed = 0
            orb.fadeIn = fadeIn -- plate-copy orbs fade in during the hold (profile.fadeIn); crossfade's B over bFade
            if orb.group then
                orb.fadeIn = profile.bFade / orb.dur
            elseif isStreamPop then
                orb.fadeIn = 0 -- the pop already faded in
            end
            orb.rested = rested
            orb.size = config.size * scale * (rested and RESTED_SIZE or 1)
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

-- popsInUse, popFramesCreated, popFrameCap
function Orbs:PopInfo()
    return nPops, popsCreated, POP_FRAMES
end

-- freePop, popFramesCreated, popsAlive, crossfadeFramesAlive: pool bookkeeping (idle = freePop == popFramesCreated and
-- the other two 0; a released frame always has refs 0).
function Orbs:PoolInfo()
    return #freePop, popsCreated, nPops, nCrossfade
end

-- Stream origin for /xporbs test (style = a render style). Popstream (Nameplate) follows the kill rule
-- (Target:StreamOrigin: the estimate P-hat, the portrait only without one); Direct Stream and Popstream (Direct) start
-- at the estimate too; otherwise target frame, else the cursor,
-- else the screen centre. Every read is
-- checked for secrecy and pcall'd. Returns x, y, label (x, y nil only when even the screen size is unreadable).
local function testOrigin(style, ex, ey)
    if style == "popstream" then
        local startX, startY, startLabel = Target:StreamOrigin(ex, ey)
        if startX then
            return startX, startY, startLabel
        end
    elseif (style == "stream" or style == "streampop") and isNumber(ex) and isNumber(ey) then
        return ex, ey, "estimate"
    end
    local frameX, frameY = Target:TargetFrameOrigin()
    if frameX then
        return frameX, frameY, "targetframe"
    end
    local okCursor, cursorX, cursorY = pcall(GetCursorPosition)
    local okScale, scale = pcall(UIParent.GetEffectiveScale, UIParent)
    if okCursor and okScale and isNumber(cursorX) and isNumber(cursorY) and isNumber(scale) and scale > 0 then
        return cursorX / scale, cursorY / scale, "cursor"
    end
    local okWidth, width = pcall(UIParent.GetWidth, UIParent)
    local okHeight, height = pcall(UIParent.GetHeight, UIParent)
    if okWidth and okHeight and isNumber(width) and isNumber(height) then
        return width / 2, height / 2, "centre"
    end
    return nil, nil, "centre"
end

-- Fires one test burst of pct % of a level. Returns the numbers the /xporbs test report prints.
local function fireTest(pct, rested, force, forceMode, path)
    local config = settings()
    local okXpMax, xpMax = pcall(UnitXPMax, "player")
    if not okXpMax or not isNumber(xpMax) or xpMax <= 0 then
        xpMax = 1000 -- max level, no data or a secret value: any positive number gives the same orb count
    end
    local gain = pct / 100 * xpMax
    local n, scale = OrbMath.Count(gain, xpMax, config.density, config.cap)
    local nPurple = 0
    if rested then
        local _
        _, nPurple = OrbMath.RestedSplit(n, gain, gain / 2)
    end
    -- the target's estimate (its GUID, when readable, finds a mouseover sample); no target = a keyboard-style estimate
    local guid
    local okGuid, targetGuid = pcall(UnitGUID, "target")
    if okGuid and readable(targetGuid) and type(targetGuid) == "string" then
        guid = targetGuid
    end
    local ex, ey, est, estW = ns.Mouseover:Estimate(guid)
    -- the options window's "Test target" stand-in (Preview.lua): a located mob with a nameplate, whatever is targeted
    -- Burst hangs the pop off the plate it is given at a style-dependent offset (the zoom anchor's body offset below
    -- BOTTOM, else POP_Y from the CENTER for the Popstream pop, else the BOTTOM itself), so the stand-in is told that
    -- offset and places its invisible anchor frame to cancel it: the pop lands on the model's chest whatever the
    -- zoom-anchor setting (Preview.lua).
    local standInPlate
    if ns.Preview then
        local popOffsetY = zoomAnchorY(config)
        if not popOffsetY then
            local renderStyle = ns.RenderStyle(force or config.style, forceMode or config.popMode)
            popOffsetY = renderStyle == "popstream" and POP_Y + (ns.Preview.ANCHOR_SIZE or 0) / 2 or 0
        end
        local okStandIn, plateFrame, bodyX, bodyY = pcall(ns.Preview.TestTarget, ns.Preview, popOffsetY)
        if okStandIn and plateFrame then
            standInPlate = plateFrame
            ex, ey, est, estW = bodyX, bodyY, "mouseover", 1 -- bodyY is already raised towards the pop anchor
        end
    end
    local x, y, label = testOrigin(ns.RenderStyle(force or config.style, forceMode or config.popMode), ex, ey)
    local mode = Orbs:Burst({
        x = x,
        y = y,
        plate = standInPlate or Target:TargetPlate(),
        n = n,
        scale = scale,
        nPurple = nPurple,
        kind = "test",
        style = force,
        popMode = forceMode,
        path = path,
        ex = ex,
        ey = ey,
        est = est,
        estW = estW,
        zoomFactor = standInPlate and 1 or nil, -- the stand-in's window is fixed: the camera must not size its pop
    })
    if standInPlate then
        pcall(ns.Preview.PlayDeath, ns.Preview) -- the stand-in dies as the orbs leave it
    end
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
    stressEl = stressEl + (isNumber(dt) and dt or 0)
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

-- what /xporbs test prints as style= for each Burst result
local TEST_USED = { ["pop+stream"] = "popstream/nameplate", streampop = "popstream/direct" }

-- /xporbs test [pct] [rested] [popstream|crossfade|stream] [nameplate|direct] [smooth|chaos|helix]
-- (any style alias works: streampop = Popstream (Direct), wide / mob = Popstream (Nameplate); nameplate / direct alone
-- mean Popstream with that pop; smooth / chaos / helix override the flight path for that burst; the old "frame" /
-- "plate" words are ignored)
-- /xporbs test stress [n]
-- quiet = true fires the burst without the chat report (the Test Kill buttons use it through ns.TestKill; the slash
-- handler passes a second argument of its own, so the flag is not a parameter of ns.commands.test).
local function runTest(arg, quiet)
    local first, count = string.match(arg or "", "^%s*(%S+)%s*(%S*)")
    if first == "stress" then
        startStress(count)
        return
    end
    local config = settings()
    local pct, rested, force, forceMode, path = 5, false, nil, nil, nil
    for tok in string.gmatch(arg or "", "%S+") do
        if tok == "rested" then
            rested = true
        elseif ns.STYLE_ALIAS[tok] then
            force = tok
        elseif ns.PATH_LABEL[tok] then
            path = tok
        elseif tok == "nameplate" or tok == "direct" then
            force, forceMode = force or "popstream", tok
        elseif tok ~= "frame" and tok ~= "plate" then
            local v = tonumber(tok)
            if v and v > 0 then
                pct = min(v, 1000)
            end
        end
    end
    Orbs.lastUnknown = nil
    local n, scale, nPurple, est, estW, mode, label = fireTest(pct, rested, force, forceMode, path)
    if quiet then
        return
    end
    local used = TEST_USED[mode] or mode
    if mode == "crossfade" then
        label = "estimated"
    end
    ns.Print(string.format("test: %g%% of a level -> %d orbs (%d purple), scale %.2f, est=%s w=%.2f pop=%s stream=%s"
        .. " style=%s", pct, n, nPurple, scale, est or "none", estW or 0, mode == "pop+stream" and "yes" or "no",
        label, used) .. (Orbs.lastUnknown and " unknown=" .. Orbs.lastUnknown or "")
        .. (path and " path=" .. path or ""))
end

function ns.commands.test(arg)
    runTest(arg, false)
end

-- The Test Kill buttons (Preview.lua, Options.lua): the same burst as /xporbs test, with no chat output.
function ns.TestKill(arg)
    runTest(arg, true)
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
        local okUpdate = pcall(UpdateAddOnMemoryUsage)
        local okUsage, kb = pcall(GetAddOnMemoryUsage, ADDON)
        if okUpdate and okUsage and isNumber(kb) then
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

-- Plays one random note of a voice at the saved volume so the options panel and /xporbs sound can preview it (even with
-- the chime off). One pcall, no state.
function Orbs:PreviewSound(voice)
    if CHIME_PATHS[voice] and PlaySoundFile then
        pcall(PlaySoundFile, chimeNotePaths(voice)[random(CHIME_NOTES)], "SFX")
    end
end

local SOUND_ALIAS = { glassa = "glass", glassb = "coin", brush = "swish", ding = "pixel" } -- older voice names
-- /xporbs sound on|off|glass|coin|swish|pixel|volume N: the arrival chime. Turning it on also clears a SOUND_ERR
-- shutdown, so it can be retried. A voice name picks the sound (and turns the chime on); the older names glassa, glassb,
-- brush and ding still work (as glass, coin, swish and pixel). volume N sets the volume in percent
-- (snapped to the options slider's steps) and plays a sample note if the chime is on.
function ns.commands.sound(arg)
    local word, rest = string.match(arg or "", "^%s*(%S*)%s*(.-)%s*$")
    local voice = SOUND_ALIAS[word] or word
    if word == "on" or CHIME_PATHS[voice] then
        settings().sound = true
        if word ~= "on" then
            settings().soundVoice = voice
        end
        soundDead = false
        refreshPanel()
    elseif word == "off" then
        settings().sound = false
        refreshPanel()
    elseif word == "volume" then
        local range = ns.ranges.soundVolume
        local percent = ns.OrbMath.Snap(ns.OrbMath.ParseNumber(rest), range[1], range[2], range[3])
        if not percent then
            ns.Print(string.format("sound: volume needs a number, %d to %d (percent)", range[1], range[2]))
            return
        end
        settings().soundVolume = percent
        refreshPanel()
        if settings().sound and not soundDead then
            Orbs:PreviewSound(settings().soundVoice)
        end
    elseif word ~= "" then
        ns.Print("sound: use on, off, glass, coin, swish, pixel or volume N")
        return
    end
    local note = soundDead and " (switched off this session: the client wouldn't play the file)" or ""
    ns.Print(string.format("chime: %s, %s, volume %d%%%s", settings().sound and "on" or "off",
        tostring(settings().soundVoice),
        tonumber(settings().soundVolume) or ns.defaults.soundVolume, note))
end

-- true once a sound failure has switched the chime off for this session
function Orbs:SoundDisabled()
    return soundDead
end

-- /xporbs style popstream [nameplate|direct] | crossfade | stream, plus the old names (Core STYLE_ALIAS): streampop =
-- Popstream (Direct), wide / mob = Popstream (Nameplate) with Wide on. /xporbs pop on|off = popstream|stream.
function ns.commands.style(arg)
    local word, subMode = string.match(arg or "", "^%s*(%S*)%s*(%S*)")
    if word == "nameplate" or word == "direct" then
        word, subMode = "popstream", word
    end
    if word ~= "" then
        local alias = ns.STYLE_ALIAS[word]
        if not alias
            or (subMode ~= "" and (alias[1] ~= "popstream" or (subMode ~= "nameplate" and subMode ~= "direct"))) then
            ns.Print("style: use popstream [nameplate|direct], crossfade or stream")
            return
        end
        ns.SetStyle(settings(), word)
        if subMode ~= "" then
            settings().popMode = subMode
        end
        refreshPanel()
    end
    ns.Print("kill style: " .. ns.StyleLabel(settings()))
end

-- /xporbs path smooth|chaos|helix: how orbs fly (db.flightPath). No argument shows the current one.
function ns.commands.path(arg)
    local word = string.match(arg or "", "^%s*(%S*)")
    if word ~= "" then
        if not ns.PATH_LABEL[word] then
            ns.Print("path: use smooth, chaos or helix")
            return
        end
        settings().flightPath = word
        refreshPanel()
    end
    ns.Print("flight style: " .. (ns.PATH_LABEL[settings().flightPath] or "Smooth"))
end

-- /xporbs shape starlight|retro|globe|crackle: how the orbs are drawn (db.orbShape; the old names power and wisp still
-- work). Size, quantity and opacity are remembered per shape (ns.SetOrbShape). No argument shows the current one.
function ns.commands.shape(arg)
    local word = string.match(arg or "", "^%s*(%S*)")
    if word ~= "" then
        settings()
        if not ns.SetOrbShape(word) then
            ns.Print("shape: use starlight, retro, globe or crackle")
            return
        end
        refreshPanel()
    end
    ns.Print("orb shape: " .. (ns.SHAPE_LABEL[settings().orbShape] or ns.SHAPE_LABEL.starlight))
end

-- /xporbs pulse on|off: the "Pulsing" tickbox (db.pulse, the current shape's own): Globe orbs gently swell and shrink.
function ns.commands.pulse(arg)
    local word = string.match(arg or "", "%S+")
    if word == "on" or word == "off" then
        ns.SetLook("pulse", word == "on")
        refreshPanel()
    elseif word ~= nil then
        ns.Print("pulse: use on or off (now " .. (settings().pulse and "on" or "off") .. ")")
        return
    end
    ns.Print("pulsing: " .. (settings().pulse and "on" or "off")
        .. (settings().orbShape ~= "globe" and " (Globe only)" or ""))
end

local function spreadState()
    return settings().zoomSpread and "on" or "off"
end

-- /xporbs wide on|off: the "Zoom-scaled spread" tickbox (db.zoomSpread): located orbs' spawn spread scales with zoom.
function ns.commands.wide(arg)
    local word = string.match(arg or "", "%S+")
    if word == "on" or word == "off" then
        settings().zoomSpread = word == "on"
        refreshPanel()
    elseif word ~= nil then
        ns.Print("wide: use on or off (now " .. spreadState() .. ")")
        return
    end
    ns.Print("zoom-scaled spread: " .. spreadState())
end

-- /xporbs unknown off|wide: where the stream starts when the mob is not located (no Options control; "off" is kept
-- for future quest/exploration streams)
function ns.commands.unknown(arg)
    local word = string.match(arg or "", "%S+")
    if word ~= nil and UNKNOWN.level[word] == nil then
        ns.Print("unknown: use off or wide (now " .. tostring(settings().unknownOrigin) .. ")")
        return
    end
    if word ~= nil then
        settings().unknownOrigin = word
    end
    ns.Print("unknown origin: " .. tostring(settings().unknownOrigin))
end

function ns.commands.pop(arg)
    local word = string.match(arg or "", "%S+")
    if word == "on" then
        settings().style = "popstream"
        refreshPanel()
    elseif word == "off" then
        settings().style = "stream"
        refreshPanel()
    elseif word ~= nil then
        ns.Print("pop: use on or off")
        return
    end
    ns.Print("kill style: " .. ns.StyleLabel(settings()))
end

table.insert(ns.statusProviders, function()
    Target:GetDestination()
    return string.format(
        "orbs: driver=%s, live textures=%d, pool=%d/%d, dest=%s, fallback=%s, style=%s, pops=%d (frames %d/%d)",
        active and "active" or "idle",
        texInUse,
        texCreated,
        ceiling(),
        tostring(Target.lastName) .. (Target.lastSourceLabel and (" [" .. Target.lastSourceLabel .. "]") or ""),
        Target.lastOk and "no" or "yes",
        ns.RenderStyle(settings().style, settings().popMode),
        nPops,
        popsCreated,
        POP_FRAMES
    )
end)

table.insert(ns.statusProviders, function()
    return "kill style: " .. ns.StyleLabel(settings()) .. ", zoom-scaled spread: " .. spreadState()
end)

table.insert(ns.statusProviders, function()
    return "unknown origin: " .. tostring(settings().unknownOrigin)
end)

table.insert(ns.statusProviders, function()
    local config = settings()
    return string.format("orb shape: %s (size %d, quantity %d%%, opacity %d%%), pulsing %s",
        ns.SHAPE_LABEL[config.orbShape] or ns.SHAPE_LABEL.starlight, config.size, config.density, config.opacity,
        config.pulse and "on" or "off")
end)

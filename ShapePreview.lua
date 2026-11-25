-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Orb preview window: a framed window like the "Test target" one (Preview.lua), docked to the right of the settings
-- panel with the test target window hung under it. It shows a cluster of stationary orbs of the current shape: the
-- count follows Quantity (n = round(5 * density / 100), 2..12; 5 at the default 100%) in a fixed pattern (pair,
-- triangle, diamond, cross, a centre with a ring, a centre with two rings), the last 2/5 of them rested when Rested
-- tint is on. The shape's own animation runs (Starlight's spinning sparkle, Retro's blinking twinkle on its grid,
-- Globe's breathing and glint, Crackle's bolt swaps), no trail. It is drawn by the same shape code as real orbs (the
-- shape's setup and draw with the orb area as the frame), from 36 textures of its own, and follows the shape, size,
-- quantity, blend, opacity, pulsing and colour settings as they change. The pattern's spacing scales with the orb's
-- size, so overlap shows Natural against Solid honestly.
--
-- The window is built on first need and shown and hidden with the options panel (Options.lua calls Sync(true) from the
-- panel's OnShow, Sync() after every change and Sync(false) from OnHide); its OnUpdate runs only while it is up. Every
-- call is made under pcall by Options.lua, so a panel built before Orbs.lua and Shapes.lua are ready never errors, and
-- a failed build is remembered so it never leaks another frame. Preview.lua asks ShapePreview:Frame() what to dock
-- under and falls back to the settings panel when there is none.

local ShapePreview = {}
ns.ShapePreview = ShapePreview

local WINDOW_W, WINDOW_H = 200, 164 -- px; the width matches the test target window
local PAD, TITLE_H = 8, 28 -- px: the window's side/bottom padding and the room for the title above the orb area
local AREA_W, AREA_H = WINDOW_W - 2 * PAD, WINDOW_H - TITLE_H - PAD
local MIN_ORBS, MAX_ORBS, SLOTS = 2, 12, 36 -- 12 orbs x 3 textures
-- Neighbour distance per px of orb size, per shape (Retro: RETRO_CELLS of its cells, see spacingFor).
local SPACING = { starlight = 1.0, globe = 0.9, crackle = 1.0 }
local RETRO_CELLS = 7 -- neighbouring Retro orbs share one column of cells
local FLOOR = 0.75 -- the spacing is squeezed to this fraction at most to fit the area, then the area clips
local ROW_H = math.sqrt(3) / 2 -- honeycomb row height, in neighbour distances
local ROWS = { [7] = { 2, 3, 2 }, [8] = { 3, 2, 3 }, [9] = { 3, 3, 3 }, [10] = { 3, 4, 3 }, [11] = { 4, 3, 4 },
    [12] = { 4, 4, 4 } }
local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local TWO_PI = math.pi * 2
local random = math.random

ShapePreview.WINDOW_W, ShapePreview.WINDOW_H = WINDOW_W, WINDOW_H
ShapePreview.SPACING, ShapePreview.RETRO_CELLS, ShapePreview.FLOOR = SPACING, RETRO_CELLS, FLOOR

local window, box -- the window, and the orb area inside it (box.tex holds the 36 textures, box.st the per-orb state)
local looks -- what the orbs are currently set up with (see signature), to spot a change
local buildFailed = false -- build threw once: do not try again this session (every attempt would leak a frame)
local errSeen = false

local function lerp(channel, toward, amount)
    return channel + (toward - channel) * amount
end

local function round(x)
    return math.floor(x + 0.5)
end

-- ---------------------------------------------------------------- how many orbs, and where

-- Orbs shown for a Quantity setting (percent).
function ShapePreview.Count(density)
    local n = round(5 * (tonumber(density) or 100) / 100)
    return math.max(MIN_ORBS, math.min(MAX_ORBS, n))
end

-- How many of the n orbs are rested (the last ones) when Rested tint is on.
function ShapePreview.RestedCount(n)
    return round(n * 2 / 5)
end

local function ring(points, count, radius)
    for k = 0, count - 1 do
        local angle = math.pi / 2 - TWO_PI * k / count -- from the top, clockwise
        points[#points + 1] = { radius * math.cos(angle), radius * math.sin(angle) }
    end
end

-- The pattern for n orbs as unit offsets from the centre (x right, y up; 1 = the neighbour distance): 2 a pair, 3 a
-- triangle, 4 a diamond, 5 a cross, 6 a centre and a ring of five, 7-12 honeycomb rows (y = +-0.866 and 0) in which
-- every neighbour is one unit away (equal rows are shifted +-0.25 so they interlock). The slots run top row first, so
-- the last ones (the rested orbs) form the bottom row.
function ShapePreview.Pattern(n)
    local points = {}
    if n <= 2 then
        points = { { -0.5, 0 }, { 0.5, 0 } }
    elseif n == 3 then
        ring(points, 3, 0.58)
    elseif n == 4 then
        points = { { 0, 0.7 }, { 0.7, 0 }, { 0, -0.7 }, { -0.7, 0 } }
    elseif n == 5 then
        points = { { 0, 0 }, { 0, 1 }, { 0, -1 }, { -1, 0 }, { 1, 0 } }
    elseif n == 6 then
        points[1] = { 0, 0 }
        ring(points, 5, 1)
    else
        local rows = ROWS[n]
        local equal = rows[1] == rows[2] and rows[2] == rows[3]
        for r, count in ipairs(rows) do
            local shift = equal and (r % 2 == 1 and 0.25 or -0.25) or 0
            for c = 1, count do
                points[#points + 1] = { c - (count + 1) / 2 + shift, (2 - r) * ROW_H }
            end
        end
    end
    return points
end

-- Neighbour distance in px for the current look: per-shape spacing times the orb size; Retro 7 of its cells.
local function spacingFor(db)
    if db.orbShape == "retro" then
        return RETRO_CELLS * db.size
    end
    return (SPACING[db.orbShape] or SPACING.starlight) * ns.OrbSize(db)
end
ShapePreview.SpacingFor = spacingFor

-- The spacing in px for a pattern: the wanted spacing, fitted to the area in x and y separately (an orb's half-extent
-- is its OrbSize, times the rested scale when Rested tint is on), squeezed to FLOOR at most (what is left is cropped by
-- the area's clipping), and for Retro kept on whole cells.
local function radiusFor(points, db)
    local want = spacingFor(db)
    local size = ns.OrbSize(db)
    if db.restedTint then
        size = size * ns.OrbShapes.k.restedSize
    end
    local reachX, reachY = 1e-9, 1e-9
    for _, p in ipairs(points) do
        reachX, reachY = math.max(reachX, math.abs(p[1])), math.max(reachY, math.abs(p[2]))
    end
    local fit = math.min((AREA_W / 2 - size) / reachX, (AREA_H / 2 - size) / reachY)
    local radius = math.max(FLOOR * want, math.min(want, fit))
    if db.orbShape == "retro" then
        radius = round(radius / db.size) * db.size
    end
    return math.max(radius, 0)
end
ShapePreview.RadiusFor = radiusFor -- (exposed for tests)

-- ---------------------------------------------------------------- Starlight's drawing

-- Starlight is drawn inline in Orbs.lua, so the preview has its own small copy of that drawing (the k table of
-- ns.OrbShapes carries the same constants): underlay, body and a spinning sparkle.
local function starlightSetup(under, body, spark, st, red, green, blue)
    local k = ns.OrbShapes.k
    under:SetTexture(ORB_TEX)
    under:SetBlendMode("BLEND")
    under:SetDrawLayer("ARTWORK", -1)
    under:SetVertexColor(red * k.underK, green * k.underK, blue * k.underK)
    body:SetTexture(ORB_TEX)
    body:SetBlendMode("ADD")
    body:SetDrawLayer("ARTWORK", 0)
    body:SetVertexColor(red, green, blue)
    spark:SetTexture(SPARKLE_TEX)
    spark:SetBlendMode("ADD")
    spark:SetDrawLayer("ARTWORK", 1)
    spark:SetVertexColor(lerp(red, 1, k.sparkleWhite), lerp(green, 1, k.sparkleWhite), lerp(blue, 1, k.sparkleWhite))
    st.rotation = random() * TWO_PI
end

local function starlightDraw(st, t, rel, under, body, spark, x, y, size, alpha)
    local host, k = ns.OrbShapes.host, ns.OrbShapes.k
    local bodySize = size * k.glow
    host.putAt(under, rel, x, y, bodySize * k.underSize, alpha * k.underAlpha)
    host.putAt(body, rel, x, y, bodySize, alpha)
    host.putAt(spark, rel, x, y, size * k.sparkle, alpha * k.sparkleAlpha)
    spark:SetRotation(st.rotation + TWO_PI * t)
end

-- What the orbs' set-up depends on: when it changes the orbs are set up again.
local function signature(db, red, green, blue)
    local rested = db.restedColor
    return table.concat({ db.orbShape, db.size, ns.OrbSize(db), ShapePreview.Count(db.density), tostring(db.blend),
        tostring(db.sparkle), tostring(db.pulse), db.restedTint and 1 or 0, red, green, blue, rested[1], rested[2],
        rested[3] }, "|")
end

-- ---------------------------------------------------------------- the window

local function build()
    local created, frame = pcall(CreateFrame, "Frame", nil, UIParent, "BackdropTemplate")
    if not (created and frame) then
        frame = CreateFrame("Frame", nil, UIParent)
    end
    window = frame
    frame:SetSize(WINDOW_W, WINDOW_H)
    frame:SetFrameStrata("MEDIUM") -- below the orbs overlay (HIGH), like the test target
    frame:EnableMouse(true)
    ns.Preview.AddBackground(frame)
    local title = frame:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    title:SetPoint("TOP", frame, "TOP", 0, -10)
    title:SetText("Preview")
    frame.title = title
    box = CreateFrame("Frame", nil, frame)
    box:SetPoint("TOPLEFT", frame, "TOPLEFT", PAD, -TITLE_H)
    box:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -PAD, PAD)
    pcall(box.SetClipsChildren, box, true) -- a large orb stays inside the area
    box.tex, box.st, box.time = {}, {}, 0
    for i = 1, SLOTS do
        local tex = box:CreateTexture(nil, "ARTWORK")
        tex:SetAlpha(0)
        tex:Hide()
        tex.xoShown = false
        box.tex[i] = tex
    end
    ShapePreview.window, ShapePreview.box = window, box
end

-- build threw part-way: hide the half-built window, drop every reference and remember the failure.
local function abandon()
    buildFailed = true
    if window then
        pcall(window.Hide, window)
    end
    window, box, looks = nil, nil, nil
    ShapePreview.window, ShapePreview.box = nil, nil
end

local function dock()
    window:ClearAllPoints()
    window:SetPoint("TOPLEFT", _G.SettingsPanel, "TOPRIGHT", ns.Preview and ns.Preview.GAP or 4, 0)
end

-- Sets the orbs up for the current settings: n orbs get their three textures set up, the other slots are hidden.
local function configure(db, red, green, blue)
    local shape = ns.OrbShapes.by[db.orbShape] -- nil: Starlight
    local setup = shape and shape.setup or starlightSetup
    local n = ShapePreview.Count(db.density)
    local restedFrom = n - (db.restedTint and ShapePreview.RestedCount(n) or 0) + 1
    local restedColour = db.restedColor
    box.n = n
    for i = 1, MAX_ORBS do
        local first = (i - 1) * 3
        for j = 1, 3 do
            local tex = box.tex[first + j]
            tex:SetTexCoord(0, 1, 0, 1) -- (the last shape may have cropped or rotated it)
            tex:SetAlpha(0)
            tex:Hide()
            tex.xoShown = false
        end
        if i <= n then
            local colour = i >= restedFrom and restedColour or { red, green, blue }
            local st = { base = ns.OrbSize(db) } -- Retro's one cell size comes from base
            box.st[i] = st
            setup(box.tex[first + 1], box.tex[first + 2], box.tex[first + 3], st, colour[1], colour[2], colour[3])
        else
            box.st[i] = nil
        end
    end
    box.pattern, box.restedFrom = ShapePreview.Pattern(n), restedFrom
end

local function draw(db)
    local shape = ns.OrbShapes.by[db.orbShape]
    local draws = shape and shape.draw or starlightDraw
    local alpha = db.opacity / 100
    local restedSize = ns.OrbShapes.k.restedSize
    local base = ns.OrbSize(db)
    local radius = radiusFor(box.pattern, db)
    for i = 1, box.n do
        local first = (i - 1) * 3
        local size = base * (db.restedTint and i >= box.restedFrom and restedSize or 1)
        local p = box.pattern[i]
        draws(box.st[i], box.time, box, box.tex[first + 1], box.tex[first + 2], box.tex[first + 3], p[1] * radius,
            p[2] * radius, size, alpha)
    end
end

local function onUpdate(_, dt)
    local db = ns.db
    if not (db and looks) then
        return
    end
    box.time = box.time + dt
    local ok, err = pcall(draw, db)
    if not ok and not errSeen then
        errSeen = true
        ns:Log("PREVIEW_ERR %s", string.sub(tostring(err), 1, 120))
    end
end

local function configureIfChanged()
    local db = ns.db
    local red, green, blue = ns.Orbs.NormalRGB(db)
    local now = signature(db, red, green, blue)
    if now ~= looks then
        looks = now
        configure(db, red, green, blue)
    end
end

local function ready()
    return ns.db and _G.SettingsPanel and ns.Preview and ns.Preview.AddBackground and ns.OrbShapes
        and ns.OrbShapes.host and ns.Orbs and ns.Orbs.NormalRGB
end

-- The window the test target docks under: nil unless the preview is up.
function ShapePreview:Frame()
    return window and window.up and window or nil
end

-- Options.lua: Sync(true) when the panel is shown (builds the window on first need, docks and shows it), Sync(false)
-- when it is hidden, Sync() after every setting change (sets the orbs up again if the look changed). Returns true
-- while the window is up.
function ShapePreview:Sync(show)
    if show == false then
        self:Stop()
        if window and window.up then
            window.up = false
            window:Hide()
        end
        return false
    end
    if buildFailed or not ready() then
        return false
    end
    if not window then
        if show ~= true then
            return false
        end
        if not pcall(build) then
            abandon()
            return false
        end
    end
    if not window.up then
        if show ~= true then
            return false
        end
        window.up = true
        dock()
        window:Show()
    end
    configureIfChanged()
    box:SetScript("OnUpdate", onUpdate)
    return true
end

-- Ends the animation (the panel was hidden).
function ShapePreview:Stop()
    if box then
        box:SetScript("OnUpdate", nil)
    end
end

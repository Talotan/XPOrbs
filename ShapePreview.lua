-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Orb preview window: a framed window like the "Test target" one (Preview.lua), docked to the right of the settings
-- panel with the test target window hung under it (anchored to its bottom edge, so it follows when the window grows).
-- A header row holds the "Preview" title (top left) and the Cluster tickbox (top right). It shows a cluster of
-- stationary orbs of the current shape: the count follows Quantity (n = round(6 * density / 100), 2..12; 6 at the
-- default 100%) in a fixed pattern (pair, triangle, 2 x 2, pentagon, honeycomb rows; fewer per row when big orbs
-- don't fit the width), the last 2/5 of them rested when Rested tint is on. The orbs are spaced so their visible
-- discs just do not touch; the "Cluster" tickbox (db.previewCluster) packs them into an overlapping
-- cloud instead, like orbs piled up after a kill, with the rested ones mixed in. The shape's own animation runs
-- (Starlight's spinning sparkle, Retro's blinking twinkle on its grid,
-- Bubble's breathing and glint, Crackle's bolt swaps), no trail. It is drawn by the same shape code as real orbs (the
-- shape's setup and draw with the orb area as the frame), from 36 textures of its own, and follows the shape, size,
-- quantity, blend, opacity, pulsing and colour settings as they change. The spacing scales with the orb's size, and
-- the window grows taller (never wider) so the orbs get the spacing they want and nothing is clipped (AreaHeightFor).
--
-- The window is built on first need and shown and hidden with the options panel (Options.lua calls Sync(true) from the
-- panel's OnShow, Sync() after every change and Sync(false) from OnHide); its OnUpdate runs only while it is up. Every
-- call is made under pcall by Options.lua, so a panel built before Orbs.lua and Shapes.lua are ready never errors, and
-- a failed build is remembered so it never leaks another frame. Preview.lua asks ShapePreview:Frame() what to dock
-- under and falls back to the settings panel when there is none.

local ShapePreview = {}
ns.ShapePreview = ShapePreview

local WINDOW_W, WINDOW_H = 200, 120 -- px; the width matches the test target window, the height is the least
local CLUSTER_TIP = "Pile the orbs up, overlapping, as they look right after a kill."
local CHECK = 20 -- px: the Cluster tickbox
local PAD, TITLE_H = 8, 28 -- px: the window's side/bottom padding and the header row (title, Cluster) above the area
local AREA_W, AREA_H = WINDOW_W - 2 * PAD, WINDOW_H - TITLE_H - PAD -- the area's width, and its least height
local MIN_ORBS, MAX_ORBS, SLOTS = 2, 12, 36 -- 12 orbs x 3 textures
-- The visible disc's diameter per px of orb size, per shape: the drawn quad times the share of it that is seen (about
-- 0.6 of Starlight's 2 x quad once the glow is discounted, the Bubble body's plateau is 0.72 of its 1.5 x quad,
-- Crackle's core 0.4 of its 2.3 x quad plus a little for the bolts). Retro's disc is 8 cells.
local VISIBLE = { starlight = 1.15, bubble = 1.08, crackle = 1.35 } -- (Crackle: the bolts need room in the tidy layout)
local CLUSTER_VISIBLE = { crackle = 1.15 } -- the unit of the pile where it differs from VISIBLE
local GAP_K, GAP_MIN = 0.12, 3 -- the gap between neighbouring discs: this share of the diameter, at least this many px
local RETRO_GAP = 2 -- cells between neighbouring Retro discs (the grid snap eats up to one)
-- How far an orb's drawn art reaches from its centre, per px of OrbSize (the faint underlay is not counted):
-- Starlight's body quad, Bubble's body at the top of its breath, Crackle's bolt layer. Retro's is 5 cells (the
-- underlay) plus the half cell its grid snap can move it.
local HALF = { starlight = 1.0, bubble = 0.8, crackle = 1.3 }
local RETRO_HALF_CELLS, RETRO_MIN_CELLS = 5.5, 9 -- drawn Retro centres stay at least the disc (8) plus one cell apart
local ROW_H = math.sqrt(3) / 2 -- honeycomb row height, in neighbour distances
local ROWS = { [6] = { 3, 3 }, [7] = { 2, 3, 2 }, [8] = { 3, 2, 3 }, [9] = { 3, 3, 3 }, [10] = { 3, 4, 3 },
    [11] = { 4, 3, 4 }, [12] = { 4, 4, 4 } }
-- The cluster: a loose overlapping pile in the manner of the cloud piles in the art sheets, in units of a NORMAL
-- orb's visible diameter (y up), in growth order: n orbs are the first n entries, re-centred on their mean. The
-- first is the heart of the pile. CLUSTER_SCALE stretches it per shape (Starlight's glow reads tighter).
local CLUSTER = { { 0, 0 }, { 0.75, 0.34 }, { -0.15, 0.49 }, { 0.30, -0.19 }, { -0.75, -0.04 }, { 0.39, 0.70 },
    { -0.72, 0.65 }, { -0.39, -0.54 }, { 0.90, -0.32 }, { 0.10, 1.03 }, { -1.36, 0.23 }, { 1.39, 0.23 } }
local CLUSTER_SCALE = { starlight = 1.3 }
-- Which growth indices of a pile of n are rested (blue), when Rested tint is on; the heart (1) is always purple.
local CLUSTER_RESTED = { [2] = { 2 }, [3] = { 2 }, [4] = { 2, 3 }, [5] = { 2, 3 }, [6] = { 2, 3 }, [7] = { 2, 4, 7 },
    [8] = { 2, 4, 7 }, [9] = { 2, 4, 7, 8 }, [10] = { 2, 4, 7, 8 }, [11] = { 2, 4, 7, 8 }, [12] = { 2, 4, 7, 8, 10 } }
local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local TWO_PI = math.pi * 2
local random = math.random

ShapePreview.WINDOW_W, ShapePreview.WINDOW_H = WINDOW_W, WINDOW_H
ShapePreview.VISIBLE, ShapePreview.HALF = VISIBLE, HALF
ShapePreview.TITLE_H, ShapePreview.PAD, ShapePreview.AREA_W = TITLE_H, PAD, AREA_W
ShapePreview.CLUSTER_SCALE = CLUSTER_SCALE

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
    local n = round(6 * (tonumber(density) or 100) / 100)
    return math.max(MIN_ORBS, math.min(MAX_ORBS, n))
end

-- How many of the n orbs are rested when Rested tint is on.
function ShapePreview.RestedCount(n)
    return round(n * 2 / 5)
end

-- The growth index of the orb in each slot of a pile of n, and the pile's offsets by growth index re-centred on the
-- mean. Slots run outermost first (by distance from the mean) with the heart last, so it is drawn on top.
local function clusterOrder(n)
    local sumX, sumY = 0, 0
    for i = 1, n do
        sumX, sumY = sumX + CLUSTER[i][1], sumY + CLUSTER[i][2]
    end
    local centred, order = {}, {}
    for i = 1, n do
        centred[i] = { CLUSTER[i][1] - sumX / n, CLUSTER[i][2] - sumY / n }
        order[i] = i
    end
    table.sort(order, function(a, b)
        if a == 1 or b == 1 then
            return b == 1 and a ~= 1
        end
        local da = centred[a][1] ^ 2 + centred[a][2] ^ 2
        local db = centred[b][1] ^ 2 + centred[b][2] ^ 2
        if da ~= db then
            return da > db
        end
        return a < b
    end)
    return order, centred
end

-- Which slots (1..n) are rested, as a table of booleans. Tidy layout: the last ones, so they form the bottom row.
-- Cluster: CLUSTER_RESTED by growth index, so blue is mixed into the pile.
function ShapePreview.RestedSlots(n, cluster)
    local rested = {}
    if cluster then
        local order = clusterOrder(n)
        local blue = {}
        for _, growth in ipairs(CLUSTER_RESTED[n] or {}) do
            blue[growth] = true
        end
        for slot, growth in ipairs(order) do
            rested[slot] = blue[growth] or nil
        end
        return rested
    end
    local count = ShapePreview.RestedCount(n)
    for j = 1, count do
        rested[n - count + j] = true
    end
    return rested
end

local function ring(points, count, radius)
    for k = 0, count - 1 do
        local angle = math.pi / 2 - TWO_PI * k / count -- from the top, clockwise
        points[#points + 1] = { radius * math.cos(angle), radius * math.sin(angle) }
    end
end

-- The honeycomb rows for 6-12 orbs as unit offsets (1 = the neighbour distance): every neighbour is one unit away
-- (three equal rows are shifted +-0.25 so they interlock; 6 is a plain 3 x 2 grid), rows centred on y = 0, top row
-- first.
local function honeycomb(rows)
    local points = {}
    local equal = rows[1] == rows[2] and rows[2] == (rows[3] or rows[2])
    local pitch = #rows == 2 and 1 or ROW_H -- two rows of three sit on a grid, a pitch of one unit
    for r, count in ipairs(rows) do
        local shift = equal and #rows > 2 and (r % 2 == 1 and 0.25 or -0.25) or 0
        for c = 1, count do
            points[#points + 1] = { c - (count + 1) / 2 + shift, ((#rows + 1) / 2 - r) * pitch }
        end
    end
    return points
end

-- The cluster for n orbs as offsets in normal visible diameters, in slot order (see clusterOrder).
local function clusterPoints(n)
    local order, centred = clusterOrder(n)
    local points = {}
    for slot, growth in ipairs(order) do
        points[slot] = centred[growth]
    end
    return points
end

-- The layout for n orbs as offsets from the centre (x right, y up). Tidy (the default): unit 1 = the neighbour
-- distance, no two closer than 1: 2 a pair, 3 a triangle, 4 a 2 x 2 square, 5 a pentagon, 6-12 honeycomb rows (6 is
-- two rows of three, then three rows). The slots run top row first, so the last ones (the rested orbs) form the bottom
-- row. Cluster: unit 1 = the visible diameter, a fixed overlapping pile (see CLUSTER).
function ShapePreview.Pattern(n, cluster)
    local points = {}
    if cluster then
        return clusterPoints(n)
    elseif n <= 2 then
        points = { { -0.5, 0 }, { 0.5, 0 } }
    elseif n == 3 then
        ring(points, 3, 1 / math.sqrt(3))
    elseif n == 4 then
        points = { { -0.5, 0.5 }, { 0.5, 0.5 }, { -0.5, -0.5 }, { 0.5, -0.5 } }
    elseif n == 5 then
        ring(points, 5, 1 / (2 * math.sin(math.pi / 5)))
    else
        points = honeycomb(ROWS[n])
    end
    return points
end

-- The biggest visible disc's diameter in px for the current look (rested orbs are bigger when Rested tint is on).
-- Retro: 8 cells of the burst's one cell size (every Retro orb is drawn on it, rested ones too).
local function visibleFor(db, normal)
    if db.orbShape == "retro" then
        return 8 * db.size
    end
    local rested = not normal and db.restedTint and ns.OrbShapes.k.restedSize or 1
    local share = normal and CLUSTER_VISIBLE[db.orbShape] or VISIBLE[db.orbShape] or VISIBLE.starlight
    return share * ns.OrbSize(db) * rested
end
ShapePreview.VisibleFor = visibleFor

-- Neighbour distance in px for the tidy layout: the visible disc plus a small gap (Retro: two cells).
local function spacingFor(db)
    local visible = visibleFor(db)
    if db.orbShape == "retro" then
        return visible + RETRO_GAP * visible / 8
    end
    return visible + math.max(GAP_MIN, GAP_K * visible)
end
ShapePreview.SpacingFor = spacingFor

-- An orb's half-extent in px (the biggest one: rested orbs are bigger when Rested tint is on; Retro's are not).
local function halfFor(db)
    if db.orbShape == "retro" then
        return RETRO_HALF_CELLS * db.size
    end
    local half = (HALF[db.orbShape] or HALF.starlight) * ns.OrbSize(db)
    return db.restedTint and half * ns.OrbShapes.k.restedSize or half
end

local function reachOf(points)
    local reachX, reachY = 1e-9, 1e-9
    for _, p in ipairs(points) do
        reachX, reachY = math.max(reachX, math.abs(p[1])), math.max(reachY, math.abs(p[2]))
    end
    return reachX, reachY
end

-- Retro's tidy unit in whole cells: the wanted one or the next that keeps every pair of drawn centres, after the
-- draw's whole-cell snap, at least RETRO_MIN_CELLS apart.
local function retroCells(points, db)
    local first = math.ceil(spacingFor(db) / db.size - 1e-6)
    for cells = first, first + 40 do
        local xs, ys, ok = {}, {}, true
        for i, p in ipairs(points) do
            xs[i], ys[i] = math.floor(p[1] * cells + 0.5), math.floor(p[2] * cells + 0.5)
        end
        for i = 1, #points - 1 do
            for j = i + 1, #points do
                local dx, dy = xs[i] - xs[j], ys[i] - ys[j]
                if dx * dx + dy * dy < RETRO_MIN_CELLS ^ 2 then
                    ok = false
                end
            end
        end
        if ok then
            return cells
        end
    end
    return first + 40
end

-- The wanted unit in px for a layout: spacingFor (Retro: whole cells, see retroCells), or for the cluster the visible
-- diameter.
local function wantFor(points, db, cluster)
    if cluster then
        return visibleFor(db, true) * (CLUSTER_SCALE[db.orbShape] or 1)
    elseif db.orbShape == "retro" then
        return retroCells(points, db) * db.size
    end
    return spacingFor(db)
end

-- The unit in px for a layout. Tidy: the wanted one (Pattern / Layout choose rows that fit the width). Cluster: the
-- wanted one, shrunk to fit the width if the pile is too wide (Retro on whole cells).
local function radiusFor(points, db, cluster)
    local want = wantFor(points, db, cluster)
    if not cluster then
        return want
    end
    local fit = (AREA_W / 2 - halfFor(db)) / (reachOf(points))
    local radius = math.max(0, math.min(want, fit))
    if db.orbShape == "retro" and radius < want then
        radius = math.floor(radius / db.size + 1e-6) * db.size
    end
    return radius
end
ShapePreview.RadiusFor = radiusFor -- (exposed for tests)

-- The orb area's height in px: tall enough for the layout at its unit plus the orbs' half-extent at the top and
-- bottom, at least AREA_H.
local function areaHeightFor(points, db, cluster)
    local _, reachY = reachOf(points)
    return math.max(AREA_H, math.ceil(2 * (reachY * radiusFor(points, db, cluster) + halfFor(db))))
end
ShapePreview.AreaHeightFor = areaHeightFor

-- The window's height in px for a layout: the header row, the orb area and the bottom padding.
local function heightFor(points, db, cluster)
    return TITLE_H + areaHeightFor(points, db, cluster) + PAD
end
ShapePreview.HeightFor = heightFor

-- n orbs in rows of at most k, honeycomb-interlocked like the ROWS layouts, top row first, centred, in unit offsets.
-- Alternating k and k-1 when that tiles n exactly, else balanced rows (the extra orbs on the top rows). Adjacent rows
-- are offset by half a unit sideways (one is shifted when both rows' counts have the same parity).
local function rowsLayout(n, k)
    local rows = math.ceil(n / k)
    local counts = {}
    if k >= 2 and rows >= 2 and n == math.ceil(rows / 2) * k + math.floor(rows / 2) * (k - 1) then
        for r = 1, rows do
            counts[r] = r % 2 == 1 and k or k - 1
        end
    else
        for r = 1, rows do
            counts[r] = math.floor(n / rows) + (r <= n % rows and 1 or 0)
        end
    end
    local points, shift, low, high = {}, 0, math.huge, -math.huge
    for r, count in ipairs(counts) do
        if r > 1 and counts[r - 1] % 2 == count % 2 then
            shift = shift <= 0 and shift + 0.5 or shift - 0.5
        end
        for c = 1, count do
            local x = c - (count + 1) / 2 + shift
            points[#points + 1] = { x, ((rows + 1) / 2 - r) * ROW_H }
            low, high = math.min(low, x), math.max(high, x)
        end
    end
    for _, p in ipairs(points) do
        p[1] = p[1] - (low + high) / 2
    end
    return points
end

-- The layout for n orbs of the current look as offsets (see Pattern). The tidy one is Pattern's, kept whenever its
-- width fits the area at the wanted unit; otherwise rows of fewer orbs (rowsLayout), as many as fit, so the window
-- grows taller instead. The cluster squeezes its unit instead (radiusFor).
function ShapePreview.Layout(n, cluster, db)
    local points = ShapePreview.Pattern(n, cluster)
    if cluster then
        return points
    end
    local half = halfFor(db)
    local function fits(pts)
        return 2 * reachOf(pts) * wantFor(pts, db) + 2 * half <= AREA_W + 1e-6
    end
    if fits(points) then
        return points
    end
    for k = math.max(1, math.min(n, math.floor((AREA_W - 2 * half) / spacingFor(db)) + 1)), 1, -1 do
        points = rowsLayout(n, k)
        if fits(points) then
            break
        end
    end
    return points
end

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
        tostring(db.sparkle), tostring(db.pulse), tostring(db.crackleSpeed), db.restedTint and 1 or 0,
        db.previewCluster and 1 or 0, red, green, blue, rested[1], rested[2], rested[3] }, "|")
end

-- ---------------------------------------------------------------- the window

local function build()
    local frame = ns.Preview.NewWindow(UIParent)
    window = frame
    frame:SetSize(WINDOW_W, WINDOW_H)
    frame:SetFrameStrata("DIALOG") -- above the settings panel (HIGH); the orbs (FULLSCREEN_DIALOG) draw over it
    pcall(function()
        frame:SetToplevel(true) -- raises on click
    end)
    frame:EnableMouse(true)
    ns.Preview.AddBackground(frame)
    local title = frame:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    title:SetPoint("TOPLEFT", frame, "TOPLEFT", PAD, -10)
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
    -- the Cluster tickbox in the top right corner, on the title's row (small, its label to its left)
    local check = CreateFrame("CheckButton", nil, frame, "UICheckButtonTemplate")
    check:SetSize(CHECK, CHECK)
    check:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -4, -7) -- its centre (y -17) sits on the title's (about -16)
    local text = frame:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    text:SetPoint("RIGHT", check, "LEFT", 0, 1)
    text:SetText("Cluster")
    pcall(check.SetHitRectInsets, check, -50, 0, 0, 0) -- the label is part of the target
    check:SetScript("OnEnter", function(self)
        pcall(function()
            GameTooltip:SetOwner(self, "ANCHOR_TOP")
            GameTooltip:SetText(CLUSTER_TIP, nil, nil, nil, nil, true)
        end)
    end)
    check:SetScript("OnLeave", function()
        pcall(function()
            GameTooltip:Hide()
        end)
    end)
    check:SetScript("OnClick", function(self)
        if ns.db then
            ns.db.previewCluster = self:GetChecked() and true or false
        end
        ShapePreview:Sync()
    end)
    ShapePreview.window, ShapePreview.box, ShapePreview.check = window, box, check
end

-- build threw part-way: hide the half-built window, drop every reference and remember the failure.
local function abandon()
    buildFailed = true
    if window then
        pcall(window.Hide, window)
    end
    window, box, looks = nil, nil, nil
    ShapePreview.window, ShapePreview.box, ShapePreview.check = nil, nil, nil
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
    local cluster = db.previewCluster == true
    local rested = db.restedTint and ShapePreview.RestedSlots(n, cluster) or {}
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
            if tex.xoShine then -- Retro Solid's shine overlay (Shapes.lua) lives on the body; its draw re-shows it
                tex.xoShine:Hide()
                tex.xoShine.xoShown = false
            end
        end
        if i <= n then
            local colour = rested[i] and restedColour or { red, green, blue }
            local st = { base = ns.OrbSize(db) } -- Retro's one cell size comes from base
            box.st[i] = st
            setup(box.tex[first + 1], box.tex[first + 2], box.tex[first + 3], st, colour[1], colour[2], colour[3])
        else
            box.st[i] = nil
        end
    end
    box.pattern, box.rested, box.cluster = ShapePreview.Layout(n, cluster, db), rested, cluster
    window:SetSize(WINDOW_W, heightFor(box.pattern, db, cluster)) -- grows to fit (the test target hangs under it)
end

local function draw(db)
    local shape = ns.OrbShapes.by[db.orbShape]
    local draws = shape and shape.draw or starlightDraw
    local alpha = db.opacity / 100
    local restedSize = ns.OrbShapes.k.restedSize
    local base = ns.OrbSize(db)
    local radius = radiusFor(box.pattern, db, box.cluster)
    for i = 1, box.n do
        local first = (i - 1) * 3
        local size = base * (box.rested[i] and restedSize or 1)
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
    ShapePreview.check:SetChecked(db.previewCluster == true)
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
        pcall(window.Raise, window) -- in front of other DIALOG frames
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

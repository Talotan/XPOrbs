-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Orb preview for the settings panel: a small box above the panel's footer showing five stationary orbs of the current
-- shape (three normal, two rested), with the shape's own animation running (Starlight's spinning sparkle, Retro's
-- blinking twinkle on its grid, Globe's breathing and glint, Crackle's bolt swaps), no trail. It is drawn by the same
-- shape code as real orbs (the shape's setup and draw with the box as the frame), from 15 textures of its own, and it
-- follows the shape, size, opacity, pulsing and colour settings as they change.
--
-- A testing aid for now: it only exists while db.debug is on. To make it public later, drop the debug test in
-- ShapePreview:Sync (and mention it in the README). The box is built on first need, its OnUpdate runs only while the
-- panel is shown (Options.lua calls Stop from the panel's OnHide), and every call here is made under pcall by
-- Options.lua, so a panel built before Orbs.lua and Shapes.lua are ready never errors.

local ShapePreview = {}
ns.ShapePreview = ShapePreview

local BOX_W, BOX_H = 264, 86 -- px
local TITLE_H = 18 -- px at the top of the box for the "Preview" title
local ORBS, RESTED_FROM = 5, 4 -- orbs 4 and 5 are the rested ones
local ORB_TEX = "Interface\\AddOns\\XPOrbs\\media\\orb"
local SPARKLE_TEX = "Interface\\AddOns\\XPOrbs\\media\\sparkle"
local TWO_PI = math.pi * 2
local random = math.random

local box -- the box frame, once built; box.tex holds its 15 textures, box.st the per-orb shape state
local looks -- what the orbs are currently set up with (see signature), to spot a change
local errSeen = false

local function lerp(channel, toward, amount)
    return channel + (toward - channel) * amount
end

-- Starlight is drawn inline in Orbs.lua, so the box has its own small copy of that drawing (the k table of
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

-- What the orbs' set-up depends on: when it changes the five orbs are set up again.
local function signature(db, red, green, blue)
    local rested = db.restedColor
    return table.concat({ db.orbShape, db.size, db.restedTint and 1 or 0, red, green, blue, rested[1], rested[2],
        rested[3] }, "|")
end

local function build(panel)
    box = CreateFrame("Frame", nil, panel)
    box:SetSize(BOX_W, BOX_H)
    box:SetPoint("BOTTOMLEFT", panel, "BOTTOMLEFT", ns.Options.rightX - BOX_W, ns.Options.footerY + 4)
    pcall(box.SetClipsChildren, box, true) -- a large orb stays inside the box
    local back = box:CreateTexture(nil, "BACKGROUND")
    back:SetAllPoints(box)
    back:SetColorTexture(0.04, 0.05, 0.09, 0.85)
    local title = box:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    title:SetPoint("TOPLEFT", box, "TOPLEFT", 6, -4)
    title:SetJustifyH("LEFT")
    title:SetText("Preview")
    box.title = title
    box.tex, box.st, box.time = {}, {}, 0
    for i = 1, ORBS * 3 do
        local tex = box:CreateTexture(nil, "ARTWORK")
        tex:SetAlpha(0)
        tex:Hide()
        tex.xoShown = false
        box.tex[i] = tex
    end
    ShapePreview.box = box
end

-- Sets the five orbs up for the current settings.
local function configure(db, red, green, blue)
    local shape = ns.OrbShapes.by[db.orbShape] -- nil: Starlight
    local setup = shape and shape.setup or starlightSetup
    local restedColour = db.restedColor
    for i = 1, ORBS do
        local rested = db.restedTint and i >= RESTED_FROM
        local colour = rested and restedColour or { red, green, blue }
        local first = (i - 1) * 3
        local under, body, spark = box.tex[first + 1], box.tex[first + 2], box.tex[first + 3]
        for j = 1, 3 do
            local tex = box.tex[first + j]
            tex:SetTexCoord(0, 1, 0, 1) -- (the last shape may have cropped or rotated it)
            tex:SetAlpha(0)
            tex:Hide()
            tex.xoShown = false
        end
        local st = { base = db.size } -- Retro's one cell size comes from base
        box.st[i] = st
        setup(under, body, spark, st, colour[1], colour[2], colour[3])
    end
end

local function draw(db)
    local shape = ns.OrbShapes.by[db.orbShape]
    local draws = shape and shape.draw or starlightDraw
    local alpha = db.opacity / 100
    local restedSize = ns.OrbShapes.k.restedSize
    local step = (BOX_W - 24) / ORBS
    for i = 1, ORBS do
        local first = (i - 1) * 3
        local size = db.size * (db.restedTint and i >= RESTED_FROM and restedSize or 1)
        draws(box.st[i], box.time, box, box.tex[first + 1], box.tex[first + 2], box.tex[first + 3],
            (i - (ORBS + 1) / 2) * step, -TITLE_H / 2, size, alpha)
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

-- Keeps the panel's scroll area clear of the box while it is up (and puts it back after).
local function makeRoom(on)
    local scroll = ns.Options.scroll
    if not scroll then
        return
    end
    scroll:ClearAllPoints()
    scroll:SetPoint("TOPLEFT", ns.Options.panel, "TOPLEFT", 0, -40)
    scroll:SetPoint("BOTTOMRIGHT", ns.Options.panel, "BOTTOMRIGHT", -28, ns.Options.footerY + (on and BOX_H + 8 or 0))
end

-- Called by Options.lua after every change and when the panel is shown: shows the box while db.debug is on (building
-- it on first need) and sets the orbs up again when the shape, size or colours changed; hides it otherwise.
function ShapePreview:Sync()
    local db = ns.db
    local want = db and db.debug and ns.Options and ns.Options.panel and ns.OrbShapes and ns.OrbShapes.host
        and ns.Orbs and ns.Orbs.NormalRGB
    if not want then
        self:Stop()
        if box and box.up then
            box.up = false
            box:Hide()
            makeRoom(false)
        end
        return
    end
    if not box then
        build(ns.Options.panel)
    end
    if not box.up then
        box.up = true
        box:Show()
        makeRoom(true)
    end
    local red, green, blue = ns.Orbs.NormalRGB(db)
    local now = signature(db, red, green, blue)
    if now ~= looks then
        looks = now
        configure(db, red, green, blue)
    end
    box:SetScript("OnUpdate", onUpdate)
end

-- Ends the animation (the panel was hidden, or the box is off).
function ShapePreview:Stop()
    if box then
        box:SetScript("OnUpdate", nil)
    end
end

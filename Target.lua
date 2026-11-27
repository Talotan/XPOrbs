-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Where the orbs fly to: the fill edge of the XP bar, in UIParent coordinates. Only reads Blizzard frames. The frame
-- picker (/xporbs pick) is in Picker.lua, which shares the helpers it needs through Target.internal.

local Target = {}
ns.Target = Target

local OrbMath = ns.OrbMath

local BAR_FRAMES = { "MainStatusTrackingBarContainer", "StatusTrackingBarManager", "MainMenuExpBar" }
local FALLBACK_Y = 20
local lastRect = { left = 0, bottom = 0, w = 0, h = 0 } -- the one table Target.lastRect points at (no garbage)

Target.lastName = nil -- frame name used by the last GetDestination() call (nil on fallback)
Target.lastSource = nil -- id of the bar source that supplied it (nil for a pick, a Blizzard container or the fallback)
Target.lastSourceLabel = nil -- that source's display label
Target.lastSourceViaPick = false -- true when a saved pick was redirected to its source (see PICK_ALIASES)
Target.lastOk = false
Target.lastXP, Target.lastXPMax = nil, nil -- the last readable XP pair: aimed at when the current reading is secret

local function readable(v)
    return not issecretvalue or not issecretvalue(v)
end

local function num(v)
    return type(v) == "number" and readable(v)
end

local function isVisible(f)
    if f.IsVisible then
        return f:IsVisible()
    end
    return f:IsShown()
end

-- How full a StatusBar is as the bar itself draws it: frac, vertical, reverse. nil when f isn't a StatusBar or any
-- reading is missing or secret (the caller then falls back to the XP numbers). Never throws.
local function statusFill(f)
    if not (f.GetMinMaxValues and f.GetValue and f.GetOrientation and f.GetReverseFill) then
        return nil
    end
    local okMinMax, lo, hi = pcall(f.GetMinMaxValues, f)
    local okValue, v = pcall(f.GetValue, f)
    local okOrient, orient = pcall(f.GetOrientation, f)
    local okReverse, rev = pcall(f.GetReverseFill, f)
    if not (okMinMax and okValue and okOrient and okReverse and num(lo) and num(hi) and num(v) and hi > lo) then
        return nil
    end
    if type(orient) ~= "string" or not readable(orient) or type(rev) ~= "boolean" or not readable(rev) then
        return nil
    end
    return (v - lo) / (hi - lo), orient == "VERTICAL", rev
end

-- Fill-edge point of a plain (non-StatusBar) frame the player marked as vertical (glow shape "vertical"): the XP
-- fraction measured from the bottom up. Guarded like OrbMath.FillEdge, so an unreadable XP pair aims at the bottom.
local function verticalFillEdge(left, bottom, w, h, xp, xpMax)
    local frac = 0
    if num(xp) and num(xpMax) and xpMax > 0 then
        frac = xp / xpMax
    end
    return OrbMath.StatusFill(left, bottom, w, h, frac, true, false)
end

-- The point of the bar frame the orbs aim at (db.targetAnchor), or nil for the default (the fill edge, or the centre of
-- a round frame). GetDestination sets it per call: the portrait is never aimed at a corner, so it clears it there.
local aimAnchor
-- The rect of the frame the last successful frameEdge measured; GetDestination copies it into Target.lastRect.
local measured = { left = 0, bottom = 0, w = 0, h = 0 }

-- Returns x, y, w, h (UIParent units) and whether the point came from a vertical bar: a vertical StatusBar, or any
-- other frame while the glow shape is "vertical".
local function frameEdge(f, xp, xpMax, centre)
    if not isVisible(f) then
        return nil
    end
    local left, bottom, w, h = f:GetLeft(), f:GetBottom(), f:GetWidth(), f:GetHeight()
    if not (num(left) and num(bottom) and num(w) and num(h)) or w <= 0 then
        return nil
    end
    local frameScale, parentScale = f:GetEffectiveScale(), UIParent:GetEffectiveScale()
    if not (num(frameScale) and num(parentScale)) or parentScale == 0 then
        return nil
    end
    left, bottom = OrbMath.ToUIParent(left, bottom, frameScale, parentScale)
    w, h = OrbMath.ToUIParent(w, h, frameScale, parentScale)
    measured.left, measured.bottom, measured.w, measured.h = left, bottom, w, h
    if aimAnchor then
        -- a chosen corner, edge or centre replaces the fill edge and the round centre, XP readable or not; the vertical
        -- flag (it picks the flash shape) is what it would have been without the anchor
        local ax, ay = OrbMath.AnchorPoint(left, bottom, w, h, aimAnchor)
        local isVertical
        if not centre then
            local fillFrac, fillVertical = statusFill(f)
            isVertical = fillFrac and fillVertical or (not fillFrac and ns.db and ns.db.glowShape == "vertical") or nil
        end
        return ax, ay, w, h, isVertical
    end
    if centre then
        return left + w / 2, bottom + h / 2, w, h
    end
    local frac, vertical, reverse = statusFill(f)
    if frac then
        local sx, sy = OrbMath.StatusFill(left, bottom, w, h, frac, vertical, reverse)
        return sx, sy, w, h, vertical
    end
    if ns.db and ns.db.glowShape == "vertical" then
        local sx, sy = verticalFillEdge(left, bottom, w, h, xp, xpMax)
        return sx, sy, w, h, true
    end
    local x, y = OrbMath.FillEdge(left, bottom, w, h, xp, xpMax)
    return x, y, w, h
end

local function tryObject(f, xp, xpMax, centre)
    if type(f) ~= "table" then
        return nil
    end
    local ok, x, y, w, h, vertical = pcall(frameEdge, f, xp, xpMax, centre)
    if ok and num(x) and num(y) then
        return x, y, w, h, vertical
    end
    return nil
end

local function tryFrame(name, xp, xpMax, centre)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    return tryObject(_G[name], xp, xpMax, centre)
end

-- Bar sources: where other UI suites keep their XP bar. Each resolve() returns a frame or nil and runs under pcall; the
-- frame only counts if tryObject can measure it (visible, usable geometry). Tried in this order after the user's
-- pick and before Blizzard's own containers. frameNames lists the globals the frame may be registered under, used for
-- Target.lastName when the frame itself can't report a name.
local function frameIsVisible(frame)
    if type(frame) ~= "table" then
        return false
    end
    local ok, visible = pcall(isVisible, frame)
    return ok and visible == true
end

-- Blizzard's own experience StatusBar: StatusTrackingBarManager keeps the bars in containers, and the one that carries
-- the exhaustion (rested) overlay is the XP bar, wherever the manager put it (a watched faction shown as the
-- experience bar takes the main container and moves XP to the secondary one).
local function blizzardExperienceBar()
    local manager = _G.StatusTrackingBarManager
    local containers = type(manager) == "table" and manager.barContainers
    if type(containers) ~= "table" then
        return nil
    end
    local firstFound
    for _, container in pairs(containers) do
        local bars = type(container) == "table" and container.bars
        if type(bars) == "table" then
            for _, bar in pairs(bars) do
                if type(bar) == "table" and (bar.ExhaustionTick or bar.ExhaustionLevelFillBar) then
                    local statusBar = type(bar.StatusBar) == "table" and bar.StatusBar or bar
                    if frameIsVisible(statusBar) then
                        return statusBar
                    end
                    firstFound = firstFound or statusBar
                end
            end
        end
    end
    return firstFound
end

local BAR_SOURCES = {
    {
        id = "ellesmere",
        label = "EllesmereUI",
        frameNames = { "EllesmereEAB_XPBar_Bar" },
        resolve = function()
            return _G.EllesmereEAB_XPBar_Bar
        end,
    },
    {
        id = "flare",
        label = "FlareUI",
        resolve = function()
            local root = _G.FlareUI_XPBar
            local leftBar = type(root) == "table" and root.Left
            -- the left bar shows reputation instead of XP at max level
            if type(leftBar) == "table" and type(leftBar.info) == "table" and leftBar.info.kind == "xp" then
                return leftBar
            end
            return nil
        end,
    },
    {
        id = "daylight",
        label = "DaylightUI",
        resolve = function()
            local daylight = _G.DaylightUI
            if type(daylight) ~= "table" or type(daylight.GetModule) ~= "function" then
                return nil
            end
            local infoPanel = daylight:GetModule("InfoPanel")
            if type(infoPanel) == "table" and infoPanel.enabled and type(infoPanel.ns) == "table"
                and type(infoPanel.ns.XP) == "table" then
                return infoPanel.ns.XP.bar
            end
            return nil
        end,
    },
    {
        id = "smoothxp",
        label = "Smooth Experience Bar",
        frameNames = { "SmoothExperienceBarFrame", "SmoothExperienceBarDefaultFrame" },
        resolve = function()
            local mainFrame = _G.SmoothExperienceBarFrame
            if frameIsVisible(mainFrame) then
                return mainFrame
            end
            return _G.SmoothExperienceBarDefaultFrame
        end,
    },
    {
        id = "enhanceqol",
        label = "EnhanceQoL",
        frameNames = { "EQOL_XPBar" },
        resolve = function()
            return _G.EQOL_XPBar
        end,
    },
    { id = "blizzard", label = "Blizzard XP bar", resolve = blizzardExperienceBar },
}

local SOURCE_BY_ID = {}
for _, source in ipairs(BAR_SOURCES) do
    SOURCE_BY_ID[source.id] = source
end

-- Containers that players saved with /xporbs pick on these UIs, mapped to the source that knows the real bar. The
-- saved variable is left alone; GetDestination just prefers the source while it resolves.
local PICK_ALIASES = {
    DaylightUIInfoPanel = "daylight",
    DaylightUIInfoPanelBody = "daylight",
    FlareUI_XPBar = "flare",
    EllesmereEAB_XPBar = "ellesmere",
}

-- The name Target.lastName reports for a source's frame: its own GetName(), else the listed global that is this
-- frame, else the source label. Runs every frame while orbs fly, so it allocates nothing (no closures, no tables).
local NO_NAMES = {}

local function sourceFrameName(source, frame)
    if type(frame.GetName) == "function" then
        local ok, frameName = pcall(frame.GetName, frame)
        if ok and type(frameName) == "string" and readable(frameName) and frameName ~= "" then
            return frameName
        end
    end
    local globalNames = source.frameNames or NO_NAMES
    for i = 1, #globalNames do
        if rawequal(rawget(_G, globalNames[i]), frame) then
            return globalNames[i]
        end
    end
    return source.label
end

-- Same as tryObject for a bar source: x, y, w, h, vertical, frameName; nil when the resolver fails, throws, or the
-- frame it returns can't be measured.
local function trySource(source, xp, xpMax, centre)
    if not source then
        return nil
    end
    local okResolve, frame = pcall(source.resolve)
    if not okResolve or type(frame) ~= "table" then
        return nil
    end
    local x, y, w, h, vertical = tryObject(frame, xp, xpMax, centre)
    if not x then
        return nil
    end
    return x, y, w, h, vertical, sourceFrameName(source, frame)
end

-- What a saved pick (db.targetFrame) means, parsed once per saved string and cached so the per-frame lookup does no
-- string work: "@id" names a bar source, "Root.key.key" is a path of fields below a global frame, anything else is a
-- plain global frame name.
local PLAIN_PICK = { kind = "name" }
local PARSED_PICKS = {}

local function parsePick(saved)
    local cached = PARSED_PICKS[saved]
    if cached then
        return cached
    end
    local parsed = PLAIN_PICK
    if string.sub(saved, 1, 1) == "@" then
        local source = SOURCE_BY_ID[string.lower(string.sub(saved, 2))]
        if source then
            parsed = { kind = "source", source = source }
        end
    elseif string.find(saved, ".", 1, true) and not string.find(saved, "^%.") and not string.find(saved, "%.$")
        and not string.find(saved, "%.%.") then
        local keys = {}
        for key in string.gmatch(saved, "[^.]+") do
            keys[#keys + 1] = key
        end
        parsed = { kind = "path", keys = keys, whole = saved }
    end
    PARSED_PICKS[saved] = parsed
    return parsed
end

-- The object a parsed path points at: _G[keys[1]][keys[2]]..., read raw so no metamethod runs. Falls back to a global
-- whose name really contains dots. Allocates nothing; the result is unchecked (the caller measures it under pcall).
local function resolvePath(parsed)
    local keys = parsed.keys
    local node = rawget(_G, keys[1])
    for i = 2, #keys do
        if type(node) ~= "table" then
            node = nil
            break
        end
        node = rawget(node, keys[i])
    end
    if node == nil then
        node = rawget(_G, parsed.whole)
    end
    return node
end

-- The bar source a saved "@id" pick names (nil for anything else), and the text to show for a saved pick.
function Target.PickSource(saved)
    if type(saved) ~= "string" then
        return nil
    end
    local parsed = parsePick(saved)
    return parsed.kind == "source" and parsed.source or nil
end

function Target.PickLabel(saved)
    local source = Target.PickSource(saved)
    return source and source.label or saved
end

local PORTRAIT_NAME = "PlayerPortrait" -- Target.lastName when the player portrait was the destination

-- The player portrait frame to aim at: PlayerFrame.PlayerFrameContainer.PlayerPortrait (pcall'd walk), else the
-- PlayerPortrait global, else PlayerFrame itself. Returns the candidates in that order (some may be nil).
local function playerPortraitCandidates()
    local ok, port = pcall(function()
        local pf = _G.PlayerFrame
        local container = type(pf) == "table" and pf.PlayerFrameContainer or nil
        return type(container) == "table" and container.PlayerPortrait or nil
    end)
    return ok and port or nil, _G.PlayerPortrait, _G.PlayerFrame
end

-- At max level the XP bar is idle, so with no frame picked by the user the orbs fly to the player portrait instead.
-- A user's pick (db.targetFrame) always wins. Never throws.
function Target:PortraitMode()
    local saved = ns.db
    if saved and type(saved.targetFrame) == "string" and saved.targetFrame ~= "" then
        return false
    end
    return ns.AtMaxLevel() == true
end

-- Returns x, y, ok. ok is false when no bar frame was usable and the bottom-centre fallback was returned.
-- With a secret XP reading the last readable pair is used (cached in Target.lastXP / lastXPMax); with none, the frame
-- centre.
-- Target.lastW / lastH are the destination frame's size in UIParent units (nil on the fallback); Target.lastRect is its
-- { left, bottom, w, h } in the same units (nil on the fallback, one table reused between calls).
-- db.targetAnchor (not "fill") aims at that point of the bar frame instead of the fill edge or the centre; the portrait
-- ignores it.
-- centre = true aims at the middle of the frame instead of the XP fill edge (a round target such as a portrait has
-- no fill edge).
-- db.glowOffsetX / glowOffsetY (UIParent px) are added to every result, the fallback included: the offset is the
-- user's "land here" nudge, so it moves the landing point wherever it would otherwise be. lastW / lastH are unaffected.
-- portrait = true (the caller decided once per burst, see Target:PortraitMode) tries the player portrait first and aims
-- at its centre; nil asks PortraitMode itself, so only per-frame callers should pass it.
function Target:GetDestination(centre, portrait)
    if portrait == nil then
        portrait = self:PortraitMode()
    end
    local okxp, xp = pcall(UnitXP, "player")
    local okmax, xpMax = pcall(UnitXPMax, "player")
    if okxp and okmax and num(xp) and num(xpMax) then
        self.lastXP, self.lastXPMax = xp, xpMax
    else
        -- unreadable (secret) right now: aim where the bar's fill edge was last known to be, else the frame centre
        xp, xpMax = self.lastXP, self.lastXPMax
        if xp == nil or xpMax == nil then
            centre = true
        end
    end
    local x, y, frameW, frameH, frameVertical
    local name, usedSource, viaPick
    local anchor = ns.db and ns.db.targetAnchor
    if type(anchor) ~= "string" or anchor == "fill" then
        anchor = nil
    end
    aimAnchor = nil
    if portrait then
        local portrait1, portrait2, portrait3 = playerPortraitCandidates()
        x, y, frameW, frameH, frameVertical = tryObject(portrait1, xp, xpMax, true)
        if not x then
            x, y, frameW, frameH, frameVertical = tryObject(portrait2, xp, xpMax, true)
        end
        if not x then
            x, y, frameW, frameH, frameVertical = tryObject(portrait3, xp, xpMax, true)
        end
        name = PORTRAIT_NAME
        if not x then
            -- no usable portrait: the usual bar frames, with the shape the user chose (the caller's `centre` was
            -- forced on for the portrait)
            centre = (ns.db ~= nil and ns.db.glowShape == "round") or xp == nil or xpMax == nil
        end
    else
        aimAnchor = anchor
        local picked = ns.db and ns.db.targetFrame
        local parsed = type(picked) == "string" and parsePick(picked) or PLAIN_PICK
        if parsed.kind == "source" then
            local sourceName
            x, y, frameW, frameH, frameVertical, sourceName = trySource(parsed.source, xp, xpMax, centre)
            if x then
                name, usedSource = sourceName, parsed.source
            end
        elseif parsed.kind == "path" then
            name = picked
            x, y, frameW, frameH, frameVertical = tryObject(resolvePath(parsed), xp, xpMax, centre)
        else
            local aliasSource = type(picked) == "string" and SOURCE_BY_ID[PICK_ALIASES[picked]] or nil
            if aliasSource then
                local sourceName
                x, y, frameW, frameH, frameVertical, sourceName = trySource(aliasSource, xp, xpMax, centre)
                if x then
                    name, usedSource, viaPick = sourceName, aliasSource, true
                end
            end
            if not x then
                name = picked
                x, y, frameW, frameH, frameVertical = tryFrame(name, xp, xpMax, centre)
            end
        end
    end
    aimAnchor = anchor -- no portrait aim from here on: the bar frames below take the chosen point
    if not x then
        for i = 1, #BAR_SOURCES do
            local sourceName
            x, y, frameW, frameH, frameVertical, sourceName = trySource(BAR_SOURCES[i], xp, xpMax, centre)
            if x then
                name, usedSource = sourceName, BAR_SOURCES[i]
                break
            end
        end
    end
    if not x then
        for i = 1, #BAR_FRAMES do
            name = BAR_FRAMES[i]
            x, y, frameW, frameH, frameVertical = tryFrame(name, xp, xpMax, centre)
            if x then
                break
            end
        end
    end
    if x then
        self.lastName, self.lastOk = name, true
        self.lastW, self.lastH, self.lastVertical = frameW, frameH, frameVertical == true
        local rect = lastRect
        rect.left, rect.bottom, rect.w, rect.h = measured.left, measured.bottom, measured.w, measured.h
        self.lastRect = rect
        self.lastSource, self.lastSourceLabel = usedSource and usedSource.id, usedSource and usedSource.label
        self.lastSourceViaPick = viaPick == true
        x, y = OrbMath.ApplyOffset(x, y, ns.db and ns.db.glowOffsetX, ns.db and ns.db.glowOffsetY)
        return x, y, true
    end
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    self.lastName, self.lastOk, self.lastW, self.lastH, self.lastVertical = nil, false, nil, nil, false
    self.lastRect = nil
    self.lastSource, self.lastSourceLabel, self.lastSourceViaPick = nil, nil, false
    local fx, fy = OrbMath.ApplyOffset(okw and num(w) and w / 2 or 0, FALLBACK_Y, ns.db and ns.db.glowOffsetX,
        ns.db and ns.db.glowOffsetY)
    return fx, fy, false
end

local function portraitOf(f)
    local container = f.TargetFrameContainer
    return type(container) == "table" and container.Portrait or nil
end

-- Centre of a frame in UIParent space, or nil when unreadable. Visibility is NOT required: a hidden frame keeps its
-- laid-out rect (the target frame is hidden once the mob is deselected on death).
local function frameCentre(f)
    if type(f) ~= "table" then
        return nil
    end
    local cx, cy = f:GetCenter()
    local frameScale, parentScale = f:GetEffectiveScale(), UIParent:GetEffectiveScale()
    if not (num(cx) and num(cy) and num(frameScale) and num(parentScale)) or parentScale == 0 then
        return nil
    end
    return OrbMath.ToUIParent(cx, cy, frameScale, parentScale)
end

Target.lastFrameX, Target.lastFrameY = nil, nil -- last good target-frame centre (UIParent space)

-- Centre of the Blizzard target unit frame (portrait first) in UIParent space. Returns the last good result when
-- nothing is measurable now, nil only if it has never worked. Never throws.
function Target:TargetFrameOrigin()
    local tf = _G.TargetFrame
    local okTf, port = pcall(function()
        return type(tf) == "table" and portraitOf(tf) or nil
    end)
    local cands = { okTf and port or nil, _G.TargetFramePortrait, tf }
    for i = 1, 3 do
        local f = cands[i]
        if f then
            local ok, x, y = pcall(frameCentre, f)
            if ok and num(x) and num(y) then
                self.lastFrameX, self.lastFrameY = x, y
                return x, y
            end
        end
    end
    if self.lastFrameX then
        return self.lastFrameX, self.lastFrameY
    end
    return nil
end

-- Where the popstream stream starts for a kill: the estimate (ex, ey) whenever there is one, else the target frame
-- portrait (only when there is no estimate). Returns x, y, "estimate"|"targetframe", or nil when neither applies.
function Target:StreamOrigin(ex, ey)
    local fx, fy
    if type(ex) ~= "number" or type(ey) ~= "number" then
        fx, fy = self:TargetFrameOrigin()
    end
    return ns.MobEstimate.PickOrigin(ex, ey, fx, fy)
end

-- The nameplate frame of the current target, or nil. Only ever used as an anchor, never measured.
function Target:TargetPlate()
    if not (C_NamePlate and C_NamePlate.GetNamePlateForUnit) then
        return nil
    end
    local ok, plate = pcall(C_NamePlate.GetNamePlateForUnit, "target")
    if ok and plate and readable(plate) and type(plate) == "table" then
        return plate
    end
    return nil
end

-- What Picker.lua (loaded right after this file) shares with the rest of this file: read-only helpers and the
-- bar-source list, taken from here so there is one copy. Nothing mutable is shared.
Target.internal = {
    readable = readable,
    num = num,
    isVisible = isVisible,
    frameIsVisible = frameIsVisible,
    BAR_SOURCES = BAR_SOURCES,
    parsePick = parsePick,
    resolvePath = resolvePath,
}

table.insert(ns.statusProviders, function()
    local picked = ns.db and ns.db.targetFrame
    Target:GetDestination()
    return string.format("xp bar frame: %s, using %s", picked and ("picked " .. Target.PickLabel(picked)) or "auto",
        Target.lastSourceLabel or Target.lastName or "bottom-centre fallback")
end)

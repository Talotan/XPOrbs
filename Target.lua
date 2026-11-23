-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Where the orbs fly to: the fill edge of the XP bar, in UIParent coordinates. Only reads Blizzard frames.

local Target = {}
ns.Target = Target

local OrbMath = ns.OrbMath

local BAR_FRAMES = { "MainStatusTrackingBarContainer", "StatusTrackingBarManager", "MainMenuExpBar" }
local FALLBACK_Y = 20

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

-- Fill-edge point (or, with centre, the middle) of a frame in UIParent space plus its size, or nil if it is hidden or
-- its geometry is unusable.
-- How full a StatusBar is as the bar itself draws it: frac, vertical, reverse. nil when f isn't a StatusBar or any
-- reading is missing or secret (the caller then falls back to the XP numbers). Never throws.
local function statusFill(f)
    if not (f.GetMinMaxValues and f.GetValue and f.GetOrientation and f.GetReverseFill) then
        return nil
    end
    local okm, lo, hi = pcall(f.GetMinMaxValues, f)
    local okv, v = pcall(f.GetValue, f)
    local oko, orient = pcall(f.GetOrientation, f)
    local okr, rev = pcall(f.GetReverseFill, f)
    if not (okm and okv and oko and okr and num(lo) and num(hi) and num(v) and hi > lo) then
        return nil
    end
    if type(orient) ~= "string" or not readable(orient) or type(rev) ~= "boolean" or not readable(rev) then
        return nil
    end
    return (v - lo) / (hi - lo), orient == "VERTICAL", rev
end

-- Returns x, y, w, h (UIParent units) and whether the point came from a vertical StatusBar.
local function frameEdge(f, xp, xpMax, centre)
    if not isVisible(f) then
        return nil
    end
    local l, b, w, h = f:GetLeft(), f:GetBottom(), f:GetWidth(), f:GetHeight()
    if not (num(l) and num(b) and num(w) and num(h)) or w <= 0 then
        return nil
    end
    local fs, ps = f:GetEffectiveScale(), UIParent:GetEffectiveScale()
    if not (num(fs) and num(ps)) or ps == 0 then
        return nil
    end
    l, b = OrbMath.ToUIParent(l, b, fs, ps)
    w, h = OrbMath.ToUIParent(w, h, fs, ps)
    if centre then
        return l + w / 2, b + h / 2, w, h
    end
    local frac, vertical, reverse = statusFill(f)
    if frac then
        local sx, sy = OrbMath.StatusFill(l, b, w, h, frac, vertical, reverse)
        return sx, sy, w, h, vertical
    end
    local x, y = OrbMath.FillEdge(l, b, w, h, xp, xpMax)
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
        local c = type(pf) == "table" and pf.PlayerFrameContainer or nil
        return type(c) == "table" and c.PlayerPortrait or nil
    end)
    return ok and port or nil, _G.PlayerPortrait, _G.PlayerFrame
end

-- At max level the XP bar is idle, so with no frame picked by the user the orbs fly to the player portrait instead.
-- A user's pick (db.targetFrame) always wins. Never throws.
function Target:PortraitMode()
    local d = ns.db
    if d and type(d.targetFrame) == "string" and d.targetFrame ~= "" then
        return false
    end
    return ns.AtMaxLevel() == true
end

-- Returns x, y, ok. ok is false when no bar frame was usable and the bottom-centre fallback was returned.
-- With a secret XP reading the last readable pair is used (cached in Target.lastXP / lastXPMax); with none, the frame
-- centre.
-- Target.lastW / lastH are the destination frame's size in UIParent units (nil on the fallback).
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
    local x, y, fw, fh, fv
    local name, usedSource, viaPick
    if portrait then
        local c1, c2, c3 = playerPortraitCandidates()
        x, y, fw, fh, fv = tryObject(c1, xp, xpMax, true)
        if not x then
            x, y, fw, fh, fv = tryObject(c2, xp, xpMax, true)
        end
        if not x then
            x, y, fw, fh, fv = tryObject(c3, xp, xpMax, true)
        end
        name = PORTRAIT_NAME
        if not x then
            -- no usable portrait: the usual bar frames, with the shape the user chose (the caller's `centre` was
            -- forced on for the portrait)
            centre = (ns.db ~= nil and ns.db.glowShape == "round") or xp == nil or xpMax == nil
        end
    else
        local picked = ns.db and ns.db.targetFrame
        local parsed = type(picked) == "string" and parsePick(picked) or PLAIN_PICK
        if parsed.kind == "source" then
            local sourceName
            x, y, fw, fh, fv, sourceName = trySource(parsed.source, xp, xpMax, centre)
            if x then
                name, usedSource = sourceName, parsed.source
            end
        elseif parsed.kind == "path" then
            name = picked
            x, y, fw, fh, fv = tryObject(resolvePath(parsed), xp, xpMax, centre)
        else
            local aliasSource = type(picked) == "string" and SOURCE_BY_ID[PICK_ALIASES[picked]] or nil
            if aliasSource then
                local sourceName
                x, y, fw, fh, fv, sourceName = trySource(aliasSource, xp, xpMax, centre)
                if x then
                    name, usedSource, viaPick = sourceName, aliasSource, true
                end
            end
            if not x then
                name = picked
                x, y, fw, fh, fv = tryFrame(name, xp, xpMax, centre)
            end
        end
    end
    if not x then
        for i = 1, #BAR_SOURCES do
            local sourceName
            x, y, fw, fh, fv, sourceName = trySource(BAR_SOURCES[i], xp, xpMax, centre)
            if x then
                name, usedSource = sourceName, BAR_SOURCES[i]
                break
            end
        end
    end
    if not x then
        for i = 1, #BAR_FRAMES do
            name = BAR_FRAMES[i]
            x, y, fw, fh, fv = tryFrame(name, xp, xpMax, centre)
            if x then
                break
            end
        end
    end
    if x then
        self.lastName, self.lastOk, self.lastW, self.lastH, self.lastVertical = name, true, fw, fh, fv == true
        self.lastSource, self.lastSourceLabel = usedSource and usedSource.id, usedSource and usedSource.label
        self.lastSourceViaPick = viaPick == true
        x, y = OrbMath.ApplyOffset(x, y, ns.db and ns.db.glowOffsetX, ns.db and ns.db.glowOffsetY)
        return x, y, true
    end
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    self.lastName, self.lastOk, self.lastW, self.lastH, self.lastVertical = nil, false, nil, nil, false
    self.lastSource, self.lastSourceLabel, self.lastSourceViaPick = nil, nil, false
    local fx, fy = OrbMath.ApplyOffset(okw and num(w) and w / 2 or 0, FALLBACK_Y, ns.db and ns.db.glowOffsetX,
        ns.db and ns.db.glowOffsetY)
    return fx, fy, false
end

local function portraitOf(f)
    local c = f.TargetFrameContainer
    return type(c) == "table" and c.Portrait or nil
end

-- Centre of a frame in UIParent space, or nil when unreadable. Visibility is NOT required: a hidden frame keeps its
-- laid-out rect (the target frame is hidden once the mob is deselected on death).
local function frameCentre(f)
    if type(f) ~= "table" then
        return nil
    end
    local cx, cy = f:GetCenter()
    local fs, ps = f:GetEffectiveScale(), UIParent:GetEffectiveScale()
    if not (num(cx) and num(cy) and num(fs) and num(ps)) or ps == 0 then
        return nil
    end
    return OrbMath.ToUIParent(cx, cy, fs, ps)
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
    local ok, p = pcall(C_NamePlate.GetNamePlateForUnit, "target")
    if ok and p and readable(p) and type(p) == "table" then
        return p
    end
    return nil
end

-- ---------------------------------------------------------------- /xporbs pick

local PICK_TIMEOUT = 15 -- seconds the picker stays armed
local PICK_DEPTH = 40
local PICK_HL_STEP = 0.06 -- highlight refresh interval (about 16 Hz)
local picking, pickElapsed, hlElapsed = false, 0, 0
local pickFrame
local hl, hlLabel, hlFor, hlBad -- highlight frame, its name label, the frame it covers, a frame that won't anchor

local function isOurs(f)
    local O, Opt = ns.Orbs, ns.Options
    return f == pickFrame
        or f == hl
        or f == ns.eventFrame
        or (O ~= nil and (f == O.overlay or f == O.driver))
        or (Opt ~= nil and f == Opt.panel)
end

-- The live nameplate frames as a set (frame -> true), or nil. Built once per call so the picker's frame scan does an
-- O(1) lookup per ancestor instead of looping over every plate. Identity only: a plate is never measured.
local function plateList()
    if not (C_NamePlate and C_NamePlate.GetNamePlates) then
        return nil
    end
    local ok, t = pcall(C_NamePlate.GetNamePlates)
    if not (ok and type(t) == "table" and readable(t)) then
        return nil
    end
    local set = {}
    for i = 1, #t do
        local f = t[i]
        if type(f) == "table" then
            set[f] = true
        end
    end
    return set
end

local function isPlateFrame(f, plates)
    return plates ~= nil and type(f) == "table" and rawget(plates, f) == true
end

local function nameOf(f)
    local ok, name = pcall(f.GetName, f)
    if ok and type(name) == "string" and readable(name) and name ~= "" then
        return name
    end
    return nil
end

-- True when f, or any ancestor up to (not including) UIParent / the WorldFrame, is a nameplate (live plate or
-- NamePlate* name) or one of our own frames. Identity and name checks only: nothing is measured.
local function unsafeChain(f, plates)
    for _ = 1, PICK_DEPTH do
        if type(f) ~= "table" or not readable(f) or f == UIParent or f == _G.WorldFrame then
            return false
        end
        local name = nameOf(f)
        if (name and string.sub(name, 1, 9) == "NamePlate") or isPlateFrame(f, plates) or isOurs(f) then
            return true
        end
        local okp, parent = pcall(f.GetParent, f)
        if not okp then
            return false
        end
        f = parent
    end
    return false
end

local function mouseFocus()
    local f
    if GetMouseFoci then
        local ok, t = pcall(GetMouseFoci)
        if ok and type(t) == "table" then
            f = t[1]
        end
    end
    if f == nil and GetMouseFocus then
        local ok, v = pcall(GetMouseFocus)
        if ok then
            f = v
        end
    end
    return f
end

-- Name (and the frame itself) of the first frame at or above f (walking GetParent) that has a readable, non-empty
-- name. nil when the chain has none, or reaches UIParent, the WorldFrame or one of our own frames first, or when the
-- frame or any ancestor is a nameplate.
function Target.PickName(f)
    local plates = plateList()
    local foundName, foundFrame
    for _ = 1, PICK_DEPTH do
        if type(f) ~= "table" or not readable(f) then
            break
        end
        if f == UIParent or f == _G.WorldFrame or isOurs(f) then
            break
        end
        local ok, name = pcall(f.GetName, f)
        local named = ok and type(name) == "string" and readable(name) and name ~= ""
        -- The whole chain is checked, even once a name is found: nothing on or inside a nameplate may be picked (the
        -- picker would anchor a frame to it). Identity and name checks only; a plate is never measured.
        if (named and string.sub(name, 1, 9) == "NamePlate") or isPlateFrame(f, plates) then
            return nil
        end
        if named and not foundName then
            foundName, foundFrame = name, f
        end
        local okp, parent = pcall(f.GetParent, f)
        if not okp then
            break
        end
        f = parent
    end
    if foundName then
        return foundName, foundFrame
    end
    return nil
end

-- Fallback for bars that ignore the mouse (EnhanceQoL's, say): they are never the mouse focus, so scan every frame
-- for named, visible, mid-sized ones under the cursor and take the smallest. Only runs while picking, never per frame.
-- A frame is name-checked and plate-checked (identity only) before anything is measured: plates are restricted.
local MAX_AREA_FRACTION = 0.5 -- frames covering more than this share of UIParent (full-screen containers) are skipped
local PICK_SCAN_STEP = 0.25 -- seconds between hover scans
local scanElapsed = PICK_SCAN_STEP
local scanPick, scanLabel, scanFrame -- last hover scan result, reused between scans
Target.scanCount = 0

local function areaOf(f)
    local okw, w = pcall(f.GetWidth, f)
    local okh, h = pcall(f.GetHeight, f)
    if okw and okh and num(w) and num(h) and w > 0 and h > 0 then
        return w * h
    end
    return nil
end

-- One candidate: returns its area when it qualifies (all filters passed, cursor over it), else nil.
local function scanArea(f, plates, cap)
    if type(f) ~= "table" or not readable(f) or f == UIParent or f == _G.WorldFrame then
        return nil
    end
    local okf, forbidden = pcall(f.IsForbidden, f)
    if okf and forbidden then
        return nil
    end
    if not nameOf(f) or unsafeChain(f, plates) then
        return nil -- unnamed, or a plate / ours / under one: skipped before any geometry call
    end
    local okv, vis = pcall(isVisible, f)
    if not (okv and vis == true) then
        return nil
    end
    local area = areaOf(f)
    if not area or area > cap then
        return nil
    end
    local okm, over = pcall(f.IsMouseOver, f)
    if okm and over == true then
        return area
    end
    return nil
end

-- The smallest qualifying frame under the cursor (later-created wins a tie), or nil. Never throws.
local function scanFrames()
    if not EnumerateFrames then
        return nil
    end
    Target.scanCount = Target.scanCount + 1
    local okw, pw = pcall(UIParent.GetWidth, UIParent)
    local okh, ph = pcall(UIParent.GetHeight, UIParent)
    if not (okw and okh and num(pw) and num(ph)) then
        return nil
    end
    local cap = pw * ph * MAX_AREA_FRACTION
    local plates = plateList()
    local best, bestArea
    local ok, f = pcall(EnumerateFrames)
    for _ = 1, 100000 do
        if not ok or f == nil then
            break
        end
        local oka, area = pcall(scanArea, f, plates, cap)
        if oka and area and (not bestArea or area <= bestArea) then
            best, bestArea = f, area
        end
        ok, f = pcall(EnumerateFrames, f)
    end
    return best
end

-- ---- smart pick: what a click would save
-- Order: a known addon bar under the cursor ("@id"), else a StatusBar under the cursor whose values match the player's
-- XP (saved by name, or as a path of fields below its nearest named ancestor), else the first named ancestor of the
-- frame under the cursor, unless that is far bigger than the frame the player pointed at.

local SEARCH_DEPTH = 4 -- levels below the frame under the cursor that are searched for the XP StatusBar
local SEARCH_BUDGET = 200 -- most frames visited in one search
local MAX_CONTAINER_RATIO = 4 -- an unnamed bar's named ancestor may be at most this many times its area
local FRACTION_TOLERANCE = 0.02 -- how far a 0..1 bar may be from xp / xpMax and still count as the XP bar

-- The first known bar source whose frame is shown and under the cursor, and that frame. A source whose frame has a
-- name of its own is skipped: saving that name works as it always did.
local function barSourceUnderCursor()
    for i = 1, #BAR_SOURCES do
        local source = BAR_SOURCES[i]
        local okResolve, frame = pcall(source.resolve)
        if okResolve and frameIsVisible(frame) and not nameOf(frame) then
            local okMouse, over = pcall(frame.IsMouseOver, frame)
            if okMouse and over == true then
                return source, frame
            end
        end
    end
    return nil
end

local function readPlayerXP()
    local okxp, xp = pcall(UnitXP, "player")
    local okmax, xpMax = pcall(UnitXPMax, "player")
    if okxp and okmax and num(xp) and num(xpMax) and xpMax > 0 then
        return xp, xpMax
    end
    return nil
end

-- 2 when frame is a StatusBar showing exactly the player's XP, 1 when it is a 0..1 bar showing the same fraction, else
-- nil. Never throws.
local function xpMatchScore(frame, xp, xpMax)
    if type(frame.GetObjectType) ~= "function" then
        return nil
    end
    local okType, objectType = pcall(frame.GetObjectType, frame)
    if not (okType and objectType == "StatusBar") then
        return nil
    end
    local okRange, _, hi = pcall(frame.GetMinMaxValues, frame)
    local okValue, value = pcall(frame.GetValue, frame)
    if not (okRange and okValue and num(hi) and num(value)) then
        return nil
    end
    if hi == xpMax and value == xp then
        return 2
    end
    if hi == 1 and math.abs(value - xp / xpMax) < FRACTION_TOLERANCE then
        return 1
    end
    return nil
end

local function frameLevelOf(frame)
    if type(frame.GetFrameLevel) ~= "function" then
        return 0
    end
    local ok, level = pcall(frame.GetFrameLevel, frame)
    return ok and num(level) and level or 0
end

-- The visible StatusBar under the cursor, at or below root, that shows the player's XP: exact matches beat fraction
-- matches, then the higher frame level wins, then the deeper one. Breadth-first, bounded by SEARCH_DEPTH and
-- SEARCH_BUDGET. Never throws.
local function findXPBar(root, xp, xpMax, plates)
    local queue, depths = { root }, { 0 }
    local head, visited = 1, 0
    local best, bestScore, bestLevel
    while queue[head] and visited < SEARCH_BUDGET do
        local frame, depth = queue[head], depths[head]
        head = head + 1
        visited = visited + 1
        if readable(frame) and not isPlateFrame(frame, plates) and not isOurs(frame) then
            local okVisible, visible = pcall(isVisible, frame)
            if okVisible and visible == true then
                local score = xpMatchScore(frame, xp, xpMax)
                if score then
                    local okMouse, over = pcall(frame.IsMouseOver, frame)
                    if okMouse and over == true then
                        local level = frameLevelOf(frame)
                        if not best or score > bestScore or (score == bestScore and level >= bestLevel) then
                            best, bestScore, bestLevel = frame, score, level
                        end
                    end
                end
            end
            if depth < SEARCH_DEPTH and type(frame.GetChildren) == "function" then
                local children = { pcall(frame.GetChildren, frame) }
                for i = 2, #children do
                    if type(children[i]) == "table" then
                        queue[#queue + 1], depths[#depths + 1] = children[i], depth + 1
                    end
                end
            end
        end
    end
    return best
end

-- The key under which parent holds child: child:GetParentKey() when parent really has it there, else the string key
-- found by scanning parent's fields. nil when there is none.
local function keyInParent(child, parent)
    if type(child.GetParentKey) == "function" then
        local ok, key = pcall(child.GetParentKey, child)
        if ok and type(key) == "string" and readable(key) and key ~= "" and rawequal(rawget(parent, key), child) then
            return key
        end
    end
    for key, value in pairs(parent) do
        if type(key) == "string" and rawequal(value, child) then
            return key
        end
    end
    return nil
end

-- "RootName.key1.key2" for an unnamed frame: its chain of parent keys up to the nearest named ancestor, checked by
-- resolving the result again. nil when a step has no key, a name has a dot in it, or the check fails. Never throws.
local function buildPathUnchecked(frame)
    local reversedKeys = {}
    local current = frame
    for _ = 1, PICK_DEPTH do
        local name = nameOf(current)
        if name then
            if string.find(name, ".", 1, true) or #reversedKeys == 0 then
                return nil
            end
            local parts = { name }
            for i = #reversedKeys, 1, -1 do
                parts[#parts + 1] = reversedKeys[i]
            end
            local path = table.concat(parts, ".")
            local parsed = parsePick(path)
            if parsed.kind == "path" and rawequal(resolvePath(parsed), frame) then
                return path
            end
            return nil
        end
        local okp, parent = pcall(current.GetParent, current)
        if not (okp and type(parent) == "table" and readable(parent)) then
            return nil
        end
        local key = keyInParent(current, parent)
        if not key then
            return nil
        end
        reversedKeys[#reversedKeys + 1] = key
        current = parent
    end
    return nil
end

local function buildPath(frame)
    local ok, path = pcall(buildPathUnchecked, frame)
    return ok and path or nil
end

local function refusalText(containerName)
    return "pick: that bar has no name of its own and its container (" .. containerName .. ") is much bigger, so it "
        .. "was not saved. Try /xporbs pick <FrameName> (find names with /fstack), or report your UI addon on GitHub."
end

-- What a click on root (the frame under the cursor) would save. Returns pick, label, frame (the frame to highlight);
-- or nil, nil, nil, refusalMessage when only an oversized container could be saved; or nothing at all.
local function smartPick(root)
    local source, sourceFrame = barSourceUnderCursor()
    if source then
        return "@" .. source.id, source.label, sourceFrame
    end
    if type(root) ~= "table" then
        return nil
    end
    local pointedAt = root
    local xp, xpMax = readPlayerXP()
    if xp then
        local match = findXPBar(root, xp, xpMax, plateList())
        if match then
            local name, namedFrame = Target.PickName(match)
            if not name then
                return nil
            end
            if rawequal(namedFrame, match) then
                return name, name, match
            end
            local path = buildPath(match)
            if path then
                return path, path, match
            end
            pointedAt = match
        end
    end
    local name, namedFrame = Target.PickName(pointedAt)
    if not name then
        return nil
    end
    if not rawequal(namedFrame, pointedAt) then
        local namedArea, pointedArea = areaOf(namedFrame), areaOf(pointedAt)
        if namedArea and pointedArea and namedArea > MAX_CONTAINER_RATIO * pointedArea then
            return nil, nil, nil, refusalText(name)
        end
    end
    return name, name, namedFrame
end

-- The frame under the cursor that smartPick starts from: the mouse focus, unless it is the screen itself, one of ours
-- or part of a nameplate.
local function pointedFrame()
    local focus = mouseFocus()
    if type(focus) ~= "table" or not readable(focus) or focus == UIParent or focus == _G.WorldFrame then
        return nil
    end
    if unsafeChain(focus, plateList()) then
        return nil
    end
    return focus
end

-- What a click would save: the frame under the mouse first, then (scan = true) the smallest named frame under the
-- cursor for bars that ignore the mouse. Returns pick, label, frame, refusal.
local function resolvePick(scan)
    local pick, label, frame, refusal = smartPick(pointedFrame())
    if pick or refusal or not scan then
        return pick, label, frame, refusal
    end
    local candidate = scanFrames()
    if candidate then
        return smartPick(candidate)
    end
    return nil
end

local function refreshPanel()
    if ns.Options and ns.Options.Refresh then
        ns.Options:Refresh()
    end
end

-- One highlight frame of ours: a translucent fill, a thin border and a name label, SetAllPoints'd onto the frame that
-- would be picked. It never takes the mouse (EnableMouse(false)), so it can't become the mouse focus itself.
local function ensureHighlight()
    if hl then
        return hl
    end
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetFrameStrata("TOOLTIP")
    f:EnableMouse(false)
    local fill = f:CreateTexture(nil, "BACKGROUND")
    fill:SetAllPoints(f)
    fill:SetColorTexture(0.35, 0.65, 1, 0.18)
    for i = 1, 4 do
        local e = f:CreateTexture(nil, "OVERLAY")
        e:SetColorTexture(0.35, 0.65, 1, 0.95)
        if i == 1 then
            e:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
            e:SetPoint("TOPRIGHT", f, "TOPRIGHT", 0, 0)
            e:SetHeight(2)
        elseif i == 2 then
            e:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 0, 0)
            e:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", 0, 0)
            e:SetHeight(2)
        elseif i == 3 then
            e:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
            e:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 0, 0)
            e:SetWidth(2)
        else
            e:SetPoint("TOPRIGHT", f, "TOPRIGHT", 0, 0)
            e:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", 0, 0)
            e:SetWidth(2)
        end
    end
    local back = f:CreateTexture(nil, "ARTWORK")
    back:SetColorTexture(0, 0, 0, 0.7)
    local label = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    label:SetPoint("TOPLEFT", f, "TOPLEFT", 6, -6)
    label:SetJustifyH("LEFT")
    back:SetPoint("TOPLEFT", label, "TOPLEFT", -3, 3)
    back:SetPoint("BOTTOMRIGHT", label, "BOTTOMRIGHT", 3, -3)
    f:Hide()
    hl, hlLabel = f, label
    Target.highlight = f
    return f
end

local function hideHighlight()
    hlFor = nil
    if hl then
        pcall(hl.Hide, hl)
    end
end

-- Highlights the frame a click would pick and says what it would save (same resolution as the click). The scan
-- fallback runs at most once per PICK_SCAN_STEP; in between, its last result is reused. Never throws.
local function updateHighlight()
    local pick, label, frame = smartPick(pointedFrame())
    if pick then
        scanPick, scanLabel, scanFrame = nil, nil, nil
    else
        if scanElapsed >= PICK_SCAN_STEP then
            scanElapsed = 0
            scanPick, scanLabel, scanFrame = resolvePick(true)
        end
        pick, label, frame = scanPick, scanLabel, scanFrame
    end
    if not frame then
        hideHighlight()
        hlBad = nil
        return
    end
    if frame == hlFor or frame == hlBad then
        return -- unchanged (or known not to anchor): nothing to do
    end
    if isPlateFrame(frame, plateList()) then
        hideHighlight() -- never anchor to a plate
        hlBad = frame
        return
    end
    ensureHighlight()
    local ok = pcall(function()
        hl:ClearAllPoints()
        hl:SetAllPoints(frame)
    end)
    if not ok then
        hlBad = frame
        hideHighlight()
        return
    end
    hlBad, hlFor = nil, frame
    pcall(hlLabel.SetText, hlLabel, label)
    hl:Show()
end

local function disarm(msg)
    picking = false
    hideHighlight()
    hlBad = nil
    scanPick, scanLabel, scanFrame = nil, nil, nil
    if pickFrame then
        pcall(pickFrame.UnregisterEvent, pickFrame, "GLOBAL_MOUSE_DOWN")
        pickFrame:SetScript("OnUpdate", nil)
    end
    if msg then
        ns.Print(msg)
    end
end

-- Whether orbs can use a freshly saved pick right now, measured by asking GetDestination.
local function pickIsUsable(pick)
    local _, _, ok = Target:GetDestination()
    if not ok then
        return false
    end
    local source = Target.PickSource(pick)
    if source then
        return Target.lastSource == source.id
    end
    return Target.lastName == pick or Target.lastSourceViaPick == true
end

local function onPickMouse(_, event, button)
    if event ~= "GLOBAL_MOUSE_DOWN" or not picking then
        return
    end
    if button == "LeftButton" then
        local pick, label, _, refusal = resolvePick(true)
        if pick then
            ns.db.targetFrame = pick
            local msg = "XP bar frame set to " .. label .. "."
            if not pickIsUsable(pick) then
                msg = "XP bar frame set to " .. label .. ", but it can't be measured right now (hidden?). "
                    .. "Orbs use auto-detection until it shows."
            end
            disarm(msg)
            refreshPanel()
        elseif refusal then
            disarm(refusal)
        else
            disarm("pick: no named frame under the mouse (it and its parents are unnamed); still using "
                .. (ns.db.targetFrame and Target.PickLabel(ns.db.targetFrame) or "auto-detect")
                .. ". If your XP bar ignores the mouse, use /xporbs pick <FrameName> (find the name with /fstack)")
        end
    elseif button == "RightButton" then
        disarm("pick cancelled")
    end
end

local function onPickUpdate(_, dt)
    dt = type(dt) == "number" and dt or 0
    pickElapsed = pickElapsed + dt
    if pickElapsed >= PICK_TIMEOUT then
        disarm("pick timed out")
        return
    end
    hlElapsed = hlElapsed + dt
    scanElapsed = scanElapsed + dt
    if hlElapsed >= PICK_HL_STEP then
        hlElapsed = 0
        pcall(updateHighlight)
    end
end

-- Arms the picker: the next left click saves the named frame under the mouse. Returns true when armed.
function Target:StartPick()
    if not pickFrame then
        pickFrame = CreateFrame("Frame")
        Target.pickFrame = pickFrame
        pickFrame:SetScript("OnEvent", onPickMouse)
    end
    if not pcall(pickFrame.RegisterEvent, pickFrame, "GLOBAL_MOUSE_DOWN") then
        ns.Print("pick: picking isn't available on this client (set the frame another way or leave it on auto)")
        return false
    end
    picking, pickElapsed, hlElapsed, scanElapsed = true, 0, PICK_HL_STEP, PICK_SCAN_STEP
    pcall(ensureHighlight)
    pickFrame:SetScript("OnUpdate", onPickUpdate)
    ns.Print("Click the XP bar (right-click to cancel)")
    return true
end

function Target:IsPicking()
    return picking
end

-- /xporbs pick <text>: set the destination by hand. The text is a global frame name, a path of fields below one
-- ("Root.key.key") or a bar source ("@flare"). Refuses anything that isn't a frame, is ours, is the screen itself, or
-- is (or sits under) a nameplate. Never throws.
local function pickByName(text)
    local parsed = parsePick(text)
    if parsed.kind == "source" then
        local saved = "@" .. parsed.source.id
        ns.db.targetFrame = saved
        local msg = "pick: XP bar set to " .. parsed.source.label
        if not pickIsUsable(saved) then
            msg = msg .. " (not showing right now; orbs use auto-detect until it shows)"
        end
        ns.Print(msg)
        refreshPanel()
        return
    end
    local ok, f
    if parsed.kind == "path" then
        ok, f = pcall(resolvePath, parsed)
    else
        ok, f = pcall(rawget, _G, text)
    end
    if not (ok and type(f) == "table" and readable(f)) then
        ns.Print("pick: no frame called " .. text)
        return
    end
    local okg, getLeft = pcall(function()
        return f.GetLeft
    end)
    if not (okg and getLeft) then
        ns.Print("pick: no frame called " .. text)
        return
    end
    if f == UIParent or f == _G.WorldFrame or string.sub(text, 1, 9) == "NamePlate" or unsafeChain(f, plateList()) then
        ns.Print("pick: " .. text .. " can't be used (it is the screen, a nameplate or one of this addon's frames)")
        return
    end
    ns.db.targetFrame = text
    local msg = "pick: XP bar set to " .. text
    if not pickIsUsable(text) then
        msg = msg .. " (hidden right now; orbs use auto-detect until it shows)"
    end
    ns.Print(msg)
    refreshPanel()
end

function ns.commands.pick(arg, raw)
    if arg == "clear" then
        disarm()
        ns.db.targetFrame = nil
        ns.Print("XP bar frame: auto-detect")
        refreshPanel()
    elseif arg == nil or arg == "" then
        Target:StartPick()
    else
        pcall(pickByName, type(raw) == "string" and raw ~= "" and raw or arg)
    end
end

table.insert(ns.statusProviders, function()
    local picked = ns.db and ns.db.targetFrame
    Target:GetDestination()
    return string.format("xp bar frame: %s, using %s", picked and ("picked " .. Target.PickLabel(picked)) or "auto",
        Target.lastSourceLabel or Target.lastName or "bottom-centre fallback")
end)

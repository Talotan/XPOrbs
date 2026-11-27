-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- The XP bar frame picker (/xporbs pick, the Setup and Options "Pick" buttons): arms a mouse-click grab, highlights the
-- frame under the cursor, smart-picks the XP bar inside whatever was clicked and saves the result as db.targetFrame.
-- Its functions attach to ns.Target (StartPick, IsPicking, PickName, scanCount) so callers are unchanged; the shared
-- helpers come from Target.internal (Target.lua, loaded right before this file).

local Target = ns.Target
local internal = Target.internal
local readable, num = internal.readable, internal.num
local isVisible, frameIsVisible = internal.isVisible, internal.frameIsVisible
local BAR_SOURCES = internal.BAR_SOURCES
local parsePick, resolvePath = internal.parsePick, internal.resolvePath

-- ---------------------------------------------------------------- /xporbs pick

local PICK_TIMEOUT = 15 -- seconds the picker stays armed
local PICK_DEPTH = 40
local PICK_HL_STEP = 0.06 -- highlight refresh interval (about 16 Hz)
local picking, pickElapsed, hlElapsed = false, 0, 0
local pickFrame
-- the highlight frame, its name label, the frame it currently covers, and a frame that refused to anchor
local highlight, highlightLabel, highlightFor, highlightBad

local function isOurs(f)
    local Orbs, Opts = ns.Orbs, ns.Options
    return f == pickFrame
        or f == highlight
        or f == ns.eventFrame
        or (Orbs ~= nil and (f == Orbs.overlay or f == Orbs.driver))
        or (Opts ~= nil and f == Opts.panel)
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
        local okParent, parent = pcall(f.GetParent, f)
        if not okParent then
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
        local okParent, parent = pcall(f.GetParent, f)
        if not okParent then
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
local scanLabel, scanFrame -- last hover scan result, reused between scans
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
local function scanArea(f, plates, maxArea)
    if type(f) ~= "table" or not readable(f) or f == UIParent or f == _G.WorldFrame then
        return nil
    end
    local okForbidden, forbidden = pcall(f.IsForbidden, f)
    if okForbidden and forbidden then
        return nil
    end
    if not nameOf(f) or unsafeChain(f, plates) then
        return nil -- unnamed, or a plate / ours / under one: skipped before any geometry call
    end
    local okVisible, vis = pcall(isVisible, f)
    if not (okVisible and vis == true) then
        return nil
    end
    local area = areaOf(f)
    if not area or area > maxArea then
        return nil
    end
    local okMouseOver, over = pcall(f.IsMouseOver, f)
    if okMouseOver and over == true then
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
    local okWidth, screenW = pcall(UIParent.GetWidth, UIParent)
    local okHeight, screenH = pcall(UIParent.GetHeight, UIParent)
    if not (okWidth and okHeight and num(screenW) and num(screenH)) then
        return nil
    end
    local maxArea = screenW * screenH * MAX_AREA_FRACTION
    local plates = plateList()
    local best, bestArea
    local ok, f = pcall(EnumerateFrames)
    for _ = 1, 100000 do
        if not ok or f == nil then
            break
        end
        local okArea, area = pcall(scanArea, f, plates, maxArea)
        if okArea and area and (not bestArea or area <= bestArea) then
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
local UPWARD_LEVELS = 2 -- how many parents smartPick may climb when the search below the cursor finds no bar
local UPWARD_BUDGET_FACTOR = 2 -- all passes of one upward search together visit at most this many SEARCH_BUDGETs
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
-- `budget` (default SEARCH_BUDGET). Returns the bar or nil, and how many frames it visited. Never throws.
local function findXPBar(root, xp, xpMax, plates, budget)
    local queue, depths = { root }, { 0 }
    local head, visited = 1, 0
    local best, bestScore, bestLevel
    budget = budget or SEARCH_BUDGET
    while queue[head] and visited < budget do
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
    return best, visited
end

-- Like findXPBar, but when nothing is found below root it retries from root's parent, then its grandparent. A
-- mouse-enabled overlay (text, hit box) is often a child or sibling of the unnamed bar rather than its ancestor, so
-- a downward-only search misses it. Stops climbing at the screen itself or a nameplate; every pass draws on one shared
-- budget (a small multiple of SEARCH_BUDGET) so the repeated walks stay bounded.
local function findXPBarNear(root, xp, xpMax, plates)
    local remaining = SEARCH_BUDGET * UPWARD_BUDGET_FACTOR
    local current = root
    for _ = 0, UPWARD_LEVELS do
        local match, visited = findXPBar(current, xp, xpMax, plates, math.min(SEARCH_BUDGET, remaining))
        if match then
            return match
        end
        remaining = remaining - visited
        if remaining <= 0 or type(current.GetParent) ~= "function" then
            return nil
        end
        local okParent, parent = pcall(current.GetParent, current)
        if not (okParent and type(parent) == "table" and readable(parent)) or parent == UIParent
            or parent == _G.WorldFrame or isPlateFrame(parent, plates) then
            return nil
        end
        current = parent
    end
    return nil
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
        local okParent, parent = pcall(current.GetParent, current)
        if not (okParent and type(parent) == "table" and readable(parent)) then
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
        local match = findXPBarNear(root, xp, xpMax, plateList())
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
    if highlight then
        return highlight
    end
    local f = CreateFrame("Frame", nil, UIParent)
    f:SetFrameStrata("TOOLTIP")
    f:EnableMouse(false)
    local fill = f:CreateTexture(nil, "BACKGROUND")
    fill:SetAllPoints(f)
    fill:SetColorTexture(0.35, 0.65, 1, 0.18)
    for i = 1, 4 do
        local edge = f:CreateTexture(nil, "OVERLAY")
        edge:SetColorTexture(0.35, 0.65, 1, 0.95)
        if i == 1 then
            edge:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
            edge:SetPoint("TOPRIGHT", f, "TOPRIGHT", 0, 0)
            edge:SetHeight(2)
        elseif i == 2 then
            edge:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 0, 0)
            edge:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", 0, 0)
            edge:SetHeight(2)
        elseif i == 3 then
            edge:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
            edge:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 0, 0)
            edge:SetWidth(2)
        else
            edge:SetPoint("TOPRIGHT", f, "TOPRIGHT", 0, 0)
            edge:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", 0, 0)
            edge:SetWidth(2)
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
    highlight, highlightLabel = f, label
    Target.highlight = f
    return f
end

local function hideHighlight()
    highlightFor = nil
    if highlight then
        pcall(highlight.Hide, highlight)
    end
end

-- Highlights the frame a click would pick and says what it would save (same resolution as the click). The scan
-- fallback runs at most once per PICK_SCAN_STEP; in between, its last result is reused. Never throws.
local function updateHighlight()
    local pick, label, frame = smartPick(pointedFrame())
    if pick then
        scanLabel, scanFrame = nil, nil
    else
        if scanElapsed >= PICK_SCAN_STEP then
            scanElapsed = 0
            local _, scanned, scannedFrame = resolvePick(true)
            scanLabel, scanFrame = scanned, scannedFrame
        end
        label, frame = scanLabel, scanFrame
    end
    if not frame then
        hideHighlight()
        highlightBad = nil
        return
    end
    if frame == highlightFor or frame == highlightBad then
        return -- unchanged (or known not to anchor): nothing to do
    end
    if isPlateFrame(frame, plateList()) then
        hideHighlight() -- never anchor to a plate
        highlightBad = frame
        return
    end
    ensureHighlight()
    local ok = pcall(function()
        highlight:ClearAllPoints()
        highlight:SetAllPoints(frame)
    end)
    if not ok then
        highlightBad = frame
        hideHighlight()
        return
    end
    highlightBad, highlightFor = nil, frame
    pcall(highlightLabel.SetText, highlightLabel, label)
    highlight:Show()
end

local function disarm(msg)
    picking = false
    hideHighlight()
    highlightBad = nil
    scanLabel, scanFrame = nil, nil
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

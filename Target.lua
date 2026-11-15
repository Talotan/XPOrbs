local ADDON, ns = ...

-- Where the orbs fly to: the fill edge of the XP bar, in UIParent coordinates. Only reads Blizzard frames.

local Target = {}
ns.Target = Target

local OrbMath = ns.OrbMath

local BAR_FRAMES = { "MainStatusTrackingBarContainer", "StatusTrackingBarManager", "MainMenuExpBar" }
local FALLBACK_Y = 20

Target.lastName = nil -- frame name used by the last GetDestination() call (nil on fallback)
Target.lastOk = false

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
    local x, y = OrbMath.FillEdge(l, b, w, h, xp, xpMax)
    return x, y, w, h
end

local function tryFrame(name, xp, xpMax, centre)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    local f = _G[name]
    if type(f) ~= "table" then
        return nil
    end
    local ok, x, y, w, h = pcall(frameEdge, f, xp, xpMax, centre)
    if ok and num(x) and num(y) then
        return x, y, w, h
    end
    return nil
end

-- Returns x, y, ok. ok is false when no bar frame was usable and the bottom-centre fallback was returned.
-- Target.lastW / lastH are the destination frame's size in UIParent units (nil on the fallback).
-- centre = true aims at the middle of the frame instead of the XP fill edge (a round target such as a portrait has
-- no fill edge).
-- db.glowOffsetX / glowOffsetY (UIParent px) are added to every result, the fallback included: the offset is the
-- user's "land here" nudge, so it moves the landing point wherever it would otherwise be. lastW / lastH are unaffected.
function Target:GetDestination(centre)
    local okxp, xp = pcall(UnitXP, "player")
    local okmax, xpMax = pcall(UnitXPMax, "player")
    if not okxp then
        xp = 0
    end
    if not okmax then
        xpMax = 0
    end
    local x, y, fw, fh
    local name = ns.db and ns.db.targetFrame
    x, y, fw, fh = tryFrame(name, xp, xpMax, centre)
    if not x then
        for i = 1, #BAR_FRAMES do
            name = BAR_FRAMES[i]
            x, y, fw, fh = tryFrame(name, xp, xpMax, centre)
            if x then
                break
            end
        end
    end
    if x then
        self.lastName, self.lastOk, self.lastW, self.lastH = name, true, fw, fh
        x, y = OrbMath.ApplyOffset(x, y, ns.db and ns.db.glowOffsetX, ns.db and ns.db.glowOffsetY)
        return x, y, true
    end
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    self.lastName, self.lastOk, self.lastW, self.lastH = nil, false, nil, nil
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
-- name. nil when the chain has none, or reaches UIParent, the WorldFrame or one of our own frames first.
function Target.PickName(f)
    for _ = 1, PICK_DEPTH do
        if type(f) ~= "table" or not readable(f) then
            return nil
        end
        if f == UIParent or f == _G.WorldFrame or isOurs(f) then
            return nil
        end
        local ok, name = pcall(f.GetName, f)
        if ok and type(name) == "string" and readable(name) and name ~= "" then
            return name, f
        end
        local okp, parent = pcall(f.GetParent, f)
        if not okp then
            return nil
        end
        f = parent
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

-- Highlights the frame a click would pick (same resolution as the click: Target.PickName). Never throws.
local function updateHighlight()
    local name, frame = Target.PickName(mouseFocus())
    if not frame then
        hideHighlight()
        hlBad = nil
        return
    end
    if frame == hlFor or frame == hlBad then
        return -- unchanged (or known not to anchor): nothing to do
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
    pcall(hlLabel.SetText, hlLabel, name)
    hl:Show()
end

local function disarm(msg)
    picking = false
    hideHighlight()
    hlBad = nil
    if pickFrame then
        pcall(pickFrame.UnregisterEvent, pickFrame, "GLOBAL_MOUSE_DOWN")
        pickFrame:SetScript("OnUpdate", nil)
    end
    if msg then
        ns.Print(msg)
    end
end

local function onPickMouse(_, event, button)
    if event ~= "GLOBAL_MOUSE_DOWN" or not picking then
        return
    end
    if button == "LeftButton" then
        local name = Target.PickName(mouseFocus())
        if name then
            ns.db.targetFrame = name
            disarm("XP bar frame set to " .. name)
            refreshPanel()
        else
            disarm("pick: no named frame under the mouse (it and its parents are unnamed); still using "
                .. (ns.db.targetFrame or "auto-detect"))
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
    picking, pickElapsed, hlElapsed = true, 0, PICK_HL_STEP
    pcall(ensureHighlight)
    pickFrame:SetScript("OnUpdate", onPickUpdate)
    ns.Print("Click the XP bar (right-click to cancel)")
    return true
end

function Target:IsPicking()
    return picking
end

function ns.commands.pick(arg)
    if arg == "clear" then
        disarm()
        ns.db.targetFrame = nil
        ns.Print("XP bar frame: auto-detect")
        refreshPanel()
    elseif arg == nil or arg == "" then
        Target:StartPick()
    else
        ns.Print("usage: /xporbs pick (then click the bar) or /xporbs pick clear")
    end
end

table.insert(ns.statusProviders, function()
    local picked = ns.db and ns.db.targetFrame
    Target:GetDestination()
    return string.format("xp bar frame: %s, using %s", picked and ("picked " .. picked) or "auto",
        Target.lastName or "bottom-centre fallback")
end)

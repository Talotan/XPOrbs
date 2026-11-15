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

-- Fill-edge point of a frame in UIParent space, or nil if it is hidden or its geometry is unusable.
local function frameEdge(f, xp, xpMax)
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
    return OrbMath.FillEdge(l, b, w, h, xp, xpMax)
end

local function tryFrame(name, xp, xpMax)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    local f = _G[name]
    if type(f) ~= "table" then
        return nil
    end
    local ok, x, y = pcall(frameEdge, f, xp, xpMax)
    if ok and num(x) and num(y) then
        return x, y
    end
    return nil
end

-- Returns x, y, ok. ok is false when no bar frame was usable and the bottom-centre fallback was returned.
function Target:GetDestination()
    local okxp, xp = pcall(UnitXP, "player")
    local okmax, xpMax = pcall(UnitXPMax, "player")
    if not okxp then
        xp = 0
    end
    if not okmax then
        xpMax = 0
    end
    local x, y
    local name = ns.db and ns.db.targetFrame
    x, y = tryFrame(name, xp, xpMax)
    if not x then
        for i = 1, #BAR_FRAMES do
            name = BAR_FRAMES[i]
            x, y = tryFrame(name, xp, xpMax)
            if x then
                break
            end
        end
    end
    if x then
        self.lastName, self.lastOk = name, true
        return x, y, true
    end
    local okw, w = pcall(UIParent.GetWidth, UIParent)
    self.lastName, self.lastOk = nil, false
    return (okw and num(w) and w / 2 or 0), FALLBACK_Y, false
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
local picking, pickElapsed = false, 0
local pickFrame

local function isOurs(f)
    local O, Opt = ns.Orbs, ns.Options
    return f == pickFrame
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

-- Name of the first frame at or above f (walking GetParent) that has a readable, non-empty name. nil when the chain
-- has none, or reaches UIParent, the WorldFrame or one of our own frames first.
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
            return name
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

local function disarm(msg)
    picking = false
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
    pickElapsed = pickElapsed + (type(dt) == "number" and dt or 0)
    if pickElapsed >= PICK_TIMEOUT then
        disarm("pick timed out")
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
    picking, pickElapsed = true, 0
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

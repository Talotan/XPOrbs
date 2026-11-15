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

function ns.commands.pick()
    ns.Print("pick: coming in M5")
end

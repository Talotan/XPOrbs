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

function ns.commands.pick()
    ns.Print("pick: coming in M5")
end

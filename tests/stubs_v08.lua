-- v0.8 stub extensions: AnimationGroup/Animation widgets, forced measurement failures, anchor-failure hooks.
-- Load AFTER stubs_m2/m3/m22 (it wraps their methods). Called as a chunk with (ns).
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

stub.animGroups = {} -- every animation group created, in order
stub.scaleApi = "new" -- "new" (SetScaleFrom/To) | "old" (SetFromScale/ToScale) | "none"
stub.failSecondAnchorTo = nil -- a frame: SetPoint(rel == that frame) raises when the region already has a point
stub.failAnchorToKind = nil -- table kind -> true: SetPoint(rel of that kind) always raises

local animBase = {}
animBase.__index = animBase
function animBase:SetDuration(d)
    self.duration = d
end
function animBase:SetOrigin(point, x, y)
    self.origin = { point, x, y }
end

local function newAnim(kind)
    local a = setmetatable({ animKind = kind }, animBase)
    if kind == "Translation" then
        function a:SetOffset(x, y)
            self.offset = { x, y }
        end
    elseif kind == "Scale" then
        if stub.scaleApi == "new" then
            function a:SetScaleFrom(x, y)
                self.scaleFrom = { x, y }
            end
            function a:SetScaleTo(x, y)
                self.scaleTo = { x, y }
            end
        elseif stub.scaleApi == "old" then
            function a:SetFromScale(x, y)
                self.scaleFrom = { x, y }
            end
            function a:SetToScale(x, y)
                self.scaleTo = { x, y }
            end
        end
    end
    return a
end

local groupMethods = {}
groupMethods.__index = groupMethods
function groupMethods:SetLooping(mode)
    self.looping = mode
end
function groupMethods:CreateAnimation(kind)
    local a = newAnim(kind)
    self.anims[#self.anims + 1] = a
    return a
end
function groupMethods:Play()
    self.playing = true
    self.plays = self.plays + 1
end
function groupMethods:Stop()
    self.playing = false
end
function groupMethods:IsPlaying()
    return self.playing
end

function fm:CreateAnimationGroup()
    local g = setmetatable({ owner = self, anims = {}, playing = false, plays = 0 }, groupMethods)
    stub.animGroups[#stub.animGroups + 1] = g
    return g
end

function stub.playingGroups()
    local n = 0
    for _, g in ipairs(stub.animGroups) do
        if g.playing then
            n = n + 1
        end
    end
    return n
end

-- All animations of a kind ("Scale", "Translation") across every group, as an array of { anim =, owner = }.
function stub.animsOfKind(kind)
    local out = {}
    for _, g in ipairs(stub.animGroups) do
        for _, a in ipairs(g.anims) do
            if a.animKind == kind then
                out[#out + 1] = { anim = a, owner = g.owner, group = g }
            end
        end
    end
    return out
end

-- Frames flagged measureFails raise from GetCenter.
local baseGetCenter = fm.GetCenter
function fm:GetCenter(...)
    if self.measureFails then
        error("Can't measure (stub)")
    end
    return baseGetCenter(self, ...)
end

function stub.failMeasure(f)
    f.measureFails = true
end

local baseSetPoint = fm.SetPoint
function fm:SetPoint(point, rel, ...)
    if type(rel) == "table" then
        if stub.failAnchorToKind and stub.failAnchorToKind[rel.kind] then
            error("Cannot anchor to that region (stub, kind " .. tostring(rel.kind) .. ")")
        end
        if stub.failSecondAnchorTo and rawequal(rel, stub.failSecondAnchorTo) and #self.points >= 1 then
            error("Cannot anchor to a restricted region together with another anchor (stub)")
        end
    end
    return baseSetPoint(self, point, rel, ...)
end

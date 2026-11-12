-- v0.9 stub extensions: restricted-region emulation (nameplates), a fake TargetFrame, forced measurement failures.
-- Load AFTER stubs_m2.lua and stubs_m3.lua (it wraps their methods). Called as a chunk with (ns).
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

stub.restrictedHits = 0 -- measuring calls made on restricted-family frames (each also raises)

-- A frame is restricted when flagged (a nameplate) or once anchored to a restricted frame; this mirrors how the
-- restriction propagates through the anchor family in game.
local function isRestricted(f)
    return f.restricted or false
end

local baseSetPoint = fm.SetPoint
function fm:SetPoint(point, rel, ...)
    if type(rel) == "table" then
        local relR = isRestricted(rel)
        -- in game: "SetPoint would result in anchor family connection" when a restricted-family frame gets a
        -- second anchor to anything else (either order)
        for _, pt in ipairs(self.points) do
            local other = pt[2]
            if type(other) == "table" and not rawequal(other, rel) and (relR or isRestricted(other)) then
                error("SetPoint would result in anchor family connection (stub)")
            end
        end
        if relR then
            self.restricted = true
        end
    end
    return baseSetPoint(self, point, rel, ...)
end

local MEASURE = { "GetCenter", "GetLeft", "GetRight", "GetTop", "GetBottom", "GetRect", "GetWidth", "GetHeight" }
for _, name in ipairs(MEASURE) do
    local base = fm[name] or function()
        return nil
    end
    fm[name] = function(self, ...)
        if isRestricted(self) then
            stub.restrictedHits = stub.restrictedHits + 1
            error("Can't measure restricted regions")
        end
        if name == "GetCenter" and self.measureFails then
            error("Can't measure (stub)")
        end
        return base(self, ...)
    end
end

function stub.failMeasure(f)
    f.measureFails = true
end

local baseCreate = CreateFrame
function CreateFrame(kind, name, parent)
    local f = baseCreate(kind)
    f.createdParent = parent
    return f
end
function fm:SetParent(p)
    self.createdParent = p
end
-- Textures made through frame:CreateTexture remember their parent frame (stubs_m2 sets parentFrame).

-- A target unit frame whose portrait is centred at (cx, cy). Returns the portrait.
function stub.setTargetFrame(cx, cy, visible)
    local tf = CreateFrame("Frame")
    local portrait = CreateFrame("Frame")
    portrait.cx, portrait.cy = cx, cy
    portrait.shown = visible ~= false
    tf.TargetFrameContainer = { Portrait = portrait }
    tf.cx, tf.cy = cx, cy
    _G.TargetFrame = tf
    return portrait
end

function stub.clearTargetFrame()
    _G.TargetFrame = nil
end

-- Like stub.addPlate, but the plate is a restricted region from the start. Friendly plates (canAttack=false) never
-- start the sampler, so tests can count measuring calls from our own frames.
function stub.addRestrictedPlate(unit, opts)
    opts = opts or {}
    local plate = CreateFrame("Frame")
    plate.cx, plate.cy, plate.scale = opts.cx or 960, opts.cy or 540, opts.scale or 1
    plate.restricted = true
    stub.plates[unit] = plate
    stub.units[unit] = {
        guid = opts.guid,
        name = opts.name,
        canAttack = opts.canAttack ~= false,
        dead = false,
        hp = 100,
        isTarget = opts.isTarget or false,
    }
    ns.fire("NAME_PLATE_UNIT_ADDED", unit)
    stub.restrictedHits = 0
    return plate
end

-- Pop frames made by Orbs.lua: 1x1 frames that set a frame strata (Plates' size-1 proxies never do).
function stub.popFrames()
    local out = {}
    for _, f in ipairs(stub.frames) do
        if f.kind == "Frame" and f.width == 1 and f.height == 1 and f.calls and f.calls.SetFrameStrata then
            out[#out + 1] = f
        end
    end
    return out
end

-- Textures parented to a pop frame (pop = true) or to anything else (pop = false).
function stub.texturesByOwner(pop)
    local isPop = {}
    for _, f in ipairs(stub.popFrames()) do
        isPop[f] = true
    end
    local out = {}
    for _, f in ipairs(stub.frames) do
        if f.kind == "Texture" and f.parentFrame ~= nil and (isPop[f.parentFrame] == true) == pop then
            out[#out + 1] = f
        end
    end
    return out
end

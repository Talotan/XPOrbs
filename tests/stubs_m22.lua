-- M2.2 stub extensions: StatusBar widgets, restricted-region emulation, a fake TargetFrame.
-- Load AFTER stubs_m2.lua and stubs_m3.lua (it wraps their methods). Called as a chunk with (ns).
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

stub.restrictedHits = 0 -- measuring calls made on restricted-family frames (each also raises)

-- A frame is restricted when flagged (e.g. a nameplate) or when it, or the bar owning a fill texture, was anchored
-- to a restricted frame. This mirrors how the restriction propagates through the anchor family in game.
local function isRestricted(f)
    return f.restricted or (f.barOwner ~= nil and f.barOwner.restricted) or false
end

local function markIfAnchoredToRestricted(self, rel)
    if type(rel) == "table" and isRestricted(rel) then
        self.restricted = true
    end
end

local baseSetPoint = fm.SetPoint
function fm:SetPoint(...)
    baseSetPoint(self, ...)
    markIfAnchoredToRestricted(self, (select(2, ...)))
end

function fm:SetAllPoints(rel)
    self.allPoints = rel
    self.points = { { "TOPLEFT", rel, "TOPLEFT", 0, 0 }, { "BOTTOMRIGHT", rel, "BOTTOMRIGHT", 0, 0 } }
    markIfAnchoredToRestricted(self, rel)
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
        return base(self, ...)
    end
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

-- StatusBar API.
function fm:SetOrientation(o)
    self.orientation = o
end
function fm:SetMinMaxValues(lo, hi)
    self.minValue, self.maxValue = lo, hi
end
function fm:SetValue(v)
    self.value = v
end
function fm:GetValue()
    return self.value
end
function fm:SetStatusBarTexture(path)
    self.statusBarPath = path
    self:GetStatusBarTexture()
end
function fm:GetStatusBarTexture()
    if not self.fill then
        self.fill = CreateFrame("StatusBarTexture")
        self.fill.barOwner = self
    end
    return self.fill
end
function fm:SetStatusBarColor(r, g, b, a)
    self.statusBarColor = { r, g, b, a }
end

-- A visible target unit frame whose portrait is centred at (cx, cy). Returns the portrait.
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

function stub.statusBars()
    local out = {}
    for _, f in ipairs(stub.frames) do
        if f.kind == "StatusBar" then
            out[#out + 1] = f
        end
    end
    return out
end

-- Like stub.addPlate, but the plate is a restricted region from the start (GetCenter raises, anchors propagate).
-- Friendly plates (canAttack=false) never start the sampler, so tests can count measuring calls from our own frames.
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

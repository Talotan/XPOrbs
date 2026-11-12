-- M2 stub extensions: texture/frame methods, cursor, fake XP bars and an OnUpdate driver.
-- Called as a chunk with (ns) after wowstub.lua and BEFORE the addon files load.
local ns = ...
local stub = ns.stub
local fm = getmetatable(UIParent).__index

for _, name in ipairs({
    "SetTexture", "SetVertexColor", "SetBlendMode", "SetDrawLayer", "SetRotation", "SetAllPoints",
    "SetFrameStrata", "EnableMouse", "SetParent", "SetHeight",
}) do
    fm[name] = function(self, ...)
        self.calls = self.calls or {}
        self.calls[name] = { ... }
    end
end
function fm:SetAlpha(a)
    self.alpha = a
end
function fm:GetAlpha()
    return self.alpha or 1
end
function fm:IsVisible()
    return self.shown and (self.parentFrame == nil or self.parentFrame:IsVisible())
end
function fm:GetLeft()
    return self.left
end
function fm:GetBottom()
    return self.bottom
end
function fm:GetHeight()
    return self.height
end
function fm:CreateTexture()
    local t = CreateFrame("Texture")
    t.parentFrame = self
    return t
end

UIParent.width, UIParent.height = 1920, 1080

stub.cursor = { x = 960, y = 540 }
function GetCursorPosition()
    return stub.cursor.x, stub.cursor.y
end

-- A fake XP bar registered as a global frame. Returns the frame.
function stub.makeBar(name, left, bottom, width, height, visible)
    local f = CreateFrame("Frame")
    f.left, f.bottom, f.width, f.height = left, bottom, width, height
    f.shown = visible ~= false
    _G[name] = f
    return f
end

-- Advance time and run every live OnUpdate script (snapshot, since handlers may remove themselves).
function stub.tick(dt)
    stub.time = stub.time + dt
    local snapshot = {}
    for i, f in ipairs(stub.frames) do
        snapshot[i] = f
    end
    for _, f in ipairs(snapshot) do
        local fn = f.scripts.OnUpdate
        if fn then
            fn(f, dt)
        end
    end
end

-- Count shown textures (frames of kind "Texture").
function stub.shownTextures()
    local n = 0
    for _, f in ipairs(stub.frames) do
        if f.kind == "Texture" and f.shown then
            n = n + 1
        end
    end
    return n
end

function stub.allTextures()
    local n = 0
    for _, f in ipairs(stub.frames) do
        if f.kind == "Texture" then
            n = n + 1
        end
    end
    return n
end

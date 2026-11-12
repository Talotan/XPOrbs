-- Minimal WoW API stub for loading addon files outside the game.
-- Called as a chunk with (ns): installs globals and adds test helpers to ns.stub / ns.fire.
local ns = ...

local stub = { time = 0, xp = 0, xpMax = 1000, chat = {}, frames = {} }
ns.stub = stub

function GetTime()
    return stub.time
end
function UnitXP()
    return stub.xp
end
function UnitXPMax()
    return stub.xpMax
end

local frameMethods = {}
frameMethods.__index = frameMethods

function frameMethods:RegisterEvent(event)
    self.events[event] = true
end
function frameMethods:UnregisterEvent(event)
    self.events[event] = nil
end
function frameMethods:SetScript(name, fn)
    self.scripts[name] = fn
end
function frameMethods:GetScript(name)
    return self.scripts[name]
end
function frameMethods:SetPoint(...)
    self.points[#self.points + 1] = { ... }
end
function frameMethods:ClearAllPoints()
    self.points = {}
end
function frameMethods:SetSize(w, h)
    self.width, self.height = w, h
end
function frameMethods:SetWidth(w)
    self.width = w
end
function frameMethods:GetWidth()
    return self.width
end
function frameMethods:CreateTexture()
    return CreateFrame("Texture")
end
function frameMethods:Show()
    self.shown = true
end
function frameMethods:Hide()
    self.shown = false
end
function frameMethods:IsShown()
    return self.shown
end
function frameMethods:GetCenter()
    return self.cx, self.cy
end
function frameMethods:GetEffectiveScale()
    return self.scale
end

function CreateFrame(kind)
    local f = setmetatable({
        kind = kind,
        events = {},
        scripts = {},
        points = {},
        width = 0,
        height = 0,
        shown = true,
        cx = 0,
        cy = 0,
        scale = 1,
    }, frameMethods)
    stub.frames[#stub.frames + 1] = f
    return f
end

UIParent = CreateFrame("Frame")
issecretvalue = nil
SlashCmdList = {}
DEFAULT_CHAT_FRAME = {
    AddMessage = function(_, msg)
        stub.chat[#stub.chat + 1] = msg
    end,
}

COMBATLOG_XPGAIN_FIRSTPERSON = "%s dies, you gain %d experience."
COMBATLOG_XPGAIN_FIRSTPERSON_GROUP = "%s dies, you gain %d experience. (+%d group bonus)"
COMBATLOG_XPGAIN_EXHAUSTION1 = "%s dies, you gain %d experience. (%s exp %s bonus)"
COMBATLOG_XPGAIN_EXHAUSTION1_GROUP = "%s dies, you gain %d experience. (%s exp %s bonus, +%d group bonus)"

-- Dispatch an event to every frame that registered it and has an OnEvent script.
function ns.fire(event, ...)
    for _, f in ipairs(stub.frames) do
        local handler = f.scripts.OnEvent
        if f.events[event] and handler then
            handler(f, event, ...)
        end
    end
end

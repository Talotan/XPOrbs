-- P2a stub: LibStub + LibDataBroker-1.1 + LibDBIcon-1.0 recorders, and a recording GameTooltip. Opt-in: load BEFORE
-- the addon (libs present); skip it for the "libs missing" case. Called as a chunk with (ns).
local ns = ...
local stub = ns.stub

local p = { registers = {}, shown = {}, calls = {}, refreshes = 0, lines = {}, tip = {} }
stub.p2a = p

local ldb = {
    NewDataObject = function(_, name, obj)
        p.object = obj
        p.objectName = name
        return obj
    end,
}

local registered = {}
local ldbi = {
    Register = function(_, name, obj, db)
        registered[name] = true
        p.registers[#p.registers + 1] = { name = name, obj = obj, db = db }
    end,
    IsRegistered = function(_, name)
        return registered[name] or false
    end,
    Show = function(_, name)
        p.calls[#p.calls + 1] = "Show"
        p.shown[name] = true
    end,
    Hide = function(_, name)
        p.calls[#p.calls + 1] = "Hide"
        p.shown[name] = false
    end,
    Refresh = function()
        p.refreshes = p.refreshes + 1
    end,
}

local libs = { ["LibDataBroker-1.1"] = ldb, ["LibDBIcon-1.0"] = ldbi }
p.libs = libs

-- like the real LibStub: LibStub(name) errors when the library is missing, LibStub(name, true) returns nil
LibStub = setmetatable({}, {
    __call = function(_, name, silent)
        local lib = libs[name]
        if not lib and not silent then
            error("Cannot find a library instance of \"" .. tostring(name) .. "\".", 2)
        end
        return lib
    end,
})

-- a recording tooltip (the LDB tooltip and GameTooltip are the same kind of object)
function stub.newTooltip()
    local tt = { lines = {}, shown = false }
    function tt:SetText(text)
        self.title = text
    end
    function tt:AddLine(text, r, g, b)
        self.lines[#self.lines + 1] = { text = text, r = r, g = g, b = b }
    end
    function tt:SetOwner(owner, anchor)
        self.owner, self.anchor = owner, anchor
    end
    function tt:Show()
        self.shown = true
    end
    function tt:Hide()
        self.shown = false
    end
    return tt
end
GameTooltip = stub.newTooltip()

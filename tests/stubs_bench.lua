-- Stubs for the dev benchmark tests only (dev/Bench.lua): build info, cvars, addon metadata, date, combat flag, the
-- physical screen size and the few frame methods the progress panel adds.
-- Called as a chunk with (ns) after the M5 stubs; changes nothing the other tests rely on.
local ns = ...
local stub = ns.stub

function GetBuildInfo()
    return "1.16.1", "12345", "Nov 27 2026", 16001
end

stub.cvars = { vsync = "0", maxFPS = "0", useMaxFPS = "0", targetFPS = "0", useTargetFPS = "0" }
function GetCVar(name)
    return stub.cvars[name]
end

C_AddOns = {
    GetAddOnMetadata = function(_, field)
        if field == "Version" then
            return "9.9.9"
        end
    end,
}

date = os.date

function UnitAffectingCombat()
    return stub.inCombat
end

-- The physical screen: GetPhysicalScreenSize exists once a test sets stub.physical = { w, h } (a client without it falls
-- back to the resolution cvars).
stub.physical = nil
function GetPhysicalScreenSize()
    return stub.physical[1], stub.physical[2]
end
stub.physical = { 2560, 1440 }

-- Frame methods the progress panel uses that no earlier stub provides: recorded, nothing more.
do
    local fm = getmetatable(UIParent).__index
    for _, name in ipairs({ "SetStatusBarTexture", "SetStatusBarColor", "SetTextColor" }) do
        if fm[name] == nil then
            fm[name] = function(self, ...)
                self.calls = self.calls or {}
                self.calls[name] = { ... }
            end
        end
    end
end

-- The addon profiler, switched on by a test with stub.profiler(true). Like the real client, LastTime reads 0 and only
-- RecentAverageTime answers: a constant 0.5 ms for XPOrbs, 2 ms overall.
function stub.profiler(on)
    if not on then
        C_AddOnProfiler, Enum = nil, nil
        return
    end
    Enum = { AddOnProfilerMetric = { LastTime = 1, RecentAverageTime = 3 } }
    C_AddOnProfiler = {
        IsEnabled = function()
            return true
        end,
        GetAddOnMetric = function(_, metric)
            return metric == 3 and 0.5 or 0
        end,
        GetOverallMetric = function(metric)
            return metric == 3 and 2 or 0.15
        end,
    }
end

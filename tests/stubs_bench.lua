-- Stubs for the dev benchmark tests only (dev/Bench.lua): build info, cvars, addon metadata, date, combat flag.
-- Called as a chunk with (ns) after the M5 stubs; changes nothing the other tests rely on.
local ns = ...
local stub = ns.stub

function GetBuildInfo()
    return "1.16.1", "12345", "Nov 27 2026", 16001
end

stub.cvars = { maxFPS = "0", gxVSync = "0" }
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

-- The addon profiler, switched on by a test with stub.profiler(true): a constant 0.5 ms for XPOrbs, 2 ms overall.
function stub.profiler(on)
    if not on then
        C_AddOnProfiler, Enum = nil, nil
        return
    end
    Enum = { AddOnProfilerMetric = { LastTime = 1 } }
    C_AddOnProfiler = {
        IsEnabled = function()
            return true
        end,
        GetAddOnMetric = function()
            return 0.5
        end,
        GetOverallMetric = function()
            return 2
        end,
    }
end

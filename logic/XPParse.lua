local ADDON, ns = ...

-- Pure logic: turns Blizzard XP-gain format strings into Lua patterns and parses chat messages.
-- Touches no WoW globals; the caller passes the globals table to Build.

local XPParse = {}
ns.XPParse = XPParse

local smatch, ssub, sgsub = string.match, string.sub, string.gsub

-- Format string -> anchored pattern plus capture order.
-- %s -> (.-), %d -> (%d+), %1$s / %2$d positional forms, %% literal. order[i] = format-argument index of capture i.
function XPParse.PatternFrom(fmt)
    if type(fmt) ~= "string" then
        return nil
    end
    local out, order = { "^" }, {}
    local nextArg = 1
    local i, n = 1, #fmt
    while i <= n do
        local c = ssub(fmt, i, i)
        if c == "%" then
            local pos, conv, after = smatch(fmt, "^(%d+)%$([sd])()", i + 1)
            if not pos then
                conv, after = smatch(fmt, "^([sd])()", i + 1)
            end
            if conv then
                local idx
                if pos then
                    idx = tonumber(pos)
                else
                    idx = nextArg
                    nextArg = nextArg + 1
                end
                order[#order + 1] = idx
                out[#out + 1] = (conv == "s") and "(.-)" or "(%d+)"
                i = after
            else
                out[#out + 1] = "%%" -- "%%" (or a stray "%") is a literal percent sign
                i = i + (ssub(fmt, i + 1, i + 1) == "%" and 2 or 1)
            end
        else
            out[#out + 1] = (sgsub(c, "%p", "%%%0"))
            i = i + 1
        end
    end
    out[#out + 1] = "$"
    return table.concat(out), order
end

-- Global names, tagged. kind: "kill" (mob name is arg 1) or "other". role: what the 3rd argument means.
local SUFFIXES = { "", "_GROUP", "_RAID" }
local function nameList()
    local list = {}
    local function add(base, kind, role)
        for _, s in ipairs(SUFFIXES) do
            list[#list + 1] = { name = "COMBATLOG_XPGAIN_" .. base .. s, kind = kind, role = role }
        end
    end
    add("FIRSTPERSON", "kill", nil)
    add("EXHAUSTION1", "kill", "rested")
    add("EXHAUSTION2", "kill", "rested")
    add("EXHAUSTION3", "kill", "rested")
    add("EXHAUSTION4", "kill", "penalty")
    add("EXHAUSTION5", "kill", "penalty")
    add("FIRSTPERSON_UNNAMED", "other", nil)
    add("QUEST", "other", "rested")
    return list
end

-- "+45" / "45" -> 45. Leading sign stripped; nil when not a number.
local function magnitude(s)
    if type(s) ~= "string" then
        return nil
    end
    return tonumber((sgsub(s, "^[+-]", "")))
end

-- Build a parser from a table of globals (e.g. _G). Non-string globals are skipped, identical patterns collapse.
-- Longer patterns are tried first so the plain wording can never shadow a variant, and the lazy %s captures cannot
-- swallow a ", +N group bonus" tail (every pattern is also anchored with "$").
function XPParse.Build(globals)
    local entries, seen = {}, {}
    for _, meta in ipairs(nameList()) do
        local fmt = globals[meta.name]
        if type(fmt) == "string" then
            local pattern, order = XPParse.PatternFrom(fmt)
            if pattern and not seen[pattern] then
                seen[pattern] = true
                entries[#entries + 1] = {
                    pattern = pattern,
                    order = order,
                    kind = meta.kind,
                    role = meta.role,
                    seq = #entries,
                }
            end
        end
    end
    table.sort(entries, function(a, b)
        if #a.pattern ~= #b.pattern then
            return #a.pattern > #b.pattern
        end
        return a.seq < b.seq
    end)

    local parser = { entries = entries }

    -- msg -> { amount, mob|nil, rested|nil, penalty|nil, kind } or nil. `readable` (optional) rejects secret values.
    function parser:Parse(msg, readable)
        if type(msg) ~= "string" then
            return nil
        end
        if readable and not readable(msg) then
            return nil
        end
        for _, e in ipairs(self.entries) do
            local ok, c1, c2, c3, c4, c5, c6 = pcall(smatch, msg, e.pattern)
            if ok and c1 ~= nil then
                local caps = { c1, c2, c3, c4, c5, c6 }
                local args = {}
                for ci, argIdx in ipairs(e.order) do
                    args[argIdx] = caps[ci]
                end
                local amountIdx = (e.kind == "kill") and 2 or 1
                local amount = tonumber(args[amountIdx])
                if amount then
                    local res = { amount = amount, kind = e.kind }
                    if e.kind == "kill" then
                        res.mob = args[1]
                    end
                    if e.role == "rested" then
                        res.rested = magnitude(args[amountIdx + 1])
                    elseif e.role == "penalty" then
                        res.penalty = magnitude(args[amountIdx + 1])
                    end
                    return res
                end
            end
        end
        return nil
    end

    return parser
end

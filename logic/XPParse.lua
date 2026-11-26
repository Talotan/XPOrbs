-- SPDX-License-Identifier: GPL-3.0-or-later
local _, ns = ...

-- Pure logic: turns Blizzard XP-gain format strings into Lua patterns and parses chat messages.
-- Touches no WoW globals; the caller passes the globals table to Build.

local XPParse = {}
ns.XPParse = XPParse

local stringMatch, stringSub, stringGsub = string.match, string.sub, string.gsub

-- Format string -> anchored pattern plus capture order.
-- %s -> (.-), %d -> (%d+), %1$s / %2$d positional forms, %% literal. order[i] = format-argument index of capture i;
-- conversions[i] = "s" or "d", the kind of capture i (internal: PatternFrom hides it).
local function buildPattern(fmt)
    if type(fmt) ~= "string" then
        return nil
    end
    local out, order, conversions = { "^" }, {}, {}
    local nextArg = 1
    local i, length = 1, #fmt
    while i <= length do
        local char = stringSub(fmt, i, i)
        if char == "%" then
            local pos, conv, after = stringMatch(fmt, "^(%d+)%$([sd])()", i + 1)
            if not pos then
                conv, after = stringMatch(fmt, "^([sd])()", i + 1)
            end
            if conv then
                local argIndex
                if pos then
                    argIndex = tonumber(pos)
                else
                    argIndex = nextArg
                    nextArg = nextArg + 1
                end
                order[#order + 1] = argIndex
                conversions[#conversions + 1] = conv
                out[#out + 1] = (conv == "s") and "(.-)" or "(%d+)"
                i = after
            else
                out[#out + 1] = "%%" -- "%%" (or a stray "%") is a literal percent sign
                i = i + (stringSub(fmt, i + 1, i + 1) == "%" and 2 or 1)
            end
        else
            out[#out + 1] = (stringGsub(char, "%p", "%%%0"))
            i = i + 1
        end
    end
    out[#out + 1] = "$"
    return table.concat(out), order, conversions
end

function XPParse.PatternFrom(fmt)
    local pattern, order = buildPattern(fmt)
    if pattern == nil then
        return nil
    end
    return pattern, order
end

-- Reader for a one-number system message such as ERR_ZONE_EXPLORED_XP ("Discovered %s: %d experience gained"):
-- returns a function msg -> amount (the %d capture) or nil. Tolerates a trailing period on the message. nil when fmt
-- is not a format string or has no number in it.
function XPParse.AmountReader(fmt)
    local pattern, _, conversions = buildPattern(fmt)
    if not pattern then
        return nil
    end
    local numberCapture
    for captureIndex, conv in ipairs(conversions) do
        if conv == "d" then
            numberCapture = captureIndex
            break
        end
    end
    if not numberCapture then
        return nil
    end
    pattern = stringSub(pattern, 1, -2) .. "%.?$"
    return function(msg)
        if type(msg) ~= "string" then
            return nil
        end
        local ok, c1, c2, c3, c4, c5, c6 = pcall(stringMatch, msg, pattern)
        if not ok or c1 == nil then
            return nil
        end
        return tonumber(({ c1, c2, c3, c4, c5, c6 })[numberCapture])
    end
end

-- Global names, tagged. kind: "kill" (mob name is arg 1) or "other". role: what the 3rd argument means.
local SUFFIXES = { "", "_GROUP", "_RAID" }
local function nameList()
    local list = {}
    local function add(base, kind, role)
        for _, suffix in ipairs(SUFFIXES) do
            list[#list + 1] = { name = "COMBATLOG_XPGAIN_" .. base .. suffix, kind = kind, role = role }
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
local function magnitude(text)
    if type(text) ~= "string" then
        return nil
    end
    return tonumber((stringGsub(text, "^[+-]", "")))
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
    table.sort(entries, function(left, right)
        if #left.pattern ~= #right.pattern then
            return #left.pattern > #right.pattern
        end
        return left.seq < right.seq
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
        for _, entry in ipairs(self.entries) do
            local ok, c1, c2, c3, c4, c5, c6 = pcall(stringMatch, msg, entry.pattern)
            if ok and c1 ~= nil then
                local captures = { c1, c2, c3, c4, c5, c6 }
                local args = {}
                for captureIndex, argIdx in ipairs(entry.order) do
                    args[argIdx] = captures[captureIndex]
                end
                local amountIdx = (entry.kind == "kill") and 2 or 1
                local amount = tonumber(args[amountIdx])
                if amount then
                    local result = { amount = amount, kind = entry.kind }
                    if entry.kind == "kill" then
                        result.mob = args[1]
                    end
                    if entry.role == "rested" then
                        result.rested = magnitude(args[amountIdx + 1])
                    elseif entry.role == "penalty" then
                        result.penalty = magnitude(args[amountIdx + 1])
                    end
                    return result
                end
            end
        end
        return nil
    end

    return parser
end

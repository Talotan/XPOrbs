-- SPDX-License-Identifier: GPL-3.0-or-later
local ADDON, ns = ...

-- Bench: the dev-only in-game benchmark (/xporbs bench). It fires scripted, seeded kills from 8 invisible slot frames
-- through Orbs:Burst exactly like a nameplate kill with a mouseover estimate, samples frame and addon time every frame
-- and saves each run to XPOrbsDB.bench (format: tools/bench/SCHEMA.md, read by tools/bench/report.py).
-- Never packaged: the toc lists this file inside a do-not-package block and .pkgmeta ignores dev/.
-- The player's settings are swapped for a preset while it runs and always put back (finish, stop, error, combat,
-- logout, or the next load after a crash: a deep copy waits in XPOrbsDB.bench.restore meanwhile).

local floor, ceil, max, min = math.floor, math.ceil, math.max, math.min
local format, sort, remove = string.format, table.sort, table.remove
local prof = debugprofilestop
local OrbMath = ns.OrbMath

local Bench = {}
ns.Bench = Bench
Bench.durationScale = 1 -- tests shrink every duration with this; read when a bench starts

local SCHEMA = 1
local SCENARIO_VERSION = 1
local MAX_RUNS = 30 -- saved runs kept, oldest dropped
local SETTLE, BASELINE, DRAIN_MAX, DRAIN_GUESS = 2, 10, 8, 3 -- seconds (DRAIN_GUESS: only for the time estimate)
local STEP = 0.5 -- timeline bucket, seconds
local CAP_FRAMES = 30000 -- samples kept per phase (68 s at 440 fps); the arrays are filled once, never grown per frame
local OVER = { 1, 5, 10, 16.67 } -- Stats over1 / over5 / over10 / over16 thresholds, ms
local ORDER = { "max", "aoe", "typical" }
local DEFAULT_REPS, MAX_REPS = 3, 10
local SCENARIOS = {
    max = { seed = 1001, duration = 30 },
    aoe = { seed = 2002, duration = 60 },
    typical = { seed = 3003, duration = 60 },
}
Bench.SCENARIOS = SCENARIOS

-- The eight fake mobs: fractions of UIParent's width and height.
local SLOT_FX = { 0.30, 0.40, 0.50, 0.60, 0.70, 0.35, 0.55, 0.65 }
local SLOT_FY = { 0.55, 0.60, 0.52, 0.58, 0.62, 0.48, 0.50, 0.46 }
local N_SLOTS = #SLOT_FX

-- ---------------------------------------------------------------- scenario scripts

-- Park-Miller minimal standard generator: a closure returning numbers in (0, 1).
local function newRng(seed)
    local state = seed
    return function()
        state = (state * 16807) % 2147483647
        return state / 2147483647
    end
end

-- `count` distinct slots among the 8 (a partial Fisher-Yates shuffle); the first `count` entries of the result.
local function pickSlots(rng, count)
    local pool = { 1, 2, 3, 4, 5, 6, 7, 8 }
    for i = 1, count do
        local j = i + floor(rng() * (N_SLOTS - i + 1))
        pool[i], pool[j] = pool[j], pool[i]
    end
    return pool
end

-- The kills of a scenario as a time-ordered list of { t, slot, pct, rested, group } (t in script seconds, pct = % of a
-- level, group = the wave or pull a kill belongs to; max has one kill per group).
-- Same seed every call, so every rep replays the same fight. Waves and pulls never interleave (the shortest gap is
-- longer than the longest in-wave spread), so generation order is already time order.
function Bench.Schedule(scenario)
    local def = SCENARIOS[scenario]
    if not def then
        return nil
    end
    local events, n = {}, 0
    local function add(t, slot, pct, rested, group)
        if t < def.duration then
            n = n + 1
            events[n] = { t = t, slot = slot, pct = pct, rested = rested, group = group }
        end
    end
    if scenario == "max" then
        -- a burst every 0.25 s cycling the slots, rested every 3rd; 30 % of a level is past the cap at density 300
        -- (OrbMath.Count: (3 + 5 * sqrt(30)) * 3 = 91 > 80), so every burst is a full-cap one
        for i = 1, floor(def.duration / 0.25) do
            add((i - 1) * 0.25, (i - 1) % N_SLOTS + 1, 30, i % 3 == 0, i)
        end
        return events
    end
    local rng = newRng(def.seed)
    local t, group = 0, 0
    while true do
        if scenario == "aoe" then
            -- waves of 2-4 kills 2-4 s apart, kills 0.1-0.6 s apart inside a wave
            t = t + 2 + 2 * rng()
            if t >= def.duration then
                break
            end
            group = group + 1
            local kills = 2 + floor(rng() * 3)
            local slots = pickSlots(rng, kills)
            local at = t
            for k = 1, kills do
                if k > 1 then
                    at = at + 0.1 + 0.5 * rng()
                end
                add(at, slots[k], 0.4 + 0.8 * rng(), rng() < 0.3, group)
            end
        else
            -- pulls 8-12 s apart of 1-3 kills (weights 0.40 / 0.35 / 0.25), 0-1.5 s apart, the first at the pull
            t = t + 8 + 4 * rng()
            if t >= def.duration then
                break
            end
            group = group + 1
            local roll = rng()
            local kills = roll < 0.40 and 1 or (roll < 0.75 and 2 or 3)
            local slots = pickSlots(rng, kills)
            local at = t
            for k = 1, kills do
                if k > 1 then
                    at = at + 1.5 * rng()
                end
                add(at, slots[k], 0.8 + 1.7 * rng(), rng() < 0.3, group)
            end
        end
    end
    return events
end

-- ---------------------------------------------------------------- statistics

local function round(x, places)
    local k = 10 ^ places
    return floor(x * k + 0.5) / k
end

-- Stats of arr[1..n] (ms): { n, mean, p50, p95, p99, max, over1, over5, over10, over16 }. Percentiles are nearest-rank
-- on a sorted copy: s[max(1, ceil(q * n))]. overX counts the samples above X ms (over16 = above 16.67).
function Bench.Stats(arr, n)
    local stats = { n = n, mean = 0, p50 = 0, p95 = 0, p99 = 0, max = 0, over1 = 0, over5 = 0, over10 = 0, over16 = 0 }
    if n <= 0 then
        return stats
    end
    local sorted, sum = {}, 0
    for i = 1, n do
        local v = arr[i]
        sorted[i] = v
        sum = sum + v
    end
    sort(sorted)
    stats.mean = round(sum / n, 4)
    stats.p50 = round(sorted[max(1, ceil(0.50 * n))], 4)
    stats.p95 = round(sorted[max(1, ceil(0.95 * n))], 4)
    stats.p99 = round(sorted[max(1, ceil(0.99 * n))], 4)
    stats.max = round(sorted[n], 4)
    local counts = { 0, 0, 0, 0 }
    for i = 1, n do
        local v = sorted[i]
        for k = 1, 4 do
            if v > OVER[k] then
                counts[k] = counts[k] + 1
            end
        end
    end
    stats.over1, stats.over5, stats.over10, stats.over16 = counts[1], counts[2], counts[3], counts[4]
    return stats
end

-- ---------------------------------------------------------------- settings: snapshot, preset, restore

local function deepCopy(value)
    if type(value) ~= "table" then
        return value
    end
    local copy = {}
    for k, v in pairs(value) do
        copy[k] = deepCopy(v)
    end
    return copy
end

-- Makes `target` equal to `source`, in place: sub-tables that exist on both sides keep their identity (LibDBIcon holds
-- db.minimap, other files hold db.shapeLook entries), everything else is replaced by a deep copy.
local function syncInto(target, source)
    for k in pairs(target) do
        if source[k] == nil then
            target[k] = nil
        end
    end
    for k, v in pairs(source) do
        if type(v) == "table" and type(target[k]) == "table" then
            syncInto(target[k], v)
        else
            target[k] = deepCopy(v)
        end
    end
end

-- Every look, flight, style and glow key a preset overwrites (ns.defaults values first, then the scenario's own).
-- The player's destination keys (targetFrame, glowOffsetX/Y, glowShape, zoomAnchor, zoomA, zoomB, zoomMin,
-- zoomPoints, minimap, setupDismissed, debug) are never touched.
local PRESET_KEYS = {
    "orbShape", "size", "density", "opacity", "blend", "pulse", "sparkle", "crackleSpeed", "cap",
    "trail", "trailOpacity", "color", "classColor", "restedTint", "restedColor",
    "flightPath", "flightMode", "flightTime", "flightSpeed",
    "style", "popMode", "unknownOrigin", "zoomSpread",
    "glow", "glowIntensity",
}
local PRESETS = {
    max = {
        orbShape = "starlight", size = 32, density = 300, cap = 80, opacity = 100, blend = "natural", sparkle = true,
        pulse = false, trail = true, trailOpacity = 100, flightPath = "chaos", flightMode = "time", flightTime = 1.5,
        style = "popstream", popMode = "nameplate", glow = true, glowIntensity = 200,
    },
    aoe = {}, -- the defaults
    typical = {},
}

local function refreshPanel()
    if ns.Options and ns.Options.Refresh then
        pcall(ns.Options.Refresh, ns.Options)
    end
end

-- Writes the scenario's preset into ns.db (the same table every module holds). The active look keys and the shape's own
-- shapeLook entry are written together through ns.SetShapeLook so they agree. Orbs.lua reads ns.db on every burst and
-- caches nothing between bursts, so no refresh hook exists beyond the options panel (repainted by the caller).
local function applyPreset(name)
    local db = ns.db
    for _, key in ipairs(PRESET_KEYS) do
        db[key] = deepCopy(ns.defaults[key])
    end
    for key, value in pairs(PRESETS[name]) do
        db[key] = value
    end
    db.sound, db.enabled = false, true
    local shape = db.orbShape
    for _, key in ipairs(ns.SHAPE_LOOK_KEYS) do
        ns.SetShapeLook(shape, key, db[key])
    end
    refreshPanel()
end

-- The preset as applied, for run.settings.
local function summarySettings()
    local db = ns.db
    return {
        orbShape = db.orbShape, size = db.size, density = db.density, cap = db.cap, flightPath = db.flightPath,
        style = db.style, popMode = db.popMode, flightMode = db.flightMode, flightTime = db.flightTime,
        trail = db.trail, glowIntensity = db.glowIntensity, sound = db.sound,
    }
end

-- XPOrbsDB.bench, made when missing (existing runs are kept).
local function ensureStore()
    local store = ns.db.bench
    if type(store) ~= "table" then
        store = {}
        ns.db.bench = store
    end
    store.schema = SCHEMA
    if type(store.runs) ~= "table" then
        store.runs = {}
    end
    return store
end

-- Puts the saved copy back (every db key but `bench`) and clears it. False when there is nothing to restore.
local function restoreSettings()
    local db, store = ns.db, ns.db and ns.db.bench
    local saved = type(store) == "table" and store.restore
    if type(saved) ~= "table" then
        return false
    end
    for k in pairs(db) do
        if k ~= "bench" and saved[k] == nil then
            db[k] = nil
        end
    end
    for k, v in pairs(saved) do
        if k ~= "bench" then
            if type(v) == "table" and type(db[k]) == "table" then
                syncInto(db[k], v)
            else
                db[k] = deepCopy(v)
            end
        end
    end
    store.restore = nil
    refreshPanel()
    return true
end

-- ---------------------------------------------------------------- run state

local running = false
local orbs -- ns.Orbs
local eventFrame, sampleFrame
local queue, qi, batch, repsTotal, done -- the planned runs, the current one, the batch id, reps, finished runs
local scale = 1 -- Bench.durationScale at start
local useProfiler, hasOverall, getMetric, getOverall, metricLast
local run -- the run record being built
local phase, phaseT, loadT -- "settle" | "baseline" | "load"; seconds in the phase
local events, nEvents, nextEv, scriptEnd
local kills, orbsTotal, peakLive, peakTex
local burstMs = {}
local burstAcc = 0 -- Burst ms fired in the current frame (internal source: counted in the next frame's sample)
local lastPerfTotal, perfFrames0, perfTotal0, gc0, mem0
local params = {} -- the Burst argument, reused for every kill
local slots = {}
-- per-frame samples of the phase being measured (filled in place: nothing is allocated in the sampling OnUpdate)
local frameArr, addonArr, overallArr, timeArr, liveArr = {}, {}, {}, {}, {}
local arrN = 0

local function say(msg)
    ns.Print("bench: " .. msg)
end

local function fillArrays()
    if frameArr[CAP_FRAMES] == nil then
        for i = 1, CAP_FRAMES do
            frameArr[i], addonArr[i], timeArr[i], liveArr[i] = 0, 0, 0, 0
        end
    end
    if hasOverall and overallArr[CAP_FRAMES] == nil then
        for i = 1, CAP_FRAMES do
            overallArr[i] = 0
        end
    end
end

local function releaseArrays()
    frameArr, addonArr, overallArr, timeArr, liveArr, burstMs = {}, {}, {}, {}, {}, {}
end

local function placeSlots()
    local width = tonumber(UIParent:GetWidth()) or 1920
    local height = tonumber(UIParent:GetHeight()) or 1080
    for i = 1, N_SLOTS do
        local slot = slots[i]
        if not slot then
            local frame = CreateFrame("Frame", nil, UIParent)
            frame:SetSize(1, 1)
            slot = { frame = frame }
            slots[i] = slot
        end
        slot.x, slot.y = SLOT_FX[i] * width, SLOT_FY[i] * height
        slot.frame:ClearAllPoints()
        slot.frame:SetPoint("CENTER", UIParent, "BOTTOMLEFT", slot.x, slot.y)
    end
end

-- C_AddOnProfiler when it works (a number comes back for LastTime), else the internal timers.
local function pickSource()
    useProfiler, hasOverall, getMetric, getOverall, metricLast = false, false, nil, nil, nil
    local profiler = C_AddOnProfiler
    if not (profiler and profiler.GetAddOnMetric and Enum and Enum.AddOnProfilerMetric) then
        return
    end
    metricLast = Enum.AddOnProfilerMetric.LastTime
    if metricLast == nil then
        return
    end
    if profiler.IsEnabled then
        local ok, enabled = pcall(profiler.IsEnabled)
        if ok and enabled == false then
            return
        end
    end
    local ok, value = pcall(profiler.GetAddOnMetric, ADDON, metricLast)
    if ok and type(value) == "number" then
        useProfiler, getMetric = true, profiler.GetAddOnMetric
        if profiler.GetOverallMetric then
            hasOverall, getOverall = true, profiler.GetOverallMetric
        end
    end
end

local function cvar(name)
    if GetCVar then
        local ok, value = pcall(GetCVar, name)
        if ok and value ~= nil then
            return tostring(value)
        end
    end
    return nil
end

local function addonVersion()
    local fn = (C_AddOns and C_AddOns.GetAddOnMetadata) or GetAddOnMetadata
    if fn then
        local ok, value = pcall(fn, ADDON, "Version")
        if ok and type(value) == "string" then
            return value
        end
    end
    return "unknown"
end

local function stamp(fmt)
    if date then
        local ok, text = pcall(date, fmt)
        if ok and type(text) == "string" then
            return text
        end
    end
    return ""
end

local function readMem()
    if not (UpdateAddOnMemoryUsage and GetAddOnMemoryUsage) then
        return nil
    end
    local okUpdate = pcall(UpdateAddOnMemoryUsage)
    local okUsage, kb = pcall(GetAddOnMemoryUsage, ADDON)
    if okUpdate and okUsage and type(kb) == "number" then
        return round(kb, 1)
    end
    return nil
end

-- The run record with its metadata; phases and results are added as the run goes.
local function newRun(item)
    local def = SCENARIOS[item.scenario]
    local build, buildNumber, interface = "unknown", "0", 0
    if GetBuildInfo then
        local ok, version, number, _, toc = pcall(GetBuildInfo)
        if ok then
            build, buildNumber, interface = tostring(version or build), tostring(number or buildNumber), toc or 0
        end
    end
    local width = tonumber(UIParent:GetWidth()) or 0
    local height = tonumber(UIParent:GetHeight()) or 0
    local okScale, uiScale = pcall(UIParent.GetEffectiveScale, UIParent)
    uiScale = okScale and tonumber(uiScale) or 1
    return {
        id = batch .. "-" .. item.scenario .. "-" .. item.rep,
        batch = batch,
        scenario = item.scenario,
        scenarioVersion = SCENARIO_VERSION,
        rep = item.rep,
        reps = repsTotal,
        seed = def.seed,
        addonVersion = addonVersion(),
        build = build,
        buildNumber = buildNumber,
        interface = interface,
        date = stamp("!%Y-%m-%dT%H:%M:%SZ"),
        -- physical pixels: UIParent's size is in UI units, its effective scale converts
        screenW = floor(width * uiScale + 0.5),
        screenH = floor(height * uiScale + 0.5),
        uiScale = round(uiScale, 4),
        maxFPS = cvar("maxFPS"),
        vsync = cvar("gxVSync"),
        source = useProfiler and "profiler" or "internal",
        settings = summarySettings(),
    }
end

-- ---------------------------------------------------------------- sampling (the hot path: allocates nothing)

local function sample(dt, burstPrev, t)
    if arrN >= CAP_FRAMES then
        return
    end
    local i = arrN + 1
    arrN = i
    frameArr[i] = dt * 1000
    timeArr[i] = t
    if useProfiler then
        local ok, value = pcall(getMetric, ADDON, metricLast)
        addonArr[i] = (ok and type(value) == "number") and value or 0
        if hasOverall then
            local okAll, all = pcall(getOverall, metricLast)
            overallArr[i] = (okAll and type(all) == "number") and all or 0
        end
    else
        local _, _, _, total = orbs:BenchProbe()
        addonArr[i] = (total - lastPerfTotal) + burstPrev
        lastPerfTotal = total
    end
end

-- One scripted kill: Orbs:Burst as a nameplate kill with a mouseover estimate (the slot frame is the plate).
local function fireKill(ev)
    local db = ns.db
    local slot = slots[ev.slot]
    local gain = ev.pct / 100 * 1000
    local n, burstScale = OrbMath.Count(gain, 1000, db.density, db.cap)
    local nPurple = 0
    if ev.rested then
        local _, purple = OrbMath.RestedSplit(n, gain, gain / 2)
        nPurple = purple
    end
    params.x, params.y, params.plate = slot.x, slot.y, slot.frame
    params.ex, params.ey, params.est, params.estW = slot.x, slot.y, "mouseover", 1
    params.n, params.scale, params.nPurple = n, burstScale, nPurple
    params.kind, params.zoomFactor = "kill", 1
    local t0 = prof()
    orbs:Burst(params)
    local ms = prof() - t0
    kills = kills + 1
    orbsTotal = orbsTotal + n
    burstMs[kills] = ms
    burstAcc = burstAcc + ms
end

-- ---------------------------------------------------------------- phases

local function makePhase(seconds)
    return {
        seconds = round(seconds, 3),
        frames = arrN,
        addonMs = Bench.Stats(addonArr, arrN),
        overallMs = hasOverall and Bench.Stats(overallArr, arrN) or nil,
        frameMs = Bench.Stats(frameArr, arrN),
    }
end

-- The load phase in STEP buckets: mean and worst XPOrbs ms, mean frame ms, live orbs at the bucket's last frame.
local function buildTimeline()
    local timeline = { step = STEP, addonMs = {}, addonMaxMs = {}, frameMs = {}, live = {} }
    if arrN == 0 then
        return timeline
    end
    local last = floor((timeArr[arrN] - 1e-9) / STEP) + 1
    local addonSum, frameSum, count, worst, live = {}, {}, {}, {}, {}
    for b = 1, last do
        addonSum[b], frameSum[b], count[b], worst[b], live[b] = 0, 0, 0, 0, 0
    end
    local carry = 0
    for i = 1, arrN do
        local b = max(1, floor((timeArr[i] - 1e-9) / STEP) + 1)
        addonSum[b] = addonSum[b] + addonArr[i]
        frameSum[b] = frameSum[b] + frameArr[i]
        count[b] = count[b] + 1
        if addonArr[i] > worst[b] then
            worst[b] = addonArr[i]
        end
        live[b] = liveArr[i]
    end
    for b = 1, last do
        local c = count[b]
        timeline.addonMs[b] = c > 0 and round(addonSum[b] / c, 4) or 0
        timeline.addonMaxMs[b] = round(worst[b], 4)
        timeline.frameMs[b] = c > 0 and round(frameSum[b] / c, 4) or 0
        if c > 0 then
            carry = live[b]
        end
        timeline.live[b] = carry -- an empty bucket (a long hitch) repeats the last count
    end
    return timeline
end

local function stopSampling()
    if sampleFrame then
        sampleFrame:SetScript("OnUpdate", nil)
    end
end

local function resetState()
    running = false
    phase, run, queue, events, done = nil, nil, nil, nil, nil
    releaseArrays()
    arrN = 0
end

-- Ends the whole bench early: the current run is discarded and the settings go back.
local function abort(reason)
    if not running then
        return
    end
    stopSampling()
    local ok, err = pcall(restoreSettings)
    resetState()
    say("aborted (" .. reason .. "); " .. (ok and "settings restored" or ("restoring failed: " .. tostring(err))))
end

-- True when a leftover restore copy was put back (a crash or a /reload took the last bench down mid-run).
local function recover()
    if running or not ns.db then
        return false
    end
    if restoreSettings() then
        say("restored your settings after an interrupted run")
        return true
    end
    return false
end

local function beginBaseline()
    phase, phaseT, arrN, burstAcc = "baseline", 0, 0, 0
    local _, _, _, total = orbs:BenchProbe()
    lastPerfTotal = total
end

local function beginLoad()
    phase, loadT, arrN, burstAcc = "load", 0, 0, 0
    nextEv, kills, orbsTotal, peakLive, peakTex = 1, 0, 0, 0, 0
    local _, _, frames, total = orbs:BenchProbe()
    perfFrames0, perfTotal0, lastPerfTotal = frames, total, total
    mem0 = readMem()
    gc0 = collectgarbage("count")
end

local function startRun(index)
    qi = index
    local item = queue[index]
    run = newRun(item) -- before the preset: the metadata is the player's screen, the settings summary is overwritten
    applyPreset(item.scenario)
    run.settings = summarySettings()
    events = Bench.Schedule(item.scenario)
    nEvents, nextEv = #events, 1
    scriptEnd = SCENARIOS[item.scenario].duration * scale
    burstMs = {}
    for i = 1, nEvents do
        burstMs[i] = 0
    end
    placeSlots()
    phase, phaseT = "settle", 0
end

local function summaryLine(scenario)
    local n, net, p99, fpsBase, fpsLoad = 0, 0, 0, 0, 0
    for _, r in ipairs(done) do
        if r.scenario == scenario then
            n = n + 1
            net = net + max(0, r.load.addonMs.mean - r.baseline.addonMs.mean)
            p99 = p99 + r.load.addonMs.p99
            fpsBase = fpsBase + (r.baseline.frameMs.mean > 0 and 1000 / r.baseline.frameMs.mean or 0)
            fpsLoad = fpsLoad + (r.load.frameMs.mean > 0 and 1000 / r.load.frameMs.mean or 0)
        end
    end
    if n == 0 then
        return nil
    end
    return format("%s x%d: net %.3f ms/frame, p99 %.3f ms, fps %.0f -> %.0f", scenario, n, net / n, p99 / n,
        fpsBase / n, fpsLoad / n)
end

local function finishAll()
    stopSampling()
    restoreSettings()
    local lines = {}
    for _, name in ipairs(ORDER) do
        lines[#lines + 1] = summaryLine(name)
    end
    resetState()
    say("done, settings restored")
    for _, line in ipairs(lines) do
        say(line)
    end
end

-- Closes the load phase: measures first (memory, heap), then the statistics, then saves the run at once.
local function finishRun()
    local memEnd = readMem()
    local gcRise = collectgarbage("count") - gc0
    local _, _, frames, total = orbs:BenchProbe()
    run.load = makePhase(loadT)
    run.kills, run.orbs = kills, orbsTotal
    run.peakLive, run.peakTextures = peakLive, peakTex
    run.burstMs = Bench.Stats(burstMs, kills)
    local driverFrames = frames - perfFrames0
    run.driverMs = driverFrames > 0 and round((total - perfTotal0) / driverFrames, 4) or 0
    run.memStartKB, run.memEndKB = mem0, memEnd
    run.gcKB = round(gcRise, 1)
    run.timeline = buildTimeline()
    local runs = ensureStore().runs
    runs[#runs + 1] = run
    while #runs > MAX_RUNS do
        remove(runs, 1)
    end
    done[#done + 1] = run
    say(format("%s done: %d kills, %d orbs, net %.3f ms/frame", run.id, kills, orbsTotal,
        max(0, run.load.addonMs.mean - run.baseline.addonMs.mean)))
    if qi < #queue then
        startRun(qi + 1)
    else
        finishAll()
    end
end

local function tick(dt)
    if phase == "settle" then
        phaseT = phaseT + dt
        if phaseT >= SETTLE * scale then
            beginBaseline()
        end
        return
    end
    if phase == "baseline" then
        phaseT = phaseT + dt
        sample(dt, 0, phaseT)
        if phaseT >= BASELINE * scale then
            run.baseline = makePhase(phaseT)
            beginLoad()
        end
        return
    end
    -- load: sample, fire what is due, then drain until nothing is flying
    loadT = loadT + dt
    local burstPrev = burstAcc
    burstAcc = 0
    sample(dt, burstPrev, loadT)
    while nextEv <= nEvents do
        local ev = events[nextEv]
        if ev.t * scale > loadT then
            break
        end
        fireKill(ev)
        nextEv = nextEv + 1
    end
    local live, pops = orbs:BenchProbe()
    local _, textures = orbs:Info()
    if live > peakLive then
        peakLive = live
    end
    if textures > peakTex then
        peakTex = textures
    end
    if arrN > 0 then
        liveArr[arrN] = live
    end
    if nextEv > nEvents and loadT >= scriptEnd and ((live == 0 and pops == 0) or loadT >= scriptEnd + DRAIN_MAX) then
        finishRun()
    end
end

local function onUpdate(_, dt)
    local ok, err = pcall(tick, type(dt) == "number" and dt or 0)
    if not ok then
        abort("error: " .. tostring(err))
    end
end

-- ---------------------------------------------------------------- commands

local function inCombat()
    if InCombatLockdown and InCombatLockdown() then
        return true
    end
    if UnitAffectingCombat then
        local ok, fighting = pcall(UnitAffectingCombat, "player")
        if ok and fighting then
            return true
        end
    end
    return false
end

local function usage()
    say("usage:")
    say("/xporbs bench all|max|aoe|typical [reps] - run the benchmark (reps 1-10, default 3; all = max, aoe, typical)")
    say("/xporbs bench stop - abort now (the current run is discarded, your settings come back)")
    say("/xporbs bench list - the last 10 saved runs")
end

local function warnings()
    local maxFps = tonumber(cvar("maxFPS"))
    local vsync = cvar("gxVSync")
    if (maxFps and maxFps > 0) or vsync == "1" or vsync == "true" then
        say("warning: an fps cap/vsync hides the real cost: turn it off for comparable numbers")
    end
    if not useProfiler then
        say("note: C_AddOnProfiler is off or missing, timing with the internal counters (see /console "
            .. "addonProfilerEnabled 1)")
    end
end

local function startBench(list, count)
    if running then
        say("already running; /xporbs bench stop aborts it")
        return
    end
    if inCombat() then
        say("not while in combat")
        return
    end
    orbs = ns.Orbs
    if not (orbs and orbs.BenchProbe and orbs.Info and orbs.Burst and OrbMath) then
        say("Orbs.lua is not ready (no BenchProbe), cannot run")
        return
    end
    recover() -- never snapshot a half-applied preset
    pickSource()
    local store = ensureStore()
    store.restore = {}
    for k, v in pairs(ns.db) do
        if k ~= "bench" then
            store.restore[k] = deepCopy(v)
        end
    end
    scale = tonumber(Bench.durationScale) or 1
    if scale <= 0 then
        scale = 1
    end
    queue, qi, repsTotal, done = {}, 0, count, {}
    local seconds = 0
    for _, name in ipairs(list) do
        for rep = 1, count do
            queue[#queue + 1] = { scenario = name, rep = rep }
            seconds = seconds + (SETTLE + BASELINE + SCENARIOS[name].duration + DRAIN_GUESS) * scale
        end
    end
    batch = stamp("!%Y%m%dT%H%M%S")
    fillArrays()
    if not sampleFrame then
        sampleFrame = CreateFrame("Frame")
        Bench.frame = sampleFrame
    end
    say(format("%d run(s), about %d min %02d s (source: %s). Stand still, do not touch the camera or mouse.", #queue,
        floor(seconds / 60), floor(seconds % 60), useProfiler and "profiler" or "internal"))
    warnings()
    running = true
    local ok, err = pcall(startRun, 1)
    if not ok then
        abort("error: " .. tostring(err))
        return
    end
    sampleFrame:SetScript("OnUpdate", onUpdate)
end

local function listRuns()
    local store = ns.db.bench
    local runs = type(store) == "table" and store.runs
    if type(runs) ~= "table" or #runs == 0 then
        say("no saved runs")
        return
    end
    for i = max(1, #runs - 9), #runs do
        local r = runs[i]
        local net = max(0, r.load.addonMs.mean - r.baseline.addonMs.mean)
        local fpsBase = r.baseline.frameMs.mean > 0 and 1000 / r.baseline.frameMs.mean or 0
        local fpsLoad = r.load.frameMs.mean > 0 and 1000 / r.load.frameMs.mean or 0
        say(format("%s %d/%d v%s net %.3f ms p99 %.3f ms fps %.0f -> %.0f", r.scenario, r.rep, r.reps, r.addonVersion,
            net, r.load.addonMs.p99, fpsBase, fpsLoad))
    end
end

function ns.commands.bench(arg)
    local word, count = string.match(arg or "", "^%s*(%S*)%s*(%S*)")
    if word == "" or word == "help" then
        usage()
    elseif word == "stop" then
        if running then
            abort("stopped")
        elseif not recover() then
            say("nothing is running")
        end
    elseif word == "list" then
        listRuns()
    elseif word == "all" or SCENARIOS[word] then
        local reps = DEFAULT_REPS
        if count ~= "" then
            reps = tonumber(count)
            if not reps then
                usage()
                return
            end
            reps = max(1, min(MAX_REPS, floor(reps)))
        end
        startBench(word == "all" and ORDER or { word }, reps)
    else
        usage()
    end
end

function Bench.IsRunning()
    return running
end

-- Events: put a crashed run's settings back at load, abort on combat and on logout / reload.
eventFrame = CreateFrame("Frame")
Bench.eventFrame = eventFrame
eventFrame:RegisterEvent("ADDON_LOADED")
eventFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
eventFrame:RegisterEvent("PLAYER_REGEN_DISABLED")
eventFrame:RegisterEvent("PLAYER_LOGOUT")
eventFrame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" then
        if name == ADDON then
            recover()
        end
    elseif event == "PLAYER_ENTERING_WORLD" then
        recover()
    elseif event == "PLAYER_REGEN_DISABLED" then
        abort("you entered combat")
    elseif event == "PLAYER_LOGOUT" then
        abort("logging out or reloading")
    end
end)

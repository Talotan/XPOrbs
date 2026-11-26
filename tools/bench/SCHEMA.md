# Benchmark data format (schema 1)

The in-game bench (`dev/Bench.lua`, never packaged) writes runs to `XPOrbsDB.bench`. `tools/bench/report.py ingest`
reads them from the SavedVariables file and writes one JSON file per release to `docs/performance/data/`.
`report.py render` turns every JSON file into `docs/performance/README.md` and its charts.

## In game: `XPOrbsDB.bench`

```lua
XPOrbsDB.bench = {
    schema = 1,
    restore = nil,  -- while a bench runs: a deep copy of the player's settings (every db key except `bench`);
                    -- restored and cleared on finish, stop, error, combat, or the next load after a /reload
    runs = {        -- newest last; at most 30 (oldest dropped). Aborted runs are never saved.
        {
            id = "20261127T101500-aoe-2",   -- date("!%Y%m%dT%H%M%S") of the batch start, scenario, rep
            batch = "20261127T101500",      -- shared by every run of one /xporbs bench command
            scenario = "aoe",               -- "max" | "aoe" | "typical"
            scenarioVersion = 1,            -- bump when a scenario's script or settings change
            rep = 2, reps = 3,
            seed = 4242,
            addonVersion = "1.4.2",         -- the toc ## Version
            build = "1.16.1", buildNumber = "12345", interface = 16001,   -- GetBuildInfo()
            date = "2026-11-27T10:15:00Z",
            screenW = 2560, screenH = 1440, uiScale = 0.71,  -- UIParent width/height and effective scale
            maxFPS = "0", vsync = "0",      -- GetCVar values as strings (nil when unreadable)
            source = "profiler",            -- "profiler" (C_AddOnProfiler) | "internal" (driver timer + Burst timer)
            settings = {                    -- the scenario preset as applied (summary for the report)
                orbShape = "starlight", size = 14, density = 100, cap = 40, flightPath = "smooth",
                style = "popstream", popMode = "nameplate", flightMode = "time", flightTime = 1.0,
                trail = true, glowIntensity = 100, sound = false,
            },
            baseline = Phase,               -- idle phase before the load (bench running, no bursts)
            load = Phase,                   -- the scripted kills, then the drain until no orb/pop is left (cap +8 s)
            kills = 37, orbs = 412,         -- bursts fired, orbs requested (sum of n)
            peakLive = 96, peakTextures = 410,
            burstMs = Stats,                -- time inside each Orbs:Burst call (debugprofilestop), n = kills
            driverMs = 0.81,                -- Orbs' own driver timer over the load phase: total ms / frames
            memStartKB = 812.4, memEndKB = 815.0,  -- GetAddOnMemoryUsage after UpdateAddOnMemoryUsage
            gcKB = 3.2,                     -- collectgarbage("count") rise over the load phase (Lua heap, all addons)
            timeline = {                    -- load phase in 0.5 s buckets (index i covers [(i-1)*step, i*step))
                step = 0.5,
                addonMs = {},               -- mean XPOrbs ms per frame in the bucket
                addonMaxMs = {},            -- worst frame in the bucket
                frameMs = {},               -- mean frame time (ms) in the bucket
                live = {},                  -- live orbs at the bucket's last frame
            },
        },
    },
}
```

`Phase`:

```lua
{
    seconds = 10.0, frames = 1004,
    addonMs = Stats,     -- XPOrbs time per frame (profiler LastTime; internal: driver + Burst ms)
    overallMs = Stats,   -- all addons per frame (C_AddOnProfiler.GetOverallMetric LastTime); nil when internal
    frameMs = Stats,     -- whole frame time from OnUpdate elapsed
}
```

`Stats` (all in ms): `{ n, mean, p50, p95, p99, max, over1, over5, over10, over16 }`. `overX` = how many samples
were above X ms (`over16` means above 16.67 ms, one 60 fps frame).
Percentiles: nearest-rank on the sorted samples (`p = s[max(1, ceil(q * n))]`).

## Published: `docs/performance/data/<version>.json`

```json
{
  "schema": 1,
  "version": "1.4.2",
  "date": "2026-11-27",
  "rig": "Ryzen 7 7800X3D, RTX 4070, 1440p",
  "build": "1.16.1 (12345)",
  "screen": "2560x1440",
  "source": "profiler",
  "scenarios": {
    "max": {
      "scenarioVersion": 1,
      "settings": {},
      "reps": 3,
      "summary": {
        "netMeanMs": 0.98, "meanMs": 1.01, "baselineMeanMs": 0.03,
        "p95Ms": 1.6, "p99Ms": 2.1, "maxMs": 2.7,
        "over5": 0, "over16": 0,
        "frameMsBaseline": 9.9, "frameMsLoad": 10.9, "fpsBaseline": 101.0, "fpsLoad": 91.7,
        "burstMeanMs": 0.12, "burstMaxMs": 0.4,
        "peakLive": 160, "peakTextures": 810, "kills": 120, "orbs": 9600,
        "memDeltaKB": 2.6, "gcKB": 3.2,
        "shareOfAppPct": 9.3
      },
      "repsDetail": [{ "netMeanMs": 0.97, "p99Ms": 2.0, "fpsLoad": 92.1 }],
      "timeline": { "step": 0.5, "addonMs": [], "addonMaxMs": [], "frameMs": [], "live": [] }
    }
  }
}
```

- Summary values are the **median across reps** of each rep's value. `netMeanMs` = load `addonMs.mean` minus baseline
  `addonMs.mean` (never below 0). `fps*` = 1000 / `frameMs.mean`. `shareOfAppPct` = 100 * load addon mean / load
  frame mean. `timeline` is the rep whose `netMeanMs` is the median.
- **Never** written: account names, character names, realm, file paths, the SavedVariables location.
- Comparisons across releases only use files with the same `rig` and, per scenario, the same `scenarioVersion`.

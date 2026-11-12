# M3 probe results

**Session:** 2026-11-13, WoW Forever 1.60.1, Wetlands, level 22 Shaman (Talotan), XPOrbs v0.4 with `debug` and `probe` on.

**Data:** 6 kills in about 10 minutes, all mobs around the player's level, nameplates visible. There was no grey mob, no quest turn-in and no rested XP.

## Answers
| Question | Answer | Evidence |
|---|---|---|
| Is the `UNIT_DIED` GUID readable? | **Yes**, every time (11 of 11 events, including deaths that weren't ours) | `UNIT_DIED guidReadable=true` |
| Is the plate GUID readable at add time? | **Yes** | `PLATE_ADDED guidReadable=true nameReadable=true` |
| Do our kills match a tracked plate? | **Yes, 6 of 6 at tier 1** | `matched=true`, `STATS tier1=6` |
| Is plate geometry readable in combat? | **Not answered.** The sampler stored zero samples and didn't count a single secret value either, so `sample()` failed silently: no plate, a `GetCenter` error, or nil. | `geomOK=0 geomSecret=0`, `hadPos=false` on every `PLATE_REMOVED` |
| Does the chat XP equal the XP-bar delta? | **Yes, 6 of 6** (no rested or group XP in the sample) | `AMOUNTCHECK ... equal=true` |
| Is `UnitIsDead` readable at plate removal? | **Yes**. True for our kills, false for plates that scrolled out of range | `deadReadable=true deadAtRemoval=true` |

## Event order per kill (consistent across all 6)
1. `CHAT_MSG_COMBAT_XP_GAIN` and `UNIT_DIED` fire in **the same frame** (same `GetTime()`), with chat logged first.
2. `PLAYER_XP_UPDATE` arrives 0.0–0.4 s later.
3. `NAME_PLATE_UNIT_REMOVED` (dead) arrives about 0.3 s after the death.

Effects on the design:
- The plate is still alive when `UNIT_DIED` fires, so tier 1 is the main path and tier 2 is a backup.
- `chatWait = 0.5` and `deltaWait = 0.4` are adequate. Two deltas landed near 0.4 s, but the kill had already been emitted, so the "owed" mechanism claimed them.
- **There is no need to delay the burst for position**, because the plate is live at that moment.

## Gate decision
- The roadmap gate (at least 9 of 11 kills at tier 1 or 2, grey mob dropped, quest as `other`) is **only partly tested**: 6 of 6 kills reached tier 1, and the grey-mob and quest cases weren't run. Attribution passes.
- **Geometry is the real gap.** Every burst would have started at screen centre. The same bug is why `/xporbs test` ignored the target and used the cursor.

## Fix in v0.5 (this commit)
- **Roadmap fallback (c):**
  1. Measure the plate (method A).
  2. If that fails with an error or nil, measure a pooled 1×1 proxy frame anchored CENTER-to-CENTER on the plate (method B). ForeverCombatText anchors its text frame to the plate the same way.
- **Late plates:** if `GetNamePlateForUnit` returned nil at add time, the sampler fetches the plate again.
- **Forbidden plates:** skipped and counted.
- **Diagnostics:**
  - New counters `okA okB noPlate forbidden errA errB nilA nilB`, shown in `/xporbs status` (`geom:` line) and logged as `GEOM ...` on each plate removal.
  - The first error message per method is logged once as `GEOM_ERR method=<A|B> err=...`.

## Re-probe needed (short)
1. `/reload`.
2. Target a mob, then `/xporbs test 10`. The orbs should start at the mob's plate.
3. Kill 2–3 mobs, then `/xporbs status` and `/reload`.
4. Then read the `geom:` line and any `GEOM_ERR` lines, and check `BURST ... hadXY=true origin=plate`.

**If both methods fail:** the fallback is the last target position cached from earlier, readable samples, or screen centre. That decision would be made then.

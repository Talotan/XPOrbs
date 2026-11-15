# Changelog

## 0.14
- **Glow intensity** (`db.glowIntensity`, percent 25-200, step 5, default 100), in Arrival glow after Shape. With k = percent / 100 the flash alpha is multiplied by k (clamped to 1) and its size by 0.8 + 0.2k, for both shapes (`OrbMath.GlowIntensity`). Dimmed while Show glow is off.
- **Circular shape aims at the frame centre whatever Show glow says.** The shape now describes the target frame (bar or round), so `aimCentre` only looks at `db.glowShape`. The Shape row and its description no longer dim when Show glow is off. New description: "Horizontal: orbs land on the bar's fill edge. Circular: orbs land on the centre of a round frame such as a portrait."
- **Offset X / Offset Y** (`db.glowOffsetX/Y`, -100..100 px, step 1, default 0, UIParent units) shift the landing point for both shapes. Applied inside `Target:GetDestination` (`OrbMath.ApplyOffset`), so kills, `/xporbs test` and the flash agree; the bottom-centre fallback is shifted too.
- A sentence under the XP bar picker says why you would use it.
- Typed values may end in `px`. The panel content grows to 1070 px; the Style, XP bar and Advanced sections moved down.
- Design re-review fixes: top rule under the title, footer rule and Reset all share the right edge (x 568), 20 px radios whose label is clickable, shape description width 280, a y cursor replaces literal row positions, section "Arrival glow" renamed "Arrival".
- DB schema unchanged (4): `deepFill` adds the three new keys.
- Tests: `tests/test_v014.py`.

## 0.13
- **Options panel rework** (layout from `docs/review-v012/review.md`). Fixed title and footer, a scrolling body (`ScrollFrameTemplate`, falling back to `UIPanelScrollFrameTemplate`, then a bare scroll frame with mouse-wheel scrolling) holding one column of rows: a label column at x 32 and a control column at x 260, slider value at 472 and a reset gutter at 548. Sections: General, Look, Arrival glow, Style, XP bar, Advanced. Every label is `GameFontHighlight`; no `GameFontHighlightSmall` anywhere. Rested tint moved next to Rested colour, Debug log moved to Advanced.
- **Style radios** (`UIRadioButtonTemplate`, falling back to a check button) each with their own grey description line underneath.
- **Dimming:** Rested colour while Rested tint is off; the glow shape while Show glow is off; the Orb colour swatch while Class colour is on.
- **Per-row reset buttons** (revert icon, atlas `transmog-icon-revert` with a texture fallback), shown only when the value differs from the default (floats within 1e-4, colours within 0.005, `targetFrame` when set). The gutter is fixed, so nothing shifts. Tooltip "Reset to default: <value>". The panel refreshes after `/xporbs style|pop|debug|pick clear|reset` too.
- **Reset all to default** is in the footer and asks first (`StaticPopupDialogs.XPORBS_RESET_ALL`). `/xporbs reset` is unchanged (immediate). Schema version, log and debug are kept.
- **Right-click a slider's value to type one** (`InputBoxTemplate`). Enter or losing focus applies the nearest permitted value (`OrbMath.Snap`: clamp and snap to the step), Escape cancels, junk restores the old value. Hovering the value turns it white and shows "Right-click to type a value (min-max)".
- **Class colour** (`db.classColor`, default off): normal orbs, their sparkle, trail and the arrival flash use the player's class colour (`C_ClassColor.GetClassColor`, then `RAID_CLASS_COLORS`, then `db.color`); resolved once per burst. Rested orbs keep the rested colour.
- **Arrival glow options:** `db.glow` (default on) turns the arrival flash off; `db.glowShape` is `bar` (default) or `round`. Round reuses `media/orb` as a circle of diameter `min(w,h)*1.3` clamped to [32, 160] (orb size x 6 without a frame size), and the orbs then aim at the **centre** of the destination frame (`Target:GetDestination(true)`; `Target.lastW/lastH` hold its size) instead of the XP fill edge. The aim only follows the shape while Show glow is on.
- **Picker highlight:** while `/xporbs pick` is armed, a ~16 Hz updater outlines the frame a click would pick (`Target.PickName`, now also returning the frame) with a translucent blue fill, border and name label on one of our own `TOOLTIP`-strata frames (`SetAllPoints`, `EnableMouse(false)`, excluded from `isOurs`). Anchor errors are pcall'd; it hides on every disarm.
- The panel's **Test burst** includes rested orbs when Rested tint is ticked (as `/xporbs test 5 rested`). The slash command is unchanged.
- "Orb multiplier" is now "Orb quantity multiplier".
- DB schema unchanged (4): `deepFill` adds `classColor`, `glow` and `glowShape` to older databases.
- Tests: `tests/test_v013.py`; `stubs_m5.lua` gained scroll frames, enable/disable, edit boxes, tooltip, static popups, atlas and class-colour stubs.

## 0.12
- **Options panel (M5).** New `Options.lua`, last in the toc: a canvas category "XPOrbs" (Esc > Options > AddOns, or `/xporbs options`) built from plain `CreateFrame` controls. General: enabled, rested tint, trail, quest bursts, show at max level, debug. Look: sliders for orb multiplier (25-400 %, step 25), max orbs (5-80), size (8-32), flight time (0.4-1.5 s, step 0.05), each with its value shown, plus colour swatches for the orb and rested colours (`ColorPickerFrame:SetupColorPickerAndShow`; cancel restores the old colour; swatches are hidden when the picker is missing). Style: popstream / crossfade / stream as three radio-style check buttons with a hint. XP bar: read-only line with the frame in use, and buttons "Pick XP bar frame", "Test burst" (`/xporbs test 5`) and "Reset". Every control writes `XPOrbsDB` directly, so changes apply to the next burst, and the panel re-reads the db whenever it is shown. Without the `Settings` API there is no panel and `/xporbs options` prints a fallback.
- **`/xporbs pick`** (in `Target.lua`): arms for 15 s, registers `GLOBAL_MOUSE_DOWN` only while armed. Left click saves the first named frame at or above the one under the mouse (walking `GetParent`); right click cancels; other buttons are ignored. UIParent, WorldFrame and our own frames never count, an all-unnamed chain saves nothing. `/xporbs pick clear` returns to auto-detect, and `/xporbs status` shows the picked frame. A picked frame that is missing or hidden still falls back to auto at burst time.
- **`/xporbs reset`** restores every default (the db schema version, debug flag and log are kept), refreshes the panel and confirms.
- `Orbs.overlay` is exposed so the picker can recognise our own frames. DB schema unchanged (4).
- Tests: `tests/test_m5.py` and `tests/stubs_m5.lua` (Settings, slider and check-button stubs, ColorPickerFrame, `GLOBAL_MOUSE_DOWN`). `test_rested_orbs_start_later_and_bigger` no longer depends on rand() order across tests.

## 0.11
- **No-mouseover kills start the stream at the mob.** `MobEstimate` cursor weight 0.35 -> 0 (an idle cursor said nothing about the mob and pulled P-hat about 230 px off); the code path stays configurable and the source label is `default` without a sample. popstream's stream origin is always P-hat when an estimate exists (the portrait is only the no-estimate fallback, and `stream` style keeps portrait -> centre). `CONFIDENT` and `Target:TargetFrameVisible` removed (dead).
- **crossfade is catchable and paced like popstream.** Each orb blooms at the plate as copy A only (`XF_HOLD` 0.22 s, ring radius `XF_BLOOM_R` 18 px, size x1.5 easing to 1, `XF_FADE_IN` 0.06 s), then flies for `XF_FLIGHT` 1.2 x flightTime with a gentler launch (`XF_EASE_OUT` 0.25, via the new optional `OrbMath.PopEase(p, w)` argument). Tight `POP_STREAM_SPREAD/LIFT` and `STAGGER_POP`. Equal-power A/B fade (cos/sin) over flight p 0.12-0.30.
- Pop ring angles interleave by the golden ratio (`OrbMath.RingAngle`) so rested orbs mix around the ring. The stream's angles are unchanged.
- Arrival flash tinted 45% towards white (`FLASH_WHITE`).
- Logs: `BURST origin=` names what Orbs uses (`estimate` for crossfade kills); `pop=` renamed `plate=` (it only ever meant a plate exists); the per-removal `GEOM ...` line is gone (counters remain in `/xporbs status`).
- DB schema unchanged (4).

## 0.10
- **Cursor-informed mob estimate.** New `logic/MobEstimate.lua` (pure) and `Mouseover.lua` (sampler). While you hover a hostile unit (`UPDATE_MOUSEOVER_UNIT`, plus a 10 Hz poll only while a unit is moused over) the cursor position is remembered per GUID (cap 20, pruned after 5 s). When a mob dies its estimated screen point P-hat blends a fresh sample (+40 px head offset; full weight up to 1 s, linear to 0 at 3 s) with 0.35 cursor + 0.65 default (screen centre x, 0.58 H). No GUID or name is ever logged.
- **popstream:** pop and stream now read as one effect. Pop 0.55 s, less upward drift (12), ring 30-55 px around a plate anchor 20 px lower, orbs gather then launch (exit phase from p=0.45, 140 px) along the direction from P-hat to the stream origin, stream delay 0.30 s. The stream after a pop is tighter (stagger 0.08, spread x0.45, lift 0.10, fade-in 0.15). Stream origin: P-hat when mouseover confidence is at least 0.7; else the target-frame portrait while that frame is visible; else P-hat (the frame hides on death).
- **crossfade:** copy A is anchored to the plate BOTTOM; the curve starts at P-hat; the fade window is 0.12-0.30 (was 0.25-0.60).
- Arrival flash is bigger and brighter (alpha 0.6 + 0.08/arrival, 12x size wide, aspect 7, 0.4 s). Pop orbs slightly bigger (1.2) with a lighter underlay (0.35).
- `BURST` log line ends with `est=mouseover|cursor|default|none w=0.00`; `/xporbs test` prints `est= w=` and uses its target's estimate. `/xporbs status` has a `mouseover:` line.
- DB schema unchanged (4).
- In-game check list: see HANDOFF "NEXT SESSION".

## 0.9 (in progress)
- Kill styles (`db.style`, `/xporbs style popstream|crossfade|stream`): **popstream** (default) pops a few orbs at the dead mob's nameplate, then streams from the target frame to the bar; **crossfade** flies the orbs from an estimated mob position, drawing a plate-relative copy that fades into the normal screen-space copy; **stream** is the old behaviour. `/xporbs pop on|off` is an alias.
- Plates are restricted regions: nothing is ever measured. Pop/crossfade frames have a single anchor (the plate) and everything else is positioned relative to them.
- `/xporbs test [pct] [rested] [style]` follows the style, pops on the target's plate if there is one, and prints `pop= stream= style=`.
- Stream origin is always target frame, then screen centre. Removed: `db.origin` and `/xporbs origin`, `/xporbs lab` (`Lab.lua`), the StatusBar anchored-flight path, `OrbMath.AnchoredWeights`. DB schema 4.

## 0.8
- Kills are live (M4): probe off by default, bursts gated by enabled / max level (showAtMax) / questBursts; quest bursts from screen centre. DB schema 3.
- Target-frame origin is the default and works with a hidden frame (last good result cached).
- Anchor errors are no longer swallowed: `ANCHOR_ERR` log lines, `lastAnchorErr` in `/xporbs status`, `/xporbs test` reports `anchor failed: <msg>`.
- `/xporbs lab`: five anchoring/animation experiments on the target's nameplate.

## 0.7
- Re-probe: nameplates can't be measured on Forever (plate and proxy GetCenter both error every time). Measuring now switches itself off after 20 failures; `geom:` shows `measurable=` and the last error.
- Anchored origin: orbs start at the mob's plate without measuring it. The path is rewritten as weight*P + known offset, and two invisible StatusBars spanning UIParent's corner to the plate produce the weighted anchor point.
- Target-frame origin (Talotan's idea): fallback when there is no plate, and selectable with `/xporbs origin plate|frame`; `/xporbs test [pct] [rested] [frame|plate]`.
- PlateReused: orbs anchored to a plate that gets reassigned fade out.

## 0.6
- Visual pass from the design review: deeper blue {0.20,0.50,1.00}, magenta rested {1.0,0.30,0.85} arriving as a later, bigger second wave, dimmer sparkle, core+halo orb texture, dark BLEND underlay for bright zones, pop-then-home cubic path, connected tapered trail, rested-tinted arrival flash.
- Orb count is now a compressed curve: n = (3 + 5*sqrt(% of level)) * multiplier; a normal kill shows ~7 orbs.
- DB schema 2: old default colours migrate to the new ones; customised colours are kept.

## 0.5
- Probe findings (docs/probe-results.md): GUIDs readable, 6/6 kills tier 1, chat XP equals bar delta, but no plate position was ever sampled.
- Plate sampling: re-fetch late plates, skip forbidden plates, fall back to a proxy frame anchored to the plate when the plate can't be measured, per-method failure counters (`geom:` status line, `GEOM`/`GEOM_ERR` log lines).

## 0.4
- M3: nameplate tracker with last-known screen position and a 2 s held list; kill pipeline (UNIT_DIED tier 1, plate-removed-while-dead tier 2, target/centre fallback) feeding KillMatcher; probe mode logs bursts instead of drawing; AMOUNTCHECK compares chat XP with the XP-bar delta.

## 0.3
- M2: orb renderer (pooled additive textures, Bezier flight, sparkle + trail, rested purple, arrival flash on the bar's fill edge), XP-bar destination lookup with fallback, `/xporbs test [pct] [rested]`, orb status line. Textures generated by `tools/make_textures.py`.

## 0.2
- M1: pure logic modules: XPParse (real enUS XP-gain strings, rested/penalty/unnamed/quest variants), OrbMath (count, rested split, bezier, easing, fill edge, XP delta with level-up wrap), KillMatcher (death/chat/delta pairing, tiers, owed deltas). 68 new tests.
- Core: `ns.commands` and `ns.statusProviders` so modules register slash commands and status lines; `probe` default for M3.
- Placeholder Plates/Target/Orbs/Kills files in the toc so M2 and M3 can run in parallel.

## 0.1
- M0: scaffold, `.toc`, Core skeleton (defaults, DB init, debug log ring, `/xporbs` dispatcher), pytest + lupa harness.

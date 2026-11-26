# Changelog

## 1.4.1 (2026-11-26)

### Changed

- Relative speed (orbs always arrive after the set flight time) is the default Speed type again. Settings from 1.4.0
  switch back to it once; pick Constant speed in the Flight tab if you prefer it.

### Fixed

- Development only: a test that could fail at random on the build server is fixed. Nothing changes in game.

## 1.4.0 (2026-11-26)

### Added

- Orb shapes: Starlight (the existing look, still the default), Bubble, Retro and Crackle. Pick one in the Look tab
  or with `/xporbs shape`.
- Each shape keeps its own size, quantity multiplier and opacity.
- Overlap Type for Bubble, Retro and Crackle: Glow (orbs brighten where they overlap) or Solid (opaque orbs that stack).
- Shape options: Pulsing for Bubble (also `/xporbs pulse`), Sparkle for Retro, Crackle speed (50 to 200 %) for
  Crackle. Retro's size is a pixel size from 1 to 5 px.
- Orb opacity (20 to 100 %) and Trail opacity (0 to 100 %).
- Speed type in the Flight tab: Constant speed (Flight speed, 50 to 250 %) or Relative speed (Flight time). Constant
  speed is the new default; a saved flight time becomes the matching flight speed.
- A preview window next to the options shows orbs with the current look: 8 at a 100 % quantity multiplier, 2 to 24
  across its range. A Cluster tickbox piles them up as they look after a kill.
- The test target window can be moved anywhere with its move icon or by dragging the window, and put back with its
  reset icon.
- Two chime voices: Swish and Pixel.

### Changed

- The options are in tabs: General, Sound, Look, Flight, Arrival. The kill style and the flight settings are in the
  Flight tab, with the kill style options in their own box. Flight style is now called Flight pathing.
- Sliders and dropdowns use the Forever settings style, with arrow buttons, and the extra windows use the Forever
  border.
- Orb quantity multiplier range: 25 to 300 % (was 25 to 400 %). Higher saved values become 300 %.
- Chime volume range: 100 to 250 % (was 25 to 250 %). Lower saved values become 100 %.
- The chime is on by default for new installs. Existing settings keep their choice.
- Rested tint and Rested colour are one row, Rested orb colour: a tickbox and its colour swatch.
- Orbs are drawn above other windows, including popup dialogs, so they stay visible over the options and the test
  target.

### Fixed

- Very dark orb colours keep their hue, and their trails show as a darker shadow instead of disappearing.
- Trails no longer break into separate dots at high flight speeds.
- The test target retries loading its model if it appears blank.
- Reset all to default keeps the minimap button where you put it.
- The calibration window's status line (`/xporbs calib`) no longer runs past the window's edge.

## 1.3.0 (2026-11-24)

- **Works with more UIs.** XP bars from EllesmereUI, FlareUI, DaylightUI and Smooth Experience Bar are found
  automatically, and orbs land on the bar's fill point. The default bar is found even when it's showing a
  reputation. The frame picker now picks the bar itself rather than the panel around it.
- **Can't find your XP bar?** A small window offers to pick it, with the glow shape, offsets and a test. Open it any
  time with `/xporbs setup`. There is a new **Vertical** glow shape, used automatically on vertical bars.
- **Flight styles:** **Smooth** (as before), **Chaos** (orbs dart like fireflies) and **Helix** (orbs spiral in
  pairs). Pick one from the Flight style dropdown or with `/xporbs path`.
- **Orbs stay on screen.** With an XP bar near the top of the screen, the orbs sweep up into it from the side instead
  of arcing off the top.
- **Chime volume** from 25% to 250%, plus a play button next to the Voice dropdown to hear a sample.
- **Quest and exploration XP** start where they happen: the button you clicked or the quest window, and the zone
  name on screen. Each has its own on/off switch.
- **Test target:** while the options are open, Hogger (Gamon for the Horde) stands next to them. Press **Test Kill**
  to see your settings in action. Drag him to rotate him.
- Popstream (Direct) pops bigger and goes straight into the stream, and its start no longer jumps around when the
  mob's position is unknown.
- The options page is reorganised: General, Sound, Look, Style, Arrival, Advanced.
- `/xporbs` on its own opens the options. Shift + right-click the minimap button to hide it.
- Fixed the setup and calibration windows sticking to the mouse after being dragged.

## 1.2.0 (2026-11-19)

- Kill styles are now three, each saying whether it uses the nameplate (your saved style carries over):
  - **Popstream** (default), with its pop either on the nameplate (as before) or **Direct**, a pop at the mob's
    estimated position that flows straight into the stream and works with nameplates off.
  - **Crossfade**: the orbs pop on the nameplate and fade away, then reappear just above the bar.
  - **Direct Stream**: a plain stream that now starts at the mob instead of the target frame.
- New "Zoom-scaled spread" option (on by default): pops and stream starts spread wider when the camera is zoomed in
  and tighter when zoomed out.
- Pops now sit on the mob's body rather than its nameplate, adjusted for camera zoom. `/xporbs calib` lets you
  fine-tune it; `/xporbs zoomanchor off` restores the old position.
- When you didn't mouse over the mob, the orbs start from a small area around the best guess instead of one point.
- Kills in instances, where the game hides the kill message from addons, now pop at the mob instead of streaming from
  the middle of the screen.
- New minimap button: click to open or close the options, right-click to turn the orbs on or off. Hide it in the
  options or with `/xporbs minimap off`. XP Orbs is also in the minimap's addon menu and has an icon in the AddOns
  list.

## 1.1.0 (2026-11-18)

- Orbs now match the XP bar's colours: purple normally, blue when rested. Saved colours that were still the old
  defaults update automatically; colours you changed are kept.
- The default flight time is now 1 s (it was 0.75 s, and a saved 0.75 s updates too).
- "Kill orbs at max level" now sends a small burst of orbs to your portrait when you kill something you were fighting.
- New optional chime as orbs arrive (off by default), with two sounds, glass (the default) and coin: pick one in
  the options panel or with `/xporbs sound glass|coin`. Both are quiet and wobble a little in pitch.
- Big pulls now show orbs for every kill: the orb pool holds two full bursts, and a crowded burst drops its trails or
  draws fewer orbs instead of leaving the later kills with none.
- Fixed the rare pop that appeared on the wrong mob, and the doubled orbs after XP was briefly unreadable.
- The gain that takes you to max level now shows its orbs.
- Level-ups are now read from the XP bar itself, so they no longer depend on event order.
- Damaged or hand-edited saved settings are repaired when the game loads them, and a failing frame can no longer
  leave orbs stuck on screen.
- The frame picker no longer picks nameplates.
- `/xporbs pick` now works on XP bars that ignore the mouse (such as EnhanceQoL's), and `/xporbs pick <FrameName>`
  sets one by name. EnhanceQoL's XP bar is also detected automatically, and orbs land on the bar's actual fill point,
  whichever way it fills.
- New `/xporbs perf` (memory and frame time) and `/xporbs test stress [n]` for checking performance.
- Now also on Wago.

## 1.0.1 (2026-11-15)

- The addon now shows as "XP Orbs" in the AddOns list and the options panel. The folder, `/xporbs` and saved settings
  are unchanged.
- First release on CurseForge.

## 1.0.0 (2026-11-15)

First public release, for WoW Forever (Interface 16001).

- XP gains send a burst of orbs to your XP bar. The number of orbs scales with the share of the level the gain gave.
- Kills start the burst at the mob: a short pop on its nameplate, then a stream from where the mob was on screen.
  Quest and other non-kill XP start a little above the centre of the screen.
- Rested XP is shown in a second colour.
- Three kill styles: `popstream` (default), `crossfade` and `stream`.
- An options panel (Esc > Options > AddOns > XPOrbs) covers orb quantity, maximum orbs, size, flight time, colour or
  class colour, rested colour, landing offset, the arrival glow and its intensity, and the kill style.
- `/xporbs pick` lets you click any frame as the destination, for UIs that replace the default XP bar.
- `/xporbs status`, `/xporbs test` and an optional debug log help with bug reports. The log never records mob names or
  GUIDs.

# XP Orbs

[![License](https://img.shields.io/github/license/Talotan/XPOrbs)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Talotan/XPOrbs)](https://github.com/Talotan/XPOrbs/releases)

A World of Warcraft addon for the Forever client. When you gain experience, a burst of orbs flies to your XP bar. For a
kill the burst starts at the mob. The orbs match the game's XP bar: purple normally, blue when the XP is rested.

![Orbs flying from a killed mob to the XP bar](docs/images/hero.gif)

The number of orbs grows with the share of the current level that the gain gave, so a big kill looks bigger than a
trivial one.

## Focus

XP Orbs does one thing and tries to do it as well as possible: the best, most efficient and most beautiful XP orbs it
can draw. They should feel like part of the default UI and work alongside as many other addons as possible. Features
unrelated to XP orbs stay out, so the addon stays light. What's planned is in the [roadmap](ROADMAP.md).

## Compatibility

- WoW Forever only (`## Interface: 16001`). It has not been tested on Retail or any Classic client.
- The English client is tested. Other languages should work, because the XP message patterns are built from the
  client's own strings, but this is untested.
- The default UI XP bar; the XP bars of EllesmereUI, FlareUI, DaylightUI, Smooth Experience Bar and EnhanceQoL are
  detected automatically; any other frame you pick with `/xporbs pick`.

## Installation

### CurseForge

Open the CurseForge app, choose the WoW Forever flavor (instance), and search for XP Orbs, or use the
[CurseForge page](https://www.curseforge.com/wow/addons/xp-orbs). Some users had to reinstall the CurseForge app before
the Forever flavor appeared.

### Wago

Open the Wago app, choose WoW Forever, and search for XP Orbs, or use the
[Wago page](https://addons.wago.io/addons/ZKbqJJ61).

### Manual

1. Download `XPOrbs-<version>.zip` from [GitHub Releases](https://github.com/Talotan/XPOrbs/releases).
2. Extract it into `World of Warcraft\_forever_\Interface\AddOns\` so that you end up with
   `AddOns\XPOrbs\XPOrbs.toc`. The folder must be named `XPOrbs`.
3. `/reload` or restart the game.

## Usage

Settings are saved per account in `XPOrbsDB`. The options panel is under Esc > Options > AddOns > XP Orbs, or
`/xporbs options`. The minimap button and the XP Orbs entry in the minimap's addon menu open it too (click again to
close it); right-click either one to turn the orbs on or off.

![The XP Orbs options panel](docs/images/options.png)

| Command | What it does |
|---|---|
| `/xporbs help` | List the commands. |
| `/xporbs options` | Open the options panel. |
| `/xporbs status` | Print the version, the settings that matter, and the state of each part of the addon. |
| `/xporbs test [pct] [rested] [popstream\|crossfade\|stream] [nameplate\|direct] [smooth\|chaos\|helix]` | Fire a test burst. `pct` is the percent of a level it represents (default 5, up to 1000). `rested` colours part of it as rested. A style name overrides the saved style for this burst, `nameplate` or `direct` picks Popstream's pop, and `smooth`, `chaos` or `helix` overrides the flight path. |
| `/xporbs test stress [n]` | Fire `n` test bursts (default 20, up to 100) spread over about 2 seconds, to see how a big pull looks and runs. |
| `/xporbs perf [reset]` | Print the addon's memory use, the average and worst time of an orb frame, and how much of the orb pool is in use. `reset` zeroes the frame timings. |
| `/xporbs style popstream [nameplate\|direct]` | Set the kill style to Popstream, optionally with its pop on the nameplate or direct. With no argument, print the current style. |
| `/xporbs style crossfade\|stream` | Set the kill style to Crossfade or Direct Stream (`stream`). The older names still work: `streampop` is Popstream (Direct), and `wide` is Popstream (Nameplate) with zoom-scaled spread on. |
| `/xporbs path smooth\|chaos\|helix` | Set how orbs fly: `smooth` (the default), `chaos` or `helix`. With no argument, print the current path. |
| `/xporbs wide on\|off` | Turn the zoom-scaled spread on or off (on by default). |
| `/xporbs unknown wide\|off` | Where orbs start when the mob's position is unknown: `wide` (the default) spreads them over an area that scales with camera zoom, `off` starts them at one point. |
| `/xporbs pop on\|off` | Shortcut: `on` sets Popstream, `off` sets Direct Stream. |
| `/xporbs pick` | Arm the frame picker, then left-click the XP bar (it also works on bars that ignore the mouse). Right-click or wait 15 s to cancel. |
| `/xporbs pick FrameName` | Set the XP bar by frame name, for example `/xporbs pick EQOL_XPBar`. Find a name with `/fstack`. |
| `/xporbs pick clear` | Forget the picked frame and go back to auto-detection. |
| `/xporbs setup` | Open the XP bar setup window: pick the bar, set the glow shape and landing offset, and test. |
| `/xporbs zoomanchor on\|off` | Turn the zoom-aware anchor on or off (on by default): plate effects sit on the mob's body, using the camera zoom to work out how far below the nameplate that is. |
| `/xporbs calib [off\|reset\|fit\|save]` | Open the anchor calibration panel: target a mob, nudge the marker onto its body, save a point, and repeat at a few zooms. `reset` restores the default curve. |
| `/xporbs minimap on\|off` | Show or hide the minimap button. |
| `/xporbs sound on\|off\|coin\|glass` | Turn the arrival chime on or off (off by default), or pick its sound: `coin` or `glass` (either also turns it on). With no argument it shows the current state and volume. |
| `/xporbs sound volume N` | Set the chime volume in percent, 25 to 250 in steps of 25 (default 100); plays a sample if the chime is on. |
| `/xporbs debug on\|off` | Turn the debug log on or off. |
| `/xporbs debug maxlevel on\|off` | Pretend to be at max level until you reload, to try the max-level orbs below the cap. Never saved. |
| `/xporbs reset` | Restore every setting to its default. |

The panel has these settings: enable, trail, quest bursts, kill orbs at max level, the arrival chime with its sound (Coin or Glass) and volume, and the minimap button; orb quantity,
maximum orbs per burst, orb size and flight time (1 s by default); orb colour (or your class colour), rested tint and rested colour; the shape of the
target frame, a landing offset, and the arrival glow with its intensity; the kill style and the zoom-scaled spread; the XP bar frame; and the
debug log. The panel also has a test button and a reset button.

The default colours are a purple for normal orbs and a blue for rested ones, picked to match the Forever XP bar. If
you had kept the old default colours or the old 0.75 s flight time, they update to the new ones automatically; colours
and times you changed yourself are left alone.

### Max level

The game gives no XP at the level cap, so nothing is drawn there unless "Kill orbs at max level" is on. With it on,
each kill of a mob you were fighting (your target, or a mob that had you on its threat list in the last 10 seconds)
sends a small burst of 6 orbs to your portrait, ending in a round glow. If you picked a frame with `/xporbs pick`, the
orbs go to that frame instead.

### Chime

With "Chime when orbs arrive" on, orbs make a quiet sound as they land: up to six per burst, at most one every 70 ms,
each a slightly different pitch picked at random. Pick the sound in the options panel ("Sound") or with
`/xporbs sound glass` or `/xporbs sound coin`: **Glass** (the default) is a glassy tink, **Coin** is a soft coin clink.
Choosing one in the panel plays a sample.

**Chime volume** is a slider under the Sound choice (25 to 250 %, default 100 %; also `/xporbs sound volume N`).
Moving it plays a sample note. The game has no per-sound volume, so the addon ships every chime pre-rendered at each
level (`media/chime/<percent>/`) and plays the file for the level you picked.

The sounds are original, generated by `tools/make_sounds.py`. If the game
refuses to play one, the addon logs it once and keeps quiet until you run `/xporbs sound on` again.

## How it works

### Kill detection

Several events describe one kill, and a small matcher (`logic/KillMatcher.lua`) pairs them so that each gain
produces exactly one burst.

- `UNIT_DIED` carries the dead unit's GUID. If it matches a tracked hostile nameplate, the kill has a plate (tier 1).
- If the nameplate is removed while the unit is dead and no `UNIT_DIED` matched, that also counts as a death (tier 2).
- `CHAT_MSG_COMBAT_XP_GAIN` carries the mob name and the XP amount. The message patterns are built from the client's
  own `COMBATLOG_XPGAIN_*` strings, so they follow the client's language (only English has been tested). A message
  with no death to pair with (for example, the GUID was unreadable) still produces a burst after 0.5 s, just without
  a plate (tier 4).
- `PLAYER_XP_UPDATE` gives the XP delta. A delta equal to a pending kill's amount claims that kill, so it is not also
  shown as a second burst. A delta that no kill claims within 0.4 s is non-kill XP.

`COMBAT_LOG_EVENT_UNFILTERED` is not available to addons on this client, so the addon never uses it.

### Orb count

The count depends on the gain as a share of the XP needed for the level:

```
pct = gain / xpToLevel * 100
orbs = round((3 + 5 * sqrt(pct)) * quantity / 100), clamped to 1 .. maximum
```

`quantity` defaults to 100 and the maximum to 40. For example, 5% of a level gives 14 orbs, 10% gives 19 and 25% gives
28. When the formula asks for more than the maximum, the orbs are drawn larger instead, up to 1.5 times.

### Where orbs start

Nameplates are restricted regions on this client. An addon cannot read their position or size, and a frame anchored
to a plate cannot also be anchored to anything else. XP Orbs therefore never measures a plate, and it works around the
restriction in two ways.

- It draws a short burst on a tiny frame that is anchored to the plate and nothing else. Because the frame follows the
  plate, the burst appears on the mob wherever it is on screen. Nothing on that frame is ever measured. With the zoom
  anchor on (the default), the frame hangs below the plate by `5 + 175 / max(zoom, 5)` px, so the burst sits on the
  mob's body; the curve was fitted to in-game calibration and can be re-fitted with `/xporbs calib`.
- It estimates where the mob was on screen. While you hover a hostile unit, the addon records the cursor position
  against the unit's GUID. When that unit dies, a sample from the last second or so is used as it is, and its weight
  fades to zero at 3 seconds. The cursor sits on the body, which is where the zoom anchor aims too; with the anchor
  off (or the camera zoom unreadable) the sample is raised by 40 px to meet the plate instead. Without a usable sample
  the estimate is a fixed point at the horizontal centre of the screen and 58% of its height.

The stream then flies in screen space from that point to the destination.

### Styles

There are three kill styles. Every one starts from the estimated position; they differ in whether they pop and
whether the pop needs the mob's nameplate.

- **Popstream** (default): a pop of orbs at the mob, then a stream to the bar. It has two versions:
  - **Nameplate** (default): up to 12 orbs pop out around the nameplate for about half a second, then the stream
    flies from the estimated position. Without a nameplate (hidden or off screen), only the stream is drawn.
  - **Direct**: a quick pop at the estimated position that flows straight into the stream, nearest to the bar first.
    Never uses the nameplate, so it looks the same with nameplates off.
- **Crossfade**: the orbs pop on the nameplate, then leave it and fade out. After a short gap they reappear a little
  way short of the bar and fly the last stretch; most of the trip is implied rather than drawn. The pop needs the
  nameplate; the estimated position sets the direction the orbs leave in. Without a nameplate it is a plain stream.
- **Direct Stream** (`stream`): no pop, just the stream from the estimated position. Never uses the nameplate.

**Flight path** (Options, or `/xporbs path`): how the orbs fly to the bar, for every style. The pops and the arrival
glow don't change.

- **Smooth** (default): a clean curved arc.
- **Chaos**: each orb wobbles side to side and speeds up and slows down a little as it goes, so the stream looks
  erratic. Every orb still takes off and lands exactly where a Smooth one would.
- **Helix**: the orbs spiral around the arc in a double helix, swelling and brightening as they swing to the front and
  shrinking as they pass behind. The spiral opens quickly and closes as the orbs land.

The trail follows the same path.

**Zoom-scaled spread** (on by default): the pops and the stream's start spread wider when you zoom the camera in and
tighter when you zoom out, because the mob looks bigger or smaller on screen. At the default zoom nothing changes. It
applies to all three styles: the nameplate pop, Crossfade's pop and the spread at the estimated position. Off keeps a
fixed spread.

When you didn't mouse over the mob, its position is only a guess, so the stream (or Popstream Direct's pop) starts
somewhere in an area around the guess instead of at one point. That area also scales with zoom, whatever the tickbox
says (`/xporbs unknown off` starts them at one point).

Non-kill XP always uses a plain stream.

### Destination

Orbs land on the fill edge of the XP bar: the frame you picked with `/xporbs pick`, otherwise the XP bar of
EllesmereUI, FlareUI, DaylightUI, Smooth Experience Bar or EnhanceQoL when one is shown, otherwise the default UI's
XP bar. When the frame is a status bar, the orbs land on the point it actually
draws, whichever way it fills (left, right, up or down); a vertical bar it recognises gets an upright (vertical) glow.
The glow shape can also be set by hand: Horizontal, Vertical (for a bar that fills bottom to top, even a frame the
addon can't read as a status bar) or Circular. If no XP bar can be found, a small setup window opens (a few seconds after
you log in, or at your first burst, and never twice in one session) so you can pick the bar, choose the glow shape
and landing offset, and fire a test burst. Tick "Don't ask again" to stop it opening by itself; `/xporbs setup` opens it any time.

Picking: `/xporbs pick` and then a click on your XP bar works even when the bar has no name of its own: the picker
finds the bar by its XP values, and refuses to save a huge container that is not the bar. It also works on any named
frame, including bars that ignore the mouse (the picker
scans the frames under the cursor and takes the smallest named one, skipping nameplates and screen-sized
containers). If the click finds nothing, type the name instead: `/xporbs pick FrameName`. If the target frame shape is set to
circular, they land on the centre of the frame instead, which suits a round frame such as a portrait. At max level,
with "Kill orbs at max level" on and no frame picked, the destination is your player portrait. The landing
point can be shifted by up to 100 px on each axis. If no frame is visible, the orbs land at the bottom centre of the
screen. The arrival glow is drawn at the landing point.

### Rested XP

Forever does not print the rested bonus in the kill message, so the addon works it out from the rested pool
(`GetXPExhaustion`). Rested kills pay 200%, and the pool drains by the whole gain, so the bonus is half of the XP the
pool covered. That share of the orbs is drawn in the rested colour; they leave slightly later and are slightly
larger. If a message does include a bonus, that value is used instead. If no drop in the pool was seen for the kill,
the addon assumes the pool covered the gain, up to what was left in it.

### Non-kill XP

XP that no kill claims gets a start point that says where it came from. "Quest bursts" turns all of it off.

- **Quests:** the orbs start where you clicked Complete Quest. If the pointer was not over a window then, they start at
  the quest window (the default one, or DaylightUI's NPC window), or a little left of the centre of the screen when
  that is not known.
- **Exploration:** discovering a new area starts the orbs at the area name shown on screen, or at the top centre of
  the screen when no name is showing.
- **Anything else** starts a little above the centre of the screen.

## Limitations

- When you did not hover the mob, the start of the stream is the fixed default point, not the mob's real position.
  The pop on the plate itself is always correct.
- EllesmereUI, FlareUI, DaylightUI, Smooth Experience Bar and EnhanceQoL are detected automatically. For any other
  custom XP bar, use `/xporbs pick`.
- In instances, the client may hide GUIDs and names from addons. The addon then pairs events by order instead of by
  name, and a kill may have no plate, so it gets only the stream from the estimated point.

## Troubleshooting

`/xporbs status` shows the version, the destination frame in use, how many kills each matching tier has caught, and
whether each part of the addon is idle or running.

`/xporbs debug on` records a ring of the last 500 or so log lines in `XPOrbsDB.log`. The game writes it to
`WTF\Account\<account>\SavedVariables\XPOrbs.lua` on `/reload` or logout. The log holds counts, flags and timings
only: it never records mob names or GUIDs.

To check for Lua errors, run `/console scriptErrors 1`.

## Reporting bugs

Open an issue on [GitHub](https://github.com/Talotan/XPOrbs/issues) and include:

- the output of `/xporbs status`;
- if you can, the debug log: run `/xporbs debug on`, reproduce the problem, `/reload`, then attach
  `WTF\Account\<account>\SavedVariables\XPOrbs.lua`. It holds counts and timings only, never names or GUIDs.

## Roadmap

See [ROADMAP.md](ROADMAP.md). It is a rough plan and subject to change. Requests, enhancements and bug reports are
welcome as [GitHub issues](https://github.com/Talotan/XPOrbs/issues).

## Development

```
XPOrbs.toc           load order
Core.lua             defaults, saved-variable migration, slash commands, debug log
Plates.lua           hostile nameplate tracking (GUID, name, anchor frame); never measures a plate
Kills.lua            event wiring, kill matching, rested detection, hands bursts to Orbs
Mouseover.lua        cursor samples while hovering a hostile unit
Target.lua           destination (XP bar edge), frame picker
Orbs.lua             overlay, texture pool, plate-anchored frames, flight and glow
Calib.lua            zoom-anchor calibration panel (/xporbs calib)
Options.lua          settings panel
Minimap.lua          minimap button (LibDBIcon) and the addon-compartment entry
logic/               pure Lua: XPParse, OrbMath, KillMatcher, MobEstimate, Engaged, Chime (no WoW globals)
Libs/                embedded libraries for the minimap button, unmodified (sources and licences in Libs/README.md)
media/               orb, sparkle and flash textures, the icons, the two chime voices (coin and glass, six pitches each)
tools/               make_textures.py, make_icon.py, make_sounds.py, package.py
tests/               pytest suite and the WoW API stubs
docs/images/          README images
```

The tests run the addon's Lua 5.1 code under [lupa](https://github.com/scoder/lupa) against a stub of the WoW API.
The stub can drive events and time, and it emulates restricted regions so that any measurement of a plate fails a test.

```
uv run pytest -q
```

`.luacheckrc` and `stylua.toml` hold the luacheck and StyLua configuration. Neither tool is required, and
`tests/test_lint.py` stands in for the lint: it compiles every file, loads the addon in a sandbox and fails on any
global other than `XPOrbsDB`, `SLASH_XPORBS1` and the three `XPOrbs_OnAddonCompartment*` handlers. Lines are at most
120 columns.

The textures are generated rather than drawn. To rebuild them (and a preview sheet):

```
uv run --with pillow python tools/make_textures.py --preview
```

The chime sounds are synthesised too. To rebuild them you need `ffmpeg` with the libvorbis encoder on your `PATH`:

```
uv run python tools/make_sounds.py
```

To build `dist/XPOrbs-<version>.zip`, the same files the release workflow ships:

```
uv run python tools/package.py
```

Releases are built by the [BigWigsMods packager](https://github.com/BigWigsMods/packager) when a `v*` tag is pushed.

For development, link the repository into the game folder instead of copying it:

```
New-Item -ItemType Junction -Path "<WoW>\_forever_\Interface\AddOns\XPOrbs" -Target "<path to this repo>"
```

## License

Copyright (C) 2026 Talotan. XP Orbs is free software under the GNU General Public License v3.0 or later; see
[LICENSE](LICENSE).

# XP Orbs roadmap

XP Orbs does one thing: when you gain experience, orbs fly to your XP bar. The aim is to make those the best, most
efficient and most beautiful XP orbs possible. They should feel like part of the default UI and work alongside as many
other addons as possible. Features that have nothing to do with XP orbs stay out, so the addon stays light.

This is a rough plan subject to change. The order and contents will change as feedback comes in. What has already
shipped is in the [changelog](CHANGELOG.md).

## Next: 1.5.0

- **Per-character profiles.** Let a character use its own settings, or share a named profile with others, instead of
  every character on the account sharing one set.
- **Target alignment points.** Pin the arrival target to a corner, edge or the centre of your XP bar, with the offset
  on top, as well as today's "follow the fill" behaviour. A button to show where the target is.
- **A tidier glow.** The horizontal glow stays inside the bar near empty and full, and matches the bar's height
  (automatic, with a manual size).
- **Smoother paths to bars at the top of the screen.** No sudden flip as the bar crosses the middle, and a gentler
  arrival angle.
- **A second orb colour.** An optional secondary colour, with a slider for how the orbs split between the two (rested
  orbs keep their own colour).
- **Performance mode.** One switch that keeps the orbs light on slower PCs. The minimap icon shows when it's on, and
  greys out when the orbs are off.
- **Orb layer setting.** Choose which UI layer the orbs fly on, if they cover (or hide behind) another addon's window.
- **A copyable status window.** `/xporbs status` opens a window you can copy from, to paste into a bug report.
- **An easier frame picker** that moves the options out of the way while you pick your XP bar.
- **Tidier code.** The biggest files split into smaller ones, so the addon stays easy to read and change. This also
  frees up room under Lua's per-file limits on local variables and functions, which the largest files are close to,
  so new features have space to fit.

## Later

- **Quest and exploration anchors.** Optional handles you drag to where quest and exploration orbs should start, with
  an adjustable width.
- **Kill style previews.** Pick a kill style from small looping previews instead of names.
- **A flight path editor.** Reshape each flight style's path by dragging a few points, with a live preview.
- **Controller support.** Make the addon work without a mouse, and fix the errors some controller players see.

## Experimenting

- **XP bar timing.** Let the XP bar rise when the orbs arrive rather than when the mob dies. Only if it
  works with other XP bar addons, so this may happen together with one of them.

## Requests and bugs

Have an idea, an enhancement or a bug? Open an issue on [GitHub](https://github.com/Talotan/XPOrbs/issues). Requests
that make the orbs better, or help them work with another addon, are very welcome.

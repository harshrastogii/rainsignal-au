# RainSignal — design

Written from the built interface, not ahead of it.

## What the surface is

An operating instrument, not an article. Someone arrives with one question about one
place: is it going to rain here tomorrow, and how much should I trust that. Everything
on screen serves finding a town and reading its answer. Expression never sits in front
of the task.

**Mode: Operate.** The visitor completes something. Scanability, state, and familiar
affordances outrank expression.

## Use scene, which decided dark

Someone checking before bed or at dawn, deciding whether to water the garden, hang
washing, or bring the tools in. Often on a phone, often in a dim room. Dark is the
right ground for that, and it lets a data map carry colour without fighting the page.

## Colour

Restrained: a deep slate-blue ground with one accent, plus a single sequential ramp
that does real work.

| Token | Value | Job |
|---|---|---|
| `--ground` | `#0d1520` | Page ground. Deliberately not near-black. |
| `--glass` | `rgba(23,35,50,.72)` | The one glass material |
| `--accent` | `#4fd1c5` | Selection, focus, live state |
| `--r0…--r5` | `#33465e → #9fe6d4` | Rain probability |
| `--warn` `--bad` | `#e0a458` `#e07a5f` | Stale data, weak reliability |

The rain ramp climbs monotonically in lightness, so it survives greyscale and
colour-vision deficiency and reads as one scale rather than a rainbow. Its floor was
lifted from `#243244` to `#33465e` after the first render, where low-probability towns
disappeared into the ground.

Near-black with a single neon accent and glowing edges is the shape this brief could
easily have collapsed into. The ground is slate rather than black, the accent is a
desaturated teal rather than a signal colour, and nothing glows.

## Glass, used once

Glass appears on the instrument panel, the map's mode switch, and the legend. All three
genuinely float above a live surface, which is the only thing that earns the material.
It is not applied to list rows, readout sections, or the rail. Blur and translucency
are the effect, not the decoration.

## Type

**Archivo** for everything spoken. **JetBrains Mono** for measurements, timestamps,
coordinates and station identifiers, and nowhere else, so monospace stays a signal that
a value was measured rather than a costume for looking technical.

Display sits at 54px for the one figure that matters. Body is 15px. The readout column
holds roughly 60 characters.

## Composition

Full-bleed map, instrument panel docked right at 392px, thin rail above both. Below
900px the panel becomes the lower half and the map keeps 46vh. There are no cards: the
readout is one column of sections divided by hairlines, because the reader moves down
it in order rather than choosing between tiles.

The map is not decoration. The study's finding is geographic, so the map is where the
finding lives.

## Motion

One authored moment: the readout settling when a town is chosen, opacity and blur and a
10px rise on an exponential ease-out, with the probability bar sweeping from the left in
the same beat. Everything else is already visible at rest. Hover and focus changes are
160ms. `prefers-reduced-motion` reduces all of it to nothing.

## Browser surfaces

Selection colour, caret, scrollbars, focus rings and underline offset are themed from
the palette. Every figure that shares a column uses tabular numerals.

## Labels on the map

29 station pairs sit within one degree, and Sydney and Sydney Airport are 0.09° apart.
Three mechanisms keep the map readable:

1. Discs repel each other to a minimum 11px gap. The offset is display only; the
   readout always names the town and the list is the precise selector.
2. Each label tries four positions (right, left, above, below) against every already
   placed label **and every station disc**. Checking labels against labels alone had
   let a neighbouring dot sit on a word, so Perth rendered as "erth".
3. Capitals claim their position first, so a suburb cannot crowd out a capital.

Labels that still cannot be placed are dropped rather than overlapped. 31 of 44 place
at 1440px; below 760px none do, and the list carries the job.

## Accessibility

Verified in the built page: zero contrast failures against WCAG AA across the default,
selected, and withheld states, and all 95 interactive elements have accessible names.
Stations are focusable and operable by keyboard, the search is a combobox with arrow-key
navigation, Escape clears and deselects, and a skip link leads to the readout.

## Honesty rules the interface enforces

- An observation and a model estimate are never presented as the same kind of thing.
  The readout separates "what this is built from" (measured) from the chance (estimated).
- The word "tomorrow" appears only when the target date really is tomorrow. When the
  estimate is older, the heading, the legend and the rail all name the actual date and
  say how far behind it is.
- A town with incomplete measurements shows no number, and says which measurements were
  missing.
- Where the frozen pipeline imputed a value, the readout says so and says the estimate
  rests on less evidence.
- The Bureau disclaimer is in the panel's footer on every screen, not buried in an
  about page.

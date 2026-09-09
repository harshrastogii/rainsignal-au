# RainSignal — design

Written from the built interface, not ahead of it.

## What the surface is

An operating instrument, not an article. Someone arrives with one question about one
place: is it going to rain here tomorrow, and how much should I trust that. Everything
on screen serves finding a town and reading its answer. Expression never sits in front
of the task.

**Mode: Operate.** The visitor completes something. Scanability, state, and familiar
affordances outrank expression.

## Use scene

Someone checking before bed or at dawn, deciding whether to water the garden, hang
washing, or bring the tools in. Often on a phone. The surface is light, because the
product is a map first and cartography reads best on a pale ground.

## The map

MapLibre GL over MapTiler's Dataviz Light. The basemap renders sea and land within a
few percent of each other, which is correct for a neutral data overlay and wrong for a
weather product, so the water and its shadow are re-tinted at runtime to give the
coastline back without competing with the station colours.

Zoom is the primary answer to station density. Labels use MapLibre's native collision
handling with `symbol-sort-key`, so capitals place before neighbouring airports.

## Colour

Restrained: a near-white cartographic ground, one accent, and a single sequential ramp
that does real work.

| Token | Value | Job |
|---|---|---|
| `--ground` | `#eef2f6` | Page ground behind the map |
| `--glass` | `rgba(255,255,255,.72)` | Floating instruments |
| `--glass-solid` | `rgba(255,255,255,.78)` | The readout panel |
| `--accent` | `#0e7c86` | Selection, focus, live state |
| `--r0…--r5` | `#93aec1 → #0d425f` | Rain probability |
| `--warn` `--bad` | `#9a5a15` `#a8382a` | Stale data, weak reliability |

Lightness falls monotonically across the ramp, so it survives greyscale and
colour-vision deficiency and reads as one scale rather than a rainbow. The floor was
darkened from `#b9cbd8` to `#93aec1` after validation: at 1.56 contrast against the
basemap the palest towns were invisible.

Stations with no estimate render hollow rather than grey-filled, so "no number" is a
different kind of mark rather than a low value.

## Glass, earned

Every glass surface floats above a live map that reads through it: the readout panel,
the brand and freshness pills, the mode switch, the legend, the zoom cluster. Depth is
carried by two shadows, a close contact one and a wide ambient one, plus a one-pixel
inset highlight along the top edge where the light would catch.

Glass is not applied to list rows, readout sections, or table cells. Nothing is a card.

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

One authored moment: the readout settling when a town is chosen, opacity and blur and an
8px rise, with the probability bar sweeping from the left in the same beat and the map
easing toward the town. It is a transition rather than a keyframe, so choosing a second
town retargets from the current position instead of restarting.

Curves are `cubic-bezier(.23,1,.32,1)` for entrances and `cubic-bezier(.77,0,.175,1)`
for on-screen movement; the built-in easings are too weak to read as intentional.
Everything sits under 300ms. Presses scale to 0.97. Hover states are gated behind
`(hover: hover) and (pointer: fine)` so a tap does not leave one stuck on.
`prefers-reduced-motion` removes movement and blur while keeping opacity.

## Browser surfaces

Selection colour, caret, scrollbars, focus rings and underline offset are themed from
the palette. Every figure that shares a column uses tabular numerals.

## Station density

29 station pairs sit within one degree; Sydney and Sydney Airport are 0.09° apart, and
Melbourne, Melbourne Airport and Watsonia are tighter still.

Hand-rolled label placement on the old SVG map could not resolve this. It dropped
Melbourne entirely at desktop sizes, and an earlier revision printed Perth as "erth"
because labels were tested against other labels but not against station discs.

MapLibre resolves collisions natively. `symbol-sort-key` ranks capitals ahead of their
neighbouring airports and suburbs, `text-optional` lets a dot keep its position when its
label cannot fit, and zoom separates the rest. Melbourne now holds its label at 1440px,
and the searchable list remains the precise selector at any size.

## Accessibility

Verified in the built page at 1440px and 390px: zero contrast failures against WCAG AA
across the default, selected and withheld states, no interactive element without an
accessible name, and no horizontal overflow at any width.

The map canvas is `aria-hidden`, because a WebGL canvas cannot be read by assistive
technology. Every station it shows is reachable through the list, which carries all 44
with their values; the search is a combobox with arrow-key navigation, Escape clears and
deselects, and a skip link leads straight to the readout.

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

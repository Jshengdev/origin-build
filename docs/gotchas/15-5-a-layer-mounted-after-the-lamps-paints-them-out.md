# 15-5 · a map layer mounted after the lamps paints them out; a legend band across the map hides the house

**Symptom.** With the fixture's floor plan drawn, a Hue lamp placed on the fixture's table (map px [221, 502]) was
gone: no ring on the grey slab, and its label "Go table lamp 1" was struck through. The taught route's dashes
disappeared under the shelf's wall block, and the house's top wall (y = 50) was missing under the legend
(review round 4, headless on :7922). The lamp's ring read grey 166, the same as the slab cells beside it (166 / 161).

**Root cause.** The remote's SVG paints in document order. `<${GridLayer}/>` and `<${FloorPlanLayer}/>` mount after
the path, the stop labels, the lamps and the strip, so whatever they paint lies on top of them. 01's `.occ` squares
are translucent (rgba .6), but item 15's class squares were opaque (`.fp-slab { fill: #aaa59d; }`, a tall cell
filled #fbfaf7), and the legend sat on a `<rect class="fp-key">` 1060 px wide and 0.97 opaque (the fix in 15-3).
SVG text cannot take a background, so 15-3 had used a band as wide as the map.

**Fix (verbatim).** In ui/index.html, item 15's CSS:

```
  .fp-wall, .fp-slab, .fp-low { fill-opacity: .55; }   /* translucent like 01's .occ: a lamp, the strip, the route or a stop label under a cell still shows */
  .fp-tall { fill: none; stroke: #262323; stroke-width: 1.2; }   /* an outline only: nothing under a tall cell is hidden */
  .fp-key { flood-color: #fbfaf7; flood-opacity: .9; }   /* the legend's box: each line's own width, not a band across the map; the house's top wall shows past it */
  .fplbl { filter: url(#fp-key); }
```

and in FloorPlanLayer, instead of the band's `<rect>`, a filter whose region is each text's own bounding box (a
flood under the text, the text over it):

```
    <defs><filter id="fp-key" x="0" y="0" width="1" height="1"><feFlood class="fp-key"/><feComposite in="SourceGraphic"/></filter></defs>
```

A filter changes only the paint; hit-testing still uses the text, so a click on "▶ floor plan" still reaches its tspan.

**Verify.** The same lamp setup after the fix: the ring reads 115 / 130 against the slab cells' 144 / 157, and the
label reads whole. docs/evidence/night-2/15-remote.png: the route's dashes and path points show through the wall
block, and the house's top wall shows past the legend's end. A headless click on "▶ floor plan" hit `fp-run`, sent
one POST /dog/floorplan and wrote one `dog.floorplan` row. Any later layer mounted after the lamps (14, 16) must be
translucent or outline-only too, and a map label needs a text-sized box like this one, not a band.

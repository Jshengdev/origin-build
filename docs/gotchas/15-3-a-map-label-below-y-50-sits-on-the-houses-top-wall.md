# 15-3 · a map label below y = 50 sits on the house's top wall, which strikes through it

**Symptom.** The floor plan's legend, a `<text class="lbl">` at x = 12, y = 52 in the map's SVG (under 01's grid label
at y = 28), came out struck through in the headless screenshot: a dark line runs through every gap between words, and
the second line at y = 76 sits on the "FIREPLACE" fixture label. The `.lbl` halo (a 5 px #fbfaf7 stroke painted
under the glyphs) covers only the glyphs, not the spaces between them.

**Root cause.** ui/house.svg is drawn into the same 1060 x 1540 viewBox and its rooms start at y = 50 with a 4 px
wall (`.room { stroke-width: 4 }`, the first rects at `y="50"`). Only y < 50 is free margin, and 01's label already
uses it (y = 28). Any further line of text on the map lands on the house.

**Fix (verbatim).** A light band under the floor plan's legend lines, drawn before them, in ui/index.html:

```
    <rect class="fp-key" x="0" y="35" width="1060" height=${f?.why || f?.error ? 72 : 48}/>
```

```
  .fp-key { fill: rgba(251,250,247,.97); }   /* the legend's band: the house's top wall runs right under it */
```

The band grows by one line only when a reason or a FAILED is shown, so a long red reason gets its own line (y = 100)
instead of running off the SVG's right edge.

**Verify.** docs/evidence/night-2/15-remote.png and 15-failed.png: the legend reads cleanly over the top of the house;
the red "floor plan: no wall found: 0 cells seen 3+ times in 0 frames" is whole. Any later item that adds a map label
under y = 50 (14, 16) needs the same kind of band or another place.

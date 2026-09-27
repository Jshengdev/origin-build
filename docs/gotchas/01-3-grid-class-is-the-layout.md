# 01-3 · `.grid` is the page layout, not a free SVG class

**Symptom.** A CSS rule `.grid { fill: ...; stroke: none; pointer-events: none; }`, written to style an SVG
`<path class="grid">` of occupancy cells, makes the remote stop taking clicks: the buttons still draw, but
`document.elementFromPoint` at the centre of "draw path" returns `DIV.wrap` instead of the button, and
`getComputedStyle(button).pointerEvents` is `none`.

**Root cause.** ui/index.html already defines `.grid { display: grid; grid-template-columns: 1.55fr 1fr; ... }` in its
style block and wraps both page columns in `<div class="grid">`. A second `.grid` rule matches that div too, and
`pointer-events` is inherited, so every button, slider and map handle under the wrapper stops receiving pointer
events.

**Fix (verbatim).** The occupancy layer uses its own class names, scoped to what they draw:

```
  .occ { fill: rgba(38,35,35,.6); stroke: none; pointer-events: none; }   /* one square per grid cell (not ".grid": that is the page layout) */
  .occlbl { opacity: .85; }
```

and the SVG mounts `<path class="occ" data-cells=N d="...">` and `<text class="lbl occlbl">`. Any new SVG layer
should grep the style block for its class name before adding a rule.

**Verify.** With the page served on 7801, in a headless browser: `getComputedStyle(document.querySelector("div.grid")).pointerEvents`
is `auto` and `elementFromPoint` at the "draw path" button's centre is the button. Measured tonight: shipped page
`{"layout_div":"auto","button":"auto","hit_is_button":true}`; after `page.addStyleTag` with the `.grid` rule above
`{"layout_div":"none","button":"none","hit_is_button":false,"hit":"DIV.wrap"}`.

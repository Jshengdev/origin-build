# 27-3 · a click on the legend's background lands on the map under it

## Symptom
In #admin, with "draw path" on, a click on the legend's background (or on its cams slot row) adds a path point hidden
under the legend: the path row goes from `48 pts` to `49 pts`. The same click in "place dot" mode places a lamp there,
and in "dog is here…" mode it POSTs /dog/calibrate to a point the user cannot see.

## Root cause
The legend is a `<g>` drawn inside the map `<svg>`, whose `onClick=${onMapClick}` handles every click that bubbles up
to it. Only the rows' `rect.lg-hit` called `e.stopPropagation()`, so a click anywhere else on the legend (its
`rect.lg-bg`, the gaps, the cams slot) bubbled to the svg and was read as a map click at that point.

## Fix (verbatim)
ui/index.html, the Legend's root element:
`return html`<g class="lg" transform="translate(10 10)">`
became
`return html`<g class="lg" transform="translate(10 10)" onClick=${e => e.stopPropagation()}>`
The row toggles still run first (their own handler, then the stop). Any overlay drawn inside the map svg later (a
floor-plan legend, a camera glyph) needs the same stop at its root.

## Verify
Start the dry API (`WTDD_LEDGER=<a /tmp copy of docs/evidence/ledger-sample-2026-09-13.jsonl>
/Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7934`), open http://127.0.0.1:7934/#admin headless,
click "draw path", click the legend background's bottom-right corner and the cams row: the legend's path row stays at
`48 pts`. A click on the map outside the legend still makes it `49 pts`.

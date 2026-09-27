# 26-3 · a finger on a tick pinned the next row, and a dispatched pointerdown could not tell

**Symptom.** On the sample ledger (docs/evidence/ledger-sample-2026-09-13.jsonl), a real touch at the centre of the
dog.calibrate tick 7 pinned row 10 (`pinned · dog.calibrate · … · 0.1 m`, not `0.53 m`). At the centre of the FAILED
dog.follow tick 11, the element on top was row 12's pad. The headless check still passed and took both screenshots,
because it fired `page.dispatchEvent('[data-i="7"]', 'pointerdown')`, which delivers the event straight to that
element and never asks the browser what is under the point. The round-0 page, with a touch in place of the dispatch
(`node /tmp/night1/26/tap.js 7933 7 -`):
`FAIL topmost at the tick's centre is {"cls":"tl-hit","i":"10","pad":null}, not tick 7; the touch pinned row 10, not 7`.

**Root cause.** Each row was one `<g data-i>` holding its visible tick and its transparent tap pad (x - 8, at least 24
viewBox units wide, about 10 px). Rows draw in ledger order, so row 10's pad, drawn after row 7's tick and only 7 units
to its right, lay on top of it. SVG hit-testing takes the topmost painted element, and a transparent fill still counts
as painted.

**Fix (verbatim, ui/index.html, Timeline).** Two passes: every pad first, every visible tick on top, each with its own
pointerdown for its own row:

    ${at.map(({ r, x, w, y }) => html`<rect key=${"pad" + r.i} class="tl-hit" data-pad=${r.i} x=${x - 8} y=${y - 4} width=${Math.max(24, w + 16)} height=${LANE} onPointerDown=${tap(r.i)}/>`)}
    ${at.map(({ r, x, w, y }) => html`<g key=${r.i} data-i=${r.i} onPointerDown=${tap(r.i)}>
        <title>…</title>
        <rect class=${"tl-tick" + …} x=${x} y=${y} width=${w} height="32"/></g>`)}

A pad now only catches a tap that misses every tick. And the headless check taps like a finger: a `hasTouch` context and
`page.touchscreen.tap` at the centre of the `.tl-tick`'s bounding box, then asserts that the pinned tick's `data-i` is the
one asked for, not only that some `pinned · ` line exists.

**Verify.** `node /tmp/night1/26/tap.js 7933 7 docs/evidence/night-2/26-remote.png --expect "pinned · dog.calibrate" --expect "0.53 m"`
prints `"topmost_at_tap": {"cls": "tl-tick", "i": "7"}`, `"pinned_i": 7` and `PASS touch tap i=7`; the same with 11 and
`--bad` prints `"pinned_i": 11` and a `tl-ring tl-bad`. What it does not fix: ticks closer than about 2 s to the next one
in the same lane (1 px is about 2.2 s on this 30-minute window) still stack, and the last one drawn wins. A touch at each
tick's own centre reaches 31 of the sample's 40 rows; 0, 2, 9, 20, 31, 32, 33, 34 and 38 pin their neighbour.

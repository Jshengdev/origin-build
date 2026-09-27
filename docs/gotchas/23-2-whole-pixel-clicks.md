# 23-2 · a headless click cannot land on an exact map pixel

**Symptom.** The screenshot gate converted map point [450, 1200] to screen coordinates through `svg.getScreenCTM()` and
clicked there with `page.mouse.click(317.6, 1055.0)`. After save, GET /map held `"pt":[449,1198]`, not [450, 1200].
Clicking the rounded pixel instead gave [451, 1200]. No whole screen pixel within 3 px of the target maps back to
[450, 1200].

**Root cause.** Chromium hands the page whole-pixel `clientX`/`clientY` for a synthesized click, and the page's
`toMap()` rounds the inverse-CTM point. At the gate's viewport (1200x1600) the map's 1060 px viewBox is drawn about
663 px wide, so one screen pixel is 1.598 map pixels. Map points therefore land on a lattice about 1.6 px apart, and
some integer map points, [450, 1200] among them, are not reachable by any click at that zoom. The page is right: the
pt is exactly where the click was.

**Fix (verbatim, /tmp/night1/23/shoot.js, scratch).** Search the whole screen pixels around the target for one whose
inverse maps to it exactly, fall back to the nearest, and check GET /map against the page's own mapping of the clicked
pixel, not against the target:
```
check(JSON.stringify(cams[0].pt) === JSON.stringify(s.map), `GET /map cameras[0].pt ${JSON.stringify(cams[0].pt)} is the clicked pixel's map point ${JSON.stringify(s.map)}`);
check(Math.hypot(cams[0].pt[0] - pt[0], cams[0].pt[1] - pt[1]) <= s.scale * Math.SQRT2, `and within one screen pixel (${(s.scale * Math.SQRT2).toFixed(2)} map px) of the target [${pt}]`);
```

**Verify.** The gate prints `click map [450, 1200] -> screen pixel [318, 1055] (1 screen px = 1.598 map px; exact pixel
exists: false) -> toMap() [451,1200]`, then `PASS GET /map cameras[0].pt [451,1200] is the clicked pixel's map point
[451,1200]` and `PASS and within one screen pixel (2.26 map px) of the target [450,1200]`.

# 29-2 · chromium says nothing when an MJPEG stream ends

**Symptom.** The API ends `GET /dog/stream.mjpg` on a stall (`[wtdd:api] stream ended why=stale parts=41 s=5.0`), and the
page's `<img>` keeps showing the last frame as if it were live. In headless chromium, with inline `onload`/`onerror` on an
`<img src=/dog/stream.mjpg>` against `WTDD_VIDEO_STUB=14 WTDD_VIDEO_STUB_FREEZE_S=3`, 8 s recorded exactly one event:
`[["load",460,1280]]`. That is one `load` at the first part, none per part, and no `load` or `error` when the server
closed the response at 5.0 s.

**Root cause.** Chromium treats a finished multipart/x-mixed-replace response as a completed image and keeps the last
part. There is no event for the end, so the stall cannot be seen from the image element. Only a stream refused
before its first part (a 503 JSON body) fires `error`.

**Fix (verbatim, ui/index.html LiveView).** The page does not read the stall from the image. It reads it from what
the API serves on the 1 s `/dog/state` poll:
`if (v?.stale) return tile(`stream stalled · ${(v.age_ms / 1000).toFixed(1)} s`);` unmounts the image (which closes
the connection) for the red tile, and
`useEffect(() => { if (wasStale.current && v && !v.stale) { setFailed(null); setEpoch(e => e + 1); } wasStale.current = !!v?.stale; }, [v?.stale]);`
opens a fresh stream (`/dog/stream.mjpg?e=N`) when the video is back. Residual window, not fixed: the server ends the
stream once the newest frame is 2 s old (FRAME_STALE_S). If frames come back within about 1 s of that, before the next
poll sees `stale`, the image stays on its last frame and the stat line reads fresh. On the dog, 29.5 (pull the power)
stalls far longer than that. A Wi-Fi drop of 2 to 3 s is the case to watch.

**Verify.** `WTDD_VIDEO_STUB=14 WTDD_VIDEO_STUB_FREEZE_S=1 python -m wtdd.api 7936`. Create the session with
`curl /dog/state`, then load the page in headless chromium. After 3 s, `.lv-tile` reads `stream stalled · 3.4 s stub`,
`img.lv` is gone, and the API logs `stream ended why=stale parts=1 s=0.6` (docs/evidence/night-2/29-failed.png).

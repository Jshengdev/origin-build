# 29-3 · a remounted MJPEG image under the same src shows the ended stream, and playwright's routing hides it

**Symptom.** The live view stalls and shows the red tile. The reconnect then drops the body (`/dog/state` answers
`connected: false, video: null`), and the dog comes back. The page remounted `<img src=/dog/stream.mjpg?e=0>` under the
same URL and chromium made no request. The API log has one `GET /dog/stream.mjpg?e=0`, then
`stream ended why=stale parts=11 s=2.7`, and nothing after it. The image showed the frame from before the stall
(`complete: true`, `naturalWidth: 1280`) under a fresh stat line, `— fps · 70 ms · 17 KB · 1280×720 stub`. That is a
stale image shown as live, which the goal forbids. The first checks drove `/dog/state` with playwright's `page.route`,
and they saw a second request every time, so the bug looked absent.

**Root cause.** There are two causes.
1. The HTML spec's list of available images lets a document reuse an image it has already fetched under the same URL,
   whatever `Cache-Control: no-store` says, and chromium does this for a finished multipart response. The `?e=` that
   changes the URL was bumped only on a stale-to-fresh change of `video.stale`. That change is lost when `video` passes
   through null: the effect in 29-2 then sets `wasStale.current = !!undefined`, which is false.
2. Playwright's `page.route` turns request interception on, and interception disables chromium's cache (playwright
   docs: "Enabling routing disables http cache"). Under that check, every remount fetched again.

**Fix (verbatim, ui/index.html LiveView).** These lines replace the `wasStale` effect quoted in 29-2:
```
  const v = dog?.video, live = !!v && !v.stale, showing = !!dog?.connected && !failed && !v?.stale;   // showing: the image is mounted
  useEffect(() => { if (!showing) setEpoch(e => e + 1); }, [showing]);   // the image went away: chromium re-shows an ended stream's last part under a reused src (gotcha 29-3)
  useEffect(() => { if (live) setFailed(null); }, [live]);   // the video back (after a stall, or a new body's first frame) clears a FAILED tile
```
The image is mounted exactly when `showing` is true, so every mount gets a new `?e=`. The page checks rewrite
`/dog/state` inside the page, on `window.fetch` through `addInitScript`, and never with `page.route`.

**Verify.**
1. Start `WTDD_VIDEO_STUB=14 WTDD_VIDEO_STUB_FREEZE_S=1 python -m wtdd.api 7936`.
2. Load the page in headless chromium and wait for the stall tile. Rewrite `/dog/state` to `connected: false,
   video: null` until the image is gone, then to a fresh video (`stale: false`).
3. Before the fix, the stream requests are `[[1289,"?e=0"]]`, and the remounted image is `?e=0` with
   `naturalWidth` 1280 and no tile.
4. After the fix, they are `[[1438,"?e=1"],[6439,"?e=2"]]`. The API logs
   `WARN stream refused err=RuntimeError: video stale: last frame 4.3s ago (frames=13)`, and the tile reads
   `video FAILED · RuntimeError: video stale: last frame 4.3s ago (frames=13) stub`.

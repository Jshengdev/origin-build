# 29-4 · a stall shorter than one poll gap freezes the live image for good

This closes the "residual window" that 29-2 left open. 29-2 said the window was brief. It is not: the image stays
frozen until a page reload or the next long stall.

**Symptom.** The video stops for a little longer than FRAME_STALE_S (2 s) and then comes back. The API ends the stream
correctly (`stream ended why=stale parts=59 s=6.5`). But no 1 s `/dog/state` poll lands while `video.stale` is true.
The reviewer's repro (a real API on 7936, 14 fps, one 2.2 s gap, the real page in headless chromium, no request
rewriting) gave these results:
- 16 polls, 0 of them stale.
- One `GET /dog/stream.mjpg` in total.
- At 15 s, `img.lv` was not changing (`img_changing_at_end: false`), and the stat line read
  `12.5 fps · 2 ms · 16 KB · 1280×720`.

A frozen frame under a healthy stat line is the goal's own failure case shown as live video. A 2 to 3 s Wi-Fi drop
is enough to cause it.

**Root cause.** Chromium fires no event when an MJPEG response ends (29-2). The page learned of a stall only from a
poll that happened to see `stale`. So `showing` never went false, the `?e=` epoch never changed, and nothing asked for
a new stream. The server knew about the stall, but it served that knowledge only while the stall lasted.

**Fix (verbatim).** The server counts the stall and keeps the count. The page keys the stream URL on that count.

`wtdd/dog/body.py`, `Body.__init__`:
```
        self._gaps = 0                    # stalls past FRAME_STALE_S, counted when the frames resume: the page reopens its stream on a new count
```
`Body._drain`, immediately before the assignment of `_fr`:
```
            if self._fr_n and now - self._fr_at > FRAME_STALE_S:   # the same rule that ends every stream (session.frames)
                self._gaps += 1
```
`Body.video()` serves `"gaps": self._gaps`.

`ui/index.html`, LiveView:
```
      <img class="lv" src=${`${API}/dog/stream.mjpg?e=${epoch}.${v?.gaps ?? 0}`} onError=${onError}/>
```

The threshold is the one `session.frames()` ends a stream on, so every stall that ended a stream is counted. A gap
that ended no stream is also counted, and that costs one harmless reconnect. A new Body starts at 0 again. That
cannot reuse an old URL unseen: a Body is replaced only after its state stream is STALE_MS (5 s) old, so the video has
already been stale for more than one poll, and the page has unmounted the image and bumped the epoch.

**Verify.**
1. `python -m unittest wtdd.dog.test_stream`. `Gaps.test_a_stall_that_ended_a_stream_is_counted_when_the_frames_resume`
   ends a stream with a stall, resumes the frames, and gets `video.gaps == 1` with `stale: false`. It gets 0 before the
   stall and still 1 after more frames. `Page.test_a_counted_stall_reopens_the_stream` requires `gaps` in the stream src.
2. Run the reviewer's repro, `/tmp/night1/29/review2/hiccup_srv.py 2.2` with `hiccup.js`, with timestamped server lines.
   After the fix:
   `{"stream_requests":[[1224,"?e=1.0"],[8224,"?e=1.1"]], ... "img_changing_at_end":true,"stale_polls":[],"polls":16}`.
   `[repro] frames resume` is at 1790469590.837, and `GET /dog/stream.mjpg?e=1.1` is at 1790469591.041, 0.2 s later.
3. With the page's src reverted to `?e=${epoch}` on the same server, the same repro gives
   `{"stream_requests":[[1242,"?e=1"]], ... "img_changing_at_end":false,"stale_polls":[],"polls":16}`.

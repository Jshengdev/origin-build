# DEMO_CACHE: the whole module. What is cached: the dog's camera, replaced by ONE synthetic 1280x720 frame (a grey
# gradient with a darker upright block where the dry screenshot plants a person box), handed to the real Body._drain at
# WTDD_VIDEO_STUB frames a second. Why: a worktree has no dog, and 29's screenshots must show the live view, its stat
# line and the stall with real frame numbers flowing through the real cache, stream and /dog/state. How to run it live:
# leave WTDD_VIDEO_STUB unset (the default); the first frame request then connects to the dog. Never set on a live run.
"""The DEMO_CACHE video stub: a Body with no connection whose frames come from a synthetic track.

  WTDD_VIDEO_STUB=14 python -m wtdd.api 7936                              the live view at 14 fps, video.source "stub"
  WTDD_VIDEO_STUB=14 WTDD_VIDEO_STUB_FREEZE_S=1 python -m wtdd.api 7936   the frames stop after 1 s: the stall

DogSession.__init__ calls install() when the key is set. Every frame is the same pixels, so the same JPEG bytes and sha
(PIL's encode is deterministic): a planted watch.json can name the frame it "boxed". No ledger rows: every video path
is a read. The page shows an amber `stub` badge from video.source. UNVERIFIED: nothing here; it is not the dog."""
from __future__ import annotations
import asyncio
import time

import av
import numpy as np

from .. import config
from ..ledger import log
from .body import FRAME_TIMEOUT_S, Body

W, H = 1280, 720
BLOCK = (760, 200, 920, 640)   # x0, y0, x1, y1 of the dark block (the dry screenshot's planted person box)


class SynthTrack:
    """Stands in for aiortc's RemoteStreamTrack: recv() returns the one synthetic frame every 1/fps s, or never again
    once `freeze_s` has passed (the stall the page must name)."""

    def __init__(self, fps: float, freeze_s: float | None) -> None:
        a = np.repeat(np.linspace(150, 215, W, dtype=np.uint8)[None, :, None], H, 0).repeat(3, 2)
        x0, y0, x1, y1 = BLOCK
        a[y0:y1, x0:x1] = (70, 64, 60)
        self.frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(a), format="rgb24")
        self.period, self.freeze_s, self.t0 = 1 / fps, freeze_s, time.monotonic()

    async def recv(self):
        await asyncio.sleep(self.period)
        if self.freeze_s is not None and time.monotonic() - self.t0 > self.freeze_s:
            log("dog", "WARN DEMO_CACHE video stub frozen: no more frames", after_s=self.freeze_s)
            await asyncio.Event().wait()   # never set: the track goes quiet, as a dog losing power would
        return self.frame


def install(session) -> None:
    """Puts a stub Body on `session` and starts the real Body._drain on the session loop over a SynthTrack."""
    fps = float(config.get("WTDD_VIDEO_STUB"))
    freeze = float(config.maybe("WTDD_VIDEO_STUB_FREEZE_S") or 0) or None   # unset: the frames never stop
    b = Body()
    b._video, b._vid_t0, b.video_source = True, time.monotonic(), "stub"   # the channel counts as on: there is no conn
    session.body = b
    asyncio.run_coroutine_threadsafe(b._drain(SynthTrack(fps, freeze)), session.loop)
    while b._fr is None and time.monotonic() - b._vid_t0 < FRAME_TIMEOUT_S:   # as _video_on waits: no reader sees the
        time.sleep(0.01)                                                       # channel on before its first frame
    log("dog", "WARN DEMO_CACHE video stub: no dog, a synthetic frame", fps=fps, freeze_s=freeze, size=f"{W}x{H}")

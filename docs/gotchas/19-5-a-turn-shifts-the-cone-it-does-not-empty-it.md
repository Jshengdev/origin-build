# 19-5 · a turn between 07's pin and the scout's feed shifts the cone, it does not empty it

**Symptom.** In the fixture world, 07 pinned the chair with the dog at yaw 0, and the scout was fed after a small turn.
The blob was not empty, so the round-2 wait (19-3) never fired. The zone was proposed on the wrong cells and the chair
was marked handled for good:

```
0 deg: 11 of the chair, 0 beside it
3 deg: 9 of the chair, 2 beside it
7 deg: 6 of the chair, 5 beside it
8 deg: 0 of the chair, 0 beside it
```

A 0.1 m sideways step gives 9 of 11 plus 2 beside. A 0.3 m step back gives all 11 plus 2 beside. The module's
UNVERIFIED line said only that "a dog that moved a little may get part of the thing's cells".

**Root cause.** blob() bounds the cone from the pose at feed time, while 07's hit comes from the pose at 07's tick. The
objects thread ran `self.objects_state(draft=True)` and only then `self.scout_feed()`. objects_state's draft is 07's
one-line `llm.generate`, which can take seconds, so every new thing reached the scout from a pose one model call after
07 pinned it. A dog turning or being hand-driven in those seconds gets the shifted case.

**Fix (verbatim, wtdd/dog/session.py, DogSession._objects_loop; objects_state loses its `draft` flag, which had no other
caller).**

```python
            try:
                self.objects_state()
                try:   # the scout first: its cone is taken from the pose now, milliseconds after this thread's own tick pinned
                    self.scout_feed()
                finally:   # 07's draft (a model call that can take seconds) after it, even when the feed raised
                    objects.draft_due(self.objects)
                last = None
```

A window placed by a GET /dog/objects tick is still up to TICK_S from the feed. The gap grows while the scout's previous
Jev call holds the thread. The UNVERIFIED line in wtdd/dog/scout_zones.py now says so, with the numbers above. Anchoring
the cone on the direction to 07's hit instead of the current yaw would remove the turn error. That changes the head's
bound and the test's in_bound(), so it is left to the head.

**Verify.**

```
.venv/bin/python -m unittest \
    wtdd.dog.test_scout_zones.Session.test_the_scout_is_fed_right_after_07s_tick_and_before_the_draft_call
.venv/bin/python -c "
import math; from wtdd.dog import test_scout_zones as T, scout_zones as s
g = T.accumulated(); h = T.chair_hit(g); w = T.wall_a_expected(T.CHAIR['xyxy'], h)
for d in (0, 3, 7, 8):
    c = T.as_set(s.blob(g, {'position': [0, 0], 'yaw': math.radians(d)}, T.CHAIR['xyxy'], h, T.W, T.FOV, threshold=T.THR))
    print(f'{d} deg: {len(c & w)} of the chair, {len(c - w)} beside it')
" 2>/dev/null
```

The test fails on 3528fc6 (`[('tick', True), 'feed'] != [('tick', False), 'feed', 'draft']`) and passes on bb78965.
The second command prints the table in the symptom.

# 07-2 · a window that cannot place a known thing is not a new thing

**Symptom.** The review of 07 probed `objects.Store` with the fixture: window 1 placed o1 (chair) and o2 (backpack);
window 2 had the same boxes with `pose=None` (the state stream gone for one window, as in a reconnect); window 3 had
the pose back. Window 2 wrote two `new` rows for o3 and o4 (unplaced), window 3 matched o1 and o2 again, and o3 and o4
went on to `stale` rows. The same happened when the ray missed once (yaw = pi) and when the frame file was unreadable
for one window. On the live path each phantom is a `new` row, one `llm.generate`, and a `stale` row two seconds later.
The reverse happened too: a thing boxed before the pose or the calibration arrived became an unplaced object, and the
first window that could place it made a second, placed object.

**Root cause.** `Store.observe` matched a placed box only to placed objects (a pin within MATCH_PX) and an unplaced
box only to unplaced objects, so a failure of placement, which says nothing about what the camera sees, split one
thing into two identities.

**Fix (verbatim, wtdd/dog/objects.py, Store.observe).**

```
             same = [o for o in self.objs.values() if o["label"] == label and o["id"] not in matched]
-            if pos_px is not None:
+            fresh = [o for o in same if not o["stale"]]   # with no pin to compare, identity rides on continuity alone
+            if pos_px is not None:   # the nearest pin within MATCH_PX, else a fresh object still waiting for its first pin
                 near = [(math.dist(o["pos_px"], pos_px), o) for o in same if o["pos_px"] is not None]
                 near = [c for c in near if c[0] <= MATCH_PX]
-                o = min(near, key=lambda c: c[0])[1] if near else None
-            else:
-                o = next((o for o in same if o["pos_px"] is None), None)
+                o = min(near, key=lambda c: c[0])[1] if near else next((o for o in fresh if o["pos_px"] is None), None)
+            else:   # an unplaced object, else the fresh one seen last: a blind window (pose, ray, frame) is not a new thing
+                o = next((o for o in same if o["pos_px"] is None), None) or max(fresh, key=lambda o: o["last_seen"], default=None)
+                if o is not None and o["pos_px"] is not None:   # its last pin stays until a window places it again
+                    fields = {k: v for k, v in fields.items() if k not in ("hit_m", "dist_m", "pos_px")}
```

Both fallbacks skip stale objects: an unplaced box never revives a stale pin (that would show an old place as
fresh); a stale object comes back only by a placement within MATCH_PX of it. No row for a blind window of a known
object: a failed placement is not a change.

**Verify.** `python -m unittest wtdd.dog.test_objects`: Ran 37 tests, OK, including
`test_a_window_that_cannot_place_a_known_object_does_not_spawn_a_second_one`,
`test_a_known_unplaced_object_takes_its_first_pin_instead_of_a_second_one` (both failed first: `(['o3', 'o4'], [])
!= ([], ['o1', 'o2'])`) and `test_an_unplaced_box_does_not_revive_a_stale_pin` (fails against the same fix with
`max(same, ...)` in place of `max(fresh, ...)`). The review's probe now prints, for the pose-lost and the ray-missed
windows, `seen ['o1', 'o2']`, `unplaced ['o1', 'o2']`, rows `[('new', 'o1'), ('new', 'o2')]` only.

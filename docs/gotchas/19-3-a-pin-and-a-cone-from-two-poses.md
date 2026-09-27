# 19-3 · a pin taken from one pose and a cone from another

**Symptom.** 07 placed the fixture chair with the dog at x = 0.0. The scout was fed with the dog at x = 0.10, and both
objects were failed for good:

```
[wtdd:scout] zone.proposed ok=False app=map object_id=o1 err=no cell seen 3+ times inside the box's cone within 1.0 m of the hit from the pose now (the dog moved since 07 placed it?) ms=0
[wtdd:scout] zone.proposed ok=False app=map object_id=o2 err=no cell seen 3+ times inside the box's cone within 1.0 m of the hit from the pose now (the dog moved since 07 placed it?) ms=0
```

The dog then stood at x = 0.10 for three windows. 07 re-placed the chair each window (hit_m [2.0, 0.0], dist_m 1.9), and
blob() at that pose with that hit gave the chair's 11 cells, but the scout still proposed nothing ("0 asked, 0
proposed ..., 2 failed"). A table first boxed on the approach to a stop would never be proposed.

**Root cause.** blob() bounds the cone and the depth from the pose passed when the scout is fed, while 07's hit_m and
dist_m come from the pose when 07 placed the box. On the objects thread the two are one draft call apart, and a GET
/dog/objects tick places objects up to TICK_S before the next feed. The review's probe showed 0.06 m forward or 10
degrees of yaw was enough to empty the fixture chair's blob. The empty blob was written as a failed row, and the object
was put in `handled`, so it was never asked again.

**Fix (verbatim, wtdd/dog/scout_zones.py, Proposals._feed).**

```python
            else:
                if not cells:   # the cone from here misses 07's hit: the dog moved since 07 placed it. A wait, not a failure:
                    waiting.append(o)   # taken again by the next feed, with the hit 07 refreshes from where the dog is then
                    with self._lock:
                        self.handled.discard(o["id"])
                    continue
                err = None
            n["handled"] += 1
```

```python
        names = ", ".join(f"{o['id']} {o['label']}" for o in waiting)
        self._warn(f"WARN {len(waiting)} placed object(s) waiting ({names}): no counted cell in the box's cone from where the dog "
                   f"is now (it moved since 07 placed them); asked when 07 places them again" if waiting else None)
        return self._summary(n, t_all) if n["handled"] else n
```

The fix also excludes stale objects from the candidates (`and not o.get("stale")`), so a thing 07 no longer sees does
not wait forever, and it reads `fn = fn or decider()` only when a model call is about to be made. A waiting 4 Hz tick
therefore prints one WARN per change and no further lines.

**Verify.**

```
.venv/bin/python -m unittest \
    wtdd.dog.test_scout_zones.Feed.test_a_dog_that_moved_since_07_placed_it_waits_and_is_asked_when_07_places_it_again \
    wtdd.dog.test_scout_zones.Feed.test_a_waiting_thing_07_no_longer_sees_stops_waiting
```

The first fails on a8d3293 (`a wait writes no row`: two failed zone.proposed rows) and passes on da1d5a2. The second
fails on ae20914 (`'waiting' unexpectedly found`) and passes on faa9035.

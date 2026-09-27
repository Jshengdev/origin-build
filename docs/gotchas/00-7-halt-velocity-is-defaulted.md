# 00-7 · `_halt()["velocity"]` is not what the device sent

**Symptom (dry, not the dog).** In the round-3 review probe, a FakeBody whose state read-back carried no `velocity` key
still produced `stop.person` ok true with `state_after.velocity [0, 0, 0]`, and no settle read was taken. So a body
that never said it was still was written into the receipt as still, and the eval graded that stop.

**Root cause.** main's `DogSession._halt()` reads back the state and, for its log line, defaults a missing velocity:
`v = st.get("velocity") or [0, 0, 0]`. It then returns that `v` as `"velocity"`. Round 2 used the returned value as
the stillness verdict and as the receipt's velocity, so a missing reading became a zero reading. The same trap waits
for any later caller of `_halt()` (14's scout, 18a's dispatch) that judges the body on `h["velocity"]`.

**Fix (verbatim).** main's line stays as it is. `_halt()` also returns the velocity as sent:

```python
        return {"stop_code": code, "velocity": v, "range_obstacle": st.get("range_obstacle"), "t": t,
                "velocity_read": st.get("velocity")}   # 00: as sent (None when none); person_tick judges on it
```

`person_tick` records `"velocity": h["velocity_read"]` and judges on it, so None is not still:

```python
                    v, t_still = h["velocity_read"], h["t"]
                    if v is None or max(abs(x) for x in v) > halt.STILL_MPS:   # 00.3: ok only when read back still; none is not
                        time.sleep(halt.SETTLE_S)
                        v = self.run(self.body.fresh_state(required=True), timeout=10).get("velocity")
                        t_still = time.time()
                        r["state_after"]["velocity_settled"] = v
                        if v is None:
                            raise RuntimeError(f"no velocity in the read-back: the body never said it is still (first read-back "
                                               f"{h['velocity_read']}, again {halt.SETTLE_S} s later)")
```

Anything that judges the body after a halt reads `velocity_read`, never `velocity`.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_halt.StillMs` passes.
`test_a_read_back_with_no_velocity_is_not_a_stop_and_the_halt_stands` checks stop.person ok false with "no velocity in
the read-back", `state_after.velocity` None, the halt standing and the grade fail. On the dog (00.3), the first live
`stop.person` row must show a real list in `state_after.velocity`, never None.

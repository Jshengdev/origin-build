# 14-5 · Infinity reaches the scout through JSON, and it passes every guard and poisons the ledger for the page

**Symptom.** `POST /dog/scout {"target_deg": Infinity, "timeout_s": "inf"}` is accepted. The spin holds (0, 0, 0.5)
until someone presses POST /dog/stop: in review it was still turning at 683° after 4 s. A nan z is accepted too, holds
nothing, and fails three seconds later as "did not turn", which names the wrong cause. A refusal that did carry an
inf, such as the over-cap `z: Infinity`, would write `"z_rad_s": Infinity` into the ledger. The page JSON.parses
GET /ledger every 2 s, so every poll would then fail while that row is in the last 150.

**Root cause.** Python's `json.loads` accepts `Infinity` and `NaN`, and `float("inf")` parses. `abs(deg) >= inf` and
`elapsed >= inf` are never true. `abs(nan) > cap` is False, so the cap check lets nan through. `json.dumps` writes a
bare `Infinity` by default (`allow_nan=True`), and that is not JSON to a browser.

**Fix (verbatim).** In `DogSession.scout`, inside the refusal block, so the press gets one FAILED row, the error is
raised and nothing moves:

```
        num = lambda v: v if math.isfinite(v) else str(v)  # noqa: E731  (a bare Infinity/NaN in the ledger breaks the page's JSON.parse of GET /ledger)
        args = {"z_rad_s": num(z), "target_deg": num(target_deg), "timeout_s": num(timeout_s), ...
            if not abs(z) <= DRIVE_MAX["z"]:   # nan fails this too
                raise ValueError(f"scout refused: |z| {abs(z):g} rad/s is not within DRIVE_MAX z {DRIVE_MAX['z']} (never clamped)")
            if not (math.isfinite(target_deg) and target_deg > 0 and math.isfinite(timeout_s) and timeout_s > 0):
                raise ValueError(f"scout refused: target_deg {target_deg:g} and timeout_s {timeout_s:g} must be finite and over 0 "
                                 "(the timeout is the spin's one end guard)")
```

**Verify.**

```
python -c "import json; print(json.dumps({'target_deg': json.loads('Infinity')}, default=str))"
node -e 'try { JSON.parse("{\"a\": Infinity}") } catch (e) { console.log(e.name) }'
python -m unittest wtdd.dog.test_scout.Spin.test_a_z_target_or_timeout_that_is_not_finite_is_refused
```

The first prints `{"target_deg": Infinity}` and the second prints `SyntaxError` (both measured 2026-09-26). The test
was RED at 0619647 (`ValueError not raised`) and passes at 0fe1112. It covers nine refused values, one FAILED row
each, with every row dumped under `allow_nan=False`.

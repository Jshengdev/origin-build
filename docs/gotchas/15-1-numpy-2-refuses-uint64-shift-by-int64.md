# 15-1 · numpy 2 refuses `np.uint64(1) << int64`, so a 64-layer height mask cannot be built the obvious way

**Symptom.** Building the per-cell height mask with the shift everyone writes first,
`np.uint64(1) << np.int64(3)` (or `np.uint64(1) << k` with `k = np.rint(...).astype(np.int64)`), raises in the venv's
numpy 2.5.3:
`TypeError: ufunc 'left_shift' not supported for the input types, and the inputs could not be safely coerced to any supported types according to the casting rule ''safe''`.

**Root cause.** numpy 2's type promotion has no safe common type for uint64 and int64 (their union needs more than 64
bits), so `left_shift` finds no loop for the pair. Casting the mask to int64 instead is not a way out either: bit 63
is the sign bit there, and a layer 63 mask would come back negative (and overflow `np.asarray(..., dtype=np.int64)`
when a saved mask above 2**63 is read back).

**Fix (verbatim).** wtdd/dog/occupancy.py `Grid._or_mask`: cast the layer index to uint64 first, and OR per frame
with one `np.bitwise_or.at` over the unique cells:

```
        bits = np.left_shift(np.uint64(1), k[inside].astype(np.uint64))   # numpy 2 refuses np.uint64(1) << int64
        u, inv = np.unique(iy[inside] * w + ix[inside], return_inverse=True)
        acc = np.zeros(len(u), dtype=np.uint64)
        np.bitwise_or.at(acc, inv, bits)
        self.zmask.reshape(-1)[u] |= acc
```

`k` is already limited to 0..63 there (a layer outside that range is a WARN and dropped before the cast, never
wrapped), so the cast cannot turn a negative layer into a huge shift.

**Verify.** `python -m unittest wtdd.dog.test_floorplan.Mask`: the per-cell masks equal the fixture's analytic
`truth_zmask`, bit 63 survives a save and a load, and layers 64, 65 and -1 each print a WARN line naming the layer
and leave the mask unchanged. Measured tonight: `np.uint64(1) << np.int64(3)` raises the error above;
`np.left_shift(np.uint64(1), np.array([3, 63], dtype=np.uint64))` gives `[8 9223372036854775808]`;
`np.asarray([[1, 2, 3, 2**63 + 5]], dtype=np.int64)` raises `OverflowError: Python int too large to convert to C
long`, which is why Grid.from_dict reads the fourth column with `dtype=np.uint64` and never through int64.

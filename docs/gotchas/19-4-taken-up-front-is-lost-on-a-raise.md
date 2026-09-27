# 19-4 · a store that marks every candidate taken up front loses the rest on a raise

**Symptom.** A ledger write that raised on o1's zone.decided row (disk full, in a probe) made the feed raise, as it
should, and GET /dog/scout named the error. Once the ledger recovered, the next feed asked nobody: no row, nothing in
`failed`, and the why said "0 asked, 0 proposed". o2, the backpack placed in the same window, had never been asked and
never would be. The feed's own docstring said "the objects it had not taken yet are taken by the next feed".

**Root cause.** `Proposals._feed` put every candidate into `handled` before the loop
(`self.handled.update(o["id"] for o in cands)`). A raise part-way through the loop left the candidates it never reached
marked handled. When the next feed with new candidates cleared `error`, nothing on the page named them.

**Fix (verbatim, wtdd/dog/scout_zones.py).** The up-front `self.handled.update(...)` is gone. Each object is taken when
the loop reaches it, and the wait path does not take it at all:

```python
    def _take(self, o: dict) -> None:
        """o is handled from here on: never taken again; a raise before this feed ends names it (feed())."""
        with self._lock:
            self.handled.add(o["id"])
            self._taking = o
```

```python
                if not cells:   # the cone from here misses 07's hit: the dog moved since 07 placed it. A wait, not a failure:
                    waiting.append(o)   # not taken: the next feed tries again, with the hit 07 refreshes from where the dog is then
                    continue
                err = None
            self._take(o)
            n["handled"] += 1
```

The unreadable-frame path calls `self._take(o)` per object before its failed row, and `self._taking = None` follows the
loop. The object in flight when the feed raised stays handled, because its call was made, and becomes a line in
`failed`:

```python
        except Exception as e:
            err = f"feed: {type(e).__name__}: {e}"
            with self._lock:
                self.error = err
                o = self._taking if self._taking and not any(f["object_id"] == self._taking["id"] for f in self.failed) else None
            if o:
                self._fail(o, "feed", err)
            raise
```

**Verify.**

```
.venv/bin/python -m unittest \
    wtdd.dog.test_scout_zones.Feed.test_a_ledger_write_that_raises_mid_feed_leaves_the_untaken_things_for_the_next_feed
```

Fails on c153dd7 (`Lists differ: [] != ['o2']`: the next feed asked nobody). Passes on a37e5b3.

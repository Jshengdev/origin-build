# 22-4 · a live PASS with the API log silent: the fatal WARNs were never read

**Symptom.** 01.3's three rows landed in a temp ledger while the API log got no new line, as happens when the API is
started without the tee and `logs/api.log` is a file from an earlier session. livecheck printed
`PASS 01.3 · 2026-09-27T21:00:09 dog.grid_save ok` with no WARN. Its four fatal_warns (frame_id not odom, callback failed,
frame rejected, center far) had never been tried against a single line.

**Root cause.** run() only checked that the log file existed. The zero-log-lines WARN lived on the timeout path, and a
PASS never takes that path. Several Needs-the-dog lines start the API as plain `python -m wtdd.api`, so on the first
night the file can exist and stay silent.

**Fix (verbatim, wtdd/livecheck/__init__.py).**

```
SILENT_S = 2            # live: after the last row, how long a still-silent API log may take to show a line (ledger.step
                        # appends the row, then logs it; the tee and the poll can read them a poll apart) before FAIL
...
        if self.spec["fatal_warns"] and not self.loglines:   # the API was started without the tee: no regex was ever tried
            if self.replay or self.elapsed >= self.settle_until + SILENT_S:
                self.done("FAIL", f"the API log {self.log} was silent while {self.k} rows landed: fatal_warns never read · {TEE}", None,
                          "API log silent: fatal_warns never read")
            return
...
    elif spec["fatal_warns"] and not c.log.exists():
```

Only a step with fatal_warns reads the log, so only that step needs it. The grace exists because ledger.step appends the
row before it logs the row's own line.

**Verify.** `.venv/bin/python -m unittest wtdd.livecheck.test_livecheck.Live`:
`test_a_silent_api_log_cannot_pass_a_step_that_reads_it` (FAIL naming the log and the tee),
`test_a_log_line_trailing_the_last_row_still_passes` (seen failing with `SILENT_S = 0`), and
`test_a_step_without_fatal_warns_needs_no_api_log` (02.2 PASSes with no log file).

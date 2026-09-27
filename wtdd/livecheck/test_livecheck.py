"""The livecheck tests (goal 22's verifying command): `python -m unittest wtdd.livecheck.test_livecheck`.
Committed failing first (the package is a docstring: no run(), no match(), no CLI), then made to pass.

What is checked, each from the fixtures under wtdd/livecheck/fixtures/ (written by fixtures/make.py, every row labelled
cached true / source stub) and the table wtdd/livecheck/steps.json:
  Replay   the PASS fixture names its deciding row (the last dog.grid_save) with its ts; the per-second stderr lines carry
           the counts; the timeout FAIL names the missing tool and the where field; a fatal WARN in the log fails with
           that line; the unsafe fixture returns UNSAFE naming the dog.follow row (after route.refused); exit codes 0/1/2.
  Table    --list shows an `unchecked` step; --step on it exits 1 and says so; every entry is well formed; the items the
           goal names (01 02 03 04 06 07 09 14 15) each have at least one checked step.
  Verdict  livecheck.json is written per verdict with the goal's keys and rewritten by the next run.
  Live     a row landing after the command started is graded within a second (a thread appends rows to a temp ledger and
           the API's log lines to a temp log; rows written before the start are history and do not count: the tail starts
           at the end); a stub row never passes a live (non-replay) step; a step with fatal_warns cannot PASS while the API
           log stays silent (its regexes were never tried), a log line trailing the last row by a poll still passes, and a
           step with no fatal_warns needs no API log at all.
  Draft    needs_the_dog_lines() on the four PR-body shapes (`**Needs the dog**` and `## Needs the dog` with `1.` lines,
           fixtures trimmed from PRs #5 and #4; steps numbered inside bold, `**<k> · text**` and `- **<item>.<k>** text`,
           trimmed from PRs #14 and #15; prechecks `1.`-`4.` then `- **21.1: text**` / `- **21.1b: text**`, trimmed from
           PR #19, where k 1b is read whole, the colon is not the title's, the keys drafted twice are each one WARN naming
           the PR and both titles, and a bold step number that cannot be read whole is a WARN, never read as a shorter one)
           yields the numbered lines of that section only; draft() makes steps with empty
           rows; the table's titles for 01 and 04 are those lines verbatim; `--from-prs` (gh stubbed at open_prs) writes
           the draft, WARNs on a PR with no section, and fails loud when gh fails; a usage error exits 1 (FAIL), never 2
           (UNSAFE's code).
  Api      GET /livecheck serves livecheck.json with age_s (the remote's mono line), a stale waiting state is flagged,
           and with no file it says how to make one.
  Page     the remote's LiveCheck component, run in node against a stubbed reply: a non-2xx reply (a 500, main's 404) and
           a body with no `verdict` key draw red with the status and the reason, never the grey idle line; the API's
           idle body still draws idle and a PASS green.
  Where    match() handles a plain value, gte/lte/in/re, and a missing path, and says which field failed.
  Rows     the table against the rows and log lines the branches write, each check seen failing on what it claims: 01.1
           grades frame_id from a dog.grid_save row and fails on a first lidar frame that is not odom (feat/01 refuses
           only a frame_id that changes); 02.4 is UNSAFE when the first stop's decided lands before its watch.boxes, and
           a FAIL, never an UNSAFE, when stop 1's watch.boxes or decided failed or its decided is a stub (the order was
           right; stop 2's watch.boxes must not read as a misorder); 14.3 passes a closed clockwise spin (feat/14 closes on
           the magnitude); a replay row with no readable ts WARNs; the {tool, between: [A, B]} unsafe pattern, which no step
           uses yet, is graded on a tiny spec (seen failing with its comparison mutated to <, >= and swapped).
Nothing here touches a dog, the real ledger or the real livecheck.json: every path is a fixture or a temp file."""
from __future__ import annotations
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from wtdd import livecheck

FIX = Path(__file__).resolve().parent / "fixtures"
LEDGER_PASS = FIX / "ledger-01-3.jsonl"
LEDGER_TIMEOUT = FIX / "ledger-01-3-timeout.jsonl"
LEDGER_UNSAFE = FIX / "ledger-04-4-unsafe.jsonl"
LOG_OK = FIX / "api-01-3.log"
LOG_WARN = FIX / "api-01-3-warn.log"
VERDICT_KEYS = {"step", "title", "t0", "elapsed_s", "seen", "expected", "verdict", "deciding_row"}


def run(**kw) -> tuple[dict, str, str]:
    """livecheck.run(...) with stdout and stderr captured: (verdict object, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        v = livecheck.run(**kw)
    return v, out.getvalue(), err.getvalue()


def cli(argv: list[str]) -> tuple[int, str, str]:
    from wtdd.livecheck import __main__ as m
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = m.main(argv)
    return rc, out.getvalue(), err.getvalue()


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "livecheck.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixture_pass_names_its_row(self):
        v, out, err = run(step="01.3", ledger=LEDGER_PASS, log=LOG_OK, replay=True, out=self.out)
        self.assertEqual(v["verdict"], "PASS", v)
        self.assertEqual(v["deciding_row"]["tool"], "dog.grid_save")
        self.assertEqual(v["deciding_row"]["args"]["frames"], 74, "the second save (after the drive) decides, not the baseline")
        self.assertEqual((v["seen"], v["expected"]), (3, 3))
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("PASS 01.3 · "), last)
        self.assertIn("dog.grid_save", last)
        self.assertIn("2026-09-27T20:00:12", last, "the deciding row's ts is on the verdict line")
        ticks = [l for l in err.splitlines() if l.startswith("[wtdd:livecheck] 01.3 · ")]
        self.assertGreaterEqual(len(ticks), 10, "one stderr line per simulated second (rows at +0, +3, +12 s)")
        self.assertTrue(all(re.search(r" · \d+ s · rows \d/3 · last ", l) for l in ticks), ticks[:3])
        self.assertTrue(any(" · rows 2/3 · " in l and "waiting" in l for l in ticks), ticks)
        self.assertEqual(livecheck.exit_code(v), 0)

    def test_timeout_fail_names_missing_tool_and_field(self):
        v, out, err = run(step="01.3", ledger=LEDGER_TIMEOUT, log=LOG_OK, replay=True, timeout_s=20, out=self.out)
        self.assertEqual(v["verdict"], "FAIL", v)
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("FAIL 01.3 · timeout after 20 s: missing dog.grid_save where "), last)
        self.assertIn("args.frames gte 30", last, "the where field that the missing row had to satisfy is named")
        self.assertEqual((v["seen"], v["expected"]), (2, 3))
        self.assertEqual(v["elapsed_s"], 20)
        self.assertEqual(len([l for l in err.splitlines() if l.startswith("[wtdd:livecheck] 01.3 · ")]), 20)
        self.assertEqual(livecheck.exit_code(v), 1)

    def test_fatal_warn_in_log_fails(self):
        v, out, _ = run(step="01.3", ledger=LEDGER_PASS, log=LOG_WARN, replay=True, out=self.out)
        self.assertEqual(v["verdict"], "FAIL", v)
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("FAIL 01.3 · "), last)
        self.assertIn("WARN lidar frame callback failed err=ValueError: frame_id 'map' is not the grid's 'odom': another frame, refused",
                      last, "the fatal line, verbatim (feat/01's occupancy.update_frame refusal)")
        self.assertIn("WARN lidar frame callback failed", str(v["deciding_row"]))
        self.assertEqual(livecheck.exit_code(v), 1)

    def test_unsafe_fixture_names_the_row(self):
        v, out, _ = run(step="04.4", ledger=LEDGER_UNSAFE, log=LOG_OK, replay=True, out=self.out)
        self.assertEqual(v["verdict"], "UNSAFE", v)
        self.assertEqual(v["deciding_row"]["tool"], "dog.follow")
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("UNSAFE 04.4 · dog.follow after route.refused · "), last)
        self.assertIn('"tool": "dog.follow"', last, "the offending row, verbatim")
        self.assertIn('"ts": "2026-09-27T20:10:03"', last)
        self.assertEqual(livecheck.exit_code(v), 2)

    def test_cli_replay_exit_codes(self):
        rc, out, _ = cli(["--step", "01.3", "--replay", "--ledger", str(LEDGER_PASS), "--log", str(LOG_OK), "--out", str(self.out)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("PASS 01.3 · "))
        rc, out, _ = cli(["--step", "04.4", "--replay", "--ledger", str(LEDGER_UNSAFE), "--log", str(LOG_OK), "--out", str(self.out)])
        self.assertEqual(rc, 2, out)
        rc, out, _ = cli(["--step", "01.3", "--replay", "--timeout", "5", "--ledger", str(LEDGER_TIMEOUT), "--log", str(LOG_OK), "--out", str(self.out)])
        self.assertEqual(rc, 1, out)
        self.assertIn("timeout after 5 s", out)


class Table(unittest.TestCase):
    REQUIRED_CHECKED = ["01", "02", "03", "04", "06", "07", "09", "14", "15"]   # the goal: entered at least for these

    def test_list_shows_unchecked(self):
        rc, out, _ = cli(["--list"])
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertTrue(any("01.8" in l and "unchecked" in l for l in lines), out)
        self.assertTrue(any("01.3" in l and "rows 3" in l and "Walk about 3 m" in l for l in lines), out)

    def test_unchecked_step_cannot_pass(self):
        with tempfile.TemporaryDirectory() as d:
            outp = Path(d) / "livecheck.json"
            rc, out, _ = cli(["--step", "01.8", "--replay", "--ledger", str(LEDGER_PASS), "--log", str(LOG_OK), "--out", str(outp)])
            self.assertEqual(rc, 1, out)
            last = out.strip().splitlines()[-1]
            self.assertTrue(last.startswith("FAIL 01.8 · unchecked"), last)
            v = json.loads(outp.read_text())
            self.assertEqual(v["verdict"], "FAIL")
            self.assertIn("unchecked", v["why"])

    def test_steps_table_is_well_formed(self):
        steps = livecheck.load_steps()
        self.assertIsInstance(steps, dict)
        self.assertIn("01.3", steps)
        for key, s in steps.items():
            self.assertEqual(key, s["step"])
            self.assertTrue(key.startswith(s["item"] + "."), key)
            for k in ("item", "step", "title", "do", "rows", "fatal_warns", "unsafe", "timeout_s"):
                self.assertIn(k, s, f"{key} lacks {k}")
            self.assertTrue(s["title"].strip(), f"{key} has an empty title")
            self.assertGreater(s["timeout_s"], 0)
            for r in s["rows"]:
                self.assertIn("tool", r, key)
                self.assertIn("ok", r, key)
                self.assertIsInstance(r.get("where", {}), dict, key)
            for u in s["unsafe"]:
                self.assertIn("tool", u, key)
                self.assertTrue(("before" in u) != ("between" in u), f"{key}: unsafe is {{tool, before}} or {{tool, between}}")
            for w in s["fatal_warns"]:
                re.compile(w)
        checked = {s["item"] for s in steps.values() if s["rows"]}
        missing = [i for i in self.REQUIRED_CHECKED if i not in checked]
        self.assertEqual(missing, [], f"items with no checked step yet: {missing}")


class Verdict(unittest.TestCase):
    def test_livecheck_json_written_per_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            outp = Path(d) / "livecheck.json"
            run(step="01.3", ledger=LEDGER_PASS, log=LOG_OK, replay=True, out=outp)
            v = json.loads(outp.read_text())
            self.assertTrue(VERDICT_KEYS <= set(v), set(v))
            self.assertEqual(v["verdict"], "PASS")
            self.assertEqual(v["step"], "01.3")
            self.assertTrue(v["title"].startswith("Walk about 3 m"))
            run(step="04.4", ledger=LEDGER_UNSAFE, log=LOG_OK, replay=True, out=outp)
            v2 = json.loads(outp.read_text())
            self.assertEqual(v2["verdict"], "UNSAFE")
            self.assertEqual(v2["step"], "04.4")
            self.assertFalse(list(Path(d).glob("*.tmp")), "the atomic write leaves no temp file behind")


class Live(unittest.TestCase):
    """The non-replay path on temp files: rows appended after the start count, history does not, a stub row fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ledger, self.log, self.out = self.dir / "ledger.jsonl", self.dir / "api.log", self.dir / "livecheck.json"
        self.log.write_text("[wtdd:api] serving http://127.0.0.1:7929/  tools=23\n")

    def tearDown(self):
        self.tmp.cleanup()

    def api_says(self, tool: str, path: str) -> None:
        """The two stderr lines the API tees for one tool call: ledger.step's line, then log_message's request line."""
        with self.log.open("a") as f:
            f.write(f"[wtdd:dog] {tool} ok=True app=map ms=3 err=\n[wtdd:api] \"POST {path} HTTP/1.1\" 200 -\n")

    @staticmethod
    def live_row(ts: str, tool: str, args: dict, after) -> str:
        return json.dumps({"ts": ts, "run_id": "test", "cached": False, "source": "live", "step": tool, "agent": "dog", "tool": tool,
                           "app": "map", "args": args, "state_before": None, "state_after": after, "ok": True,
                           "response_or_error": None, "latency_ms": 1}) + "\n"

    def test_rows_landing_after_start_pass_within_a_second(self):
        history = "".join(json.loads(l) and l for l in LEDGER_PASS.read_text().splitlines(True))   # a full PASS sequence, already there
        self.ledger.write_text(history)
        t_row = []

        def land():
            time.sleep(0.4)
            with self.ledger.open("a") as f:
                f.write(self.live_row("2026-09-27T21:00:00", "dog.calibrate", {"p": [1, 2], "heading_deg": 0.0}, {"map": {"p": [1, 2]}})); f.flush()
                self.api_says("dog.calibrate", "/dog/calibrate")
                time.sleep(0.3)
                f.write(self.live_row("2026-09-27T21:00:03", "dog.grid_save", {"file": "ui/grid.json", "frames": 5, "frame_id": "odom", "resolution": 0.05, "cal_at": "x"},
                                      {"cells": 50, "frames": 5, "extent_m": {"x": [-3.2, 3.2], "y": [-3.2, 3.2]}})); f.flush()
                self.api_says("dog.grid_save", "/dog/grid")
                time.sleep(0.3)
                f.write(self.live_row("2026-09-27T21:00:09", "dog.grid_save", {"file": "ui/grid.json", "frames": 60, "frame_id": "odom", "resolution": 0.05, "cal_at": "x"},
                                      {"cells": 900, "frames": 60, "extent_m": {"x": [-3.2, 6.4], "y": [-3.2, 3.2]}})); f.flush()
                t_row.append(time.monotonic())
                self.api_says("dog.grid_save", "/dog/grid")

        threading.Thread(target=land, daemon=True).start()
        t0 = time.monotonic()
        v, out, _ = run(step="01.3", ledger=self.ledger, log=self.log, timeout_s=8, out=self.out)
        took = time.monotonic() - t0
        self.assertEqual(v["verdict"], "PASS", (v, out))
        self.assertEqual(v["deciding_row"]["ts"], "2026-09-27T21:00:09", "the new row decides, not the fixture history (the tail starts at the end)")
        self.assertLess(took - (t_row[0] - t0), 1.5, "the verdict lands within about a second of the last row")

    def test_stub_row_never_passes_a_live_step(self):
        self.ledger.write_text(LEDGER_PASS.read_text())
        v, out, _ = run(step="01.3", ledger=self.ledger, log=self.log, timeout_s=3, from_start=True, out=self.out)
        self.assertEqual(v["verdict"], "FAIL", (v, out))
        self.assertIn("stub", v["why"])
        self.assertEqual(v["deciding_row"]["tool"], "dog.calibrate")
        self.assertTrue(out.strip().splitlines()[-1].startswith("FAIL 01.3 · stub row cannot pass a live step"), out)

    def test_missing_log_fails_loud(self):
        self.log.unlink()
        self.ledger.write_text("")
        v, out, _ = run(step="01.3", ledger=self.ledger, log=self.log, timeout_s=3, out=self.out)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertIn("tee -a logs/api.log", out, "the FAIL line says how to start the API so the log exists")

    def test_a_silent_api_log_cannot_pass_a_step_that_reads_it(self):
        """The API started without the tee: logs/api.log is yesterday's file and nothing new lands in it. 01.3's rows land,
        its four fatal_warns are never tried, and a PASS here would be a green nobody checked."""
        self.ledger.write_text("")

        def land():
            time.sleep(0.4)
            with self.ledger.open("a") as f:
                f.write(self.live_row("2026-09-27T21:00:00", "dog.calibrate", {"p": [1, 2]}, {})); f.flush()
                f.write(self.live_row("2026-09-27T21:00:03", "dog.grid_save", {"frames": 5, "frame_id": "odom"}, {"cells": 50})); f.flush()
                f.write(self.live_row("2026-09-27T21:00:09", "dog.grid_save", {"frames": 60, "frame_id": "odom"}, {"cells": 900})); f.flush()

        threading.Thread(target=land, daemon=True).start()
        v, out, _ = run(step="01.3", ledger=self.ledger, log=self.log, timeout_s=8, out=self.out)
        self.assertEqual(v["verdict"], "FAIL", out)
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith(f"FAIL 01.3 · the API log {self.log} was silent while 3 rows landed: fatal_warns never read"), last)
        self.assertIn("tee -a logs/api.log", last, "the FAIL line says how to start the API so the log is written")

    def test_a_log_line_trailing_the_last_row_still_passes(self):
        """ledger.step appends the row, then logs its line: the check may read the row a poll before the line lands."""
        self.ledger.write_text("")

        def land():
            time.sleep(0.4)
            with self.ledger.open("a") as f:
                f.write(self.live_row("2026-09-27T21:00:30", "dog.scout", {"z_rad_s": 0.5},
                                      {"frames": 40, "cells_added": 300, "cb_errors_during": 0, "closed": True})); f.flush()
            time.sleep(0.5)
            self.api_says("dog.scout", "/dog/scout")

        threading.Thread(target=land, daemon=True).start()
        v, out, _ = run(step="14.1", ledger=self.ledger, log=self.log, timeout_s=8, out=self.out)
        self.assertEqual(v["verdict"], "PASS", out)

    def test_a_step_without_fatal_warns_needs_no_api_log(self):
        """02.2 runs the decide CLI outside the API: its row is the whole check, and no API log is read."""
        self.log.unlink()
        self.ledger.write_text("")
        row = {"ts": "2026-09-27T21:01:00", "run_id": "test", "cached": False, "source": "live", "step": "decided", "agent": "decide",
               "tool": "decided", "app": "openrouter", "args": {"stop": None, "threshold": 0.7}, "state_before": {"labels": ["clear"]},
               "state_after": {"label": "clear", "p": 0.62, "needs_person": True, "model": "typesafe/jev-1.13-2026-09-01"},
               "ok": True, "response_or_error": "{}", "latency_ms": 900}

        def land():
            time.sleep(0.4)
            with self.ledger.open("a") as f:
                f.write(json.dumps(row) + "\n")

        threading.Thread(target=land, daemon=True).start()
        v, out, _ = run(step="02.2", ledger=self.ledger, log=self.log, timeout_s=5, out=self.out)
        self.assertEqual(v["verdict"], "PASS", out)
        self.assertFalse(self.log.exists())


class Draft(unittest.TestCase):
    def test_from_prs_fixture_yields_numbered_lines(self):
        body = (FIX / "pr-body-01.md").read_text()
        lines = livecheck.needs_the_dog_lines(body)
        self.assertEqual([k for k, _ in lines], ["1", "2", "3", "4", "5", "6", "7", "8"])
        self.assertTrue(lines[0][1].startswith("`frame_id` must be `odom`."), lines[0])
        self.assertTrue(lines[2][1].startswith("Walk about 3 m"), lines[2])
        self.assertFalse(any("Shared files" in t or "wtdd/api.py" in t for _, t in lines), "numbered lines outside the section are not taken")
        steps = livecheck.draft([{"number": 5, "title": "01 · Every LiDAR window is accumulated ...", "body": body}])
        self.assertEqual([s["step"] for s in steps], [f"01.{k}" for k in range(1, 9)])
        self.assertTrue(all(s["rows"] == [] and s["item"] == "01" and s["pr"] == 5 for s in steps))
        self.assertEqual(steps[2]["title"], lines[2][1])

    def test_h2_heading_shape(self):
        lines = livecheck.needs_the_dog_lines((FIX / "pr-body-04.md").read_text())
        self.assertEqual([k for k, _ in lines], ["1", "2", "3", "4", "5", "6"])
        self.assertTrue(lines[3][1].startswith('Press "▶ walk the path"'), lines[3])
        self.assertFalse(any("cut from this fixture" in t for _, t in lines), "numbered lines outside the section are not taken")

    def test_table_titles_are_the_pr_lines_verbatim(self):
        steps = livecheck.load_steps()
        for item, name in (("01", "pr-body-01.md"), ("04", "pr-body-04.md")):
            for k, text in livecheck.needs_the_dog_lines((FIX / name).read_text()):
                self.assertEqual(steps[f"{item}.{k}"]["title"], text, f"{item}.{k}")

    def test_cli_from_prs_writes_the_draft(self):
        prs = [{"number": 5, "title": "01 · Every LiDAR window is accumulated ...", "body": (FIX / "pr-body-01.md").read_text()},
               {"number": 4, "title": "04 · A zone drawn on the map blocks ...", "body": (FIX / "pr-body-04.md").read_text()},
               {"number": 99, "title": "99 · a PR with no such section", "body": "**Goal**\n\n1. not a step\n"}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(livecheck, "open_prs", return_value=prs):
            outp = Path(d) / "steps.draft.json"
            rc, out, err = cli(["--from-prs", "--draft-out", str(outp)])
            self.assertEqual(rc, 0, out + err)
            steps = json.loads(outp.read_text())["steps"]
        self.assertEqual([s["step"] for s in steps], [f"01.{k}" for k in range(1, 9)] + [f"04.{k}" for k in range(1, 7)])
        self.assertTrue(all(s["rows"] == [] for s in steps))
        self.assertEqual([s["pr"] for s in steps[::8]], [5, 4])
        self.assertTrue(any("WARN" in l and "#99" in l for l in err.splitlines()), "a PR with no Needs-the-dog lines is a WARN, not a silence")

    def test_steps_numbered_inside_bold(self):
        """PR #14 (item 20) numbers its steps as bold lines, `**1 · Start the API ...**`; PR #15 (item 26) as `- **26.1** text`;
        PR #16 (item 24) as `- **24.1 · text.**`. A bold line that starts with a step number is a step, not the section's end."""
        lines = livecheck.needs_the_dog_lines((FIX / "pr-body-20.md").read_text())
        self.assertEqual([k for k, _ in lines], ["0", "1", "2", "3", "4", "5"])
        self.assertEqual(lines[0][1], "First, add `WTDD_MODE=house` to `.env` (the two lines under `# 20 · mode-vocabulary` in `.env.example`).")
        self.assertEqual(lines[1][1], "Start the API with `python -m wtdd.api`.")
        self.assertEqual(lines[4][1], "20.1 on Sunday.")
        lines = livecheck.needs_the_dog_lines((FIX / "pr-body-26.md").read_text())
        self.assertEqual([k for k, _ in lines], ["1", "2", "3", "4", "5"], "the indented 1. 2. 3. under 26.1 are not steps")
        self.assertTrue(lines[0][1].startswith("After the first live `dog.calibrate`, open the remote"), lines[0])
        self.assertTrue(lines[3][1].startswith("(a known limit) On the tablet, check whether"), lines[3])
        for name in ("pr-body-20.md", "pr-body-26.md"):
            self.assertFalse(any("cut from this fixture" in t for _, t in livecheck.needs_the_dog_lines((FIX / name).read_text())), name)
        body = "**Needs the dog**\n\n- **0 · before every step:**\n  - a sub-bullet\n- **24.1 · the six keys and the state line.**\n- **Extra · not a step.**\n"
        self.assertEqual(livecheck.needs_the_dog_lines(body), [("0", "before every step:"), ("1", "the six keys and the state line.")])
        steps = livecheck.draft([{"number": 15, "title": "26 · Every row has a tick ...", "body": (FIX / "pr-body-26.md").read_text()}])
        self.assertEqual([s["step"] for s in steps], [f"26.{k}" for k in range(1, 6)])

    def test_prechecks_then_bold_steps_with_a_letter(self):
        """PR #19 (item 21) numbers four prechecks `1.`-`4.`, then the goal's steps inside bold with the item, a colon and a
        letter suffix: `- **21.1: text**`, `- **21.1b: text**`. k 1b is read whole, the colon is not part of the title, and each
        key the two lists share (21.1 21.2 21.3) is one WARN naming the PR and both titles, never a silent duplicate."""
        body = (FIX / "pr-body-21.md").read_text()
        lines = livecheck.needs_the_dog_lines(body)
        self.assertEqual([k for k, _ in lines], ["1", "2", "3", "4", "1", "1b", "2", "3"])
        self.assertEqual(lines[4][1], "three taps on the session grid at the house. With the dog calibrated, the start is its believed pose, "
                                      "so three taps make three legs and three stops (the dry fixture's \"2 stops\" is the no-pose case).")
        self.assertTrue(lines[5][1].startswith("run this early (the round-3 reviewer's live risk). A believed pose within 40 px"), lines[5])
        self.assertTrue(lines[6][1].startswith("one tap behind the zone. Confirm a detour is drawn"), lines[6])
        self.assertEqual([t for _, t in lines if t[:1] in ":·."], [], "a separator is not part of a title")
        prs = [{"number": 19, "title": "21 · A route is planned over the session grid ...", "body": body}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(livecheck, "open_prs", return_value=prs):
            outp = Path(d) / "steps.draft.json"
            rc, out, err = cli(["--from-prs", "--draft-out", str(outp)])
            steps = json.loads(outp.read_text())["steps"]
        self.assertEqual(rc, 0, out + err)
        self.assertEqual([s["step"] for s in steps], ["21.1", "21.2", "21.3", "21.4", "21.1", "21.1b", "21.2", "21.3"])
        warns = [l for l in err.splitlines() if "WARN" in l and "drafted 2 times" in l]
        self.assertEqual([re.search(r" (21\.\w+) drafted", l).group(1) for l in warns], ["21.1", "21.2", "21.3"], err)
        self.assertTrue(all(l.count("#19 ") == 2 for l in warns), err)
        self.assertIn("The voxel origin under a pure turn", warns[0])
        self.assertIn("three taps on the session grid", warns[0])
        self.assertIn("3 duplicate step keys", err.strip().splitlines()[-1])

    def test_a_bold_step_number_that_cannot_be_read_is_loud(self):
        body = "## Needs the dog\n- **21.1.2 · a nested number**\n- **21.1bc: two letters**\n1. a step\n## Cut\n"
        with redirect_stderr(io.StringIO()) as err:
            lines = livecheck.needs_the_dog_lines(body, "#99")
        self.assertEqual(lines, [("1", "a step")], "a number that cannot be read whole is not read as a shorter one")
        warns = [l for l in err.getvalue().splitlines() if l.startswith("[wtdd:livecheck] WARN #99 ") and "step number" in l]
        self.assertEqual(len(warns), 2, err.getvalue())
        self.assertIn("**21.1bc: two letters**", warns[1])

    def test_a_usage_error_is_a_fail_not_an_unsafe(self):
        """argparse exits 2 on a usage error, UNSAFE's code: a typo must read as a FAIL (1)."""
        from wtdd.livecheck import __main__ as m
        for argv in (["--stp", "01.3"], []):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as e:
                m.main(argv)
            self.assertEqual(e.exception.code, 1, f"{argv}: {out.getvalue()} {err.getvalue()}")
            self.assertTrue(out.getvalue().startswith("FAIL usage · "), f"{argv}: {out.getvalue()!r}")

    def test_cli_from_prs_fails_loud_when_gh_fails(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(livecheck, "open_prs", side_effect=RuntimeError("gh pr list failed: not logged in")):
            outp = Path(d) / "steps.draft.json"
            rc, out, err = cli(["--from-prs", "--draft-out", str(outp)])
            self.assertEqual(rc, 1)
            self.assertIn("not logged in", out + err)
            self.assertFalse(outp.exists(), "no draft is written when the PRs could not be read")


class Api(unittest.TestCase):
    """GET /livecheck on a real wtdd.api handler on an ephemeral port, livecheck.OUT pointed at a temp file."""

    def setUp(self):
        from http.server import ThreadingHTTPServer
        from wtdd import api
        self.tmp = tempfile.TemporaryDirectory()
        self.outp = Path(self.tmp.name) / "livecheck.json"
        self.err = io.StringIO()
        self.quiet = redirect_stderr(self.err)
        self.quiet.__enter__()
        self.patch = mock.patch.object(livecheck, "OUT", self.outp)
        self.patch.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/livecheck"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.patch.stop()
        self.quiet.__exit__(None, None, None)
        self.tmp.cleanup()

    def get(self) -> dict:
        import urllib.request
        with urllib.request.urlopen(self.url, timeout=5) as r:
            self.assertEqual(r.status, 200)
            return json.loads(r.read())

    def test_no_verdict_yet_says_how(self):
        d = self.get()
        self.assertIsNone(d.get("verdict"), d)
        self.assertIn("python -m wtdd.livecheck --step", d.get("why", ""))

    def test_serves_the_newest_verdict(self):
        run(step="04.4", ledger=LEDGER_UNSAFE, log=LOG_OK, replay=True, out=self.outp)   # captured: the verdict line stays out of the gate's output
        d = self.get()
        self.assertEqual((d["step"], d["verdict"]), ("04.4", "UNSAFE"))
        self.assertEqual(d["deciding_row"]["tool"], "dog.follow")
        self.assertIsInstance(d["age_s"], (int, float))
        self.assertFalse(d["stale"])

    def test_a_dead_waiting_state_is_stale(self):
        self.outp.write_text(json.dumps({"step": "01.3", "title": "t", "t0": "x", "elapsed_s": 4, "seen": 1, "expected": 3,
                                         "verdict": "waiting", "deciding_row": None}))
        old = time.time() - 30
        os.utime(self.outp, (old, old))
        d = self.get()
        self.assertEqual(d["verdict"], "waiting")
        self.assertTrue(d["stale"], "a waiting state nobody rewrote for 30 s is a killed livecheck, flagged for the page to draw red")



class Page(unittest.TestCase):
    """The remote's LiveCheck component (ui/index.html, the `// 22 · livecheck` block, extracted verbatim) run in node
    against one stubbed GET /livecheck reply each: a non-2xx reply (main's API has no route and answers 404) and a 2xx
    body with no `verdict` key draw the red FAILED line with the status and the reason, never the grey idle line; the
    API's own idle body and a PASS still draw idle and green. React's two hooks, htm's tag and fetch are stubbed in the
    harness, so nothing is loaded from npm or the network; node is the one already on this Mac for the playwright
    screenshots. No node is a failed test, never a skip."""
    HARNESS = r"""
let state, effect;
const useState = init => [state === undefined ? init : state, v => { state = v; }];
const useEffect = fn => { effect = fn; };
const setInterval = () => 0, clearInterval = () => {};
const html = (s, ...v) => s.reduce((a, x, i) => a + x + (i < v.length ? v[i] : ""), "");
const REPLY = JSON.parse(process.argv[2]);
const fetch = async () => ({ ok: REPLY.status >= 200 && REPLY.status < 300, status: REPLY.status,
                             json: async () => JSON.parse(REPLY.body), text: async () => REPLY.body });
/*COMPONENT*/
LiveCheck(); effect();
setTimeout(() => process.stdout.write(String(LiveCheck())), 50);
"""

    def draw(self, status: int, body) -> str:
        """The component's markup after one poll answered with `status` and `body` (a dict is sent as JSON)."""
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.fail("node is not on PATH: the page test runs the LiveCheck component in node (the one playwright uses)")
        src = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
        m = re.search(r"^// 22 · livecheck · start\n(.*?)^// 22 · livecheck · end$", src, re.S | re.M)
        self.assertIsNotNone(m, "ui/index.html has no `// 22 · livecheck` block")
        with tempfile.TemporaryDirectory() as d:
            js = Path(d) / "page.js"
            js.write_text(self.HARNESS.replace("/*COMPONENT*/", m.group(1)))
            body = body if isinstance(body, str) else json.dumps(body)
            p = subprocess.run([node, str(js), json.dumps({"status": status, "body": body})], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def assertRed(self, out: str, *reason: str) -> None:
        self.assertIn("class=lc-line bad", out, out)
        self.assertIn("FAILED", out, out)
        self.assertNotIn("no step running", out, "a failed poll drew the grey idle line: " + out)
        self.assertNotIn("undefined", out, out)
        for r in reason:
            self.assertIn(r, out, out)

    def test_a_500_draws_red_with_the_status_and_reason(self):
        self.assertRed(self.draw(500, {"error": "livecheck.json is not JSON"}), "500", "livecheck.json is not JSON")

    def test_mains_api_without_the_route_draws_red(self):
        self.assertRed(self.draw(404, {"error": "no livecheck"}), "404", "no livecheck")   # main's api.py static fallthrough

    def test_a_body_with_no_verdict_key_is_a_fail_never_idle(self):
        self.assertRed(self.draw(200, {"error": "boom"}), "verdict", "boom")
        self.assertRed(self.draw(200, {}), "verdict")

    def test_the_idle_body_and_a_pass_still_draw(self):
        why = "no livecheck.json yet: run python -m wtdd.livecheck --step <item>.<k>"
        out = self.draw(200, {"verdict": None, "why": why})
        self.assertIn("class=lc-line idle", out, out)
        self.assertIn("livecheck · no step running · " + why, out)
        out = self.draw(200, {"step": "01.3", "verdict": "PASS", "short": "PASS · 01.3 · dog.grid_save ok", "stale": False})
        self.assertIn("class=lc-line ok", out, out)
        self.assertIn(">PASS · 01.3 · dog.grid_save ok<", out, out)

class Where(unittest.TestCase):
    ROW = {"tool": "dog.grid_save", "ok": True, "source": "live", "args": {"frame_id": "odom", "frames": 74}, "state_after": {"cells": 1510, "extent_m": 8.9}}

    def test_match_operators(self):
        self.assertIsNone(livecheck.match(self.ROW, {"tool": "dog.grid_save", "ok": True, "where": {"args.frame_id": "odom", "args.frames": {"gte": 30}}}))
        self.assertIsNone(livecheck.match(self.ROW, {"tool": "dog.grid_save", "ok": True, "where": {"state_after.extent_m": {"gte": 3, "lte": 20}, "source": {"in": ["live", "stub"]}, "args.frame_id": {"re": "^od"}}}))
        why = livecheck.match(self.ROW, {"tool": "dog.grid_save", "ok": True, "where": {"args.frames": {"gte": 100}}})
        self.assertIn("args.frames gte 100", why)
        self.assertIn("74", why, "the value seen is named")
        self.assertIsNotNone(livecheck.match(self.ROW, {"tool": "dog.grid_save", "ok": False, "where": {}}))
        self.assertIsNotNone(livecheck.match(self.ROW, {"tool": "dog.calibrate", "ok": True, "where": {}}))
        why = livecheck.match(self.ROW, {"tool": "dog.grid_save", "ok": True, "where": {"args.cal_at": {"re": "."}}})
        self.assertIn("args.cal_at", why)
        self.assertIsNotNone(livecheck.match(self.ROW, {"tool": "dog.grid_save", "agent": "watch", "ok": True, "where": {}}), "agent, when given, must match")


class Rows(unittest.TestCase):
    """steps.json's rows against the shapes on feat/01-occupancy, feat/02-decide and feat/14-scout-spin, replayed from temp files."""
    FIRST = ("[wtdd:dog] first lidar frame frame_id={} voxels=3812 width=[128, 128, 38] res=0.05 origin=[-3.2, -3.2, -0.3] "
             "center=[0.0, 0.0, 0.65] odom_pos=[0.28, 0.12, 0.31] center_vs_odom_m=0.31 z_layers={{}}\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.ledger, self.log, self.out = d / "ledger.jsonl", d / "api.log", d / "livecheck.json"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def r(s: int, tool: str, agent: str = "dog", args=None, after=None, **kw) -> dict:
        return {"ts": f"2026-09-27T21:00:{s:02d}", "run_id": "test", "cached": False, "source": "live", "step": tool, "agent": agent,
                "tool": tool, "app": "map", "args": args or {}, "state_before": None, "state_after": after, "ok": True,
                "response_or_error": None, "latency_ms": 1, **kw}

    def replay(self, step: str, rows: list[dict], log: str = "", **kw):
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.log.write_text(log)
        return run(step=step, ledger=self.ledger, log=self.log, replay=True, out=self.out, **kw)

    def test_01_1_grades_the_frame_id_from_the_device(self):
        connect = self.r(0, "dog.connect", app="unitree")
        save = lambda fid: self.r(6, "dog.grid_save", args={"file": "ui/grid.json", "frames": 40, "frame_id": fid, "resolution": 0.05, "cal_at": None})
        v, out, _ = self.replay("01.1", [connect, save("odom")], self.FIRST.format("odom"))
        self.assertEqual(v["verdict"], "PASS", out)
        self.assertEqual(v["deciding_row"]["tool"], "dog.grid_save", "the save carrying frame_id decides, not the connect")
        v, out, _ = self.replay("01.1", [connect, save("map")], self.FIRST.format("map"))
        self.assertEqual(v["verdict"], "FAIL", out)
        self.assertIn("first lidar frame frame_id=map", out.strip().splitlines()[-1],
                      "a frame_id that is consistently not odom is refused nowhere on feat/01: the first-frame line decides")
        v, out, _ = self.replay("01.1", [connect, save("map")], "", timeout_s=5)
        self.assertEqual(v["verdict"], "FAIL", "without the first-frame line the row's own frame_id still fails it: " + out)
        v, out, _ = self.replay("01.1", [connect], "", timeout_s=5)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FAIL 01.1 · timeout after 5 s: missing dog.grid_save where args.frame_id odom"),
                        "a LiDAR never switched on is a FAIL, not a PASS on the connect alone: " + out)

    def test_02_4_the_first_stop_order_decides(self):
        boxes = lambda s: self.r(s, "watch.boxes", "watch", {"file": "look-down.jpg"}, {"n": 1}, app="yolo")
        dec = lambda s, stop: self.r(s, "decided", "decide", {"stop": stop}, {"label": "clear", "p": 0.91, "model": "typesafe/jev-1.13-2026-09-01"},
                                     app="openrouter")
        v, out, _ = self.replay("02.4", [boxes(0), dec(2, 1), boxes(10), dec(12, 2)])
        self.assertEqual((v["verdict"], (v["deciding_row"] or {}).get("ts")), ("PASS", "2026-09-27T21:00:02"), out)
        v, out, _ = self.replay("02.4", [dec(0, 1), boxes(2), dec(10, 2), boxes(12)])
        self.assertEqual(v["verdict"], "UNSAFE", "the same rows with the stop's decided before its watch.boxes: " + out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("UNSAFE 02.4 · watch.boxes after decided · "), out)
        self.assertEqual(v["deciding_row"]["ts"], "2026-09-27T21:00:02")

    def live(self, step: str, rows: list[dict], log: str = "", **kw):
        """The rows as a live ledger read from its first line (--from-start): the stub rule is on, as on the dog."""
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.log.write_text(log)
        return run(step=step, ledger=self.ledger, log=self.log, from_start=True, timeout_s=5, out=self.out, **kw)

    def stop_rows(self):
        """feat/02-decide's rows at a stop (dog_say.look_and_see): watch.boxes on the floor frame, then decided; a picked room
        frame is boxed again after decided. A failed step is its own row with ok false (ledger.step)."""
        boxes = lambda s, ok=True: self.r(s, "watch.boxes", "watch", {"file": "look-down.jpg"}, {"n": 1} if ok else None, app="yolo", ok=ok,
                                          response_or_error=None if ok else "RuntimeError: detector rc=1: ")
        dec = lambda s, stop, ok=True: self.r(s, "decided", "decide", {"stop": stop},
                                              {"label": "clear", "p": 0.91, "model": "typesafe/jev-1.13-2026-09-01"} if ok else None,
                                              app="openrouter", ok=ok, response_or_error=None if ok else "HTTPError: HTTP Error 404: Not Found")
        stub = lambda s, stop: self.r(s, "decided", "decide", {"stop": stop}, {"label": "clear", "p": 0.8, "model": "stub"},
                                      app="stub", cached=True, source="stub")
        return boxes, dec, stub

    def test_02_4_a_stub_decided_at_stop_1_is_a_fail_not_an_unsafe(self):
        boxes, _, stub = self.stop_rows()
        v, out, _ = self.live("02.4", [boxes(0), stub(2, 1), boxes(10), stub(12, 2)])
        self.assertEqual(v["verdict"], "FAIL", "no JEV_API_KEY: the order was right, the decision was the stub's: " + out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FAIL 02.4 · stub row cannot pass a live step · "), out)
        self.assertEqual(v["deciding_row"]["ts"], "2026-09-27T21:00:02", "stop 1's stub decided decides, not stop 2's watch.boxes")

    def test_02_4_a_failed_stop_1_is_a_fail_not_an_unsafe(self):
        boxes, dec, _ = self.stop_rows()
        v, out, _ = self.live("02.4", [boxes(0, ok=False), dec(2, 1), boxes(10), dec(12, 2)])
        self.assertEqual(v["verdict"], "FAIL", "stop 1's detector failed, its order was right: " + out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FAIL 02.4 · watch.boxes failed: row 1/2 wants watch.boxes ok · "), out)
        self.assertEqual(v["deciding_row"]["ts"], "2026-09-27T21:00:00")
        v, out, _ = self.live("02.4", [boxes(0), dec(2, 1, ok=False), boxes(3), boxes(10)])
        self.assertEqual(v["verdict"], "FAIL", "stop 1's Jev call failed (a 404), then the picked frame was boxed: " + out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FAIL 02.4 · decided failed: row 2/2 wants decided ok · "), out)
        self.assertEqual(v["deciding_row"]["ts"], "2026-09-27T21:00:02")
        v, out, _ = self.live("02.4", [dec(0, 1), boxes(2), dec(10, 2), boxes(12)])
        self.assertEqual(v["verdict"], "UNSAFE", "the misorder itself, live, is still UNSAFE: " + out)

    def test_14_3_a_clockwise_spin_that_closed_passes(self):
        want = livecheck.load_steps()["14.3"]["rows"][0]
        after = {"turned_deg": -358.2, "closed_deg": -358.2, "closed": True, "avoid": True, "velocity_path": "sport"}
        self.assertIsNone(livecheck.match(self.r(0, "dog.scout", after=after), want), "feat/14 closes a negative-z spin on its magnitude")
        self.assertIsNotNone(livecheck.match(self.r(0, "dog.scout", after={**after, "closed": False}), want))

    def test_between_a_tool_after_a_and_before_b_is_unsafe(self):
        """{tool: T, between: [A, B]}: no step in steps.json uses it yet, so it is graded here on a tiny spec through _Check."""
        spec = {"step": "99.1", "title": "between", "rows": [{"tool": "x.end", "ok": True}], "fatal_warns": [],
                "unsafe": [{"tool": "dog.move", "between": ["zone.armed", "zone.disarmed"]}], "timeout_s": 10, "settle_s": 0}

        def grade(*tools):
            self.ledger.write_text("".join(json.dumps(self.r(s, t)) + "\n" for s, t in enumerate(tools + ("x.end",))))
            c = livecheck._Check("99.1", spec, self.out, True, self.ledger, self.log, None)
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                livecheck._replay(c)
            return c.v, out.getvalue()
        v, out = grade("zone.armed", "dog.move")
        self.assertEqual(v["verdict"], "UNSAFE", "a move after the zone was armed and before it was disarmed: " + out)
        self.assertTrue(out.startswith("UNSAFE 99.1 · dog.move between zone.armed and zone.disarmed · "), out)
        self.assertEqual((v["deciding_row"]["tool"], v["deciding_row"]["ts"]), ("dog.move", "2026-09-27T21:00:01"), "the T row decides")
        self.assertEqual(grade("zone.armed", "zone.disarmed", "dog.move")[0]["verdict"], "PASS", "a move after the disarm")
        self.assertEqual(grade("dog.move")[0]["verdict"], "PASS", "a move with no A row at all")
        v, out = grade("zone.disarmed", "zone.armed", "dog.move")
        self.assertEqual(v["verdict"], "UNSAFE", "a B row before the A row does not close the window: " + out)

    def test_replay_row_without_a_ts_is_loud(self):
        save = self.r(6, "dog.grid_save", args={"frames": 40, "frame_id": "odom"})
        del save["ts"]
        _, _, err = self.replay("01.1", [self.r(0, "dog.connect"), save], self.FIRST.format("odom"))
        self.assertIn("WARN 01.1 · replay row has no readable ts", err)


if __name__ == "__main__":
    unittest.main()

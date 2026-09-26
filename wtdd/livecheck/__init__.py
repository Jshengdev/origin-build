"""livecheck: one command grades a live hardware step from the ledger rows and the API's stderr log within a second of
them landing, PASS / FAIL / UNSAFE with the deciding row, graded from device state like the evals (never from anyone's
report). The table of steps is wtdd/livecheck/steps.json, drafted from every PR's Needs-the-dog list.

  python -m wtdd.livecheck --step 01.3                 tail <repo>/ledger.jsonl and <repo>/logs/api.log from their current
                                                       end, one stderr line per second, then the verdict on stdout
  python -m wtdd.livecheck --step 01.3 --replay --ledger wtdd/livecheck/fixtures/ledger-01-3.jsonl --log wtdd/livecheck/fixtures/api-01-3.log
                                                       the fixture, clocked by the rows' ts, no sleeping (the dry path)
  python -m wtdd.livecheck --list                      the table: item, step, title, rows count; `unchecked` when rows is empty
  python -m wtdd.livecheck --from-prs                  every open PR's Needs-the-dog lines -> wtdd/livecheck/steps.draft.json (rows empty;
                                                       `gh pr list` then `gh pr view <n> --json body`; --draft-out elsewhere)
  GET /livecheck                                       <repo>/livecheck.json (OUT), the newest verdict or waiting state plus age_s (the
                                                       remote's one mono line); --out writes elsewhere (the tests)

Step keys are <item>.<k>: k is the number (or letter) of the line in that item's PR under **Needs the dog**, the same k
the evening's `live <item> <k>` uses. A step with no rows is `unchecked`: it cannot PASS and says so (exit 1).

Verdicts, in the order they are decided while the files are tailed:
  UNSAFE <step> · <U> after <T> · <the U row, verbatim>        an `unsafe` pattern matched ({tool: T, before: U}: a T row
                                                              then a U row; {tool: T, between: [A, B]}: a T row after A and
                                                              before B); exit 2
  FAIL   <step> · <the fatal WARN line, verbatim>              a `fatal_warns` regex matched a log line; exit 1
  FAIL   <step> · stub row cannot pass a live step · <row>     a matched row with cached true or source "stub" outside
                                                              --replay (a fixture row never grades a live step); exit 1
  FAIL   <step> · timeout after N s: missing <tool> where <field op value>    N s since the check started (timeout_s,
                                                              or --timeout) and the next expected row never landed; exit 1
  PASS   <step> · <ts> <tool> ok                               every expected row matched in order, then settle_s more
                                                              seconds with no fatal warn and no unsafe pattern; exit 0
Every verdict, and every per-second `waiting` state, is written atomically to <repo>/livecheck.json
{step, title, t0, elapsed_s, seen, expected, verdict, why, deciding_row, ...}.

Tailing: both files are opened and seeked to their end when the command starts (--from-start reads history too); rows
are matched by `tool` (and `agent` when given) and by `ok`, then by every `where` field (a dotted path over the row:
args.zone, state_after.extent_m, source; a plain value is equality, {gte, lte, in, re} are operators). Log lines carry no
timestamp, so in --replay every log line is read before the first tick and the clock is the rows' ts.

UNVERIFIED on the real dog: nothing here has tailed a live ledger; the frames/cells thresholds in steps.json are guesses
(marked in each step's `note`) until the first live 01.3 writes its two dog.grid_save rows.
"""

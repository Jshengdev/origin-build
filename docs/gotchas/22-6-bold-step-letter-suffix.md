# 22-6 · a bold step number with a letter read as the item number

**Symptom.** `python -m wtdd.livecheck --from-prs` drafted PR #19's `- **21.1b: run this early** ...` as step `21.21`,
titled `.1b: run this early ...`. Every other bold step in that PR had a title that started with `: `. The same section
lists four prechecks `1.`-`4.` before its `21.1`-`21.3`, so the draft held 21.1, 21.2 and 21.3 twice. stderr said only
`--from-prs · 19 PRs · 121 steps · wrote ...`.

**Root cause.** The bold step regex read k as `(\d+|[a-z])\b` after an optional `<item>.`. In `21.1b` there is no word
boundary between `1` and `b`, so the regex backtracked: it dropped the `21.` prefix and took `21` as k, whose `\b` sits
before the `.`. Nothing checked that the number was read whole. The separator after k was only ` ·`, so `: ` stayed in the
title. Two numbered lists in one section give the same k twice, and the draft had no check for a repeated key.

**Fix (verbatim).** wtdd/livecheck/__init__.py:

```
BOLD = re.compile(r"^(?:- )?\*\*(?:\d+[a-z]?\.)?(\d+[a-z]?|[a-z])\b(?!\.\w)\s*([^*]*?)\s*\*\*\s*(.*)$")   # **1 · text** / - **21.1b: text**
NUMBOLD = re.compile(r"^(?:- )?\*\*\s*\d")   # a bold line opening with a number: a step, or a WARN when BOLD cannot read it
```

```
        elif m := BOLD.match(l):
            out.append((m.group(1), " ".join(t for t in m.group(2, 3) if t).lstrip(":· ")))
        elif NUMBOLD.match(l):
            say(f"WARN {who or 'Needs the dog'} · a bold line opens with a number that is not a step number read whole, not drafted: {l.strip()[:160]}")
```

wtdd/livecheck/__main__.py, `_from_prs`:

```
    dups = {k: ss for k, ss in by.items() if len(ss) > 1}
    for k, ss in dups.items():   # two numbered lists in one section (PR #19's prechecks, then its 21.k): load_steps refuses both
        lc.say(f"WARN --from-prs · {k} drafted {len(ss)} times, rename all but one before it goes in steps.json: "
               + " | ".join(f'#{s["pr"]} "{s["title"][:80]}"' for s in ss))
```

**Verify.** `.venv/bin/python -m unittest wtdd.livecheck.test_livecheck.Draft`, which runs these checks:
- `test_prechecks_then_bold_steps_with_a_letter`, on `fixtures/pr-body-21.md` (PR #19's section verbatim);
- `test_a_bold_step_number_that_cannot_be_read_is_loud`.

Then `python -m wtdd.livecheck --from-prs --draft-out /tmp/d.json` prints three `drafted 2 times` WARNs for #19 and
`3 duplicate step keys`, and the other open PRs draft as before.

Rule: a regex that reads a number out of free text must refuse a number it cannot read whole. Otherwise backtracking finds
a shorter number and nothing says so.

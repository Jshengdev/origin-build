# 22-2 · the API-log fixtures end in .log, which .gitignore ignores everywhere

**Symptom.** `git add wtdd/livecheck/fixtures/api-01-3.log wtdd/livecheck/fixtures/api-01-3-warn.log` refuses both
files ("The following paths are ignored by one of your .gitignore files ... Use -f if you really want to add them"),
so the RED commit went in with `git add -f`. A later fixture ending in `.log` would be left out the same way, and the
replay would then FAIL on a fresh checkout with `no API log at wtdd/livecheck/fixtures/<name>.log`.

**Root cause.** Line 21 of `.gitignore`, `*.log` under `# os / editor`, matches any `.log` in any directory. Main's rules
still match both tracked fixtures:
`git ls-files -i -c --exclude-from=<main's .gitignore> wtdd/livecheck/fixtures/` prints `api-01-3-warn.log` and
`api-01-3.log`.

**Fix (verbatim, appended at the end of .gitignore).**

```
# 22 · livecheck: the teed process logs it tails, its verdict file, the --from-prs draft; its .log fixtures are tracked
logs/
livecheck.json
wtdd/livecheck/steps.draft.json
!wtdd/livecheck/fixtures/*.log
```

The negation sits after `*.log`, so it wins for that directory only; `logs/api.log` and every other `.log` stay ignored.

**Verify.** `git check-ignore -v --no-index wtdd/livecheck/fixtures/api-01-3.log` names
`.gitignore:52:!wtdd/livecheck/fixtures/*.log` (the negation: not ignored), and
`git ls-files -i -c --exclude-from=.gitignore wtdd/livecheck/fixtures/` prints nothing;
`git check-ignore -v --no-index logs/api.log livecheck.json` names `logs/` and `livecheck.json`.

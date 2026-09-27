# 27-2 · a fixture named state.json cannot be committed

## Symptom
`git add wtdd/fixtures/page/state.json` is refused: "The following paths are ignored by one of your .gitignore files".
The page state fixture for the dry screenshots never reaches the branch, so any other checkout gets a
FileNotFoundError when WTDD_STATE_FIXTURE names it.

## Root cause
.gitignore line 39 is the bare pattern `state.json`, meant for the runtime file at the repo root. A pattern with no
slash matches at any depth, so it also ignores `wtdd/fixtures/page/state.json`.

## Fix (verbatim)
The fixture was renamed to `wtdd/fixtures/page/dog-state.json`. .gitignore is not touched: the runtime `state.json`
stays ignored everywhere.

## Verify
```
git check-ignore -v wtdd/fixtures/page/state.json       # .gitignore:39:state.json	wtdd/fixtures/page/state.json  (exit 0)
git check-ignore -v wtdd/fixtures/page/dog-state.json   # no output (exit 1): not ignored
```

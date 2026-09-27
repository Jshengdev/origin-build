# 02-2 · a test that pops an env key still reads it from .env

**Symptom.** `python -m unittest wtdd.test_decide` passed in a worktree (no `.env`) and failed in a checkout whose `.env` tuned the decide keys: with `WTDD_DECIDE_THRESHOLD=0.5`, `JEV_LIVE=1` and `WTDD_SHIFT=night-x` in `.env`, three checks failed for no bug in the code (`Stub.test_two_eyes_disagreeing_asks_a_person`: p 0.6 is not below 0.5; `Row.test_decided_row_shape`: threshold 0.5 != 0.7; `Live.test_stub_cli_prints_a_labeled_decision`: the CLI exited 2).

**Root cause.** `wtdd/config.py` `_load()` runs on the first `config.get()`/`config.maybe()` and does `os.environ.setdefault(k, v)` for every line of `<repo>/.env`. `os.environ.pop(key)` at the top of a test module only removes the key until that first call; the file then puts it back. `setdefault` leaves a key alone only when it is present, and `maybe()` reads an empty value as unset, so an empty string is the one value that both blocks the file and means "the default". A subprocess (`python -m wtdd.decide`) loads `.env` again from its own `config`, so its env needs the same empty keys.

**Fix (verbatim, `wtdd/test_decide.py`).**
```python
for _k in ("JEV_API_KEY", "JEV_MODEL", "JEV_LIVE", "WTDD_DECIDE_THRESHOLD", "WTDD_SHIFT"):
    os.environ[_k] = ""                   # the stub path and the defaults; config.maybe() reads an empty value as unset
```
```python
    def tearDown(self):
        os.environ["WTDD_DECIDE_THRESHOLD"] = ""
```
```python
    def tearDown(self):
        os.environ["WTDD_SHIFT"] = ""
```
```python
        e = {**os.environ, "WTDD_LEDGER": str(Path(_TMP) / "cli-ledger.jsonl"), "JEV_API_KEY": "", "JEV_LIVE": "",
             "WTDD_DECIDE_THRESHOLD": "", **env}
```

**Verify.** In a worktree, write a `.env` holding `JEV_API_KEY=sk-not-real`, `WTDD_DECIDE_THRESHOLD=0.5`, `JEV_LIVE=1`, `WTDD_SHIFT=night-x`, `JEV_MODEL=jev-latest`; `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide` reads `OK`; delete the `.env`. Any new test module that relies on a key being unset sets it to `""`, never pops it.

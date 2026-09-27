# 27-5 · the state fixture makes the page connect the dog, then hides the real dog behind invented numbers

## Symptom
With WTDD_STATE_FIXTURE set, GET /dog/state serves the fixture's `connected: true`. The page then pulls
/dog/frame.jpg every 2 s, and each pull runs Body.connect. In a worktree the connect fails on the venv check, and the
dry stub run for 27-remote.png wrote one `dog.probe` row in 3 s. In the repo checkout with the dog powered, the pull
would connect the real dog with no one pressing anything, and /dog/state would keep serving the fixture's pose.
`evals.run_follow` (wtdd/evals.py) and `field._dog` (wtdd/field.py) read GET /dog/state and never look at `source`.
A follow eval would grade from fixture numbers, and a lights-follow walk would drive the real lights from them, in rows
stamped live. "Never set it live" was only a sentence under Needs the dog, and nothing enforced it.

## Root cause
The DEMO_CACHE block at the top of `DogSession.state()` returned the fixture before looking at `self.body`. So the
dry-only path had no way to tell that it was no longer dry.

## Fix (verbatim)
wtdd/dog/session.py, inside `if fx:`, before the `return`:
```
            if self.body is not None:   # a real dog is connected: never serve an invented pose in its place (evals.run_follow and field._dog read GET /dog/state without looking at source)
                raise RuntimeError("WTDD_STATE_FIXTURE is set while a dog is connected: it is for dry screenshots only; unset it")
```
Once a Body is attached, GET /dog/state drops the connection and the API prints the RuntimeError. The page's dog tiles
turn red with `no answer from GET /dog/state`. Both readers above get a dropped connection, never fixture numbers.
Every branch that carries the same WTDD_STATE_FIXTURE block (24, 25, 29, 30) needs these two lines.

## Verify
1. `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_page_layers.StateFixture.test_fixture_with_a_real_dog_refuses`
   fails without the two lines (`RuntimeError not raised`) and passes with them.
2. In-process, with WTDD_STATE_FIXTURE set and `DogSession.get().body = object()`, serve `wtdd.api.H` on port 7934 and
   run `curl -sS http://127.0.0.1:7934/dog/state`. It prints `curl: (52) Empty reply from server`, and the server
   prints the RuntimeError.

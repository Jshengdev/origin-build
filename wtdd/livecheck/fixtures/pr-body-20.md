<!-- fixture for wtdd/livecheck/test_livecheck.py: the shape of PR #14's body (feat/20-mode-vocabulary), `**Bold**` headings and
the steps numbered inside bold (`**<k> · text**`). The Needs the dog section is copied verbatim from that PR; every other
section is cut down to a stub so the parser meets numbered lines outside the section. Nothing here is a result. -->
**Goal**

20 · "Modes" are a vocabulary the vision model and Jev already consume: YOLO11n stays the person and box detector unchanged, a site or house word list reaches the prompts and the label list, the mode is visible on the page, the false licence claim in `watch.py` is corrected, and every number about detectors is an artefact in the repo before it is a sentence.

**Verified**

1. (cut from this fixture)

**Needs the dog**

Nothing here ran on the dog. Run every step in /Users/johnnysheng/code/origin-build itself, never in a worktree (body.py refuses one).

**0 · First, add `WTDD_MODE=house` to `.env`** (the two lines under `# 20 · mode-vocabulary` in `.env.example`).
- Without it, `python -m wtdd.api` refuses to start: `RuntimeError: [wtdd:config] WTDD_MODE is required.`
- Everything that needs the API goes down with it: the intruder watch (watch.py calls the API), the page's lights and the follower.
- Every look (`see()`) also raises until its process has the key. That covers the listener's looks, the round's `who dis?!` and the evals `look` and `person` scenarios. Restart the listener after editing .env.

**1 · Start the API with `python -m wtdd.api`.**
- stderr shows `[wtdd:vocab] mode house: 12 words` before `[wtdd:api] serving`.
- The page shows the `mode · house` chip (hover it for the 12 words) and `vocab · person, cup, sock, ...` in the eye panel.
- `curl -s 127.0.0.1:7788/dog/state` returns mode, vocab and `vocab_error: null`.

**2 · The detector is unchanged on the live loop.** Run `python -m wtdd.watch` with the dog connected.
- The first line reads `model yolo11n.pt loaded ... device=cpu`.
- The watch.detect rows keep the same args and `{name, conf, xyxy}` boxes.
- Optional: `WTDD_WATCH_DEVICE=mps` should print `device=mps` and no WARN. A `WARN WTDD_WATCH_DEVICE=mps but ... running on cpu` line means the fallback worked.

**3 · 20.2, the person path is untouched.** Arm the intruder watch and step into frame.
- `who dis?!` and the alarm still fire on the detector's `person` box.
- The watch.detect row lists person.

**4 · 20.1 on Sunday.**
- Set `WTDD_MODE=site`, restart the API and check the chip reads `mode · site`.
- Put a listed thing (a traffic cone) in view and run one stop (`python -m wtdd dog_say` or a chat look).
- The llm.generate row's `say` or `out_of_place` should name the listed word. That would be the first live evidence; nothing here claims it.

**5 · Optional negative check.** Remove `vocab.site` from the map while the API runs.
- The chip turns yellow.
- A look fails loud before any model call (`couldn't look: LookupError ...` in the chat).
- Restore the map afterwards.

**Shared files touched**

1. (cut from this fixture)
**2 · (cut from this fixture)**

**Cut**

1. (cut from this fixture)

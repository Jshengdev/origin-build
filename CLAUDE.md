# origin-build · the weekend build

The code for Origin Weekend (USC, submit Sun 2026-09-27 23:59 PT): one agent, one body (a Unitree Go2), one group chat, lights, a LiDAR map, a ledger, evals graded from device state. The map, the sources of truth and the decisions live in `~/code/origin` and are read here through the gitignored `context/`. Nothing from `context/` is ever committed.

## Read first, in order
1. `context/READ-ORDER.md`, then `context/DECISION-001.md` (why this repo exists, in Johnny's words).
2. `goals/roadmap.md`: the contract for every item, one section each.
3. `README.md`: what exists and how it is known to work. It is the record of the shipped system; do not rewrite it to describe plans.
4. The docstring at the top of every file you touch. Each file says what it does, how, and what is UNVERIFIED on the real dog.

## Laws (unchanged from the shipped system; every PR is checked against them)
- **No silent stubs.** No canned result behind a catch, no `[]` hiding an error, no `?? default` that swallows a failure. A failure renders a visible FAILED state and a ledger row.
- **Every shortcut is labeled** `// DEMO_CACHE:` (or `# DEMO_CACHE:`) naming what is cached, why, and how to run it live. The test: could a judge flip one flag and watch the live path produce it.
- **Receipts.** Every step appends one row to the ledger with the device state before and after, the raw response or the error, and the latency. Append-only. Never rewritten. A step counts as done only when the device said so.
- **Evals, RED first.** A check that has never failed has never checked anything. Commit the failing test, then make it pass. Grade from device state, never from the agent's own report. `pass`, `fail`, `unsafe`.
- **Fail loud, log loud.** One line per step to stderr with counts and latency. Zero of anything is a WARN.
- **Lazy-senior-dev fast, not fake-it fast.** Reuse, fewest lines, fewest deps. No framework. No abstraction that was not requested. Deletion over addition.
- **Models label; they never draw geometry the LiDAR did not see.** Shapes come from points. Words come from models. A model that invents a wall is a fabricated performance claim.

## The hardware rule for agents
Agents do not have the dog, the lights, the Hue bridge, or this Mac's Messages. Every feature is built and verified in dry mode on synthetic or replayed data: the ledger samples in `docs/evidence/`, synthetic voxel frames (see how `wtdd/dog/lidar.py` did it offline), stub clients for Jev, Hue, Tuya and chat. Each PR lists, under **Needs the dog**, the exact steps Johnny runs on hardware and what the first live run must confirm. No PR claims it ran on hardware.

## Branches and pull requests
- One roadmap item per branch: `feat/<nn>-<slug>` (`nn` from `goals/roadmap.md`).
- Base is `main` unless the goal says `stacks_on: <nn>`; then the base branch is that item's branch and the PR targets it. Stacked PRs say so in the first line of the body.
- Nothing is merged by an agent. Ever. Johnny merges, one by one, after testing.
- Never force-push. Never rewrite history. Atomic commits, one idea each, why-focused messages.
- Stay inside the files the goal names. Touching a shared file (`wtdd/api.py`, `wtdd/ledger.py`, `ui/index.html`, `wtdd/config.py`) is allowed but announced in the PR body under **Shared files touched**, so stacked items can rebase.
- PR title: `<nn> · <goal sentence>`. PR body, in this order: **Goal** · **Makes true** (the demo beat and the drill row it serves) · **Verified** (the goal's verifying command and its pasted output, RED then GREEN) · **Needs the dog** · **Shared files touched** · **Cut** (what was in the goal and is not in the PR, and why) · **Deviations** (each departure from the goal classified good / neutral / bad, never averaged).
- A gotcha found on the way is appended as a new file in `docs/gotchas/` as `NN-<slug>.md`: Symptom · Root cause · Fix (verbatim) · Verify. Never edited after.

## Verification that must stay green on every branch
```
WTDD_WAKE_SHOW=0 python -m unittest wtdd.chat.test_triggers wtdd.chat.test_chat wtdd.hue.test_stub
python -m wtdd list
python -m wtdd.evals --scenario twice
```
plus the goal's own verifying command, shown failing before the build and passing after.

## Who does what
Each roadmap item is one background run with three tiers. **Fable** is the head: it reads `context/`, restates the goal, cuts the verifying command if the goal's is not runnable, reviews every diff against the laws and the goal, and writes the PR body. **Opus** builds: the code, the tests, the fixtures, the gotcha files. **Sonnet** pulls: callers of a symbol, the relevant docstrings, a doc page or a driver source, a summary of a long file, and hands it up. Nobody below the head decides scope.

## What this repo is not
Not the place for yaps, research, decks or decisions; those are in `~/code/origin` and reach here only through `context/`. Not a fleet console, not a platform, not a second body. One agent, one body, one job.

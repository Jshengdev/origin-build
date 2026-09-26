# 08-1 · the remote goes blank in dry mode

**Symptom.** With no Hue keys (any worktree, any machine without `.env`), `python -m wtdd.api <port>` serves the page, it renders, and about a second after load the whole page is blank: no panels, no map, only the page background. A headless screenshot (`playwright screenshot --wait-for-timeout 3000 …`) of main's page on port 7806 on 2026-09-26 was one flat colour.

**Root cause.** At load the page calls `POST /tools/lights_status`; without `HUE_APP_KEY` the tool fails loud (500, `RuntimeError: [wtdd:config] HUE_APP_KEY is required …`) and the page stores `{ error }` as `status` (ui/index.html:109). The palette line (ui/index.html:194) tests only `status ?` and then calls `status.hue.filter(…)` on that object, which has no `hue`; the TypeError in render unmounts React's whole tree. The "State · read back" panel (ui/index.html:360-361) has the same unguarded `status.hue.filter` / `status.strip.error`.

**Fix (verbatim, contracts F patch 1 and 1b, the same bytes on every sibling branch).**

Patch 1 (ui/index.html:194): replace the text
`const palette = status ? [...status.hue.filter(`
with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`

Patch 1b (ui/index.html:360): replace the text
`${status && html`<div class="panel"><h2>State · read back</h2>`
with
`${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>`

The lights failure stays visible: the status row still says `lights · offline` and the ledger keeps the failed read. Only the crash is gone.

**Verify.** From the worktree, with no `.env`:

```
WTDD_LEDGER=/tmp/night1/08/ledger.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7806 &
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7806/ /tmp/night1/08/after.png
```

Before the patch the PNG is one flat colour; after it the status row, the map and the right column are drawn (docs/evidence/night-1/08-remote.png).

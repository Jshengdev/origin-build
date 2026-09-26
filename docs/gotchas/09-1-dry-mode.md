# 09-1 · the remote goes blank in dry mode (no .env, no lights)

**Symptom.** Served from a worktree (no `.env`, so no Hue key), the remote draws for about a second and then the page is
empty. Headless check on a scratch copy of `ui/` with the two guards below reverted, dry API on port 7807:
`root children after 4 s: 0; page errors: ["TypeError: Cannot read properties of undefined (reading 'filter')"]`.

**Root cause.** At load the page calls `lights_status`; without a key the tool fails loud (500) and the page stores
`{ error }` as `status`. Two render expressions test only `status` for truthiness and then read `status.hue.filter(...)`
(the palette, and the "State · read back" panel). `{ error }` is truthy and has no `hue`, so the render throws and
React unmounts the whole tree. Any UI item's headless screenshot hits it, and so does a real run the first time the
bridge is unreachable.

**Fix (verbatim, NIGHT-1-CONTRACTS section F patches 1 and 1b; the same bytes on every sibling branch).**
In `ui/index.html`, replace `const palette = status ? [...status.hue.filter(` with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`, and replace
``${status && html`<div class="panel"><h2>State · read back</h2>`` with
``${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>``.
The lights card already reports the failure ("offline"); these lines only stop two panels from reading a list that is
not there.

**Verify.** Start `python -m wtdd.api 7807` from the worktree, then
`playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7807/ out.png`:
the page is drawn (map, status cards reading `lights offline`, panels), and a headless `pageerror` listener records
no errors.

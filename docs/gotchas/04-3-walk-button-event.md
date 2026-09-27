# 04-3 · "▶ walk the path" saves the map and then does nothing

## Symptom
With `roomOf` defined (04-1), pressing "▶ walk the path" on the remote sends POST /map (200, "map saved") and then no
POST /tools/walk_path. The console shows:
```
TypeError: Converting circular structure to JSON
    --> starting at object with constructor 'HTMLButtonElement'
    |     property '__reactFiber$...' -> object with constructor 'yf'
    --- property 'stateNode' closes the circle
    at JSON.stringify (<anonymous>)
    at post (http://127.0.0.1:7804/:83:119)
    at call (http://127.0.0.1:7804/:84:48)
    at play (http://127.0.0.1:7804/:160:23)
```
`playing.current` stays true, so the button is dead until the page is reloaded. Nothing walks: neither a route that
would be refused nor a clean one.

## Root cause
`const play = async (avoid = true) => {...}` takes `avoid` as its first argument, and the walk button is wired as
`onClick=${play}`, so React passes the click event as `avoid`. `call("walk_path", { source, avoid })` then
JSON-encodes the event, whose target button carries React's fiber (a cycle). The "walk WITHOUT avoidance" button calls
`play(false)` and is not affected. Present on main (ui/index.html:217 there).

## Fix (verbatim)
ui/index.html, the walk button: `<button class="key" onClick=${play} disabled=` became
`<button class="key" onClick=${() => play()} disabled=`

## Verify
Dry API on the fixture map (see 04-1), then in a browser press "▶ walk the path · simulated": the request body is
`{"source":"entity","avoid":true}`, the answer is 500 `ValueError: route refused: point 2 at 480,1100 is inside no-go
zone nogo-1 (drawn on the map)`, the admin view's Commands line reads `FAILED walk_path ... → ValueError: route
refused: ...`, the receipts panel shows `route.refused FAILED`, and the console has no `pageerror`.

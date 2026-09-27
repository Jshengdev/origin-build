# 27-4 · a poll that fails after its first answer leaves the page showing that answer as if it were fresh

## Symptom
With the page loaded and answering, abort GET /dog/state and GET /watch (the API dying mid-demo looks the same). The
four dog gauges keep a normal `20.0`, `43 ms`, `38 px` and `-4.1°`, not red, 8 s later and for as long as the page is
open. Their sparklines stop moving, which is the only sign. The dog card and the map's dog dot also keep the old pose.

## Root cause
Main's polls end in `.catch(() => {})`: ui/index.html's `fetch("/watch")…then(setWatch).catch(() => {})`, the
`/dog/lidar` poll and the `/dog/state` poll. A failed poll never calls its setter, so App keeps the last object it was
given. The gauges' red rules (`!dog`, `!connected`, `age_ms >= 2000`) read that object's own fields, which were fresh
when it arrived and never change after. `null` means "never answered", not "stopped answering". Only `/chat` sets
`null` on failure.

## Fix (verbatim)
The fix stays inside the 27 JS block. Main's polls are not edited (contracts D).
```
const PERIOD = { "/dog/state": 1000, "/dog/lidar": 500, "/watch": 500, "/chat": 3000 };   // main's poll periods (App's setIntervals); three missed answers read as no answer
```
and in `Gauges`:
```
  const hist = useRef({}), seen = useRef({}), heard = useRef({}), now = Date.now();
  const [, tick] = useState(0);   // a re-render once a second when nothing else renders; not a poll: it fetches nothing
  useEffect(() => { const t = setTimeout(() => tick(n => n + 1), 1000); return () => clearTimeout(t); });
  const quiet = (route, src) => {   // the age of a poll's last answer: a new object is a new answer; a failed poll leaves the old one
    if (heard.current[route]?.src !== src) heard.current[route] = { src, at: now };
    const ms = now - heard.current[route].at;
    return src && ms > 3 * PERIOD[route] ? `no answer from GET ${route} · ${Math.round(ms / 1000)} s` : null;
  };
```
Each red rule is then prefixed with the route's check, for example
`const dogBad = quiet("/dog/state", dog) || (!dog ? NO_DOG : …);`, and the same for `/dog/lidar`, `/watch` and `/chat`.
Any later tile that rides one of main's polls (24's vitals, 29's video) needs the same `quiet(route, src) ||` prefix.
Without it, that tile freezes too.

## Verify
1. Start the dry API:
   `WTDD_LEDGER=<a /tmp copy of docs/evidence/ledger-sample-2026-09-13.jsonl> WTDD_STATE_FIXTURE=wtdd/fixtures/page/dog-state.json /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7934`
2. In headless chromium, load http://127.0.0.1:7934/, wait 3.5 s, then `page.route("**/dog/state", r => r.abort())`
   (and the same for `/watch` and `/dog/lidar`).
3. Within about 4 s every dog tile carries `gg-stale` and reads `no answer from GET /dog/state · 4 s`, with its last
   number still shown. The lidar and detector tiles name their own routes.
4. With nothing aborted, sample the tiles for 12 s: none reads `no answer`.

# 08-2 · a panel on the page's 150-row poll says "not yet" about a row that exists

**Symptom.** The remote's night panel said `no roster yet · python -m wtdd roster` while `ledger.jsonl` held a good `schedule.shift` row. Reproduced in dry mode on port 7806, 2026-09-26: roster, then 160 `plan.route` rows, then a quote. `GET /ledger?n=150` returned 150 rows with no `schedule.shift` in them.

**Root cause.** The panel picked its rows from App's `GET /ledger?n=150` poll (ui/index.html, `setLedger`), which is the newest 150 rows only. A round writes far more than that: the old repo's real ledger peaks at 134 rows in a minute and 1686 in an hour. Anything written at the start of the night (the roster, beat 1.2) is gone from that window before the end (the quote, beat 3.3), and "not found in the window" was drawn as "not made yet".

**Fix (verbatim, ui/index.html, 08 · roster-quote).** The panel polls its own longer tail, and the hint names the window it searched:

```
function Night() {
  const N = 2000;   // rows searched: more than any hour of the old repo's ledger.jsonl (1686 at most, measured 2026-09-26)
  const [rows, setRows] = useState(null);   // null until the first read; { error } when GET /ledger fails
  useEffect(() => { const f = () => fetch(`/ledger?n=${N}`).then(r => r.json()).then(setRows).catch(e => setRows({ error: String(e) })); f(); const t = setInterval(f, 5000); return () => clearInterval(t); }, []);
  if (!Array.isArray(rows)) return html`<div class="panel night"><h2>The night · roster and quote</h2>
    <div class=${rows ? "bad" : "hint"}>${rows ? `ledger read FAILED · ${rows.error}` : `reading the last ${N} ledger rows`}</div></div>`;
```

and the two hints read `no roster in the last ${N} ledger rows · python -m wtdd roster` and `no quote in the last ${N} ledger rows · python -m wtdd quote`. App's own poll is not edited. Any other panel that looks for an early row of the night in App's `ledger` state has the same hole.

**Verify.** From the worktree, with a scratch ledger holding a roster, 160 other rows, then a quote:

```
WTDD_LEDGER=/tmp/night1/08/ledger-long.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7806 &
curl -s 'http://127.0.0.1:7806/ledger?n=150' | grep -c schedule.shift     # 0: the old window has no roster
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7806/ /tmp/night1/08/long.png
```

The screenshot shows the roster and the quote together (docs/evidence/night-1/08-remote.png). With an empty ledger the panel reads "no roster in the last 2000 ledger rows"; with an unreadable ledger it reads "ledger read FAILED · TypeError: Failed to fetch" in red.

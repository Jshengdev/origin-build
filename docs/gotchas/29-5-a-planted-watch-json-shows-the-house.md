# 29-5 · a planted watch.json makes the dry screenshot show this Mac's last real detector frame

**Symptom.** The b69ff51 take of `docs/evidence/night-2/29-remote.png` ran on the stub body with a planted
`watch.json`. Its eye panel showed a real photo from inside the house: two people's legs at a table, boxed chair 0.84,
0.587, 0.79 and bird 0.40. The caption under the photo was the fixture's `detector · yolo11n.pt · person ×1 · 41 ms`.
The photo was committed. The shot was a plain `playwright screenshot` of `http://127.0.0.1:7936/`.

**Root cause.** The eye panel draws `<img src=/pictures/watch.jpg?t=${watch.t}>` whenever `watch.age_ms < 3000`. The
API answers `/pictures/<name>` from `~/Pictures/wtdd/` (`api.PICTURES`), which is the same folder on every checkout and
every worktree. A planted `watch.json` is fresh, so the page asks for the picture, and the API serves the last frame the
real detector drew on this Mac. `WTDD_LEDGER`, `UNITREE_ROBOT_IP=` and the stub isolate the dog, the ledger and the
video, but not `~/Pictures/wtdd`.

**Fix (verbatim, /tmp/night1/29/fix3/shot.js, the screenshot script; no tracked file changes).**
```
  await p.route('**/pictures/**', r => {
    const u = r.request().url(); pics.push(u);
    if (new URL(u).pathname === '/pictures/watch.jpg') return r.fulfill({ status: 200, contentType: 'image/jpeg', body: fs.readFileSync(watchJpg) });
    return r.fulfill({ status: 404, contentType: 'application/json', body: '{"error": "screenshot: pictures are scratch-only"}' });
  });
```
`watchJpg` is the detector's own drawing of the stub frame:
`python -m wtdd.watch --source <the /dog/frame.jpg bytes> --once --out /tmp/night1/29/fix3/watch.jpg`, which writes
neither `watch.json` nor `~/Pictures/wtdd/watch.jpg`. This is a static screenshot, so gotcha 29-3's cache caveat about
`page.route` does not apply. Any item that plants `watch.json` for a screenshot needs the same route.

**Verify.**
1. Run `/tmp/night1/29/fix3/shot_remote.sh`.
2. The script's JSON names three routed requests, all `/pictures/watch.jpg?t=...`.
3. `grep -c /pictures /tmp/night1/29/fix3/api-remote.log` prints `0`.
4. Look at the PNG: the eye panel shows the grey stub frame with its dark block, and no room.

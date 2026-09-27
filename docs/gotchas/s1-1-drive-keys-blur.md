# S1-1 · a key held when the tab loses focus drives the dog until the tab comes back

**Symptom.** Found live on 2026-09-27. The remote drove the dog from W A S D Q E in every view, demo included. In a browser with today's page, holding W and then blurring the window gave 11 more `POST /dog/drive` in 2 s and no `POST /dog/stop` (/tmp/s1proof/red.txt).

**Root cause.** `ui/index.html` put the keydown and keyup listeners on the whole window, exempted only `<input>`, and had no blur or visibilitychange handler. A keyup that lands in another window never reaches the page, so the 200 ms interval keeps refreshing the server's 0.6 s dead-man and the dog never stops.

**Fix (verbatim).**
```
  const releaseAll = () => { const held = keys.current.size > 0 || driveTimer.current !== null; keys.current.clear(); if (driveTimer.current) { clearInterval(driveTimer.current); driveTimer.current = null; } if (held) post("/dog/stop"); };
  const armedRef = useRef(false); const [armed, setArmed] = useState(false);
  const arm = on => { armedRef.current = on; setArmed(on); if (!on) releaseAll(); };
  useEffect(() => { if (!admin) arm(false); }, [admin]);
    const typing = e => { const t = e.target; return !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)); };
    const kd = e => { if (!armedRef.current || typing(e) || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return; press(e.key.toLowerCase()); };
    const off = () => arm(false);   // the tab lost focus: nothing held stays held
    const vis = () => { if (document.hidden) off(); };
    window.addEventListener("blur", off); document.addEventListener("visibilitychange", vis);
```
plus a "keys drive · on/off" toggle beside the admin drive buttons.

**Verify.** `python -m unittest wtdd.test_drive_keys` (6 checks on the page source), then in a browser: the demo view and an unarmed #admin send no drive; armed, a held W then a blur sends no further drive and exactly one stop; typing in a textarea while armed sends nothing; the on-screen hold buttons still drive.

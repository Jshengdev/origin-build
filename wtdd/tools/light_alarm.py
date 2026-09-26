"""The alarm: every colour Hue light in the living room flashes red and blue (the native alternating signal) for N
seconds and the strip goes to 100 percent, all at once, each read back; then every light is put back exactly as it was
read before the alarm (off stays off, a level stays its level), read back again. A light that refuses the signal or the
restore is counted in errors and reported, never retried; the tool raises only when nothing answered. The chat's
verdict on "who dis?!" sounds it (wtdd/chat/listen.py) and the intruder tool with ask=false does too."""
ARGS = {"seconds": {"type": "number", "default": 8}}


def run(seconds=8):
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor
    from ..hue.api import HueBridge, summary
    from ..hue.__main__ import ZONES
    from ..ledger import log, step
    from ..tuya.__main__ import strip
    ids = json.loads(ZONES.read_text())["living room"]["lights"]
    b = HueBridge.from_env()
    names = {l["id"]: l["metadata"]["name"] for l in b.lights()}
    with step("lights", "lights.alarm", "hue+tuya", {"seconds": seconds, "lights": len(ids) + 1}) as r:
        before = {rid: summary(b.read(rid)) for rid in ids}     # what to put back
        before_strip = strip()
        done, errors = [], []
        with ThreadPoolExecutor(max_workers=len(ids) + 1) as pool:
            futs = {rid: pool.submit(lambda rid=rid: HueBridge.from_env().signal(rid, float(seconds))) for rid in ids}
            st = pool.submit(strip, on=True, bri=100.0)
            for rid, f in futs.items():
                try:
                    f.result()
                    done.append(names.get(rid, rid[:8]))
                except Exception as e:  # noqa: BLE001  (its own ledger row has ok=False; counted here, not hidden)
                    errors.append(f"{names.get(rid, rid[:8])}: {type(e).__name__}: {str(e)[:60]}")
            try:
                s = st.result()
                done.append(f"strip {s.get('brightness_pct')}%")
            except Exception as e:  # noqa: BLE001
                errors.append(f"strip: {type(e).__name__}: {str(e)[:60]}")
        log("lights", "alarm", signaled=len(done), errors=len(errors))
        if not done:
            raise RuntimeError(f"alarm: nothing answered: {'; '.join(errors)}")
        time.sleep(float(seconds))                                        # let the strobe run its course
        restored = []
        with ThreadPoolExecutor(max_workers=len(ids) + 1) as pool:       # back to exactly what was read before
            futs = {rid: pool.submit(lambda rid=rid, st=before[rid]: HueBridge.from_env().set(rid, on=st["on"], bri=st["brightness"] if st["on"] else None)) for rid in ids}
            st2 = pool.submit(strip, on=bool(before_strip.get("on")), bri=before_strip.get("brightness_pct") if before_strip.get("on") else None)
            for rid, f in futs.items():
                try:
                    f.result()
                    restored.append(f"{names.get(rid, rid[:8])} {'on' if before[rid]['on'] else 'off'}")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"restore {names.get(rid, rid[:8])}: {type(e).__name__}: {str(e)[:60]}")
            try:
                s2 = st2.result()
                restored.append(f"strip {'on' if s2.get('on') else 'off'}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"restore strip: {type(e).__name__}: {str(e)[:60]}")
        log("lights", "alarm over, restored", restored=len(restored), errors=len(errors))
        out = {"signaled": done, "restored": restored, "errors": errors, "seconds": seconds,
               "before": {names.get(k, k[:8]): {"on": v["on"], "brightness": v["brightness"]} for k, v in before.items()} | {"strip": {"on": before_strip.get("on"), "brightness_pct": before_strip.get("brightness_pct")}}}
        r["state_after"] = out
        return out

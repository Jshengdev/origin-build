"""The alarm: every colour Hue light in the living room goes to full brightness and flips red, blue, red ... by
explicit colour sets every ALARM_FLIP_S for N seconds, all lamps of a flip in parallel, and the strip goes to 100
percent; then every light is put back exactly as it was read before the alarm (on/off, brightness, colour), read back
again. A lamp that refuses a set is counted in errors and not retried within that flip (it is tried again on the next
one); the tool raises only when nothing answered. One lights.alarm row carries signaled/restored/errors, the flip count
and the failures per flip. The chat's verdict on "who dis?!" sounds it (wtdd/chat/listen.py) and the intruder tool
with ask=false does too.

Why explicit sets, not the native signal: live 2026-09-27 20:37-20:47 at Johnny's, HueBridge.signal (CLIP v2
signaling "alternating" red/blue) was accepted on all 4 living-room lamps and each read back signal "alternating",
yet nothing showed on the lamps. Explicit sets (`python -m wtdd.hue set <id> --on --bri 100 --xy 0.675,0.322`, then
0.167,0.04) were seen, 4/4 ok each, about 0.8 s per set on the cloud route. The native signal stays one env flip away:
WTDD_ALARM_MODE=signal (default cycle). UNVERIFIED on the real lamps: that 1.0 s flips read as a strobe from the
couch, and that an off lamp takes its colour back while lit before it is switched off."""
import json
import math
import time

ARGS = {"seconds": {"type": "number", "default": 8}}
ALARM_FLIP_S = 1.0      # one colour per second: a cloud set with its read-back takes ~0.8 s (15/15 back-to-back sets ok,
                        # median 794 ms, no 429), so every lamp of a flip lands before the next colour is sent
ALARM_MAX_SETS = 120    # cap on lamp sets per alarm: 4 lamps x 30 flips (~30 s); a longer ask is cut, never spun
MODES = ("cycle", "signal")


def run(seconds=8):
    from concurrent.futures import ThreadPoolExecutor
    from .. import config
    from ..hue.api import BLUE_XY, RED_XY, HueBridge, summary
    from ..hue.__main__ import ZONES
    from ..ledger import log, step
    from ..tuya.__main__ import strip
    mode = config.maybe("WTDD_ALARM_MODE") or "cycle"
    if mode not in MODES:
        raise ValueError(f"WTDD_ALARM_MODE={mode!r}: expected one of {MODES}")
    ids = json.loads(ZONES.read_text())["living room"]["lights"]
    b = HueBridge.from_env()
    names = {l["id"]: l["metadata"]["name"] for l in b.lights()}
    name = lambda rid: names.get(rid, rid[:8])  # noqa: E731
    with step("lights", "lights.alarm", "hue+tuya", {"seconds": seconds, "lights": len(ids) + 1, "mode": mode}) as r:
        before = {rid: summary(b.read(rid)) for rid in ids}     # what to put back
        before_strip = strip()
        errors, answered, flip_failures, flips = [], [], [], 0
        lamps = ids if mode == "signal" else [rid for rid in ids if before[rid]["xy"]]
        errors += [f"{name(rid)}: not a colour lamp, left as it was" for rid in ids if rid not in lamps]
        bridges = {rid: HueBridge.from_env() for rid in lamps}  # one session per lamp: its thread never shares it
        with ThreadPoolExecutor(max_workers=len(ids) + 1) as pool:

            def wave(fn, label):  # one call per lamp in parallel; a refusal is counted, never retried here
                futs = {rid: pool.submit(fn, rid) for rid in lamps}
                ok = []
                for rid, f in futs.items():
                    try:
                        f.result()
                        ok.append(name(rid))
                    except Exception as e:  # noqa: BLE001  (its own ledger row has ok=False; counted here, not hidden)
                        errors.append(f"{label}{name(rid)}: {type(e).__name__}: {str(e)[:60]}")
                return ok

            st = pool.submit(strip, on=True, bri=100.0)
            if mode == "signal":
                answered += wave(lambda rid: bridges[rid].signal(rid, float(seconds)), "")
                n = 0
            else:
                n = min(max(2, math.ceil(float(seconds) / ALARM_FLIP_S)), ALARM_MAX_SETS // max(1, len(lamps))) if lamps else 0
            try:
                s = st.result()
                strip_ok = [f"strip {s.get('brightness_pct')}%"]
            except Exception as e:  # noqa: BLE001
                strip_ok = []
                errors.append(f"strip: {type(e).__name__}: {str(e)[:60]}")
            for i in range(n):
                t0 = time.monotonic()
                xy = RED_XY if i % 2 == 0 else BLUE_XY
                ok = wave(lambda rid, xy=xy: bridges[rid].set(rid, on=True, bri=100.0, xy=xy), f"flip {i + 1} ")
                flips += 1
                flip_failures.append(len(lamps) - len(ok))
                answered += [x for x in ok if x not in answered]
                log("lights", "alarm flip", n=f"{i + 1}/{n}", colour="red" if i % 2 == 0 else "blue", ok=len(ok), failed=len(lamps) - len(ok))
                if i == 0 and not answered and not strip_ok:
                    break                                             # nothing answered: stop before spinning on
                time.sleep(max(0.0, ALARM_FLIP_S - (time.monotonic() - t0)))
            done = answered + strip_ok
            log("lights", "alarm", mode=mode, signaled=len(done), flips=flips, errors=len(errors))
            if not done:
                raise RuntimeError(f"alarm: nothing answered: {'; '.join(errors)}")
            if mode == "signal":
                time.sleep(float(seconds))                            # let the native strobe run its course

            def restore(rid):  # back to exactly what was read before
                s, bridge = before[rid], bridges[rid]
                xy = tuple(s["xy"]) if s["xy"] else None
                if s["on"]:
                    return bridge.set(rid, on=True, bri=s["brightness"], xy=xy)
                try:
                    if mode == "cycle":  # colour back while still lit, where the read-back can confirm it
                        bridge.set(rid, bri=s["brightness"], xy=xy)
                finally:
                    bridge.set(rid, on=False)                         # an off lamp goes off even if its colour refused

            back = wave(restore, "restore ")
            restored = [f"{name(rid)} {'on' if before[rid]['on'] else 'off'}" for rid in lamps if name(rid) in back]
            st2 = pool.submit(strip, on=bool(before_strip.get("on")), bri=before_strip.get("brightness_pct") if before_strip.get("on") else None)
            try:
                s2 = st2.result()
                restored.append(f"strip {'on' if s2.get('on') else 'off'}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"restore strip: {type(e).__name__}: {str(e)[:60]}")
        log("lights", "alarm over, restored", restored=len(restored), errors=len(errors))
        out = {"signaled": done, "restored": restored, "errors": errors, "seconds": seconds, "mode": mode,
               "flips": flips, "flip_failures": flip_failures,
               "before": {name(k): {"on": v["on"], "brightness": v["brightness"], "xy": v["xy"]} for k, v in before.items()}
               | {"strip": {"on": before_strip.get("on"), "brightness_pct": before_strip.get("brightness_pct")}}}
        r["state_after"] = out
        return out

# The dashboard

The remote Johnny runs and films at http://127.0.0.1:3970: one page per job, every value read from this repo's API
(`wtdd/api.py`) through the app's own `/api/*` proxy (`app/api/[...path]/route.ts`, which reads `WTDD_API` on every
request). It never connects the dog on load; nothing posts until a click, a drag's release or a key.

```bash
python -m wtdd.api                                    # the API, :7788 (from the repo root)
cd dashboard && pnpm install && pnpm build
WTDD_API=http://127.0.0.1:7788 pnpm start -p 3970     # the dashboard, http://127.0.0.1:3970
pnpm storybook                                        # every primitive and the map's views, on fixture frames (:6310)
```

An API that does not answer is a 502 naming the address and the cause, and the page shows it as a red FAILED line.

## Pages

| page | reads | does |
|---|---|---|
| Overview | `/dog/state`, `/dog/grid`, `/dog/floorplan`, `/dog/lidar`, `/dog/objects`, `/dog/blobs`, `/dog/scale`, `/map`, `/ledger`, `/chat`, `/shift`, `/dog/frame.jpg` | the camera; the map (house plan, memory and live scan on one depth ramp, the route, decisions); Stop and Walk; drive (W A S D Q E, S1's rules) and LiDAR switches; the map tools bar: Calibrate (drag the dog's place and heading, Place the dog, the scale slider, Scale by a wall) and Floor plan; the receipts, repeats grouped |
| Paths | `/map`, the map routes above | draw the dots, the stops and the no-go zones; save with the map's version; Ask here on a stop; walk and stop |
| Waiting | `/ledger`, `/chat` | the dog's asks to the group and what followed |
| Record | `/record/*`, `/shift`, `/evals` | start a run, its morning page and report, one signature |
| Routines, Settings, Live, Driving, Sessions, Monitoring, Images, People | none yet | marked "Sample · not live yet", greyed and inert, until each reads the API |

## Where things are

| path | what |
|---|---|
| `components/overview/`, `components/paths/`, `components/waiting/`, `components/record/` | the live pages |
| `components/twin/` | the map: `twin-map.tsx` (canvas cells and scan, SVG geometry, HTML pins), `use-live-map.tsx` (the polls, shaped into the map's props), `heat.ts` (the heat and depth ramps) |
| `components/live/` | Stop, the receipts and their lines (`ledger.ts`) |
| `lib/data/api.ts` | the polls, the POSTs (never throw; the reason comes back), the served types, redaction |
| `components/ui/` | stock shadcn/ui, never edited; `components/wtdd/` the brand wrappers |
| `stories/` | Storybook; `stories/fixtures/live-frame.json` is a labelled fixture frame |

Built on the mockup in [teriyapi/wtdd-remote-v2](https://github.com/teriyapi/wtdd-remote-v2) (design system, shadcn theme, Storybook), then wired to this API there over PRs #1-#31; this folder is that work at 92ab4ae.

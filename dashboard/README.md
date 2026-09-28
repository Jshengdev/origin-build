# What the Dog Doin: remote v2 (mockup)

A Next.js mockup of the remote v2, built from `../wtdd-product-rig` (spec, contracts, fixtures) on the design system in `../wtdd-design-system` (tokens, shadcn theme, wrappers). It runs on dry fixtures only, with no on-screen notice. **Do not film or pitch it** until it reads the real API.

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm storybook    # http://localhost:6310, every primitive in light and dark (toolbar: Theme)
pnpm build && pnpm lint
```

## Where things are

| Path | What |
|---|---|
| `app/globals.css` | `wtdd-design-system/shadcn/app/globals.css`, plus the two motion classes at the bottom |
| `components/ui/*` | Stock shadcn/ui. Never edited (and not linted) |
| `components/wtdd/*` | Brand wrappers from the DS package, plus Module loading/error states, `Sparkline`, `Gauge` |
| `components/twin/*` | TwinMap: canvas occupancy grid on the heat ramp, SVG geometry, HTML pins. `map-pin.tsx` is the DevicePin |
| `components/shell/*` | Sidebar (232px, 64px rail under 1024px), top bar, G-then-key shortcuts |
| `components/overview/*` | Overview: map, body vitals, roster, last look, receipts with the item 26 timeline and row drawer |
| `lib/data/` | `types.ts` and `data-source.ts` from the contracts, `FixtureDataSource`, the fixtures. `getDataSource()` is the one switch point for `ApiDataSource` |
| `stories/` | Storybook: Foundations, Primitives, Map, Patterns |

## Dev overlay

[plumbkit](https://www.npmjs.com/package/plumbkit) is mounted in dev (`components/shell/plumb-devtools.tsx`, and the Storybook preview decorator): alignment guides `A`, padding `P`, measure `M`. It is tree-shaken out of production builds. Drag the bar off the sidebar's Settings item; the spot persists.

## Shortcuts

`G` then `O M P U I R S` goes to Overview, Monitoring, Paths, Routines, Images, Record, Settings. On Overview, `W` walks the route and `X` stops (both log stub rows; nothing reaches the dog). Buttons do not show key hints. On the map, arrows pan, `+`/`-` zoom, `0` resets.

## Pages

Overview; Waiting (everything waiting on a person: the dog's questions, proposed zones, routines assigned to people, @mentions; count in the sidebar); Live (only while a session runs; watchers shown; Stop asks where the dog goes: home, a saved place, or stay); Driving (click out a path, Go; traces stream under the map); Routines (cards; detail with Edit/Save; assign to the robot or a person); Sessions; Monitoring; Images (a card per routine, a page per routine to compare nights, a page per point with dates, drag-to-compare, and notes with @mentions); People (roles: On call, Driver, Editor, Viewer); Settings.

Routines, sessions, captures, and the live session are client-side mockup state (`components/shell/app-state.tsx`, seeded from `lib/mock/`). A reload resets them. Nothing is shown as a stub; every value is still a fixture.

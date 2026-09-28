/**
 * The remote v2 reads everything through this interface.
 *   - FixtureDataSource: reads ../fixtures (every value is source "stub"; the UI badges it).
 *   - ApiDataSource: calls the existing wtdd API. Base URL from NEXT_PUBLIC_WTDD_API.
 *     Dry runs use the team's dry ports, never 7788 (7788 owns the real dog).
 *
 * Rule from the team: the page computes nothing. Every number shown is a value the API served
 * or a ledger row. No derived scores, percentages, or rates on screen.
 *
 * Writes are few and each maps to an existing or PR'd route. Anything not in the repo yet is marked
 * // NEEDS: <item> (<status>) and is disabled in the UI with its status word as the tooltip.
 */
import type { Site, Grid, FloorPlan, Zone, Device, Person, Stop, Route, Roster, LedgerRow, Look, MorningPage, Evals, Integration } from "./types";

export interface DataSource {
  source: "live" | "stub";
  getSite(): Promise<Site>;
  getGrid(): Promise<Grid>;                   // GET /dog/grid            (item 01, PR #5)
  getFloorPlan(): Promise<FloorPlan>;         // GET /dog/floorplan       (item 15, BUILDING)
  getZones(): Promise<Zone[]>;                // from GET /map            (item 04, PR #4; proposals item 19, BUILDING)
  getDevices(): Promise<Device[]>;            // GET /dog/state + lights + cams (vitals item 24, PR #16)
  getPeople(): Promise<Person[]>;             // config; on-call person item 03, PR #7
  getStops(): Promise<Stop[]>;                // GET /map
  getRoutes(): Promise<Route[]>;              // GET /map (+ item 21 route plans, PR #19)
  getRoster(): Promise<Roster>;               // item 08, PR #2
  tailLedger(n: number): Promise<LedgerRow[]>;// the receipts panel; confirm the route in api.py
  getLooks(): Promise<Look[]>;                // /pictures/ + look rows
  getMorningPage(): Promise<MorningPage>;     // item 10, PR #13
  getEvals(): Promise<Evals>;                 // evals.json (+ item 11 graders, PR #12)
  getIntegrations(): Promise<Integration[]>;

  /* Writes: each exists on main or in a named PR. */
  scout(): Promise<LedgerRow>;                // POST /dog/scout  (item 14, BUILDING)
  stop(): Promise<LedgerRow>;                 // POST /dog/stop   (main)
  walkRoute(routeId: string): Promise<LedgerRow>;          // "walk the path" (main); refused rows come back ok=false
  planRoute(stopIds: string[]): Promise<Route>;            // item 21, PR #19
  saveZone(z: Omit<Zone, "id">): Promise<Zone>;            // POST /map (item 04, PR #4)
  confirmZone(zoneId: string, personId: string): Promise<Zone>; // item 19, BUILDING: a person's tap makes it a rule
  sign(personId: string): Promise<MorningPage>;            // item 10 + 03; a second signature returns a refusal row
}

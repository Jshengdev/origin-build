/**
 * FixtureDataSource: reads the dry fixtures in ./fixtures. Every value is source "stub"; the UI badges it.
 * Writes do not reach anything. They return stub rows so the UI can show what a real call would log.
 */
import type { DataSource } from "./data-source";
import type {
  Site, Grid, FloorPlan, Zone, Device, Person, Stop, Route, Roster, LedgerRow, Look, MorningPage, Evals, Integration, Fixture,
} from "./types";

import site from "./fixtures/site.json";
import grid from "./fixtures/grid.json";
import floorplan from "./fixtures/floorplan.json";
import zones from "./fixtures/zones.json";
import devices from "./fixtures/devices.json";
import people from "./fixtures/people.json";
import stops from "./fixtures/stops.json";
import routes from "./fixtures/routes.json";
import roster from "./fixtures/roster.json";
import ledger from "./fixtures/ledger-rows.json";
import looks from "./fixtures/looks.json";
import morningPage from "./fixtures/morning-page.json";
import evals from "./fixtures/evals.json";
import integrations from "./fixtures/integrations.json";

const read = <T,>(f: unknown): T => structuredClone((f as Fixture<T>).data);

function stubRow(tool: string, extra: Partial<LedgerRow> = {}): LedgerRow {
  return { ts: new Date().toISOString(), tool, ok: true, cached: true, source: "stub", latency_ms: 0, ...extra };
}

export class FixtureDataSource implements DataSource {
  source = "stub" as const;
  private signature: MorningPage["signature"] = { status: "unsigned" };
  private zones: Zone[] = read<Zone[]>(zones);

  async getSite() { return read<Site>(site); }
  async getGrid() { return read<Grid>(grid); }
  async getFloorPlan() { return read<FloorPlan>(floorplan); }
  async getZones() { return structuredClone(this.zones); }
  async getDevices() { return read<Device[]>(devices); }
  async getPeople() { return read<Person[]>(people); }
  async getStops() { return read<Stop[]>(stops); }
  async getRoutes() { return read<Route[]>(routes); }
  async getRoster() { return read<Roster>(roster); }
  async tailLedger(n: number) { return read<LedgerRow[]>(ledger).slice(-n).reverse(); }
  async getLooks() { return read<Look[]>(looks); }
  async getMorningPage() { return { ...read<MorningPage>(morningPage), signature: this.signature }; }
  async getEvals() { return read<Evals>(evals); }
  async getIntegrations() { return read<Integration[]>(integrations); }

  async scout(): Promise<LedgerRow> { throw new Error("BUILDING: POST /dog/scout does not answer yet (item 14)"); }
  async stop() { return stubRow("dog.stop"); }
  async walkRoute(routeId: string) { return stubRow("dog.follow", { args: { route: routeId } }); }
  async planRoute(stopIds: string[]): Promise<Route> {
    const all = read<Route[]>(routes);
    const planned = all.find((r) => r.id === "tapped-1")!;
    return { ...planned, stopIds };
  }
  async saveZone(z: Omit<Zone, "id">) {
    const zone = { ...z, id: `nogo-${this.zones.length + 1}` };
    this.zones.push(zone);
    return zone;
  }
  /** Item 19 is BUILDING upstream; the fixture turns the proposal into a rule so the mockup shows the flow. */
  async confirmZone(zoneId: string): Promise<Zone> {
    const z = this.zones.find((x) => x.id === zoneId);
    if (!z) throw new Error(`no zone ${zoneId}`);
    Object.assign(z, { kind: "nogo", status: "rule", name: z.name.replace(/^Proposed:\s*/i, "") });
    return structuredClone(z);
  }
  async sign(personId: string): Promise<MorningPage> {
    if (this.signature.status === "signed") {
      throw new Error("sign REFUSED: record already signed");
    }
    const who = read<Person[]>(people).find((p) => p.id === personId);
    this.signature = { status: "signed", by: who?.name ?? personId, at: new Date().toISOString() };
    return this.getMorningPage();
  }
}

let instance: DataSource | null = null;

/** The one place the app picks a source. ApiDataSource slots in here (INTEGRATION.md). */
export function getDataSource(): DataSource {
  instance ??= new FixtureDataSource();
  return instance;
}

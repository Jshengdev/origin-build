/** Fixture data for stories, read synchronously. Every value is a dry stub. */
import type { Device, Evals, FloorPlan, Grid, Integration, LedgerRow, Look, MorningPage, Person, Roster, Route, Site, Stop, Zone, Fixture } from "@/lib/data";
import site from "@/lib/data/fixtures/site.json";
import grid from "@/lib/data/fixtures/grid.json";
import floorplan from "@/lib/data/fixtures/floorplan.json";
import zones from "@/lib/data/fixtures/zones.json";
import devices from "@/lib/data/fixtures/devices.json";
import people from "@/lib/data/fixtures/people.json";
import stops from "@/lib/data/fixtures/stops.json";
import routes from "@/lib/data/fixtures/routes.json";
import roster from "@/lib/data/fixtures/roster.json";
import ledger from "@/lib/data/fixtures/ledger-rows.json";
import looks from "@/lib/data/fixtures/looks.json";
import evals from "@/lib/data/fixtures/evals.json";
import integrations from "@/lib/data/fixtures/integrations.json";
import morningPage from "@/lib/data/fixtures/morning-page.json";

const d = <T,>(f: unknown) => (f as Fixture<T>).data;

export const fx = {
  site: d<Site>(site),
  grid: d<Grid>(grid),
  floorPlan: d<FloorPlan>(floorplan),
  zones: d<Zone[]>(zones),
  devices: d<Device[]>(devices),
  people: d<Person[]>(people),
  stops: d<Stop[]>(stops),
  routes: d<Route[]>(routes),
  roster: d<Roster>(roster),
  ledger: [...d<LedgerRow[]>(ledger)].reverse(),
  looks: d<Look[]>(looks),
  evals: d<Evals>(evals),
  integrations: d<Integration[]>(integrations),
  morningPage: d<MorningPage>(morningPage),
};

export const map = {
  grid: fx.grid, floorPlan: fx.floorPlan, zones: fx.zones, routes: fx.routes, stops: fx.stops, devices: fx.devices, looks: fx.looks,
};

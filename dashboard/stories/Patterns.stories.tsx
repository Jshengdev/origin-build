import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppShell } from "@/components/shell/app-shell";
import { OverviewView } from "@/components/overview/overview-view";
import { BodyStats, LastLook, TonightsRoster } from "@/components/overview/rail";
import { Receipts } from "@/components/live/receipts";
import { MonitoringView } from "@/components/monitoring/monitoring-view";
import { ImagesView } from "@/components/images/images-view";
import { AreaView } from "@/components/images/area-view";
import { RoutineImages } from "@/components/images/routine-images";
import { LiveView } from "@/components/live/live-view";
import { DrivingView } from "@/components/driving/driving-view";
import { RoutinesList } from "@/components/routines/routines-list";
import { RoutineDetail } from "@/components/routines/routine-detail";
import { RoutineEditor } from "@/components/routines/routine-editor";
import { SessionsView, SessionDetail } from "@/components/sessions/sessions-view";
import { PageHeader } from "@/components/shell/page-header";
import { SettingsView } from "@/components/settings/settings-view";
import { PeopleView } from "@/components/people/people-view";
import { WaitingView } from "@/components/waiting/waiting-view";
import { fx, map } from "./fixtures";

const meta: Meta = { title: "Patterns", parameters: { nextjs: { appDirectory: true, navigation: { pathname: "/" } } } };
export default meta;
type Story = StoryObj;

const body = fx.devices.find((d) => d.kind === "body");
const tz = fx.site.timezone;

export const StatCards: Story = {
  name: "Body stat cards",
  render: () => (
    <div className="flex max-w-[1100px] flex-col gap-4">
      <BodyStats body={body} />
      <BodyStats body={body && { ...body, vitals: { ...body.vitals!, lidarAgeMs: 6000, faults: ["motor 3 temp"] } }} />
    </div>
  ),
};

export const Rail: Story = {
  name: "Roster and last look",
  render: () => (
    <div className="grid max-w-[380px] gap-4">
      <TonightsRoster roster={fx.roster} stops={fx.stops} devices={fx.devices} people={fx.people} routine={{ id: "night-round", name: "Night round" }} />
      <LastLook look={fx.looks[0]} stop={fx.stops[0]} timeZone={tz} />
    </div>
  ),
};

export const ReceiptsPanel: Story = {
  name: "Receipts with timeline",
  render: () => <div className="grid grid-cols-12"><Receipts rows={fx.ledger} map={map} timeZone={tz} /></div>,
};

const page = (path: string, node: React.ReactNode): Story => ({
  parameters: { layout: "fullscreen", nextjs: { appDirectory: true, navigation: { pathname: path } } },
  render: () => <AppShell>{node}</AppShell>,
});
const titled = (label: string, node: React.ReactNode) => <><PageHeader crumbs={[{ label }]} />{node}</>;

export const Overview = page("/", titled("Overview", <OverviewView site={fx.site} stops={fx.stops} devices={fx.devices} people={fx.people} roster={fx.roster} ledger={fx.ledger.slice(0, 6)} looks={fx.looks} />));
export const LiveNotLive = page("/live", <LiveView map={map} />);
export const Driving = page("/driving", <DrivingView map={map} />);
export const Routines = page("/routines", <RoutinesList map={map} />);
export const RoutineSteps = page("/routines/night-round", <RoutineDetail id="night-round" map={map} />);
export const NewRoutine = page("/routines/new", <RoutineEditor map={map} />);
export const Sessions = page("/sessions", <SessionsView />);
export const Session = page("/sessions/14", <SessionDetail id={14} map={map} />);
export const Monitoring = page("/monitoring", titled("Monitoring", <MonitoringView devices={fx.devices} evals={fx.evals} />));
export const Images = page("/images", <ImagesView />);
export const RoutineImagesPage = page("/images/progress-check", <RoutineImages routineId="progress-check" />);
export const ImageCompare = page("/images/progress-check/p1", <AreaView routineId="progress-check" stepId="p1" />);
export const Settings = page("/settings", titled("Settings", <SettingsView site={fx.site} integrations={fx.integrations} />));
export const Waiting = page("/waiting", <WaitingView />);
export const People = page("/people", <PeopleView />);

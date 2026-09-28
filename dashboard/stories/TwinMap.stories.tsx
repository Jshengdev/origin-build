import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useState } from "react";
import { TwinMap } from "@/components/twin/twin-map";
import { MapPin, DeviceTip } from "@/components/twin/map-pin";
import { ActionButton } from "@/components/wtdd";
import { Dog, Lightbulb, Camera } from "lucide-react";
import { fx } from "./fixtures";

const meta: Meta<typeof TwinMap> = {
  title: "Map/TwinMap",
  component: TwinMap,
  parameters: { layout: "fullscreen" },
  decorators: [(S) => <div className="p-4"><S /></div>],
  args: {
    grid: fx.grid, floorPlan: fx.floorPlan, zones: fx.zones, routes: fx.routes.filter((r) => r.id === "taught"),
    stops: fx.stops, devices: fx.devices, looks: fx.looks,
  },
};
export default meta;
type Story = StoryObj<typeof TwinMap>;

export const Overview: Story = {
  args: {
    actions: <ActionButton intent="secondary" stage={{ kind: "building" }}>Scout: spin and draw</ActionButton>,
  },
};

export const RunActive: Story = {
  name: "Run active, lamps on",
  args: {
    runActive: true,
    devices: fx.devices.map((d) => (d.id === "hue-3" ? { ...d, on: true, brightness: 180 } : d.id === "hue-1" ? { ...d, on: true, brightness: 90 } : d)),
  },
};

export const Focus: Story = { name: "Receipts row lit", args: { focus: { kind: "stop", id: "s1", label: "ask.ack · S1" } } };

export const AllRoutes: Story = {
  name: "Paths: taught, planned, refused",
  args: { routes: fx.routes },
};

function DrawDemo() {
  const [k, setK] = useState(0);
  return (
    <div className="flex flex-col gap-3">
      <ActionButton intent="secondary" className="self-start" onClick={() => setK((n) => n + 1)}>Accept the planned route</ActionButton>
      <TwinMap key={k} grid={fx.grid} floorPlan={fx.floorPlan} stops={fx.stops} devices={fx.devices}
        routes={fx.routes.filter((r) => r.id === "tapped-1")} drawRouteId={k ? "tapped-1" : null} />
    </div>
  );
}
export const RouteAccepted: Story = { name: "Route accepted (the one animation)", render: () => <DrawDemo /> };

export const GridOnly: Story = { name: "Grid only (no plan)", args: { floorPlan: undefined, zones: [], routes: [], stops: [], devices: [], looks: [] } };
export const Empty: Story = { args: { grid: undefined, floorPlan: undefined, zones: [], routes: [], stops: [], devices: [], looks: [] } };

export const Pins: StoryObj = {
  name: "DevicePin",
  render: () => {
    const body = fx.devices.find((d) => d.kind === "body")!;
    const lamp = fx.devices.find((d) => d.id === "hue-1")!;
    const cam = fx.devices.find((d) => d.kind === "camera")!;
    const items: Array<[string, React.ReactNode]> = [
      ["dog", <MapPin key="a" at={[0, 0]} tip={<DeviceTip d={body} />}><Dog className="size-3.5" strokeWidth={1.5} /></MapPin>],
      ["dog, run active", <MapPin key="b" at={[0, 0]} tone="highlight" tip={<DeviceTip d={body} />}><Dog className="size-3.5" strokeWidth={1.5} /></MapPin>],
      ["lamp off", <MapPin key="c" at={[0, 0]} tip={<DeviceTip d={lamp} />}><Lightbulb className="size-3.5" strokeWidth={1.5} /></MapPin>],
      ["lamp on, bri 180", <MapPin key="d" at={[0, 0]} tone="peak" glow={180 / 254} tip={<DeviceTip d={{ ...lamp, on: true, brightness: 180 }} />}><Lightbulb className="size-3.5" strokeWidth={1.5} /></MapPin>],
      ["camera", <MapPin key="e" at={[0, 0]} tip={<DeviceTip d={cam} />}><Camera className="size-3.5" strokeWidth={1.5} /></MapPin>],
      ["stop", <MapPin key="f" at={[0, 0]} size={20} label="S1" tip="Front door (intruder check)"><span className="font-mono text-[11px] font-medium">1</span></MapPin>],
      ["look pin", <MapPin key="g" at={[0, 0]} size={14} shape="diamond" label="person 0.87" tip="person · p 0.87">{null}</MapPin>],
    ];
    return (
      <div className="flex flex-wrap gap-4">
        {items.map(([name, pin]) => (
          <div key={name} className="flex w-36 flex-col gap-2">
            <div className="relative h-24 rounded-xl bg-twin-canvas"><div className="absolute left-1/2 top-1/2">{pin}</div></div>
            <span className="text-[13px] text-muted-foreground">{name}</span>
          </div>
        ))}
      </div>
    );
  },
};

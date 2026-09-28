import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Gauge, Module, Sparkline } from "@/components/wtdd";

const meta: Meta = { title: "Primitives/Sparkline and Gauge" };
export default meta;
type Story = StoryObj;

/* Invented series, for the component only. */
const hz = [9.8, 10.1, 9.9, 10.0, 9.7, 10.2, 10.0, 9.9, 10.1, 10.0];
const lidarAge = [300, 320, 410, 380, 900, 2400, 1800, 600, 420, 400];

export const Sparklines: Story = {
  render: () => (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-4"><Sparkline values={hz} label="dog hz" /><span className="text-[13px] text-muted-foreground">Served values only</span></div>
      <div className="flex items-center gap-4"><Sparkline values={lidarAge} band={[2000, 2600]} label="lidar age" /><span className="text-[13px] text-muted-foreground">With a threshold band</span></div>
      <div className="flex items-center gap-4"><Sparkline values={[]} /><span className="text-[13px] text-muted-foreground">Empty</span></div>
    </div>
  ),
};

export const GaugeTiles: Story = {
  render: () => (
    <div className="grid max-w-[980px] grid-cols-12 gap-4">
      <Module title="Gauges" size="full">
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
          <Gauge label="Dog" value="10.0" unit="hz" history={hz} />
          <Gauge label="Follow distance" value="0.42" unit="m" history={[0.4, 0.45, 0.41, 0.43, 0.42]} />
          <Gauge label="Lidar age" value="400" unit="ms" history={lidarAge} band={[2000, 2600]} />
          <Gauge label="Detector" value="38" unit="ms" />
        </div>
      </Module>
    </div>
  ),
};

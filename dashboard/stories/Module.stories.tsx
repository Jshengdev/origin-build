import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Module, Reading, SignalChip } from "@/components/wtdd";

const meta: Meta<typeof Module> = {
  title: "Primitives/Module",
  component: Module,
  args: { title: "Last look", meta: "4:03 PM", size: "full" },
  decorators: [(S) => <div className="grid max-w-[480px] grid-cols-12 gap-4"><S /></div>],
};
export default meta;
type Story = StoryObj<typeof Module>;

export const Default: Story = {
  args: {
    children: (
      <div className="flex flex-col gap-3">
        <Reading value={64} unit="%" />
        <div className="flex gap-1"><SignalChip tone="neutral">no faults</SignalChip></div>
      </div>
    ),
  },
};

export const Loading: Story = { args: { loading: true } };
export const Error: Story = { args: { error: "Looks did not load. Check that the API answers, then reload." } };
export const Empty: Story = {
  args: { meta: undefined, children: <p className="text-[15px] text-muted-foreground">No looks yet. The dog looks at each stop on its round.</p> },
};

export const Sizes: Story = {
  decorators: [(S) => <div className="max-w-[1200px]"><S /></div>],
  render: () => (
    <div className="grid grid-cols-12 gap-4">
      {(["s", "m", "l", "xl", "full"] as const).map((s) => (
        <Module key={s} title={`size ${s}`} size={s}>
          <span className="font-mono text-[12px] text-muted-foreground">{{ s: 3, m: 4, l: 6, xl: 8, full: 12 }[s]} of 12 columns</span>
        </Module>
      ))}
    </div>
  ),
};

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ActionButton } from "@/components/wtdd";

const meta: Meta<typeof ActionButton> = {
  title: "Primitives/ActionButton",
  component: ActionButton,
  args: { children: "Walk the route", intent: "primary" },
  argTypes: {
    intent: { control: "inline-radio", options: ["primary", "secondary", "person", "quiet", "danger"] },
  },
};
export default meta;
type Story = StoryObj<typeof ActionButton>;

export const Playground: Story = {};

export const Intents: Story = {
  render: () => (
    <div className="flex flex-col gap-6">
      {[
        ["primary", "Walk the route", "Ink fill. At most one per view."],
        ["secondary", "Stop", "Surface fill with a line-strong edge."],
        ["person", "Make it a rule", "Highlight fill. Only where a person must act."],
        ["quiet", "Reset view", "Text-only actions."],
        ["danger", "Remove zone", "Soft alert. Passes contrast in both themes."],
      ].map(([intent, label, note]) => (
        <div key={intent} className="grid grid-cols-[100px_220px_1fr] items-center gap-4">
          <span className="font-mono text-[12px] text-muted-foreground">{intent}</span>
          <div><ActionButton intent={intent as never}>{label}</ActionButton></div>
          <span className="text-[13px] text-muted-foreground">{note}</span>
        </div>
      ))}
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <ActionButton intent="secondary" stage={{ kind: "building" }}>Scout: spin and draw</ActionButton>
      <ActionButton intent="primary" disabled>Walk the route</ActionButton>
    </div>
  ),
};

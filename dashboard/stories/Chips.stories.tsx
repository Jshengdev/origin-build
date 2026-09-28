import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { SignalChip, WaitingChip, DryBanner, Reading } from "@/components/wtdd";

const meta: Meta = { title: "Primitives/Chips and marks" };
export default meta;
type Story = StoryObj;

const Row = ({ name, note, children }: { name: string; note: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-[140px_1fr] gap-4 border-t border-border py-4 first:border-t-0">
    <div className="flex flex-col gap-1">
      <span className="text-[13px] font-medium">{name}</span>
      <span className="text-[12px] leading-4 text-muted-foreground">{note}</span>
    </div>
    <div className="flex flex-wrap items-center gap-2">{children}</div>
  </div>
);

export const All: Story = {
  render: () => (
    <div className="flex max-w-[860px] flex-col">
      <Row name="SignalChip" note="Never color alone: ↗ for good, ● for alert.">
        <SignalChip tone="good">online</SignalChip>
        <SignalChip tone="alert">FAILED</SignalChip>
        <SignalChip tone="alert">stale</SignalChip>
        <SignalChip tone="neutral">ok</SignalChip>
      </Row>
      <Row name="WaitingChip" note="Waiting on a person, and nothing else.">
        <WaitingChip>Awaiting a tap</WaitingChip>
        <WaitingChip>Unsigned</WaitingChip>
      </Row>
      <Row name="Reading" note="A value a machine produced, with its unit muted.">
        <Reading value={64} unit="%" />
        <Reading value="1307" unit="ms" />
        <Reading size="sm" value="0.87" unit="p" />
      </Row>
      <Row name="DryBanner" note="Global, whenever the source is fixtures.">
        <div className="w-full"><DryBanner show /></div>
      </Row>
    </div>
  ),
};

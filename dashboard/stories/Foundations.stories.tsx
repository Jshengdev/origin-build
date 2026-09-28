import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { useEffect, useState } from "react";
import { ActionButton } from "@/components/wtdd";

const meta: Meta = { title: "Foundations", parameters: { layout: "padded" } };
export default meta;
type Story = StoryObj;

const Section = ({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) => (
  <section className="flex flex-col gap-4 border-t border-border py-8 first:border-t-0 first:pt-0">
    <div className="flex flex-col gap-1">
      <h2 className="text-[22px] font-semibold leading-7 tracking-[-0.01em]">{title}</h2>
      {note && <p className="max-w-[640px] text-[15px] leading-[22px] text-muted-foreground">{note}</p>}
    </div>
    {children}
  </section>
);

/** Reads the live value of a CSS variable, so the swatch shows what the current theme resolves to. */
function useVar(name: string) {
  const [v, setV] = useState("");
  useEffect(() => {
    const read = () => setV(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, [name]);
  return v;
}

function Swatch({ token, rule }: { token: string; rule: string }) {
  const v = useVar(`--${token}`);
  return (
    <div className="flex flex-col gap-2">
      <div className="h-16 rounded-md border border-border" style={{ background: `var(--${token})` }} />
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium">{token}</span>
        <span className="font-mono text-[12px] text-muted-foreground">{v}</span>
      </div>
      <p className="text-[13px] leading-[18px] text-muted-foreground">{rule}</p>
    </div>
  );
}

const COLOR_GROUPS: Array<{ title: string; tokens: Array<[string, string]> }> = [
  { title: "Ground and ink", tokens: [
    ["paper", "Page ground. Cool concrete grey, never cream"],
    ["surface", "Modules and cards"],
    ["line", "Hairlines only, never a control edge"],
    ["line-strong", "Control borders, focus rings (3:1)"],
    ["ink", "Primary text, primary button fill"],
    ["ink-muted", "Secondary text, units, timestamps"],
    ["on-ink", "Text on an ink fill"],
  ] },
  { title: "The map and the heat ramp", tokens: [
    ["twin-canvas", "Map background, dark in both themes"],
    ["heat-cold", "Ramp step 1. Fill only, by served count"],
    ["heat-warm", "Ramp step 2. Fill only"],
    ["heat-hot", "Ramp step 3. Fill only"],
    ["heat-peak", "Ramp step 4. Also the stub badge edge"],
  ] },
  { title: "Meaning", tokens: [
    ["highlight", "Waiting on a person. Never decoration"],
    ["signal-good", "Positive chip, always with ↗"],
    ["signal-good-soft", "Positive chip fill"],
    ["signal-alert", "Alert chip, always with a dot or icon"],
    ["signal-alert-soft", "Alert chip fill"],
  ] },
];

export const Color: Story = {
  render: () => (
    <div className="flex flex-col">
      {COLOR_GROUPS.map((g) => (
        <Section key={g.title} title={g.title} note={g.title === "Meaning" ? "One color, one meaning. Text on highlight is always #1B1C1E, in both themes. Status is never color alone." : undefined}>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-5">
            {g.tokens.map(([t, r]) => <Swatch key={t} token={t} rule={r} />)}
          </div>
        </Section>
      ))}
    </div>
  ),
};

const TYPE = [
  { name: "display", cls: "text-[44px] leading-[46px] tracking-[-0.025em] font-semibold", spec: "Instrument Sans 44/46 600", sample: "House" },
  { name: "title", cls: "text-[22px] leading-7 tracking-[-0.01em] font-semibold", spec: "Instrument Sans 22/28 600", sample: "Tonight's roster" },
  { name: "body", cls: "text-[15px] leading-[22px]", spec: "Instrument Sans 15/22 400", sample: "A pair of socks on the living room floor." },
  { name: "label", cls: "text-[13px] leading-[18px] font-medium", spec: "Instrument Sans 13/18 500", sample: "Walk the route" },
  { name: "reading", cls: "font-mono text-[20px] leading-6 font-medium", spec: "IBM Plex Mono 20/24 500, tabular", sample: "64 %  1307 ms" },
  { name: "coord", cls: "font-mono text-[12px] leading-4", spec: "IBM Plex Mono 12/16 400", sample: "WP-06  8.2, 1.4  23:01:24" },
];

export const Type: Story = {
  render: () => (
    <Section title="Type" note="If a sensor or machine produced it, it is mono. Everything a person reads or writes is sans.">
      <div className="flex flex-col">
        {TYPE.map((t) => (
          <div key={t.name} className="grid grid-cols-[120px_1fr_260px] items-baseline gap-4 border-t border-border py-4">
            <span className="text-[13px] font-medium text-muted-foreground">{t.name}</span>
            <span className={t.cls}>{t.sample}</span>
            <span className="font-mono text-[12px] text-muted-foreground">{t.spec}</span>
          </div>
        ))}
      </div>
    </Section>
  ),
};

export const SpacingRadiusElevation: Story = {
  name: "Spacing, radius, elevation",
  render: () => (
    <div className="flex flex-col">
      <Section title="Spacing" note="Four values only.">
        <div className="flex flex-col gap-3">
          {[["space-1", 4, "tight pairs"], ["space-2", 8, "inside controls"], ["space-4", 16, "module padding and gaps"], ["space-8", 32, "between regions"]].map(([n, px, use]) => (
            <div key={n} className="grid grid-cols-[120px_60px_1fr] items-center gap-4">
              <span className="text-[13px] font-medium">{n}</span>
              <span className="font-mono text-[12px] text-muted-foreground">{px}px</span>
              <div className="flex items-center gap-3">
                <div className="h-4 bg-heat-hot" style={{ width: px as number }} />
                <span className="text-[13px] text-muted-foreground">{use}</span>
              </div>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Radius" note="Radius signals hierarchy. Avoid rounded-lg (10px) in our own components.">
        <div className="flex flex-wrap gap-8">
          {[["rounded-sm", "3px key", "key hints, heat cells"], ["rounded-md", "6px control", "buttons, inputs, chips"], ["rounded-xl", "14px module", "modules, map frame, drawers"]].map(([c, n, u]) => (
            <div key={c} className="flex flex-col gap-2">
              <div className={`size-24 border border-input bg-card ${c}`} />
              <span className="text-[13px] font-medium">{n}</span>
              <span className="text-[13px] text-muted-foreground">{u}</span>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Elevation" note="Modules have no stroke and no shadow: surface on paper. Floating layers take one shadow.">
        <div className="flex flex-wrap gap-8">
          <div className="flex h-28 w-56 items-center justify-center rounded-xl bg-card text-[13px]">Module</div>
          <div className="flex h-28 w-56 items-center justify-center rounded-xl bg-popover text-[13px] shadow-[0_8px_24px_rgb(0_0_0/0.12)] dark:shadow-[0_8px_24px_rgb(0_0_0/0.4)]">Floating layer</div>
        </div>
      </Section>
    </div>
  ),
};

function RouteDraw() {
  const [k, setK] = useState(0);
  return (
    <Section title="Motion" note="One orchestrated moment: an accepted route draws from start to end along its legs, 400ms ease-out. Everything else responds to the user in 150 to 200ms. Reduced motion is respected.">
      <div className="flex flex-col items-start gap-4">
        <svg key={k} width="480" height="160" className="rounded-xl bg-twin-canvas">
          <polyline points="30,120 120,40 240,90 330,30 450,110" fill="none" stroke="#EDEDE7" strokeWidth="2" strokeLinejoin="round" pathLength={1} className="wtdd-route-draw" />
          {[[30, 120], [120, 40], [240, 90], [330, 30], [450, 110]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r="5" fill="#EDEDE7" />)}
        </svg>
        <ActionButton intent="secondary" onClick={() => setK((n) => n + 1)}>Replay</ActionButton>
      </div>
    </Section>
  );
}

export const Motion: Story = { render: () => <RouteDraw /> };

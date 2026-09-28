import type { Decorator, Preview } from "@storybook/nextjs-vite";
import { useEffect } from "react";
import { Instrument_Sans, IBM_Plex_Mono } from "next/font/google";
import { Plumb } from "plumbkit/react";
import { TooltipProvider } from "../components/ui/tooltip";
import "../app/globals.css";

const sans = Instrument_Sans({ subsets: ["latin"], variable: "--font-instrument-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

/** Theme toolbar: toggles shadcn's `.dark` class on <html>, the same switch next-themes flips in the app. */
function ThemeFrame({ dark, children }: { dark: boolean; children: React.ReactNode }) {
  useEffect(() => {
    const html = document.documentElement;
    html.classList.toggle("dark", dark);
    html.classList.add(sans.variable, mono.variable, "antialiased");
    document.body.classList.add("bg-background", "text-foreground", "font-sans");
  }, [dark]);
  return (
    <TooltipProvider>
      {children}
      <Plumb />
    </TooltipProvider>
  );
}

const withTheme: Decorator = (Story, ctx) => (
  <ThemeFrame dark={ctx.globals.theme === "dark"}>
    <Story />
  </ThemeFrame>
);

const preview: Preview = {
  decorators: [withTheme],
  globalTypes: {
    theme: {
      description: "Theme",
      toolbar: { title: "Theme", icon: "mirror", items: [{ value: "light", title: "Light" }, { value: "dark", title: "Dark" }], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "light" },
  parameters: {
    layout: "padded",
    backgrounds: { disable: true },
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    a11y: { test: "todo" },
    options: { storySort: { order: ["Foundations", "Primitives", "Map", "Patterns"] } },
  },
};

export default preview;

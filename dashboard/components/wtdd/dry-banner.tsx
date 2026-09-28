/** Shown across the top whenever the data source is fixtures. */
export function DryBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div role="status" className="rounded-md border border-heat-peak bg-card px-4 py-2 font-mono text-[12px] text-foreground">
      Dry: fixture rows, not a night
    </div>
  );
}

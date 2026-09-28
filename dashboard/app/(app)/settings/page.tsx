import { PageHeader } from "@/components/shell/page-header";
import { SampleFrame } from "@/components/shell/sample-frame";
import { SettingsView } from "@/components/settings/settings-view";
import { getDataSource } from "@/lib/data";

/** Settings are not wired yet: shown as a sample. The dog's real health is on Overview's Body card; the theme switch is in the top bar. */
export default async function SettingsPage() {
  const ds = getDataSource();
  const [site, integrations] = await Promise.all([ds.getSite(), ds.getIntegrations()]);
  return (
    <>
      <PageHeader crumbs={[{ label: "Settings" }]} />
      <SampleFrame what="Settings are not wired yet: the dog's real health is on Overview, and the theme switch is in the top bar.">
        <SettingsView site={site} integrations={integrations} />
      </SampleFrame>
    </>
  );
}

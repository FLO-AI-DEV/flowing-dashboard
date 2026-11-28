/* Enquiries: what customers asked about and what is still open, shown exactly as the customer-care team records it.
   Tap a box (today, open, not picked up, older than 30 days) or a group for every enquiry behind it. */
import { router } from "expo-router";
import { View } from "react-native";
import { TapRow } from "../../components/Rows";
import { Em, Screen } from "../../components/Screen";
import { KpiGrid, Notices, Panel, T } from "../../components/ui";
import { useDashboard } from "../../lib/query";
import type { EnquiriesData } from "../../lib/types";

/** KPI box -> the list behind it. */
const VIEW: Record<string, string> = { today: "v-today", open: "all", old: "v-old", notpicked: "v-notpicked" };

export default function Enquiries() {
  const q = useDashboard<EnquiriesData>("/enquiries");
  return (
    <Screen
      title="Enquiries"
      q={q}
      lede={(d) => {
        const n = (id: string) => Number(d.kpis.find((k) => k.id === id)?.value ?? 0);
        return (
          <>
            <Em>{n("open")} open</Em>
            {n("notpicked") ? <>, <Em bad>{n("notpicked")} not picked up yet</Em></> : ""}. Tap a box or a group to see the enquiries.
          </>
        );
      }}
    >
      {(d) => (
        <View style={{ gap: 14 }}>
          <KpiGrid
            kpis={d.kpis}
            onPick={(id) => {
              const k = d.kpis.find((x) => x.id === id);
              if (VIEW[id]) router.push({ pathname: "/enquiry/[key]", params: { key: VIEW[id], label: k?.label ?? "Enquiries" } });
            }}
          />
          <Notices items={d.notices} />
          {d.auto_categorised > 0 && (
            <T v="small">
              {d.auto_categorised} open enquiries have no CATEGORY in the sheet yet. They are listed under “Not categorised yet”. Pick a category for each in the sheet and they move to their group.
            </T>
          )}
          <Panel title="What is still open" sub="Grouped by the CATEGORY set in the sheet. Tap a group to see every enquiry." flush>
            {d.causes.length ? (
              d.causes.map((cz, i) => (
                <TapRow
                  key={cz.key}
                  first={i === 0}
                  tone={cz.older > 0 ? "bad" : cz.today > 0 ? "warn" : "none"}
                  title={cz.label}
                  sub={[`${cz.open} open`, cz.today ? `${cz.today} today` : "", cz.older ? `${cz.older} older than 30 days` : "", `oldest ${cz.oldest_days} days`].filter(Boolean).join(" · ")}
                  onPress={() => router.push({ pathname: "/enquiry/[key]", params: { key: cz.key, label: cz.label } })}
                />
              ))
            ) : (
              <View style={{ padding: 16 }}>
                <T v="title">Nothing is open</T>
                <T>Every enquiry is marked Solved.</T>
              </View>
            )}
          </Panel>
          {d.by_source.length > 0 && (
            <Panel title="By source" flush>
              {d.by_source.map((s, i) => (
                <TapRow key={s.source} first={i === 0} title={s.source} right={`${s.open} open of ${s.total}`} />
              ))}
            </Panel>
          )}
        </View>
      )}
    </Screen>
  );
}

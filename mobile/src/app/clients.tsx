/* Clients: biggest clients first; "Days since" shows who has gone quiet. */
import { View } from "react-native";
import { DataTable } from "../components/DataTable";
import { FilterButton, useFilters } from "../components/Filters";
import { Em, Screen } from "../components/Screen";
import { Card, Empty, KpiGrid } from "../components/ui";
import { useDashboard } from "../lib/query";
import type { ClientsData } from "../lib/types";

const KEYS = ["sales_person", "channel"];
const GROUPS = [
  { key: "sales_person", label: "Sales person", raw: true },
  { key: "channel", label: "Channel", raw: true },
];

export default function Clients() {
  const f = useFilters(KEYS);
  const q = useDashboard<ClientsData>("/clients", f.values);
  return (
    <Screen
      title="Clients"
      inStack
      q={q}
      lede={(d) => {
        const quiet = Number(d.kpis.find((k) => /quiet/i.test(k.label))?.value ?? 0);
        return (
          <>
            Biggest clients first.{quiet ? <> <Em bad>{quiet} quiet for 30+ days.</Em></> : ""}
          </>
        );
      }}
      filters={(d) => (
        <View style={{ flexDirection: "row" }}>
          <FilterButton groups={GROUPS} options={d.options} values={f.values} onApply={f.setAll} />
        </View>
      )}
    >
      {(d) => (
        <View style={{ gap: 14 }}>
          <KpiGrid kpis={d.kpis} />
          {d.table.rows.length ? (
            <Card flush><DataTable table={d.table} name="flo-wing-clients" maxRows={25} titleCaseFirst={false} /></Card>
          ) : (
            <Empty title="No clients" />
          )}
        </View>
      )}
    </Screen>
  );
}

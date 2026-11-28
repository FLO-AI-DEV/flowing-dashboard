/* Every open order behind a selection: period, step it is waiting for, sales person, channel, late only. Opened from
   the Orders tab or from a "Needs action" line on Today (which sets the step or the sales person). */
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { View } from "react-native";
import { ChipRow, Toggle } from "../components/Chips";
import { DataTable } from "../components/DataTable";
import { FilterButton, useFilters } from "../components/Filters";
import { Em, Screen } from "../components/Screen";
import { SCOPES } from "../components/SendSheet";
import { Card, Empty, KpiGrid } from "../components/ui";
import { useDashboard } from "../lib/query";
import type { OrdersData } from "../lib/types";

const KEYS = ["stage", "sales_person", "channel"];
const GROUPS = [
  { key: "stage", label: "Waiting for", raw: true },
  { key: "sales_person", label: "Sales person", raw: true },
  { key: "channel", label: "Channel", raw: true },
];

export default function OrdersAll() {
  const p = useLocalSearchParams<{ stage?: string; sales_person?: string }>();
  const f = useFilters(KEYS, { stage: p.stage ? [p.stage] : [], sales_person: p.sales_person ? [p.sales_person] : [] });
  const [range, setRange] = useState("");
  const [order, setOrder] = useState("newest");
  const [late, setLate] = useState(false);
  const q = useDashboard<OrdersData>("/orders", { ...f.values, range, order, late_only: late ? "true" : undefined });
  return (
    <Screen
      title="Open orders"
      inStack
      q={q}
      lede={(d) => {
        const lateN = Number(d.kpis.find((k) => k.id === "late")?.value ?? 0);
        return (
          <>
            Every open order behind your selection
            {lateN ? <>, <Em bad>{lateN} late</Em></> : ""}.
          </>
        );
      }}
      filters={(d) => (
        <>
          <ChipRow items={SCOPES} value={range} onChange={setRange} />
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <FilterButton groups={GROUPS} options={d.options} values={f.values} onApply={f.setAll} />
            <Toggle label="Late only" on={late} onPress={() => setLate(!late)} />
            <Toggle label={order === "newest" ? "Newest first ↓" : "Oldest first ↑"} on={false} onPress={() => setOrder(order === "newest" ? "oldest" : "newest")} />
          </View>
        </>
      )}
    >
      {(d) => (
        <View style={{ gap: 14 }}>
          <KpiGrid kpis={d.kpis} />
          {d.table.rows.length ? (
            <Card flush>
              <DataTable table={d.table} name="flo-wing-orders" maxRows={25} titleCaseFirst={false} />
            </Card>
          ) : (
            <Empty title="No orders match" text="Nothing is waiting here right now." />
          )}
        </View>
      )}
    </Screen>
  );
}

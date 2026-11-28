/* The orders behind one cause (waiting for Mona's reply, PO, billing, or on hold), with just the columns that matter
   for it. Pick a period, flip the order, or send the list to the person responsible on WhatsApp. */
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { View } from "react-native";
import { ChipRow, Toggle } from "../../components/Chips";
import { DataTable } from "../../components/DataTable";
import { Em, Screen } from "../../components/Screen";
import { SCOPES, SendButton } from "../../components/SendSheet";
import { Card, Empty } from "../../components/ui";
import { useDashboard } from "../../lib/query";
import type { CauseData } from "../../lib/types";

export default function Cause() {
  const { key, label } = useLocalSearchParams<{ key: string; label?: string }>();
  const [range, setRange] = useState("");
  const [order, setOrder] = useState("oldest");
  const q = useDashboard<CauseData>(`/cause/${key}`, { range, order });
  return (
    <Screen
      title={label || "Orders"}
      inStack
      q={q}
      lede={(d) => (
        <>
          <Em bad={d.count > 0}>{d.count}</Em>
          {range ? ` of ${d.total}` : ""} order{d.count === 1 ? "" : "s"} waiting here.
        </>
      )}
      filters={() => (
        <>
          <ChipRow items={SCOPES} value={range} onChange={setRange} />
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Toggle label={order === "oldest" ? "Oldest first ↑" : "Newest first ↓"} on={false} onPress={() => setOrder(order === "oldest" ? "newest" : "oldest")} />
          </View>
          <SendButton cause={String(key)} startScope={range || "today"} />
        </>
      )}
    >
      {(d) =>
        d.table.rows.length ? (
          <Card flush>
            <DataTable table={d.table} name={`flo-wing-${key}`} maxRows={25} titleCaseFirst={false} />
          </Card>
        ) : (
          <Empty title="No orders in this period" />
        )
      }
    </Screen>
  );
}

/* Every enquiry behind one group or box: pick a period or a status, flip the order, or send the list to the
   customer-care team on WhatsApp. */
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

const STATUSES: [string, string][] = [["Pending", "Pending"], ["In process", "In process"], ["Not marked yet", "Not marked yet"]];

export default function EnquiryRows() {
  const { key, label } = useLocalSearchParams<{ key: string; label?: string }>();
  const k = String(key);
  const [range, setRange] = useState("");
  const [status, setStatus] = useState("");
  const [order, setOrder] = useState("oldest");
  const q = useDashboard<CauseData>(`/enquiries/cause/${k}`, { range, order, status });
  // a box already fixes the age or status, so its own chips would only repeat it
  const periods = SCOPES.filter(([n]) => (k === "v-today" || k === "v-old" ? false : k === "v-notpicked" ? n !== "older" : true));
  const statuses = k === "v-notpicked" ? [] : STATUSES;
  return (
    <Screen
      title={label || "Enquiries"}
      inStack
      q={q}
      lede={(d) => (
        <>
          <Em>{d.count}</Em>
          {range || status ? ` of ${d.total}` : ""} enquir{d.count === 1 ? "y" : "ies"} in this list.
        </>
      )}
      filters={() => (
        <>
          {periods.length > 0 && <ChipRow items={periods} value={range} onChange={setRange} />}
          {statuses.length > 0 && <ChipRow items={statuses} value={status} onChange={setStatus} />}
          <View style={{ flexDirection: "row" }}>
            <Toggle label={order === "oldest" ? "Oldest first ↑" : "Newest first ↓"} on={false} onPress={() => setOrder(order === "oldest" ? "newest" : "oldest")} />
          </View>
          {!k.startsWith("v-") && <SendButton cause="enquiry" group={k} noun="enquiry" startScope={range || "older"} />}
        </>
      )}
    >
      {(d) =>
        d.table.rows.length ? (
          <Card flush>
            <DataTable table={d.table} name={`flo-wing-enquiries-${k}`} maxRows={25} titleCaseFirst={false} />
          </Card>
        ) : (
          <Empty title="No enquiries in this selection" />
        )
      }
    </Screen>
  );
}

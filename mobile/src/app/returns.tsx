/* Sales returns (GR): what quality check decided, which calls to clients are still to be made, the 90-day policy, and
   returns by month, client and reason. */
import { useState } from "react";
import { View } from "react-native";
import { BarList } from "../components/charts";
import { ChipRow } from "../components/Chips";
import { DataTable } from "../components/DataTable";
import { Em, Screen } from "../components/Screen";
import { Card, Empty, KpiGrid, Panel, T } from "../components/ui";
import { useDashboard } from "../lib/query";
import type { ReturnsData } from "../lib/types";

export default function Returns() {
  const [win, setWin] = useState("fy");
  const [box, setBox] = useState("");
  const q = useDashboard<ReturnsData>("/returns", { window: win, box });
  return (
    <Screen
      title="Sales returns"
      inStack
      q={q}
      lede={(d) => {
        const pcs = Number(d.kpis.find((k) => k.id === "pcs")?.value ?? 0);
        const calls = d.pending_total ?? d.pending.rows.length;
        return (
          <>
            <Em>{pcs} pieces</Em> came back{d.window.label ? ` (${d.window.label.toLowerCase()})` : ""}
            {calls ? <>, <Em bad>{calls} calls</Em> still to be made</> : ""}.
          </>
        );
      }}
      filters={(d) => <ChipRow items={d.windows.map((w) => [w.key, w.label])} value={win} onChange={(v) => { setWin(v); setBox(""); }} required />}
    >
      {(d) => {
        return (
          <View style={{ gap: 14 }}>
            {d.notices.map((n, i) => <T key={i} v="small">{n.text}</T>)}
            <KpiGrid kpis={d.kpis} />
            <Panel title="Calls still to be made" sub="QC-pass goods with no calling remark yet. The client is called and the goods go back at the client's cost.">
              <View style={{ gap: 10 }}>
                <ChipRow items={d.boxes.map((b) => [b.key, `${b.label}: ${b.count}`])} value={box} onChange={setBox} />
              </View>
            </Panel>
            {d.pending.rows.length ? (
              <Card flush><DataTable table={d.pending} name="flo-wing-returns-calls" maxRows={20} titleCaseFirst={false} /></Card>
            ) : (
              <Empty title="No calls pending in this selection" />
            )}
            <Panel title="Why QC failed" sub="Pieces by the reason the team wrote">
              {d.reasons.length ? <BarList items={d.reasons.map((r) => ({ label: r.reason, value: r.pcs }))} unit="pcs" tone="neg" max={10} /> : <T>No QC failures in this period.</T>}
            </Panel>
            <Panel title="By month" flush><DataTable table={d.months} name="flo-wing-returns-months" maxRows={14} titleCaseFirst={false} /></Panel>
            <Panel title="Clients with the most returns" flush><DataTable table={d.clients} name="flo-wing-returns-clients" maxRows={15} titleCaseFirst={false} /></Panel>
            {d.policy.rows.length > 0 && (
              <Panel title={`Returned after ${d.policy_days} days`} sub="Outside the return policy: check before accepting." flush>
                <DataTable table={d.policy} name="flo-wing-returns-policy" maxRows={15} titleCaseFirst={false} />
              </Panel>
            )}
          </View>
        );
      }}
    </Screen>
  );
}

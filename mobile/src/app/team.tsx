/* Team: who is holding orders at each step, how the sales team is doing, and which sheet rows are incomplete. */
import { View } from "react-native";
import { DataTable } from "../components/DataTable";
import { FilterButton, MonthChips, useFilters } from "../components/Filters";
import { Screen } from "../components/Screen";
import { Empty, Panel } from "../components/ui";
import { useDashboard } from "../lib/query";
import type { TeamData } from "../lib/types";

const KEYS = ["month", "channel"];

export default function Team() {
  const f = useFilters(KEYS);
  const q = useDashboard<TeamData>("/team", f.values);
  return (
    <Screen
      title="Team"
      inStack
      q={q}
      lede={() => <>Who is holding orders, how the sales team is doing, and which sheet rows are incomplete.</>}
      filters={(d) => (
        <>
          <MonthChips months={d.options.month ?? []} value={f.values.month} onChange={(v) => f.set("month", v)} />
          <View style={{ flexDirection: "row" }}>
            <FilterButton groups={[{ key: "channel", label: "Channel", raw: true }]} options={d.options} values={f.values} onApply={f.setAll} />
          </View>
        </>
      )}
    >
      {(d) => (
        <View style={{ gap: 14 }}>
          <Panel title="Who is holding orders" sub="Waiting at each step and how many are past the deadline" flush>
            <DataTable table={d.owners} titleCaseFirst={false} />
          </Panel>
          <Panel title="Sales team" sub="Orders, sets, clients and how fast they were billed" flush>
            {d.sales.rows.length ? <DataTable table={d.sales} name="flo-wing-sales-team" titleCaseFirst={false} /> : <Empty title="No orders" />}
          </Panel>
          <Panel title="Rows to complete in the sheet" sub="Missing quantity, sales person or bill date: the sales person should fix these" flush>
            {d.fixes.rows.length ? <DataTable table={d.fixes} name="flo-wing-rows-to-fix" titleCaseFirst={false} /> : <Empty title="All rows complete" />}
          </Panel>
        </View>
      )}
    </Screen>
  );
}

import { useDashboard } from "../api/hooks";
import type { TeamData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FilterBar, MonthFilter, MultiSelect } from "../components/Filters";
import { Empty, Panel } from "../components/ui";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

const KEYS = ["month", "channel"];

export default function Team() {
  const { values, set, reset, active } = useFilters(KEYS);
  const q = useDashboard<TeamData>("/team", values);
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead title="Team" lede="Who is holding orders, how the sales team is doing, and which sheet rows are incomplete." meta={d.meta} />
            <FilterBar active={active} onReset={reset}>
              <MonthFilter options={d.options.month ?? []} value={values.month} onChange={(v) => set("month", v)} />
              <MultiSelect label="Channel" options={d.options.channel ?? []} value={values.channel} onChange={(v) => set("channel", v)} />
            </FilterBar>
            <Panel title="Who is holding orders" sub="Orders waiting at each step and how many are past the deadline" flush>
              <DataTable table={d.owners} name="flo-wing-stage-owners" csv={false} titleCaseFirst={false} />
            </Panel>
            <Panel title="Sales team" sub="Orders taken, sets, clients and how fast they were billed" flush>
              {d.sales.rows.length ? <DataTable table={d.sales} name="flo-wing-sales-team" titleCaseFirst={false} /> : <Empty />}
            </Panel>
            <Panel title="Rows to complete in the sheet" sub="Missing quantity, sales person or bill date — the sales person should fix these" flush>
              {d.fixes.rows.length ? <DataTable table={d.fixes} name="flo-wing-rows-to-fix" titleCaseFirst={false} /> : <Empty title="All rows complete" />}
            </Panel>
          </>
        )}
      </PageState>
    </div>
  );
}

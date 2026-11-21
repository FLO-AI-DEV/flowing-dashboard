import { useDashboard } from "../api/hooks";
import type { ClientsData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Panel } from "../components/ui";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

const KEYS = ["channel", "sales_person"];

export default function Clients() {
  const { values, set, reset, active } = useFilters(KEYS);
  const q = useDashboard<ClientsData>("/clients", values);
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead title="Clients" lede="Biggest clients first. 'Days since' shows who has gone quiet." meta={d.meta} />
            <FilterBar active={active} onReset={reset}>
              <MultiSelect label="Sales person" options={d.options.sales_person ?? []} value={values.sales_person} onChange={(v) => set("sales_person", v)} />
              <MultiSelect label="Channel" options={d.options.channel ?? []} value={values.channel} onChange={(v) => set("channel", v)} />
            </FilterBar>
            <KpiStrip kpis={d.kpis} cols={3} />
            <Panel title="Clients" flush>
              {d.table.rows.length ? <DataTable table={d.table} name="flo-wing-clients" maxRows={25} titleCaseFirst={false} /> : <Empty />}
            </Panel>
          </>
        )}
      </PageState>
    </div>
  );
}

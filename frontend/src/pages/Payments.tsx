import { useDashboard } from "../api/hooks";
import type { PaymentsData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel } from "../components/ui";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

const KEYS = ["owner", "sales_person"];

export default function Payments() {
  const { values, set, reset, active } = useFilters(KEYS);
  const q = useDashboard<PaymentsData>("/payments", values);
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead
              title="Payments"
              lede="Pending payments and who has not followed up. A follow-up counts when its note is time-stamped in the form."
              meta={d.meta}
            />
            <FilterBar active={active} onReset={reset}>
              <MultiSelect label="CRM member" options={d.options.owner ?? []} value={values.owner} onChange={(v) => set("owner", v)} />
              <MultiSelect label="Sales person" options={d.options.sales_person ?? []} value={values.sales_person} onChange={(v) => set("sales_person", v)} />
            </FilterBar>
            <Notices items={d.notices} />
            <KpiStrip kpis={d.kpis} cols={4} />
            <Panel title="By CRM member" sub="Pending, not followed up, and collected this month" flush>
              {d.members.rows.length ? <DataTable table={d.members} name="flo-wing-crm-members" csv={false} titleCaseFirst={false} /> : <Empty />}
            </Panel>
            <Panel title="Pending payments" sub="Not followed up first, then the longest without a follow-up" flush>
              {d.pending.rows.length ? (
                <DataTable table={d.pending} name="flo-wing-pending-payments" maxRows={25} titleCaseFirst={false} />
              ) : (
                <Empty title="Nothing pending">Every order is paid or cancelled.</Empty>
              )}
            </Panel>
          </>
        )}
      </PageState>
    </div>
  );
}

import { useDashboard } from "../api/hooks";
import type { DuesData } from "../api/types";
import { BarList } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { ExtraFilters } from "../components/ExtraFilters";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { EXTRA_KEYS, useFilters } from "../lib/filters";
import { fmtInt, inrShort } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["tab", "supplier", "agency", ...EXTRA_KEYS];

export default function Dues() {
  const f = useFilters(KEYS);
  const q = useDashboard<DuesData>("/dues", { ...f.values, tab: f.values.tab[0] ?? "" });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const s = d.summary;
          return (
            <>
              <PageHead
                title="Supplier dues"
                meta={d.meta}
                lede={
                  d.empty ? (
                    "No bills for these filters."
                  ) : (
                    <>
                      {s.overdue > 0 ? <span className="bad">{inrShort(s.overdue)} is overdue</span> : "Nothing is overdue"}
                      {" "}and <strong>{inrShort(s.due7)}</strong> falls due in the next 7 days, out of {inrShort(s.total)} payable to {fmtInt(s.suppliers)} suppliers.
                    </>
                  )
                }
              />
              <FilterBar active={f.active} onReset={f.reset}>
                <MultiSelect label="Dues list" options={d.tabs} value={f.values.tab} onChange={(v) => f.set("tab", v)} single allLabel={d.tab} pretty={(x) => x.trim()} />
                <MultiSelect label="Supplier" options={d.options.supplier} value={f.values.supplier} onChange={(v) => f.set("supplier", v)} />
                <MultiSelect label="Agency" options={d.options.agency} value={f.values.agency} onChange={(v) => f.set("agency", v)} />
                {d.title && <span className="applied">{d.title}</span>}
                <ExtraFilters f={f} options={d.options} periodLabel={d.period_label} dateOf="bill date" windowLabel="Due window" search="Search supplier, bill no., agency…" />
              </FilterBar>
              <Notices items={d.notices} />
              {d.empty ? (
                <Empty title="No bills">Try another dues list or clear a filter.</Empty>
              ) : (
                <>
                  <KpiStrip kpis={d.kpis} cols={4} lead={["overdue"]} />
                  <Section title="What to pay" sub="Bills by supplier · credit days, discount and agency from the ‘Updated Sheet’ tab">
                    <div className="grid">
                      <div className="span-8">
                        <Panel title="Dues by supplier" flush>
                          <DataTable table={d.tables.suppliers} name="dues_by_supplier" maxRows={15} />
                        </Panel>
                      </div>
                      <div className="span-4">
                        <Panel title="Ageing" sub="₹ by days past the due date">
                          <BarList items={d.charts.ageing} money tone="neg" label="Dues by days overdue" share />
                        </Panel>
                        {d.charts.agencies.length > 1 && (
                          <Panel title="By agency" sub="₹ payable" className="mt">
                            <BarList items={d.charts.agencies} money label="Dues by agency" max={6} />
                          </Panel>
                        )}
                      </div>
                    </div>
                  </Section>
                  <Section title="Every bill" sub="Most overdue first">
                    <Panel flush>
                      <DataTable table={d.tables.bills} name="dues_bills" maxRows={20} titleCaseFirst={false} />
                    </Panel>
                  </Section>
                </>
              )}
            </>
          );
        }}
      </PageState>
    </div>
  );
}

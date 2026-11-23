import { useDashboard } from "../api/hooks";
import type { DuesData, OtvData } from "../api/types";
import { BarList } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { ExtraFilters } from "../components/ExtraFilters";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { EXTRA_KEYS, useFilters } from "../lib/filters";
import { fmtInt, inrShort } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["tab", "supplier", "agency", ...EXTRA_KEYS];

/** The current tabs of the dues sheet (supplier terms, queries, agency lists) have no bills: shown as a live table. */
function SheetTab({ d, f }: { d: OtvData; f: ReturnType<typeof useFilters> }) {
  return (
    <>
      <PageHead title="Supplier dues" meta={d.meta} lede={d.empty ? "This tab has no rows." : <><strong>{fmtInt(d.rows_total)} rows</strong> on the {d.tab.trim()} tab. This tab lists supplier terms, not bills; pick an older dated list in 'Dues list' to see bill totals.</>} />
      <FilterBar active={f.active} onReset={f.reset}>
        <MultiSelect label="Dues list" options={d.tabs} value={f.values.tab} onChange={(v) => f.set("tab", v)} single allLabel={d.tab} pretty={(x) => x.trim()} />
        {d.options?.vendor && <MultiSelect label="Supplier" options={d.options.vendor} value={f.values.supplier} onChange={(v) => f.set("supplier", v)} />}
        <ExtraFilters f={f} options={d.options} periodLabel={undefined} dateOf="date" search="Search supplier, agency, remarks…" />
      </FilterBar>
      <Notices items={d.notices} />
      {d.empty ? (
        <Empty title="No rows" />
      ) : (
        <>
          <KpiStrip kpis={d.kpis} cols={Math.min(4, d.kpis.length)} />
          <Section title="All rows" sub="As in the sheet, live">
            <Panel flush>
              <DataTable table={d.tables.rows} name="dues_sheet" maxRows={25} titleCaseFirst={false} />
            </Panel>
          </Section>
        </>
      )}
    </>
  );
}

export default function Dues() {
  const f = useFilters(KEYS);
  const q = useDashboard<DuesData>("/dues", { ...f.values, tab: f.values.tab[0] || "__current__" });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          if (d.mode === "sheet") return <SheetTab d={d as unknown as OtvData} f={f} />;
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

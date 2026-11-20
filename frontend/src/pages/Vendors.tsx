import { useDashboard } from "../api/hooks";
import type { VendorsData } from "../api/types";
import { colorFor, Legend } from "../components/charts/common";
import { HBars } from "../components/charts/HBars";
import { BarList } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { FilterBar, MonthFilter, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { useFilters } from "../lib/filters";
import { inrShort, titleCase } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["month", "department", "category", "city"];

export default function Vendors() {
  const f = useFilters(KEYS);
  const q = useDashboard<VendorsData>("/vendors", f.values);
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const s = d.summary;
          return (
            <>
              <PageHead
                title="Vendors"
                meta={d.meta}
                lede={
                  d.empty ? (
                    "No PO lines for these filters."
                  ) : (
                    <>
                      <span className={s.late_vendors ? "bad" : undefined}>
                        {s.late_vendors} of {s.vendors} vendors
                      </span>{" "}
                      have PO lines past their delivery date
                      {s.most_overdue ? (
                        <>
                          ; the most overdue is <strong>{titleCase(s.most_overdue.name)}</strong> ({inrShort(s.most_overdue.value)})
                        </>
                      ) : null}
                      .
                    </>
                  )
                }
              />
              <FilterBar active={f.active} onReset={f.reset}>
                <MonthFilter options={d.options.month} value={f.values.month} onChange={(v) => f.set("month", v)} />
                <MultiSelect label="Department" options={d.options.department} value={f.values.department} onChange={(v) => f.set("department", v)} />
                <MultiSelect label="Category" options={d.options.category} value={f.values.category} onChange={(v) => f.set("category", v)} />
                <MultiSelect label="City" options={d.options.city} value={f.values.city} onChange={(v) => f.set("city", v)} />
              </FilterBar>
              <Notices items={d.notices} />
              {d.empty ? (
                <Empty title="No PO lines">Try clearing a filter.</Empty>
              ) : (
                <>
                  <KpiStrip kpis={d.kpis} cols={3} lead={["overdue"]} />
                  <Section title="Who owes what" sub="From the PO Master tab · on time = received in full on or before the delivery date">
                    <div className="grid">
                      <div className="span-6">
                        <Panel title="Received and pending" sub="₹ per vendor" right={<Legend items={d.charts.pending.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                          <HBars data={{ categories: d.charts.pending.categories, series: [...d.charts.pending.series].reverse() }} money label="Received and pending value per vendor" sortBy="Pending" max={12} />
                        </Panel>
                      </div>
                      <div className="span-6">
                        <Panel title="Overdue value" sub="₹ past the delivery date">
                          <BarList items={d.charts.overdue} money tone="neg" label="Overdue value per vendor" max={10} />
                        </Panel>
                        {d.charts.ontime.length > 0 && (
                          <Panel title="On-time delivery" sub="% of lines received in full on time (vendors with 3+ received lines)" className="mt">
                            <BarList items={d.charts.ontime} unit="%" label="On-time delivery rate per vendor" max={10} share={false} decimals={1} />
                          </Panel>
                        )}
                      </div>
                    </div>
                  </Section>
                  <Section title="Vendor scorecard" sub="Every vendor, most pending first">
                    <Panel flush>
                      <DataTable table={d.tables.scorecard} name="vendor_scorecard" maxRows={20} />
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

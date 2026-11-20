import { useDashboard } from "../api/hooks";
import type { OrdersData } from "../api/types";
import { Bars } from "../components/charts/Bars";
import { colorFor, Legend, TIMING_COLORS } from "../components/charts/common";
import { HBars } from "../components/charts/HBars";
import { BarList, Split } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { FilterBar, MonthFilter, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { useFilters } from "../lib/filters";
import { fmtInt, inrShort, titleCase } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["month", "vendor", "department", "category", "city", "timing"];

export default function Orders() {
  const f = useFilters(KEYS);
  const q = useDashboard<OrdersData>("/orders", f.values);
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const s = d.summary;
          return (
            <>
              <PageHead
                title="Orders"
                meta={d.meta}
                lede={
                  d.empty ? (
                    "No PO lines for these filters."
                  ) : (
                    <>
                      <strong>{inrShort(s.pending)}</strong> ({fmtInt(s.pending_pcs)} pcs) still to come in
                      {s.overdue_lines > 0 ? (
                        <>
                          ; <span className="bad">{fmtInt(s.overdue_lines)} lines</span> worth {inrShort(s.overdue)} are past their delivery date
                          {s.oldest ? <>, the oldest {s.oldest.days} days ({s.oldest.po}, {titleCase(s.oldest.vendor)})</> : null}.
                        </>
                      ) : (
                        "; nothing is past its delivery date."
                      )}
                    </>
                  )
                }
              />
              <FilterBar active={f.active} onReset={f.reset}>
                <MonthFilter options={d.options.month} value={f.values.month} onChange={(v) => f.set("month", v)} />
                <MultiSelect label="Vendor" options={d.options.vendor} value={f.values.vendor} onChange={(v) => f.set("vendor", v)} />
                <MultiSelect label="Department" options={d.options.department} value={f.values.department} onChange={(v) => f.set("department", v)} />
                <MultiSelect label="Category" options={d.options.category} value={f.values.category} onChange={(v) => f.set("category", v)} />
                <MultiSelect label="City" options={d.options.city} value={f.values.city} onChange={(v) => f.set("city", v)} />
                <MultiSelect label="Delivery" options={d.options.timing} value={f.values.timing} onChange={(v) => f.set("timing", v)} pretty={(x) => x} />
              </FilterBar>
              <Notices items={d.notices} />
              {d.empty ? (
                <Empty title="No PO lines">Try clearing a filter.</Empty>
              ) : (
                <>
                  <KpiStrip kpis={d.kpis} cols={3} lead={["pending"]} />

                  <Section title="Month by month" sub="By PO date">
                    <div className="grid">
                      <div className="span-7">
                        <Panel title="Ordered, received and pending" sub="₹" right={<Legend items={d.charts.monthly.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                          <Bars data={d.charts.monthly} months money label="Ordered, received and pending value by month" height={280} />
                        </Panel>
                      </div>
                      <div className="span-5">
                        <Panel title="Monthly table" flush>
                          <DataTable table={d.tables.monthly} name="orders_monthly" maxRows={13} titleCaseFirst={false} />
                        </Panel>
                      </div>
                    </div>
                  </Section>

                  <Section title="Delivery" sub="Is it coming in on time?">
                    <div className="grid">
                      <div className="span-5">
                        <Panel title="Delivery status" sub="PO lines">
                          <Split items={d.charts.timing} unit="lines" colors={TIMING_COLORS} label="PO lines by delivery status" />
                        </Panel>
                        <Panel title="Still to come in, by delivery month" sub="₹ pending" className="mt">
                          <BarList items={d.charts.receivable.categories.map((c, i) => ({ label: c, value: d.charts.receivable.series[0].values[i] }))} money tone="neg" label="Pending value by delivery month" max={12} share={false} />
                        </Panel>
                      </div>
                      <div className="span-7">
                        <Panel title="Overdue PO lines" sub={`${fmtInt(d.overdue_total)} lines · delivery date passed, pieces still pending · most late first`} flush>
                          {d.overdue_total ? <DataTable table={d.tables.overdue} name="orders_overdue_lines" maxRows={12} titleCaseFirst={false} /> : <div className="state">No PO line is overdue.</div>}
                        </Panel>
                      </div>
                    </div>
                  </Section>

                  <Section title="Vendors" sub="Who holds the most pending value">
                    <div className="grid">
                      <div className="span-5">
                        <Panel title="Received and pending by vendor" sub="₹" right={<Legend items={d.charts.vendors.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                          <HBars data={{ categories: d.charts.vendors.categories, series: [...d.charts.vendors.series].reverse() }} money label="Received and pending value per vendor" sortBy="Pending" max={12} />
                        </Panel>
                      </div>
                      <div className="span-7">
                        <Panel title="Vendor table" flush>
                          <DataTable table={d.tables.vendors} name="orders_vendors" maxRows={12} />
                        </Panel>
                      </div>
                    </div>
                  </Section>

                  <Section title="Category, department and city" sub="Where the value sits">
                    <div className="grid">
                      <div className="span-7">
                        <Panel title="By category" sub="₹" right={<Legend items={d.charts.categories.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                          <Bars data={d.charts.categories} names money label="Ordered, received and pending value by category" height={280} />
                        </Panel>
                      </div>
                      <div className="span-5">
                        <Panel title="Category table" flush>
                          <DataTable table={d.tables.categories} name="orders_categories" />
                        </Panel>
                      </div>
                      <div className="span-6">
                        <Panel title="By department" flush>
                          <DataTable table={d.tables.departments} name="orders_departments" />
                        </Panel>
                      </div>
                      <div className="span-6">
                        <Panel title="By city" flush>
                          <DataTable table={d.tables.cities} name="orders_cities" />
                        </Panel>
                      </div>
                    </div>
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

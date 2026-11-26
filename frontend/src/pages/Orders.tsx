import { useDashboard } from "../api/hooks";
import type { OrdersData } from "../api/types";
import { Bars } from "../components/charts/Bars";
import { colorFor, Legend, TIMING_COLORS } from "../components/charts/common";
import { HBars } from "../components/charts/HBars";
import { BarList, Split } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { ExtraFilters } from "../components/ExtraFilters";
import { FilterBar, MonthFilter, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { EXTRA_KEYS, useFilters } from "../lib/filters";
import { fmtInt, inrShort, titleCase } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["month", "delivery_month", "vendor", "department", "category", "city", "fabric", "timing", "date_by", ...EXTRA_KEYS];

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
                <MonthFilter label="Order month" options={d.options.month} value={f.values.month} onChange={(v) => f.set("month", v)} />
                {d.options.delivery_month && <MonthFilter label="Delivery month" options={d.options.delivery_month} value={f.values.delivery_month} onChange={(v) => f.set("delivery_month", v)} />}
                <MultiSelect label="Vendor" options={d.options.vendor} value={f.values.vendor} onChange={(v) => f.set("vendor", v)} />
                <MultiSelect label="Department" options={d.options.department} value={f.values.department} onChange={(v) => f.set("department", v)} />
                <MultiSelect label="Category" options={d.options.category} value={f.values.category} onChange={(v) => f.set("category", v)} />
                <MultiSelect label="City" options={d.options.city} value={f.values.city} onChange={(v) => f.set("city", v)} />
                {d.options.fabric && <MultiSelect label="Fabric" options={d.options.fabric} value={f.values.fabric} onChange={(v) => f.set("fabric", v)} pretty={(x) => x} />}
                <MultiSelect label="Delivery" options={d.options.timing} value={f.values.timing} onChange={(v) => f.set("timing", v)} pretty={(x) => x} />
                {d.options.date_by && <MultiSelect label="Date by" options={d.options.date_by} value={f.values.date_by} onChange={(v) => f.set("date_by", v)} single allLabel="Order date" pretty={(x) => x} />}
                <ExtraFilters f={f} options={d.options} periodLabel={d.period_label} dateOf={f.values.date_by?.[0] === "Delivery date" ? "delivery date" : "order date"} windowLabel="Due window" search="Search PO, design, vendor…" />
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

                  <Section title="Fabric" sub="Cotton, silk, viscose and so on · pick Fabric in the filters to see only that fabric">
                    <div className="grid" style={{ marginBottom: 16 }}>
                      <div className="span-7">
                        <Panel title="Ordered, received and pending by fabric" sub="₹" right={<Legend items={d.charts.fabrics.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                          <Bars data={d.charts.fabrics} names money label="Ordered, received and pending value by fabric" height={280} />
                        </Panel>
                      </div>
                      <div className="span-5">
                        <Panel title="PO lines by fabric" sub="Lines">
                          <BarList items={d.charts.fabric_lines} unit="lines" label="PO lines per fabric" max={12} share />
                        </Panel>
                      </div>
                    </div>
                    <Panel title="By fabric" sub="A line is counted under every fabric family its Fabric text names" flush>
                      <DataTable table={d.tables.fabrics} name="orders_fabrics" maxRows={15} titleCaseFirst={false} />
                    </Panel>
                  </Section>

                  <Section title={f.values.date_by?.[0] === "Delivery date" ? "Status by delivery month" : "Status by order month"} sub="How many lines are on time, delayed, overdue or still open · change 'Date by' in the filters to switch between order date and delivery date">
                    <Panel flush>
                      <DataTable table={d.tables.status_by_date} name="orders_status_by_date" maxRows={14} titleCaseFirst={false} />
                    </Panel>
                  </Section>

                  <Section title="Every PO line" sub="With order date, delivery date and received date · newest order first · use the filters above or the search to narrow it">
                    <Panel flush>
                      <DataTable table={d.tables.lines} name="orders_po_lines" maxRows={25} titleCaseFirst={false} />
                    </Panel>
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

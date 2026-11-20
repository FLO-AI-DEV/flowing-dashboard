import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard, useStatus } from "../api/hooks";
import type { Alert, OverviewData } from "../api/types";
import { Bars } from "../components/charts/Bars";
import { Legend, TIMING_COLORS, colorFor } from "../components/charts/common";
import { HBars } from "../components/charts/HBars";
import { BarList, Split } from "../components/charts/Lists";
import { DataFlow, type FlowOut } from "../components/DataFlow";
import { DataTable } from "../components/DataTable";
import { FilterBar, MonthFilter } from "../components/Filters";
import { KpiStrip, Notices, Panel, Section } from "../components/ui";
import { useFilters } from "../lib/filters";
import { inrShort, titleCase } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["month"];
const AREA_LINK: Record<string, string> = {
  overdue: "/orders?timing=Overdue+(Pending)",
  orders: "/orders",
  dues: "/dues",
  otv: "/order-to-vendors",
};
const AREA_NAME: Record<string, string> = { overdue: "Delivery", orders: "Orders", dues: "Supplier dues", otv: "Order to vendors", none: "Data" };
const SEVERITY: Record<string, number> = { error: 0, warning: 1, info: 2, success: 3 };

function AlertCard({ a }: { a: Alert }) {
  const to = AREA_LINK[a.area];
  const body = (
    <>
      <span className="tag">
        <i />
        {AREA_NAME[a.area] ?? a.area}
      </span>
      <h3>{a.title}</h3>
      <p>{a.text}</p>
      {a.top && a.top.length > 0 && (
        <div className="tops">
          {a.top.map((t) => (
            <span key={t.dimension}>
              Most pending {t.dimension.toLowerCase()}: <b>{titleCase(t.name)}</b> ({a.money ? inrShort(t.value) : t.value.toLocaleString("en-US")})
            </span>
          ))}
        </div>
      )}
    </>
  );
  return to ? (
    <Link className={`alert ${a.kind}`} to={to}>
      {body}
    </Link>
  ) : (
    <div className={`alert ${a.kind}`}>{body}</div>
  );
}

export default function Overview() {
  const f = useFilters(KEYS);
  const q = useDashboard<OverviewData>("/overview", { month: f.values.month });
  const status = useStatus();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const alerts = [...d.alerts].sort((a, b) => SEVERITY[a.kind] - SEVERITY[b.kind]);
          const worst = alerts.filter((a) => a.kind === "error" || a.kind === "warning");
          const s = d.sections;
          const outputs: FlowOut[] = d.alerts
            .filter((a) => a.area !== "none")
            .map((a) => ({ label: AREA_NAME[a.area] ?? a.area, value: a.title, to: AREA_LINK[a.area] ?? "/", hot: a.kind === "error" }));
          return (
            <>
              <PageHead
                title="Overview"
                meta={d.meta}
                lede={
                  worst.length ? (
                    <>
                      <span className="bad">{worst[0].title}</span>
                      {worst[1] ? <> and <strong>{worst[1].title}</strong></> : null}
                      {" "}need attention{f.values.month.length ? " in the selected months" : " this year"}.
                    </>
                  ) : (
                    "Nothing needs attention right now."
                  )
                }
              />
              <FilterBar active={f.active} onReset={f.reset}>
                <MonthFilter options={d.options.month} value={f.values.month} onChange={(v) => f.set("month", v)} />
                <span className="applied">Orders by PO date · dues and vendor orders are not month-filtered</span>
              </FilterBar>
              <Notices items={d.errors} />

              <div style={{ display: "grid", gap: 16 }}>
                <DataFlow sources={status.data?.sources} outputs={outputs} now={now} />
                <div className="alerts" data-n={alerts.length} data-reveal>
                  {alerts.map((a) => (
                    <AlertCard key={a.area + a.title} a={a} />
                  ))}
                </div>
              </div>

              {s.orders && (
                <Section title="Orders and receipts" sub="Order Status · PO Master, every PO line" right={<Link className="btn sm" to="/orders">Open orders</Link>}>
                  <KpiStrip kpis={s.orders.kpis} cols={5} lead={["pending"]} />
                  <div className="grid" style={{ marginTop: 16 }}>
                    <div className="span-7">
                      <Panel title="Ordered, received and pending by month" sub="₹, by PO date" right={<Legend items={s.orders.charts.monthly.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                        <Bars data={s.orders.charts.monthly} months money label="Ordered, received and pending value by month" />
                      </Panel>
                    </div>
                    <div className="span-5">
                      <Panel title="Delivery status" sub="PO lines">
                        <Split items={s.orders.charts.timing} unit="lines" colors={TIMING_COLORS} label="PO lines by delivery status" />
                      </Panel>
                    </div>
                    <div className="span-5">
                      <Panel title="Pending by vendor" sub="₹, most pending first" right={<Legend items={s.orders.charts.vendors.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
                        <HBars data={{ categories: s.orders.charts.vendors.categories, series: [...s.orders.charts.vendors.series].reverse() }} money label="Received and pending value per vendor" max={8} sortBy="Pending" />
                      </Panel>
                    </div>
                    <div className="span-7">
                      <Panel title="Overdue PO lines" sub={s.orders.overdue_total > 8 ? `Most late 8 of ${s.orders.overdue_total}` : `${s.orders.overdue_total} lines`} flush>
                        {s.orders.overdue_total ? <DataTable table={s.orders.tables.overdue} name="overview_overdue_lines" maxRows={8} titleCaseFirst={false} /> : <div className="state">No PO line is overdue.</div>}
                      </Panel>
                    </div>
                    <div className="span-12">
                      <Panel title="Vendors: pending and overdue" flush>
                        <DataTable table={s.orders.tables.vendors} name="overview_vendors" maxRows={10} />
                      </Panel>
                    </div>
                  </div>
                </Section>
              )}

              {s.dues && (
                <Section title="Supplier dues" sub={s.dues.title || "DUES PAYMENT SUPPLIERS"} right={<Link className="btn sm" to="/dues">Open dues</Link>}>
                  <Notices items={s.dues.notices} />
                  <KpiStrip kpis={s.dues.kpis} cols={4} lead={["overdue"]} />
                  <div className="grid" style={{ marginTop: 16 }}>
                    <div className="span-7">
                      <Panel title="Dues by supplier" flush>
                        <DataTable table={s.dues.tables.suppliers} name="overview_dues_suppliers" maxRows={8} />
                      </Panel>
                    </div>
                    <div className="span-5">
                      <Panel title="Ageing" sub="₹, by days past the due date">
                        <BarList items={s.dues.charts.ageing} money tone="neg" label="Dues by days overdue" share />
                      </Panel>
                    </div>
                  </div>
                </Section>
              )}

              {s.otv && (
                <Section title="Order to vendors" sub="Orders placed with vendors" right={<Link className="btn sm" to="/order-to-vendors">Open order to vendors</Link>}>
                  <KpiStrip kpis={s.otv.kpis} cols={Math.min(4, s.otv.kpis.length)} />
                  {(s.otv.charts.by_status.length > 0 || s.otv.charts.by_vendor.length > 0) && (
                    <div className="grid" style={{ marginTop: 16 }}>
                      {s.otv.charts.by_status.length > 0 && (
                        <div className="span-6">
                          <Panel title="By status" sub={s.otv.charts.money ? "₹" : "Rows"}>
                            <BarList items={s.otv.charts.by_status} money={s.otv.charts.money} unit={s.otv.charts.money ? "" : "rows"} label="Vendor orders by status" />
                          </Panel>
                        </div>
                      )}
                      {s.otv.charts.by_vendor.length > 0 && (
                        <div className="span-6">
                          <Panel title="By vendor" sub={s.otv.charts.money ? "₹" : "Rows"}>
                            <BarList items={s.otv.charts.by_vendor} money={s.otv.charts.money} unit={s.otv.charts.money ? "" : "rows"} label="Vendor orders by vendor" />
                          </Panel>
                        </div>
                      )}
                    </div>
                  )}
                </Section>
              )}
            </>
          );
        }}
      </PageState>
    </div>
  );
}

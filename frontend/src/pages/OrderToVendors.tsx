import { useDashboard } from "../api/hooks";
import type { OtvData } from "../api/types";
import { BarList } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { ExtraFilters } from "../components/ExtraFilters";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { EXTRA_KEYS, useFilters } from "../lib/filters";
import { fmtInt } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["tab", "vendor", "status", ...EXTRA_KEYS];

export default function OrderToVendors() {
  const f = useFilters(KEYS);
  const q = useDashboard<OtvData>("/order-to-vendors", { ...f.values, tab: f.values.tab[0] ?? "" });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const money = d.charts?.money;
          return (
            <>
              <PageHead
                title="Order to vendors"
                meta={d.meta}
                lede={d.empty ? "This tab has no rows." : <><strong>{fmtInt(d.rows_total)} rows</strong> on the {d.tab.trim()} tab{d.detected?.status ? `, grouped by ${d.detected.status.toLowerCase()}` : ""}.</>}
              />
              <FilterBar active={f.active} onReset={f.reset}>
                <MultiSelect label="Tab" options={d.tabs} value={f.values.tab} onChange={(v) => f.set("tab", v)} single allLabel={d.tab} pretty={(x) => x.trim()} />
                {d.options?.vendor && <MultiSelect label="Vendor" options={d.options.vendor} value={f.values.vendor} onChange={(v) => f.set("vendor", v)} />}
                {d.options?.status && <MultiSelect label="Status" options={d.options.status} value={f.values.status} onChange={(v) => f.set("status", v)} />}
                {d.detected && <span className="applied">Header found on row {d.detected.header_row}</span>}
                <ExtraFilters f={f} options={d.options} periodLabel={d.period_label} dateOf="order date" search="Search vendor, design, status…" />
              </FilterBar>
              <Notices items={d.notices} />
              {d.empty ? (
                <Empty title="No rows" />
              ) : (
                <>
                  <KpiStrip kpis={d.kpis} cols={Math.min(4, d.kpis.length)} />
                  {(d.charts.by_status.length > 0 || d.charts.by_vendor.length > 0) && (
                    <Section title="Breakdown" sub={money ? `₹ ${d.detected.amount?.toLowerCase()}` : "Rows"}>
                      <div className="grid">
                        {d.charts.by_status.length > 0 && (
                          <div className={d.charts.by_vendor.length ? "span-5" : "span-12"}>
                            <Panel title={`By ${d.detected.status?.toLowerCase() ?? "status"}`}>
                              <BarList items={d.charts.by_status} money={money} unit={money ? "" : "rows"} label="Rows by status" max={10} />
                            </Panel>
                          </div>
                        )}
                        {d.charts.by_vendor.length > 0 && (
                          <div className={d.charts.by_status.length ? "span-7" : "span-12"}>
                            <Panel title={`By ${d.detected.vendor?.toLowerCase() ?? "vendor"}`}>
                              <BarList items={d.charts.by_vendor} money={money} unit={money ? "" : "rows"} label="Rows by vendor" max={12} />
                            </Panel>
                          </div>
                        )}
                      </div>
                    </Section>
                  )}
                  <Section title="All rows" sub="As in the sheet, live">
                    <Panel flush>
                      <DataTable table={d.tables.rows} name="order_to_vendors" maxRows={25} titleCaseFirst={false} />
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

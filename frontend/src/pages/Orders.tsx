import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useDashboard } from "../api/hooks";
import type { HomeData, OrdersData } from "../api/types";
import { CloseCard, PERIODS, WrongList } from "../components/DailyClose";
import { DataTable } from "../components/DataTable";
import { FilterBar, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Panel } from "../components/ui";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

const KEYS = ["channel", "sales_person", "stage", "late", "range", "order"];
const asIs = (s: string) => s;

/** Summary: today's close and what is holding things up. Needs only /home, so it never waits for the full list. */
function Summary({ onAll }: { onAll: () => void }) {
  const q = useDashboard<HomeData>("/home", {});
  return (
    <PageState q={q}>
      {(h) => (
        <>
          <PageHead title="Orders" lede="Are today's orders done, and what is holding up the rest. Tap a cause to see the orders." meta={h.meta} />
          <CloseCard c={h.close} />
          <Panel title="What is holding things up" sub="Tap a cause to open every order behind it">
            <WrongList items={h.close.wrong} never={h.close.never_marked} />
          </Panel>
          <button type="button" className="show-all" onClick={onAll}>
            See every open order <ChevronRight aria-hidden="true" />
          </button>
        </>
      )}
    </PageState>
  );
}

/** The full list, with filters. Only fetched once someone asks for it. */
function Drilled({ onBack }: { onBack: () => void }) {
  const { values, set, reset, active } = useFilters(KEYS);
  const lateOnly = values.late[0] === "1";
  const range = values.range[0] ?? "";
  const order = values.order[0] ?? "newest";
  const q = useDashboard<OrdersData>("/orders", {
    channel: values.channel,
    sales_person: values.sales_person,
    stage: values.stage,
    late_only: lateOnly ? "true" : undefined,
    range,
    order,
  });
  return (
    <PageState q={q}>
      {(d) => (
        <>
          <PageHead title="Orders" lede="Every open order behind your selection." meta={d.meta} />
          <button type="button" className="show-all back" onClick={() => { reset(); onBack(); }}>
            <ChevronLeft aria-hidden="true" /> Back to summary
          </button>
          <FilterBar active={active} onReset={reset}>
            {PERIODS.map(([n, label]) => (
              <button key={n} type="button" className={`fbtn${range === n ? " is-set" : ""}`} aria-pressed={range === n} onClick={() => set("range", range === n ? [] : [n])}>
                <span className="k">{label}</span>
              </button>
            ))}
            <MultiSelect label="Waiting for" options={d.options.stage ?? []} value={values.stage} onChange={(v) => set("stage", v)} pretty={asIs} />
            <MultiSelect label="Sales person" options={d.options.sales_person ?? []} value={values.sales_person} onChange={(v) => set("sales_person", v)} />
            <MultiSelect label="Channel" options={d.options.channel ?? []} value={values.channel} onChange={(v) => set("channel", v)} />
            <button type="button" className="fbtn" onClick={() => set("order", order === "newest" ? ["oldest"] : [])} aria-label="Change order">
              <span className="k">{order === "newest" ? "Newest first ↓" : "Oldest first ↑"}</span>
            </button>
            <button type="button" className={`fbtn${lateOnly ? " is-set" : ""}`} aria-pressed={lateOnly} onClick={() => set("late", lateOnly ? [] : ["1"])}>
              <span className="k">Late only</span>
            </button>
          </FilterBar>
          <KpiStrip kpis={d.kpis} cols={3} />
          <Panel title="Orders" flush>
            {d.table.rows.length ? <DataTable table={d.table} name="flo-wing-orders" maxRows={25} titleCaseFirst={false} /> : <Empty title="No orders match">Nothing is waiting here right now.</Empty>}
          </Panel>
        </>
      )}
    </PageState>
  );
}

export default function Orders() {
  const { active } = useFilters(KEYS);
  const [all, setAll] = useState(false);
  return <div className="page">{active > 0 || all ? <Drilled onBack={() => setAll(false)} /> : <Summary onAll={() => setAll(true)} />}</div>;
}

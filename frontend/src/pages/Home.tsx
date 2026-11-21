import { ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard, useStatus } from "../api/hooks";
import type { Action, EnquiriesData, HomeData, PaymentsData } from "../api/types";
import { fmtKpi } from "../lib/format";
import { DataFlow, type FlowOut } from "../components/DataFlow";
import { Notices, Panel } from "../components/ui";
import { PageHead, PageState } from "./common";


type Stat = { label: string; value: string; hint?: string };

/** One card per sheet: a headline status, three numbers, and a link to its page. New sheets add one card. */
function SheetCard({ title, dept, to, tone, line, stats }: { title: string; dept: string; to: string; tone: "good" | "warn" | "bad"; line: string; stats: Stat[] }) {
  return (
    <Link to={to} className={`sheet-card ${tone}`}>
      <div className="sc-top">
        <span className="sc-dept">{dept}</span>
        <ChevronRight aria-hidden="true" />
      </div>
      <div className="sc-title">{title}</div>
      <div className="sc-line">
        <span className="dot" aria-hidden="true" />
        {line}
      </div>
      <dl className="sc-stats">
        {stats.map((x) => (
          <div key={x.label}>
            <dt>{x.label}</dt>
            <dd className="num">{x.value}</dd>
          </div>
        ))}
      </dl>
    </Link>
  );
}

const kv = (k: { value: number | string | null; format: never } | undefined) => {
  if (!k) return "—";
  const f = fmtKpi(k.value, k.format);
  return `${f.value}${f.unit ? ` ${f.unit}` : ""}`;
};

function actionLink(a: Action): string {
  const q = new URLSearchParams();
  if (a.stage === "Payments") {
    q.set("owner", a.who);
    return `/payments?${q}`;
  }
  if (a.stage === "Sales") q.set("sales_person", a.who);
  else q.set("stage", a.stage);
  return `/orders?${q}`;
}

/** One line per person who must act, worst first. Green lines confirm a stage owner is clear. */
function ActionList({ items }: { items: Action[] }) {
  return (
    <ul className="actions">
      {items.map((a, i) => (
        <li key={`${a.who}-${a.stage}-${i}`}>
          <Link to={actionLink(a)} className={`action ${a.tone}`}>
            <span className="dot" aria-label={a.tone === "bad" ? "Late" : a.tone === "warn" ? "Needs a look" : "On time"} />
            <span className="who">{a.who}</span>
            <span className="what">{a.what}</span>
            <span className="old">{a.oldest_days > 0 && a.tone !== "good" ? `oldest ${a.oldest_days} days` : ""}</span>
            <ChevronRight aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  const q = useDashboard<HomeData>("/home", {});
  const pay = useDashboard<PaymentsData>("/payments", {});
  const enq = useDashboard<EnquiriesData>("/enquiries", {});
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
          const c = d.close;
          const orderTone = c.backlog > 0 || (c.after_cutoff && c.pending > 0) ? "bad" : c.pending > 0 ? "warn" : "good";
          const late = d.kpis.find((k) => k.id === "late");
          const pk = (id: string) => pay.data?.kpis.find((k) => k.id === id);
          const stale = Number(pk("stale")?.value ?? 0);
          const ek = (id: string) => enq.data?.kpis.find((k) => k.id === id);
          const notPicked = Number(ek("notpicked")?.value ?? 0);
          return (
            <>
              <PageHead title="Today" lede="Every sheet at a glance. Tap a card to see what is behind it." meta={d.meta} />
              <Notices items={d.notices} />
              <div className="sheet-cards">
                <SheetCard
                  dept="CRM"
                  title="Orders"
                  to="/orders"
                  tone={orderTone}
                  line={c.pending === 0 && c.backlog === 0 ? "All bills done" : c.backlog > 0 ? `${c.backlog} left from earlier days` : `${c.pending} still to do today`}
                  stats={[
                    { label: "Done today", value: `${c.done} of ${c.received}` },
                    { label: "Earlier days", value: c.backlog === 0 ? "none" : String(c.backlog) },
                    { label: "Late", value: kv(late as never) },
                  ]}
                />
                {pay.data && (
                  <SheetCard
                    dept="CRM"
                    title="Payments"
                    to="/payments"
                    tone={stale > 0 ? "bad" : "good"}
                    line={stale > 0 ? `${stale} not followed up for 2+ days` : "All followed up"}
                    stats={[
                      { label: "Pending", value: kv(pk("pending") as never) },
                      { label: "Not followed up", value: kv(pk("stale") as never) },
                      { label: "Collected this month", value: kv(pk("collected") as never) },
                    ]}
                  />
                )}
                {enq.data && (
                  <SheetCard
                    dept="CRM"
                    title="Enquiries"
                    to="/enquiries"
                    tone={notPicked > 0 ? "warn" : "good"}
                    line={notPicked > 0 ? `${notPicked} not picked up yet` : "Every recent enquiry is picked up"}
                    stats={[
                      { label: "Today", value: kv(ek("today") as never) },
                      { label: "Open now", value: kv(ek("open") as never) },
                      { label: "Older than 30 days", value: kv(ek("old") as never) },
                    ]}
                  />
                )}
              </div>
              <div className="home-flow">
                <DataFlow
                  sources={status.data?.sources}
                  now={now}
                  outputs={d.actions
                    .filter((a) => a.tone !== "good")
                    .slice(0, 5)
                    .map((a): FlowOut => ({ label: a.who, value: a.what, to: actionLink(a), hot: a.tone === "bad" }))}
                />
              </div>
              <Panel title="Needs action" sub="Who must act, worst first. Tap a line to see the orders behind it.">
                <ActionList items={d.actions} />
              </Panel>
            </>
          );
        }}
      </PageState>
    </div>
  );
}

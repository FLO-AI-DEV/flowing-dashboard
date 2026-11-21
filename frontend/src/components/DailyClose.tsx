import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { useDashboard } from "../api/hooks";
import type { CauseData, DailyClose, Wrong } from "../api/types";
import { DataTable } from "./DataTable";
import { SendPanel, useNudgeWho } from "./SendPanel";
import { Empty } from "./ui";

const OLD_DAYS = 45;

/** The team's daily close: of today's orders, how many are done; what is left from earlier days. */
export function CloseCard({ c }: { c: DailyClose }) {
  const pct = c.received ? Math.round((100 * c.done) / c.received) : 100;
  const clear = c.pending === 0 && c.backlog === 0;
  const tone = clear ? "good" : c.after_cutoff || c.backlog > 0 ? "bad" : "warn";
  const line = clear
    ? "Everything is done. Fresh start tomorrow."
    : c.after_cutoff
      ? `${c.pending} of today's orders were not done by ${c.cutoff}${c.backlog ? `, and ${c.backlog} are left from earlier days` : ""}.`
      : `${c.pending} of today's orders still to do before ${c.cutoff}${c.backlog ? `. ${c.backlog} are left from earlier days` : ""}.`;
  return (
    <div className={`close ${tone}`}>
      <div className="close-head">
        <span className="close-big num">
          {c.done}
          <small> of {c.received} done today</small>
        </span>
        <span className="close-line">{line}</span>
      </div>
      <div className="close-bar" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="close-channels">
        {c.by_channel.map((ch) => (
          <span key={ch.channel}>
            {ch.channel} <b className="num">{ch.done}/{ch.received}</b>
          </span>
        ))}
        <span className="grow" />
        <span className={c.backlog ? "bad" : "good"}>
          Earlier days: <b className="num">{c.backlog === 0 ? "none left" : c.backlog}</b>
        </span>
      </div>
    </div>
  );
}

/** The rows behind one cause. Only fetched once the cause is opened. */
export const PERIODS: [string, string][] = [["today", "Today"], ["week", "Yesterday – 7 days"], ["month", "8 – 30 days"], ["older", "Older than 30 days"]];

function CauseRows({ k }: { k: Wrong["key"] }) {
  const [range, setRange] = useState("");   // nothing chosen = every order counted above
  const [order, setOrder] = useState("oldest");
  const q = useDashboard<CauseData>(`/cause/${k}`, { range, order });
  const who = useNudgeWho();
  const names = who.data?.enabled ? who.data.who[k] ?? [] : [];
  return (
    <>
      {names.length > 0 && <SendPanel cause={k} names={names} testMode={!!who.data?.test_mode} startScope={range && range !== "" ? range : "today"} />}
      <div className="cause-periods" role="group" aria-label="Show orders from">
        {PERIODS.map(([n, label]) => (
          <button key={n} type="button" className={`fbtn${range === n ? " is-set" : ""}`} aria-pressed={range === n} onClick={() => setRange(range === n ? "" : n)}>
            <span className="k">{label}</span>
          </button>
        ))}
        <button type="button" className="fbtn" onClick={() => setOrder(order === "oldest" ? "newest" : "oldest")} aria-label="Change order">
          <span className="k">{order === "oldest" ? "Oldest first ↑" : "Newest first ↓"}</span>
        </button>
        {q.data && <span className="cause-count num">{q.data.count}{range ? ` of ${q.data.total}` : ""} orders</span>}
      </div>
      {!q.data ? (
        <p className="wrong-note">Loading…</p>
      ) : !q.data.table.rows.length ? (
        <p className="wrong-note">No orders in this period.</p>
      ) : (
        <div className={q.isPlaceholderData ? "updating" : undefined}>
          <DataTable table={q.data.table} name={`flo-wing-${k}`} maxRows={15} titleCaseFirst={false} />
        </div>
      )}
    </>
  );
}

/** What is holding things up: one line per cause with counts only. Opening a cause shows every order behind it,
 *  with just the columns that matter for that cause. */
export function WrongList({ items, never }: { items: DailyClose["wrong"]; never: number }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!items.length) return <Empty title="Nothing is stuck">Every order up to today is done.</Empty>;
  return (
    <div className="wrong">
      {items.map((w) => {
        const isOpen = open === w.key;
        return (
          <div key={w.key} className={`wrong-item${isOpen ? " is-open" : ""}`}>
            <button type="button" className="wrong-top" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : w.key)}>
              <span className="wrong-label">{w.label}</span>
              <span className="wrong-count num">
                {w.backlog > 0 && <b>{w.backlog} from earlier days</b>}
                {w.backlog > 0 && w.today > 0 && " · "}
                {w.today > 0 && <span>{w.today} today</span>}
                {w.oldest_days > 0 && <span> · oldest {w.oldest_days} days</span>}
              </span>
              <span className="wrong-who">{w.who}</span>
              <ChevronRight className="chev" aria-hidden="true" />
            </button>
            {isOpen && (
              <div className="wrong-rows">
                <CauseRows k={w.key} />
              </div>
            )}
          </div>
        );
      })}
      {never > 0 && (
        <p className="wrong-note">
          {never.toLocaleString()} older orders (over {OLD_DAYS} days) were never marked billed in the sheet. They are left out here.
        </p>
      )}
    </div>
  );
}

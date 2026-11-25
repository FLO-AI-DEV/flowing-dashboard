import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { useDashboard } from "../api/hooks";
import type { CauseData, EnquiriesData, EnquiryCategories } from "../api/types";
import { PERIODS } from "../components/DailyClose";
import { DataTable } from "../components/DataTable";
import { SendPanel, useNudgeWho } from "../components/SendPanel";
import { Empty, KpiStrip, Panel } from "../components/ui";
import { PageHead, PageState } from "./common";

const STATUSES = ["Pending", "In process", "Not marked yet"];

const VIEW: Record<string, string> = { today: "v-today", open: "all", old: "v-old", notpicked: "v-notpicked" };

function Rows({ k }: { k: string }) {
  const [range, setRange] = useState("");
  const [order, setOrder] = useState("oldest");
  const [status, setStatus] = useState("");
  const q = useDashboard<CauseData>(`/enquiries/cause/${k}`, { range, order, status });
  const who = useNudgeWho();
  const names = who.data?.enabled ? who.data.who["enquiry"] ?? [] : [];
  return (
    <>
      {names.length > 0 && !k.startsWith("v-") && <SendPanel cause="enquiry" group={k} noun="enquiry" names={names} testMode={!!who.data?.test_mode} startScope={range || "older"} />}
      <div className="cause-periods" role="group" aria-label="Show enquiries from">
        {PERIODS.map(([n, label]) => (
          <button key={n} type="button" className={`fbtn${range === n ? " is-set" : ""}`} aria-pressed={range === n} onClick={() => setRange(range === n ? "" : n)}>
            <span className="k">{label}</span>
          </button>
        ))}
        {STATUSES.map((s) => (
          <button key={s} type="button" className={`fbtn${status === s ? " is-set" : ""}`} aria-pressed={status === s} onClick={() => setStatus(status === s ? "" : s)}>
            <span className="k">{s}</span>
          </button>
        ))}
        <button type="button" className="fbtn" onClick={() => setOrder(order === "oldest" ? "newest" : "oldest")} aria-label="Change order">
          <span className="k">{order === "oldest" ? "Oldest first ↑" : "Newest first ↓"}</span>
        </button>
        {q.data && <span className="cause-count num">{q.data.count}{range || status ? ` of ${q.data.total}` : ""} enquiries</span>}
      </div>
      {!q.data ? (
        <p className="wrong-note">Loading…</p>
      ) : !q.data.table.rows.length ? (
        <p className="wrong-note">No enquiries in this selection.</p>
      ) : (
        <div className={q.isPlaceholderData ? "updating" : undefined}>
          <DataTable table={q.data.table} name={`flo-wing-enquiries-${k}`} maxRows={15} titleCaseFirst={false} />
        </div>
      )}
    </>
  );
}

/** The category column for each sheet tab (the team's own choice where filled, a best guess elsewhere), to paste into
 *  the sheet by someone who can edit it. Copies one value per line, which Google Sheets spreads down the rows. */
function CategoryExport() {
  const [on, setOn] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const q = useDashboard<EnquiryCategories>("/enquiries/categories", {}, on);
  const copy = async (label: string, values: string[]) => {
    try {
      await navigator.clipboard.writeText(values.join("\n"));
      setDone(label);
    } catch {
      setDone(null);
    }
  };
  return (
    <div className="wrong-note">
      {!on ? (
        <button type="button" className="fbtn" onClick={() => setOn(true)}>
          <span className="k">Get the category column to paste into the sheet</span>
        </button>
      ) : !q.data ? (
        "Preparing…"
      ) : (
        <>
          {q.data.tabs.map((t) => (
            <button key={t.tab} type="button" className="fbtn" onClick={() => copy(t.label, t.values)}>
              <span className="k">Copy {t.label}: {t.values.length} rows</span>
            </button>
          ))}
          <p>
            Paste each one into that tab's CATEGORY column, starting at the row shown: {q.data.tabs.map((t) => `${t.label} ${t.column ?? "?"}${t.first_row}`).join(" · ")}.
            Categories the team already chose are kept.
          </p>
          {done && <p className="send-ok">{done} copied.</p>}
        </>
      )}
    </div>
  );
}

export default function Enquiries() {
  const q = useDashboard<EnquiriesData>("/enquiries", {});
  const [open, setOpen] = useState<string | null>(null);
  const [pick, setPick] = useState<string>("");
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead title="Enquiries" lede="What customers asked about, and what is still open. Shown exactly as the customer-care team records it." meta={d.meta} />
            <KpiStrip kpis={d.kpis} cols={3} onPick={(id) => setPick(pick === id ? "" : id)} picked={pick} />
            {pick && VIEW[pick] && (
              <Panel title={d.kpis.find((k) => k.id === pick)?.label ?? ""} sub="Click the same box again to close this list.">
                <Rows key={pick} k={VIEW[pick]} />
              </Panel>
            )}
            <Panel title="Today" sub="Enquiries received today, by the status written in the sheet">
              <p className="wrong-note">
                {d.today.received === 0
                  ? "No enquiries recorded today yet."
                  : `${d.today.received} today: ` + Object.entries(d.today.status).filter(([, n]) => n > 0).map(([s, n]) => `${n} ${s.toLowerCase()}`).join(" · ")}
              </p>
              <p className="wrong-note">
                Open by source: {d.by_source.map((s) => `${s.source} ${s.open} of ${s.total}`).join(" · ")}
              </p>
            </Panel>
            {d.auto_categorised > 0 && (
              <p className="wrong-note">
                {d.auto_categorised} open enquiries have no category in the sheet yet, so the dashboard has guessed one from what was typed. A category the team picks always wins.
              </p>
            )}
            <CategoryExport />
            <Panel title="What is still open" sub="Grouped by what the enquiry is about. Tap a group to see every enquiry.">
              {!d.causes.length ? (
                <Empty title="Nothing is open">Every enquiry is marked Solved.</Empty>
              ) : (
                <div className="wrong">
                  {d.causes.map((c) => {
                    const isOpen = open === c.key;
                    return (
                      <div key={c.key} className={`wrong-item${isOpen ? " is-open" : ""}`}>
                        <button type="button" className="wrong-top" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : c.key)}>
                          <span className="wrong-label">{c.label}</span>
                          <span className="wrong-count num">
                            <b>{c.open} open</b>
                            {c.today > 0 && <span> · {c.today} today</span>}
                            {c.older > 0 && <span> · {c.older} older than 30 days</span>}
                            <span> · oldest {c.oldest_days} days</span>
                          </span>
                          <ChevronRight className="chev" aria-hidden="true" />
                        </button>
                        {isOpen && (
                          <div className="wrong-rows">
                            <Rows k={c.key} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          </>
        )}
      </PageState>
    </div>
  );
}

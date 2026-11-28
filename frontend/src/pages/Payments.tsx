import { ChevronRight, Phone } from "lucide-react";
import { useState } from "react";
import { useDashboard } from "../api/hooks";
import type { PoOverview, PoPerson, PoPersonStat, PoReport } from "../api/types";
import { SendAll } from "../components/SendAll";
import { SendPanel, useNudgeWho } from "../components/SendPanel";
import { Empty, Notices, Panel } from "../components/ui";
import { inrShort } from "../lib/format";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

type Role = "crm" | "sp";
type Focus = "" | "stale";
const SCOPES: [string, string][] = [["todo", "To do today"], ["stale", "Follow-up due"], ["escalated", "Escalated (8+ days)"], ["all", "All open"]];
const BUCKET_TONE: Record<string, string> = { not_sent: "bad", past_limit: "bad", overdue: "bad", due_soon: "warn", on_track: "good" };
const AGE_CHIPS: [keyof PoPersonStat & string, string, string][] = [
  ["on_track", "on_track", "0–4 days"], ["due_soon", "due_soon", "5–7 days"], ["overdue", "overdue", "8–10 days"],
  ["past_limit", "past_limit", "11+ days"], ["not_sent", "not_sent", "PO not sent"],
];


/** One person's open POs: client, amount, how long, the last note, and what to do. */
function PersonList({ role, name, window, range, bucket, order, focus, boxLabel }: { role: Role; name: string; window: string; range: string; bucket: string; order: string; focus: Focus; boxLabel: string }) {
  const q = useDashboard<PoPerson>("/po/person", { role, name, window, range, bucket, order, focus });
  const who = useNudgeWho();
  if (!q.data) return <p className="wrong-note">Loading…</p>;
  const d = q.data;
  const cols = d.table.columns.map((c) => c.key);
  const ix = (k: string) => cols.indexOf(k);
  const startScope = focus === "stale" ? "stale" : bucket ? `b:${bucket}` : role === "crm" ? "todo" : "all";
  const scopes: [string, string][] = bucket
    ? [[`b:${bucket}`, `These ${d.count} POs (${boxLabel})`], ...SCOPES]
    : SCOPES;
  return (
    <div className={q.isPlaceholderData ? "updating" : undefined}>
      {who.data?.enabled && <SendPanel cause="payment" group={`${role}:${name}`} noun="PO" names={[d.name]} testMode={!!who.data.test_mode} startScope={startScope} scopes={scopes} />}
      {role === "crm" && d.progress.total > 0 && (
        <div className="po-progress" aria-label="Today's calls">
          <div className="po-bar"><span style={{ width: `${Math.round((d.progress.done / d.progress.total) * 100)}%` }} /></div>
          <b className="num">{d.progress.done} of {d.progress.total}</b> done today
          {d.call_clients.length > 0 && <> · <b className="num">{d.call_clients.length}</b> client{d.call_clients.length === 1 ? "" : "s"} to call (one call covers all of a client's POs)</>}
        </div>
      )}
      {role === "crm" && d.call_clients.length > 0 && (
        <details className="po-more">
          <summary>Call list by client ({d.call_clients.length})</summary>
          <ul className="po-clients">
            {d.call_clients.map((c) => (
              <li key={c.client}><b>{c.client}</b> <span className="num">{inrShort(c.amount)}</span> · {c.pos} PO{c.pos === 1 ? "" : "s"} ({c.so.join(", ")}) · oldest day {c.day}</li>
            ))}
          </ul>
        </details>
      )}
      {!d.table.rows.length ? (
        <Empty title="Nothing here">No POs match this filter for {d.name}.</Empty>
      ) : (
        <ul className="po-list">
          {d.table.rows.map((r, i) => {
            const state = d.table.states[i];
            const tone = state === "late" ? "bad" : state === "due" ? "warn" : "good";
            const phone = String(r[ix("Phone")] ?? "").split(/\s{2,}|\//)[0].replace(/[^\d+]/g, "");
            const last = String(r[ix("Last note")] ?? "");
            return (
              <li key={i} className={`po-row tone-${tone}${d.table.done[i] ? " is-done" : ""}`}>
                <div className="po-main">
                  <b className="po-client">{String(r[ix("Client")])}</b>
                  <span className="po-so">{String(r[ix("PO")])}</span>
                  <span className="po-amt num">{inrShort(Number(r[ix("Amount ₹")]))}</span>
                  <span className={`po-day tone-${tone}`}>Day {String(r[ix("Day")])}</span>
                  <span className={`po-timer tone-${tone}`}>{String(r[ix("Timer")])}</span>
                  {String(r[ix("Level")] ?? "") && <span className={`po-level lv-${String(r[ix("Level")])}`}>{String(r[ix("Level")])}</span>}
                </div>
                <div className="po-last">
                  Follow-ups: <b>{String(r[ix("Calls")] ?? 0)}</b> · next is <b>#{String(r[ix("Next")] ?? "").replace("#", "")}</b>{Number(r[ix("Missed")] ?? 0) > 0 && <span className="po-missed"> · {String(r[ix("Missed")])} daily call{Number(r[ix("Missed")]) === 1 ? "" : "s"} missed</span>} · last follow-up: <b>{String(r[ix("Last follow-up")])}</b>{last ? <> · “{last}”</> : " · never followed up"}
                  {String(r[ix("Promised")] ?? "") && <> · client promised <b>{String(r[ix("Promised")])}</b></>}
                  {Number(r[ix("Part paid ₹")] ?? 0) > 0 && <> · part paid <b>{inrShort(Number(r[ix("Part paid ₹")]))}</b> (on hold)</>}
                </div>
                <div className="po-sub">
                  {d.table.done[i] ? "Followed up today · " : ""}{String(r[ix("What to do")])} · {role === "crm" ? "sold by " : "called by "}<b>{String(r[ix(role === "crm" ? "Sales person" : "CRM member")])}</b>
                  {phone.length >= 8 && (
                    <a className="po-call" href={`tel:${phone}`}>
                      <Phone aria-hidden="true" /> {phone}
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** A one-screen performance report for one person, with a button to copy it as a WhatsApp-ready summary. */
function PersonReport({ role, name, window }: { role: Role; name: string; window: string }) {
  const q = useDashboard<PoReport>("/po/report", { role, name, window });
  const [copied, setCopied] = useState(false);
  if (!q.data) return <p className="wrong-note">Preparing the report…</p>;
  const r = q.data;
  const copy = async () => {
    try { await navigator.clipboard.writeText(r.summary); setCopied(true); } catch { setCopied(false); }
  };
  return (
    <div className="po-report">
      <div className="po-rep-head">
        <b>{r.name}: PO report</b>
        <span className="po-rep-actions">
          <button type="button" className="fbtn" onClick={copy}><span className="k">{copied ? "Copied" : "Copy summary"}</span></button>
          <button type="button" className="fbtn" onClick={() => globalThis.print()}><span className="k">Print</span></button>
        </span>
      </div>
      <div className="po-rep-kpis">
        <div><b className="num">{r.open.count}</b><span>open POs</span><em className="num">{inrShort(r.open.amount)}</em></div>
        <div className={r.late.count ? "bad" : ""}><b className="num">{r.late.count}</b><span>overdue or past limit</span><em className="num">{inrShort(r.late.amount)}</em></div>
        <div><b className="num">{r.paid_pct}%</b><span>paid (by value)</span><em className="num">{r.paid.count} POs · {inrShort(r.paid.amount)}</em></div>
        <div><b className="num">{r.days_to_pay == null ? "—" : Math.round(r.days_to_pay)}</b><span>days to pay (median)</span><em>{r.cancelled.count} cancelled</em></div>
      </div>
      <div className="po-rep-grid">
        <section>
          <h4>Unpaid POs by age</h4>
          {r.ages.map((a) => (
            <div key={a.key} className={`po-rep-row${a.key === "past_limit" || a.key === "overdue" ? " bad" : ""}`}>
              <span>{a.label}</span><b className="num">{a.count}</b><em className="num">{inrShort(a.amount)}</em>
            </div>
          ))}
        </section>
        <section>
          <h4>Last 30 days</h4>
          <div className="po-rep-row"><span>POs sent</span><b className="num">{r.recent.sent}</b><em className="num">{inrShort(r.recent.sent_amount)}</em></div>
          <div className="po-rep-row"><span>Paid</span><b className="num">{r.recent.paid}</b><em className="num">{inrShort(r.recent.paid_amount)} · {r.recent.paid_pct}%</em></div>
          <h4>Follow-up</h4>
          <div className="po-rep-row"><span>Follow-up due today</span><b className="num">{r.followup.not_followed_up}</b><em /></div>
          <div className="po-rep-row"><span>Never called</span><b className="num">{r.followup.never_called}</b><em /></div>
          <div className="po-rep-row"><span>Average calls per client (all POs)</span><b className="num">{r.followup.calls_per_client}</b><em>{r.followup.calls_per_po} per PO</em></div>
          <div className="po-rep-row"><span>Follow-ups per open PO</span><b className="num">{r.followup.avg_calls}</b><em /></div>
          {r.followup.on_hold > 0 && <div className="po-rep-row"><span>On hold (part payment)</span><b className="num">{r.followup.on_hold}</b><em /></div>}
        </section>
      </div>
      <div className="po-rep-grid">
        <section>
          <h4>Cancellations</h4>
          <div className={`po-rep-row${r.cancellations.count ? " bad" : ""}`}><span>Cancelled POs</span><b className="num">{r.cancellations.count}</b><em className="num">{inrShort(r.cancellations.amount)} · {r.cancellations.rate_pct}% of {r.cancellations.pos}</em></div>
          <div className={`po-rep-row${r.cancellations.at_risk.count ? " bad" : ""}`}><span>At risk (11+ days, unpaid)</span><b className="num">{r.cancellations.at_risk.count}</b><em className="num">{inrShort(r.cancellations.at_risk.amount)}</em></div>
          {r.cancellations.recent.map((c) => (
            <div key={c.so} className="po-rep-row wide"><span><b>{c.client}</b> <i className="po-so">{c.so}</i></span><b className="num">{inrShort(c.amount)}</b><em>made {c.made}{c.note ? ` · “${c.note}”` : ""}</em></div>
          ))}
        </section>
        <section>
          <h4>Daily follow-up discipline</h4>
          <div className={`po-rep-row${r.discipline.compliance_pct < 80 ? " bad" : ""}`}><span>Daily calls made</span><b className="num">{r.discipline.compliance_pct}%</b><em className="num">{r.discipline.done} of {r.discipline.expected}</em></div>
          <div className="po-rep-row"><span>Missed days</span><b className="num">{r.discipline.missed}</b><em>Sundays not counted</em></div>
          <div className="po-rep-row"><span>Escalated: 5–7 · 8–10 · 11+ days</span><b className="num">{r.discipline.escalated.l1} · {r.discipline.escalated.l2} · {r.discipline.escalated.l3}</b><em /></div>
          {r.discipline.worst.map((w) => (
            <div key={w.so} className="po-rep-row wide"><span><b>{w.client}</b> <i className="po-so">{w.so}</i></span><b className="num">{w.missed} missed</b><em>of {w.expected} daily calls{w.state !== "pending" ? ` · ${w.state}` : ""}</em></div>
          ))}
        </section>
      </div>
      {r.worst.length > 0 && (
        <section>
          <h4>Most overdue POs</h4>
          {r.worst.map((w) => (
            <div key={w.so} className="po-rep-row wide">
              <span><b>{w.client}</b> <i className="po-so">{w.so}</i></span>
              <b className="num">{inrShort(w.amount)}</b>
              <em>Day {w.day} · called {w.calls}×{w.note ? ` · “${w.note}”` : ""}</em>
            </div>
          ))}
        </section>
      )}
      {r.split.length > 0 && (
        <section>
          <h4>{r.role === "sp" ? "Who is calling their clients" : "Whose clients they call"} ({r.split_label.toLowerCase()})</h4>
          {r.split.map((x) => (
            <div key={x.name} className="po-rep-row wide">
              <span><b>{x.name}</b></span><b className="num">{x.open} open · {inrShort(x.amount)}</b>
              <em>{x.late} late · {x.stale} not followed up</em>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

/** One row per person with the few numbers that matter. Click the name for their POs, or click "not followed up" for exactly those POs. */
function People({ role, people, window, range, bucket, order, boxLabel, first }: { role: Role; people: PoPersonStat[]; window: string; range: string; bucket: string; order: string; boxLabel: string; first?: string }) {
  const [open, setOpen] = useState<{ name: string; focus: Focus; box: string } | null>(first ? { name: first, focus: "", box: "" } : null);
  const [rep, setRep] = useState<string | null>(null);
  const toggle = (name: string, focus: Focus, box = "") => setOpen(open?.name === name && open.focus === focus && open.box === box ? null : { name, focus, box });
  return (
    <div className="wrong">
      {people.map((p) => {
        const isOpen = open?.name === p.name;
        const risk = p.past_limit;
        return (
          <div key={p.name} className={`wrong-item${isOpen ? " is-open" : ""}`}>
            <div className="po-person">
              <button type="button" className="wrong-top" aria-expanded={isOpen} onClick={() => toggle(p.name, "")}>
                <span className="wrong-label">{p.name}</span>
                <ChevronRight className="chev" aria-hidden="true" />
              </button>
              <div className="po-stats">
                {role === "crm" ? (
                  <>
                    <span className="po-stat"><b className="num">{p.todo}</b> to call today</span>
                    {AGE_CHIPS.map(([k, b, label]) => (
                      <button key={b} type="button" className={`po-stat link${(b === "past_limit" || b === "overdue" || b === "not_sent") && p[k] ? " bad" : ""}`} disabled={!p[k]} aria-pressed={isOpen && open?.box === b} onClick={() => toggle(p.name, "", b)}>
                        <b className="num">{p[k] as number}</b> {label}
                      </button>
                    ))}
                  </>
                ) : (
                  <span className="po-stat"><b className="num">{p.open}</b> open · {inrShort(p.open_amt)}</span>
                )}
                <button type="button" className={`po-stat link${p.stale ? " bad" : ""}`} disabled={!p.stale} aria-pressed={isOpen && open?.focus === "stale" && !open?.box} onClick={() => toggle(p.name, "stale")}>
                  <b className="num">{p.stale}</b> follow-up due
                </button>
                <span className={`po-stat${p.compliance < 80 ? " bad" : ""}`} title="Daily calls made in the first 7 days, Sundays skipped"><b className="num">{Math.round(p.compliance)}%</b> daily calls made{p.fu_missed ? ` (${p.fu_missed} missed)` : ""}</span>
                {role === "sp" && <span className={`po-stat${p.cancelled ? " bad" : ""}`}><b className="num">{p.cancel_pct.toFixed(1)}%</b> cancelled ({p.cancelled} POs · {inrShort(p.cancelled_amt)})</span>}
                {role === "sp" && <span className={`po-stat${risk ? " bad" : ""}`}><b className="num">{risk}</b> at risk (11+ days)</span>}
                {role === "sp" && <span className="po-stat"><b className="num">{Math.round(p.paid_pct)}%</b> paid</span>}
                <button type="button" className="fbtn po-rep-btn" aria-pressed={rep === p.name} onClick={() => setRep(rep === p.name ? null : p.name)}>
                  <span className="k">{rep === p.name ? "Hide report" : "View report"}</span>
                </button>
              </div>
            </div>
            {rep === p.name && <PersonReport role={role} name={p.name} window={window} />}
            {isOpen && (
              <div className="wrong-rows">
                <PersonList role={role} name={p.name} window={window} range={range} bucket={open!.box || bucket} order={order} focus={open!.focus} boxLabel={open!.box ? (AGE_CHIPS.find((c) => c[1] === open!.box)?.[2] ?? "") : boxLabel} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Every employee side by side: one table to compare, print or copy. */
function TeamReport({ people, role }: { people: PoPersonStat[]; role: Role }) {
  const [copied, setCopied] = useState(false);
  const text = people.map((p) => `${p.name}: open ${p.open} (${inrShort(p.open_amt)}), 8+ days ${p.overdue + p.past_limit}, cancelled ${p.cancelled} (${p.cancel_pct.toFixed(1)}%), avg calls per client ${p.calls_per_client.toFixed(1)}, daily calls ${Math.round(p.compliance)}%, paid ${Math.round(p.paid_pct)}%`).join("\n");
  return (
    <details className="po-more">
      <summary>Team report: all {role === "crm" ? "callers" : "sales people"} side by side</summary>
      <div className="po-rep-head">
        <span />
        <span className="po-rep-actions">
          <button type="button" className="fbtn" onClick={async () => { try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); } }}><span className="k">{copied ? "Copied" : "Copy"}</span></button>
          <button type="button" className="fbtn" onClick={() => globalThis.print()}><span className="k">Print</span></button>
        </span>
      </div>
      <table className="po-team-table">
        <thead><tr><th>Name</th><th>Open</th><th>Open ₹</th><th>8+ days</th><th>Cancelled</th><th>Cancel rate</th><th>Avg calls / client</th><th>Daily calls made</th><th>Missed days</th><th>Paid %</th></tr></thead>
        <tbody>
          {people.map((p) => (
            <tr key={p.name}>
              <td><b>{p.name}</b></td><td className="num">{p.open}</td><td className="num">{inrShort(p.open_amt)}</td>
              <td className={`num${p.overdue + p.past_limit ? " bad" : ""}`}>{p.overdue + p.past_limit}</td>
              <td className="num">{p.cancelled} · {inrShort(p.cancelled_amt)}</td><td className={`num${p.cancel_pct >= 10 ? " bad" : ""}`}>{p.cancel_pct.toFixed(1)}%</td><td className="num">{p.calls_per_client.toFixed(1)}</td>
              <td className={`num${p.compliance < 80 ? " bad" : ""}`}>{Math.round(p.compliance)}%</td>
              <td className="num">{p.fu_missed}</td><td className="num">{Math.round(p.paid_pct)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** "Message everyone" when WhatsApp sending is set up; otherwise a short note on how to switch it on. */
function MessageAll({ startRole }: { startRole: Role }) {
  const who = useNudgeWho();
  if (!who.data) return null;
  if (!who.data.enabled) {
    return <span className="send-off" title="Add NUDGE_SHEET_ID to backend/.env and restart">Messages are off: NUDGE_SHEET_ID is not set{who.data.error ? ` (${who.data.error})` : ""}</span>;
  }
  return <SendAll testMode={!!who.data.test_mode} startRole={startRole} />;
}

const KEYS = ["owner", "sales_person", "window", "view", "range", "bucket", "order"];

export default function Payments() {
  const { values, set } = useFilters(KEYS);
  const window = values.window[0] || "60d";
  const view: Role = values.view[0] === "sp" ? "sp" : "crm";
  const range = "";   // the age boxes replace the old "sent today / 1–7 days" buttons
  const bucket = values.bucket[0] || "";
  const order = values.order[0] === "newest" ? "newest" : "oldest";
  const q = useDashboard<PoOverview>("/po", { window, range, bucket });
  const link = values.owner[0] || values.sales_person[0];
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const paid = d.kpis.find((k) => k.id === "paid_today");
          const boxLabel = d.buckets.find((b) => b.key === bucket)?.label ?? "";
          
          return (
            <>
              <PageHead title="PO follow-up" lede={`Payment is due ${d.rules.due_days} days after the PO goes to the client, ${d.rules.limit_days} at most.`} meta={d.meta} />
              <Notices items={d.notices.filter((n) => n.kind !== "info")} />
              <Panel title="How long POs have waited" sub={`${d.buckets.filter((b) => b.key !== "not_sent").reduce((n, b) => n + b.count, 0)} open POs. Click a box to see only those.${paid ? ` Paid today: ${paid.value} (${paid.hint}).` : ""}`}>
                <div className="po-buckets">
                  {d.buckets.map((b) => (
                    <button key={b.key} type="button" className={`po-bucket tone-${BUCKET_TONE[b.key]}${bucket === b.key ? " is-set" : ""}`} aria-pressed={bucket === b.key} onClick={() => set("bucket", bucket === b.key ? [] : [b.key])}>
                      <b className="num">{b.count}</b>
                      <span>{b.label}</span>
                      <em className="num">{inrShort(b.amount)}</em>
                    </button>
                  ))}
                </div>
                <details className="po-more" open={window !== "60d"}>
                  <summary>History{window !== "60d" ? " (changed)" : ""}</summary>
                  <div className="cause-periods" role="group" aria-label="Paid and cancelled history">
                    {d.windows.map((w) => (
                      <button key={w.key} type="button" className={`fbtn${window === w.key ? " is-set" : ""}`} aria-pressed={window === w.key} onClick={() => set("window", w.key === "60d" ? [] : [w.key])}>
                        <span className="k">{w.label}</span>
                      </button>
                    ))}
                    <span className="cause-count num">History read from {d.window.start}, plus {d.window.older_open} older open POs</span>
                  </div>
                </details>
                {bucket && (
                  <p className="wrong-note">
                    Showing: {boxLabel}.{" "}
                    <button type="button" className="btn ghost sm" onClick={() => { set("bucket", []); }}>Show all</button>
                  </p>
                )}
              </Panel>
              <Panel
                title={view === "crm" ? "Calling team" : "Sales people"}
                sub={view === "crm" ? "Click a name for their POs. Click “not followed up” to see exactly those POs and their last note." : "Click a name for their POs. Click “not followed up” to see exactly those POs and their last note."}
                right={
                  <div className="cause-periods" style={{ padding: 0 }} role="group" aria-label="Who">
                    <MessageAll startRole={view} />
                    <button type="button" className={`fbtn${view === "crm" ? " is-set" : ""}`} aria-pressed={view === "crm"} onClick={() => set("view", [])}><span className="k">Calling team</span></button>
                    <button type="button" className={`fbtn${view === "sp" ? " is-set" : ""}`} aria-pressed={view === "sp"} onClick={() => set("view", ["sp"])}><span className="k">Sales people</span></button>
                    <button type="button" className="fbtn" onClick={() => set("order", order === "oldest" ? ["newest"] : [])}><span className="k">{order === "oldest" ? "Oldest first ↑" : "Newest first ↓"}</span></button>
                  </div>
                }
              >
                {d.people[view].length > 0 && <TeamReport people={d.people[view]} role={view} />}
                {d.people[view].length ? (
                  <People key={`${view}-${window}-${range}-${bucket}-${link ?? ""}`} role={view} people={d.people[view]} window={window} range={range} bucket={bucket} order={order} boxLabel={boxLabel} first={link ? d.people[view].find((p) => p.name.toLowerCase() === link.toLowerCase())?.name : undefined} />
                ) : (
                  <Empty />
                )}
              </Panel>
              {d.notices.some((n) => n.kind === "info") && (
                <details className="po-more">
                  <summary>Data checks ({d.notices.filter((n) => n.kind === "info").length})</summary>
                  <Notices items={d.notices.filter((n) => n.kind === "info")} />
                </details>
              )}
            </>
          );
        }}
      </PageState>
    </div>
  );
}

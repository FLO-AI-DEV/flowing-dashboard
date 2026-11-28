import { useState } from "react";
import { useDashboard } from "../api/hooks";
import type { ReturnsData } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Empty, KpiStrip, Panel } from "../components/ui";
import { PageHead, PageState } from "./common";

export default function Returns() {
  const [win, setWin] = useState("fy");
  const [box, setBox] = useState("");
  const q = useDashboard<ReturnsData>("/returns", { window: win, box });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const top = Math.max(1, ...d.reasons.map((r) => r.pcs));
          return (
            <>
              <PageHead title="Sales returns" lede="Goods clients sent back (GR): what quality check decided, and which calls to clients are still to be made." meta={d.meta} />
              <div className="cause-periods" role="group" aria-label="Period">
                {d.windows.map((w) => (
                  <button key={w.key} type="button" className={`fbtn${win === w.key ? " is-set" : ""}`} aria-pressed={win === w.key} onClick={() => { setWin(w.key); setBox(""); }}>
                    <span className="k">{w.label}</span>
                  </button>
                ))}
                {d.window.label && <span className="cause-count num">{d.window.label} · from {d.window.start}</span>}
              </div>
              {d.notices.map((n, i) => <p key={i} className="wrong-note">{n.text}</p>)}
              <KpiStrip kpis={d.kpis} cols={3} />
              <Panel title="Calls still to be made" sub="QC-pass goods with no calling remark yet. The client is called and the goods go back at the client's cost. Pick an age to filter.">
                <div className="cause-periods" role="group" aria-label="Days since the goods came back">
                  {d.boxes.map((b) => (
                    <button key={b.key} type="button" className={`fbtn${box === b.key ? " is-set" : ""}`} aria-pressed={box === b.key} onClick={() => setBox(box === b.key ? "" : b.key)}>
                      <span className="k">{b.label}: {b.count}</span>
                    </button>
                  ))}
                </div>
                {d.pending.rows.length ? <DataTable table={d.pending} name="flo-wing-returns-calls" maxRows={20} titleCaseFirst={false} /> : <Empty>No calls pending in this selection.</Empty>}
              </Panel>
              <Panel title="Why QC failed" sub="Pieces by the reason the team wrote, grouped by the words used.">
                {d.reasons.length ? (
                  <ul className="bars">
                    {d.reasons.map((r) => (
                      <li key={r.reason} style={{ display: "grid", gridTemplateColumns: "14rem 1fr 4rem", gap: ".6rem", alignItems: "center", margin: ".3rem 0" }}>
                        <span>{r.reason}</span>
                        <span style={{ background: "var(--accent, #c2410c)", height: ".6rem", borderRadius: 4, width: `${(r.pcs / top) * 100}%` }} />
                        <span className="num">{r.pcs}</span>
                      </li>
                    ))}
                  </ul>
                ) : <Empty>No QC failures in this period.</Empty>}
              </Panel>
              <Panel title="By month"><DataTable table={d.months} name="flo-wing-returns-months" maxRows={14} titleCaseFirst={false} /></Panel>
              <Panel title="Clients with the most returns"><DataTable table={d.clients} name="flo-wing-returns-clients" maxRows={15} titleCaseFirst={false} /></Panel>
              {d.policy.rows.length > 0 && (
                <Panel title={`Returned after ${d.policy_days} days`} sub="Outside the return policy: check before accepting.">
                  <DataTable table={d.policy} name="flo-wing-returns-policy" maxRows={15} titleCaseFirst={false} />
                </Panel>
              )}
            </>
          );
        }}
      </PageState>
    </div>
  );
}

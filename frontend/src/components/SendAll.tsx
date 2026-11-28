import { useMutation, useQuery } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { NudgeAllPreview, NudgeAllResult } from "../api/types";

const post = <T,>(path: string, body: object) => api<T>(path, undefined, { method: "POST", body: JSON.stringify(body) });

const ROLES: [string, string][] = [["crm", "Calling team"], ["sp", "Sales people"], ["kavita", "Kavita: escalations"]];
const SCOPES: Record<string, [string, string][]> = {
  crm: [["todo", "To call today"], ["escalated", "Escalated (8+ days)"], ["all", "All open"]],
  sp: [["escalated", "Escalated (8+ days)"], ["overdue", "Overdue"], ["all", "All open"]],
  kavita: [["escalated", "Escalated (8+ days)"]],
};

/** "Message everyone": each person gets their own list. Preview first, then one click sends to all of them. */
export function SendAll({ testMode, startRole }: { testMode: boolean; startRole: "crm" | "sp" }) {
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<string>(startRole);
  const [scope, setScope] = useState<string>(startRole === "crm" ? "todo" : "escalated");
  const body = { role, scope };
  const preview = useQuery<NudgeAllPreview, Error>({
    queryKey: ["/nudge/all/preview", body], queryFn: () => post<NudgeAllPreview>("/nudge/all/preview", body),
    enabled: open, retry: false, staleTime: 5_000,
  });
  const send = useMutation<NudgeAllResult, Error, boolean>({
    mutationFn: (force) => post<NudgeAllResult>("/nudge/all/send", { ...body, force }),
    onSuccess: () => preview.refetch(),
  });
  const pick = (r: string) => { send.reset(); setRole(r); setScope(SCOPES[r][0][0]); };
  if (!open) {
    return (
      <button type="button" className="fbtn send-open" onClick={() => { send.reset(); setRole(startRole); setScope(startRole === "crm" ? "todo" : "escalated"); setOpen(true); }}>
        <Send aria-hidden="true" /> <span className="k">Message everyone</span>
      </button>
    );
  }
  const p = preview.data;
  const r = send.data;
  const again = !!p?.items.some((i) => i.already_sent_minutes !== null);
  return (
    <div className="send-panel" role="dialog" aria-label="Message everyone">
      <div className="send-head">
        <b>Message everyone on WhatsApp</b>
        {testMode && <span className="send-test">Test mode: nothing is really sent</span>}
        <button type="button" className="send-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
      </div>
      <div className="send-scopes" role="group" aria-label="Who">
        {ROLES.map(([k, label]) => (
          <button key={k} type="button" className={`fbtn${role === k ? " is-set" : ""}`} aria-pressed={role === k} onClick={() => pick(k)}><span className="k">{label}</span></button>
        ))}
      </div>
      {role !== "kavita" && (
        <div className="send-scopes" role="group" aria-label="Which POs">
          {SCOPES[role].map(([k, label]) => (
            <button key={k} type="button" className={`fbtn${scope === k ? " is-set" : ""}`} aria-pressed={scope === k} onClick={() => { send.reset(); setScope(k); }}><span className="k">{label}</span></button>
          ))}
        </div>
      )}
      {preview.isPending && <p className="wrong-note">Checking…</p>}
      {preview.error && <p className="send-err">{preview.error.message}</p>}
      {p && (
        <>
          <p className="send-count"><b className="num">{p.items.length}</b> {p.items.length === 1 ? "person has" : "people have"} POs in this list · <b className="num">{p.ready}</b> can be messaged</p>
          {p.missing.length > 0 && <p className="send-warn">Not in the Staff tab (no message): {p.missing.join(", ")}. Add NAME, WHATSAPP NUMBER and CAUSES (payment) for them.</p>}
          <ul className="send-all-list">
            {p.items.map((i) => (
              <li key={i.group}>
                <details>
                  <summary><b>{i.name}</b> · <span className="num">{i.count}</span> PO{i.count === 1 ? "" : "s"}{!i.ready && " · no number"}{i.already_sent_minutes !== null && ` · sent ${i.already_sent_minutes} min ago`}</summary>
                  {i.message && <pre className="send-msg">{i.message}</pre>}
                </details>
              </li>
            ))}
          </ul>
          {send.error && <p className="send-err">{send.error.message}</p>}
          {r ? (
            <p className="send-ok">
              Sent to {r.sent.length}: {r.sent.join(", ") || "nobody"} at {r.sent_at}.
              {r.skipped_recent.length > 0 && ` Skipped, already sent in the last 30 minutes: ${r.skipped_recent.join(", ")}.`} Iris delivers within a minute.
            </p>
          ) : (
            p.ready > 0 && (
              <div className="send-actions">
                {again && <span className="send-warn">Some of these were sent recently and are skipped unless you send again.</span>}
                <button type="button" className="send-go" disabled={send.isPending} onClick={() => send.mutate(false)}>
                  {send.isPending ? "Sending…" : `Send to ${p.ready} ${p.ready === 1 ? "person" : "people"}`}
                </button>
                {again && <button type="button" className="send-go" disabled={send.isPending} onClick={() => send.mutate(true)}>Send all again</button>}
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}

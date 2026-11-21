import { useMutation, useQuery } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { NudgePreview, NudgeWho } from "../api/types";

const SCOPES: [string, string][] = [
  ["today", "Today"],
  ["week", "Yesterday – 7 days"],
  ["month", "8 – 30 days"],
  ["older", "Older than 30 days"],
  ["custom", "Waiting at least…"],
];

const post = <T,>(path: string, body: object) => api<T>(path, undefined, { method: "POST", body: JSON.stringify(body) });

/** Who a cause goes to. Cached: the Staff tab rarely changes. */
export function useNudgeWho() {
  return useQuery<NudgeWho, Error>({ queryKey: ["/nudge/who"], queryFn: () => api<NudgeWho>("/nudge/who"), staleTime: 120_000, retry: false });
}

/** "Send to Mona": pick which orders, see the exact message, send it. The message goes out through Iris from the
 *  company number; the order sheets are never touched. */
export function SendPanel({ cause, names, testMode, startScope, group, noun = "order" }: { cause: string; names: string[]; testMode: boolean; startScope: string; group?: string; noun?: string }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState(startScope || "today");
  const [minDays, setMinDays] = useState(7);
  const body = { cause, scope, min_days: scope === "custom" ? minDays : 0, ...(group ? { group } : {}) };
  const plural = noun === "enquiry" ? "enquiries" : `${noun}s`;

  const preview = useQuery<NudgePreview, Error>({
    queryKey: ["/nudge/preview", body],
    queryFn: () => post<NudgePreview>("/nudge/preview", body),
    enabled: open,
    retry: false,
    staleTime: 5_000,
  });
  const send = useMutation<NudgePreview, Error, boolean>({
    mutationFn: (force) => post<NudgePreview>("/nudge/send", { ...body, force }),
    onSuccess: () => preview.refetch(),
  });

  const to = names.join(" and ");
  if (!open) {
    return (
      <button type="button" className="fbtn send-open" onClick={() => { setScope(startScope || "today"); send.reset(); setOpen(true); }}>
        <Send aria-hidden="true" /> <span className="k">Send to {to}</span>
      </button>
    );
  }
  const p = preview.data;
  const sentNow = send.data?.sent;
  return (
    <div className="send-panel" role="dialog" aria-label={`Send to ${to}`}>
      <div className="send-head">
        <b>Send to {to} on WhatsApp</b>
        {testMode && <span className="send-test">Test mode: nothing is really sent</span>}
        <button type="button" className="send-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
      </div>
      <div className="send-scopes" role="group" aria-label={`Which ${plural}`}>
        {SCOPES.map(([k, label]) => (
          <button key={k} type="button" className={`fbtn${scope === k ? " is-set" : ""}`} aria-pressed={scope === k} onClick={() => { send.reset(); setScope(k); }}>
            <span className="k">{label}</span>
          </button>
        ))}
        {scope === "custom" && (
          <label className="send-days">
            <input type="number" min={1} max={365} value={minDays} onChange={(e) => { send.reset(); setMinDays(Math.max(1, Number(e.target.value) || 1)); }} aria-label="Days waiting" />
            days or more
          </label>
        )}
      </div>
      {preview.isPending && <p className="wrong-note">Checking…</p>}
      {preview.error && <p className="send-err">{preview.error.message}</p>}
      {p && (
        <>
          <p className="send-count"><b className="num">{p.count}</b> {p.count === 1 ? noun : plural} · to {p.to.join(", ")}</p>
          {p.count > 0 && <pre className="send-msg">{p.message}</pre>}
          {p.count === 0 && <p className="wrong-note">No {plural} in this selection.</p>}
          {send.error && <p className="send-err">{send.error.message}</p>}
          {sentNow ? (
            <p className="send-ok">Sent at {send.data?.sent_at}. Iris delivers it within a minute.</p>
          ) : (
            p.count > 0 && (
              <div className="send-actions">
                {p.already_sent_minutes !== null && <span className="send-warn">Already sent {p.already_sent_minutes} min ago.</span>}
                <button type="button" className="send-go" disabled={send.isPending} onClick={() => send.mutate(p.already_sent_minutes !== null)}>
                  {send.isPending ? "Sending…" : p.already_sent_minutes !== null ? "Send again" : `Send ${p.count} to ${to}`}
                </button>
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}

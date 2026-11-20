import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useDashboard } from "../api/hooks";
import type { SheetInfo, SheetView } from "../api/types";
import { DataTable } from "../components/DataTable";
import { FilterBar, MultiSelect } from "../components/Filters";
import { ErrorState, Panel, PageSkeleton } from "../components/ui";
import { useFilters } from "../lib/filters";
import { fmtInt } from "../lib/format";
import { PageHead, PageState } from "./common";

const KEYS = ["source", "tab", "q"];

/** Any tab of the three sheets, read live: pick a sheet and a tab, search, download. */
export default function Sheets() {
  const f = useFilters(KEYS);
  const list = useQuery<{ sheets: SheetInfo[] }, Error>({ queryKey: ["/sheets"], queryFn: () => api("/sheets"), staleTime: 60_000 });
  const sheets = list.data?.sheets ?? [];
  const source = f.values.source[0] ?? sheets[0]?.key ?? "order_status";
  const current = sheets.find((s) => s.key === source);
  const [text, setText] = useState(f.values.q[0] ?? "");
  const q = useDashboard<SheetView>("/sheet", { source, tab: f.values.tab[0] ?? "", q: f.values.q[0] ?? "" });

  if (list.isPending) return <div className="page"><PageSkeleton /></div>;
  if (list.error) return <div className="page"><ErrorState message={list.error.message} onRetry={() => list.refetch()} /></div>;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    f.set("q", text.trim() ? [text.trim()] : []);
  };
  const pickSheet = (v: string[]) => {
    f.set("tab", []);
    f.set("q", []);
    setText("");
    f.set("source", v);
  };

  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead title="Sheets" meta={d.meta} lede={<>The three Flo-Wing sheets, read live from Google. <strong>{d.name}</strong> · {d.tab.trim()}.</>} />
            <FilterBar active={f.values.q.length + f.values.tab.length} onReset={() => { setText(""); f.set("q", []); f.set("tab", []); }}>
              <MultiSelect label="Sheet" options={sheets.map((s) => s.key)} value={[source]} onChange={(v) => v.length && pickSheet(v)} single allLabel={current?.name ?? ""} pretty={(k) => sheets.find((s) => s.key === k)?.name ?? k} />
              <MultiSelect label="Tab" options={current?.tabs ?? []} value={f.values.tab} onChange={(v) => f.set("tab", v)} single allLabel={current?.default_tab?.trim() || d.tab.trim()} pretty={(x) => x.trim()} />
              <form onSubmit={submit} style={{ display: "inline-flex", gap: 6 }}>
                <input className="field" style={{ height: 34, minWidth: 220 }} type="search" placeholder="Search vendor, PO no, design…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search rows" />
                <button className="btn sm" type="submit" aria-label="Search"><Search /> Search</button>
              </form>
              {current && (
                <a className="btn ghost sm" href={current.url} target="_blank" rel="noreferrer">
                  <ExternalLink /> Open in Google Sheets
                </a>
              )}
            </FilterBar>
            <Panel
              title={`${fmtInt(d.total)} rows${f.values.q[0] ? ` matching “${f.values.q[0]}”` : ""}`}
              sub={`Header found on row ${d.header_row}${d.shown < d.total ? ` · first ${fmtInt(d.shown)} shown` : ""}`}
              flush
            >
              <DataTable table={d.table} name={`${d.name}-${d.tab.trim()}`} maxRows={50} titleCaseFirst={false} />
            </Panel>
          </>
        )}
      </PageState>
    </div>
  );
}

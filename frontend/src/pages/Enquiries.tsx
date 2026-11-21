import { ExternalLink, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useDashboard } from "../api/hooks";
import type { EnquiryData, EnquiryView, TableData } from "../api/types";
import { Bars } from "../components/charts/Bars";
import { colorFor, Legend } from "../components/charts/common";
import { HBars } from "../components/charts/HBars";
import { BarList, Split } from "../components/charts/Lists";
import { DataTable } from "../components/DataTable";
import { FilterBar, MonthFilter, MultiSelect } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { useFilters } from "../lib/filters";
import { fmtInt } from "../lib/format";
import { PageHead, PageState } from "./common";

const SHEET_URL = "https://docs.google.com/spreadsheets/d/16-BtrzzzHdoQ7HZrMyCUkZxEQJ7YduoaHbmW_v1d9B0/edit";
const KEYS = ["view", "month", "status", "handler", "topic", "party", "city", "po_status", "approval"];

const VIEWS: { id: EnquiryView; label: string; about: string }[] = [
  { id: "enquiries", label: "Enquiries", about: "Every supplier enquiry, its status, who is following it up and how long it has waited" },
  { id: "city_po", label: "PO by city", about: "Suppliers waiting for a PO, city by city" },
  { id: "terms", label: "Terms approval", about: "Payment days and discount agreed with each supplier, and whether they are approved" },
  { id: "inactive", label: "Inactive suppliers", about: "Suppliers with no purchase this year, with the pieces bought from them before" },
  { id: "issues", label: "Purchase issues", about: "Problems logged against purchases" },
];

/** Rows of a table that contain the text (any column). */
function searchTable(t: TableData, text: string): TableData {
  const q = text.trim().toLowerCase();
  if (!q) return t;
  const keep = t.rows.map((r, i) => [r, i] as const).filter(([r]) => r.some((c) => String(c ?? "").toLowerCase().includes(q)));
  return { ...t, rows: keep.map(([r]) => r), meta: keep.map(([, i]) => t.meta[i]) };
}

const colors = (labels: string[]) => Object.fromEntries(labels.map((l, i) => [l, colorFor(l, i)]));

export default function Enquiries() {
  const f = useFilters(KEYS);
  const [text, setText] = useState("");
  const q = useDashboard<EnquiryData>("/enquiries", {
    month: f.values.month, status: f.values.status, handler: f.values.handler, topic: f.values.topic, party: f.values.party,
    city: f.values.city, po_status: f.values.po_status, approval: f.values.approval,
  });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => {
          const views = VIEWS.filter((v) => d.views.includes(v.id));
          const view = views.find((v) => v.id === f.values.view[0]) ?? views[0];
          const e = d.sections.enquiries;
          const c = d.sections.city_po;
          const active = KEYS.slice(1).reduce((n, k) => n + f.values[k].length, 0);
          const reset = () => { KEYS.slice(1).forEach((k) => f.set(k, [])); setText(""); };
          return (
            <>
              <PageHead
                title="Supplier enquiries"
                meta={d.meta}
                lede={
                  e ? (
                    <>
                      {e.summary.open > 0 ? <span className="bad">{fmtInt(e.summary.open)} enquiries are still pending</span> : "No enquiry is pending"}
                      {" "}out of {fmtInt(e.summary.total)} logged
                      {e.summary.oldest && <> · oldest: <strong>{e.summary.oldest.party}</strong>, {fmtInt(e.summary.oldest.days)} days</>}
                      {c && c.summary.pending > 0 && <> · {fmtInt(c.summary.pending)} suppliers waiting for a PO</>}.
                    </>
                  ) : (
                    "Lists kept on the Supplier's Enquiry Sheet."
                  )
                }
              />
              {views.length === 0 ? (
                <Empty title="Nothing to show">None of the expected tabs were found on the Supplier's Enquiry Sheet.</Empty>
              ) : (
                <>
                  <div className="view-switch">
                    <div className="seg" role="group" aria-label="Which list to show">
                      {views.map((v) => (
                        <button key={v.id} type="button" aria-pressed={v.id === view.id} onClick={() => f.set("view", v.id === views[0].id ? [] : [v.id])}>
                          {v.label}
                        </button>
                      ))}
                    </div>
                    <span className="view-about">{view.about}{d.tabs[view.id] ? <> · tab “{String(d.tabs[view.id]).trim()}”</> : null}</span>
                  </div>
                  <FilterBar
                    active={active}
                    onReset={reset}
                    right={<a className="btn ghost sm" href={SHEET_URL} target="_blank" rel="noreferrer"><ExternalLink /> Open sheet</a>}
                  >
                    {view.id === "enquiries" && (
                      <>
                        <MonthFilter options={d.options.month ?? []} value={f.values.month} onChange={(v) => f.set("month", v)} />
                        <MultiSelect label="Status" options={d.options.status ?? []} value={f.values.status} onChange={(v) => f.set("status", v)} pretty={(x) => x} />
                        <MultiSelect label="Handled by" options={d.options.handler ?? []} value={f.values.handler} onChange={(v) => f.set("handler", v)} pretty={(x) => x} />
                        <MultiSelect label="Topic" options={d.options.topic ?? []} value={f.values.topic} onChange={(v) => f.set("topic", v)} pretty={(x) => x} />
                        <MultiSelect label="Supplier" options={d.options.party ?? []} value={f.values.party} onChange={(v) => f.set("party", v)} />
                      </>
                    )}
                    {view.id === "city_po" && (
                      <>
                        <MultiSelect label="City" options={d.options.city ?? []} value={f.values.city} onChange={(v) => f.set("city", v)} />
                        <MultiSelect label="PO status" options={d.options.po_status ?? []} value={f.values.po_status} onChange={(v) => f.set("po_status", v)} pretty={(x) => x} />
                      </>
                    )}
                    {view.id === "terms" && (
                      <MultiSelect label="Approval" options={d.options.approval ?? []} value={f.values.approval} onChange={(v) => f.set("approval", v)} pretty={(x) => x} />
                    )}
                    <label className="search-inline">
                      <Search aria-hidden />
                      <input className="field" type="search" placeholder="Search these rows…" value={text} onChange={(ev) => setText(ev.target.value)} aria-label="Search the rows below" />
                    </label>
                  </FilterBar>
                  <Notices items={d.notices} />
                  {view.id === "enquiries" && e && <EnquiryView e={e} text={text} />}
                  {view.id === "city_po" && c && <CityView c={c} text={text} />}
                  {view.id === "terms" && d.sections.terms && (
                    <>
                      <KpiStrip kpis={d.sections.terms.kpis} cols={4} lead={["awaiting"]} />
                      <Section title="Payment terms by supplier" sub="Newest first · from the ‘Terms Approval’ tab">
                        <div className="grid">
                          <div className="span-9">
                            <Panel flush>
                              <DataTable table={searchTable(d.sections.terms.tables.terms, text)} name="terms_approval" maxRows={25} titleCaseFirst={false} />
                            </Panel>
                          </div>
                          <div className="span-3">
                            <Panel title="Approval status" sub="Suppliers">
                              <Split items={d.sections.terms.charts.status} unit="suppliers" colors={colors(d.sections.terms.charts.status.map((x) => x.label))} label="Suppliers by approval status" />
                            </Panel>
                          </div>
                        </div>
                      </Section>
                    </>
                  )}
                  {view.id === "inactive" && d.sections.inactive && (
                    <>
                      <KpiStrip kpis={d.sections.inactive.kpis} cols={2} />
                      <Section title="Inactive suppliers" sub="No purchase in 2025-26 · biggest past suppliers first">
                        <Panel flush>
                          <DataTable table={searchTable(d.sections.inactive.tables.inactive, text)} name="inactive_suppliers" maxRows={30} titleCaseFirst={false} />
                        </Panel>
                      </Section>
                    </>
                  )}
                  {view.id === "issues" && d.sections.issues && (
                    <Section title="Purchase issues">
                      <Panel flush>
                        <DataTable table={searchTable(d.sections.issues.tables.issues, text)} name="purchase_issues" maxRows={30} titleCaseFirst={false} />
                      </Panel>
                    </Section>
                  )}
                </>
              )}
            </>
          );
        }}
      </PageState>
    </div>
  );
}

function EnquiryView({ e, text }: { e: NonNullable<EnquiryData["sections"]["enquiries"]>; text: string }) {
  const [showAll, setShowAll] = useState(false);
  const list = useMemo(() => searchTable(showAll ? e.tables.all : e.tables.open, text), [e, text, showAll]);
  const statusColors = useMemo(() => colors(e.charts.status.map((x) => x.label)), [e]);
  if (!e.summary.total) return <Empty title="No enquiries">Nothing matches these filters. Clear a filter to see more.</Empty>;
  return (
    <>
      <KpiStrip kpis={e.kpis} cols={6} lead={["open"]} />
      <Section
        title={showAll ? "All enquiries" : "Pending enquiries"}
        sub={showAll ? "Newest first" : "Waiting longest first · solved ones are hidden"}
        right={
          <div className="seg" role="group" aria-label="Which enquiries">
            <button type="button" aria-pressed={!showAll} onClick={() => setShowAll(false)}>Pending</button>
            <button type="button" aria-pressed={showAll} onClick={() => setShowAll(true)}>All</button>
          </div>
        }
      >
        <Panel flush foot={text ? `${fmtInt(list.rows.length)} rows match “${text.trim()}”` : undefined}>
          <DataTable table={list} name={showAll ? "enquiries_all" : "enquiries_pending"} maxRows={15} titleCaseFirst={false} />
        </Panel>
      </Section>
      <Section title="Who is following up" sub="Enquiries per person · pending = not solved yet">
        <div className="grid">
          <div className="span-8">
            <Panel flush>
              <DataTable table={e.tables.handlers} name="enquiries_by_handler" maxRows={10} />
            </Panel>
          </div>
          <div className="span-4">
            <Panel title="Status" sub="All enquiries in view">
              <Split items={e.charts.status} unit="enquiries" colors={statusColors} label="Enquiries by status" />
            </Panel>
          </div>
        </div>
      </Section>
      <Section title="What suppliers ask about" sub="Topic read from the ‘Enquiry about’ text · month by month">
        <div className="grid">
          <div className="span-4">
            <Panel title="By topic" sub="Enquiries">
              <BarList items={e.charts.topics} unit="enquiries" label="Enquiries by topic" max={9} />
            </Panel>
          </div>
          <div className="span-8">
            <Panel title="Enquiries by month" sub="Logged, and how many of them are still pending" right={<Legend items={e.charts.monthly.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
              {e.charts.monthly.categories.length ? (
                <Bars data={e.charts.monthly} months unit="enquiries" label="Enquiries logged and still pending by month" />
              ) : (
                <Empty title="No dates">These enquiries have no date.</Empty>
              )}
            </Panel>
          </div>
        </div>
      </Section>
      <Section title="By supplier" sub="Most pending first">
        <Panel flush>
          <DataTable table={searchTable(e.tables.suppliers, text)} name="enquiries_by_supplier" maxRows={12} />
        </Panel>
      </Section>
    </>
  );
}

function CityView({ c, text }: { c: NonNullable<EnquiryData["sections"]["city_po"]>; text: string }) {
  return (
    <>
      <KpiStrip kpis={c.kpis} cols={4} lead={["po_pending"]} />
      <Section title="City by city" sub="From the side-by-side city blocks on the ‘Supplier's Enquiry Sheet’ tab">
        <div className="grid">
          <div className="span-7">
            <Panel flush>
              <DataTable table={c.tables.cities} name="po_by_city" maxRows={12} />
            </Panel>
          </div>
          <div className="span-5">
            <Panel title="PO issued and pending" sub="Suppliers per city" right={<Legend items={c.charts.by_city.series.map((x, i) => ({ name: x.name, color: colorFor(x.name, i) }))} />}>
              <HBars data={{ categories: c.charts.by_city.categories, series: [...c.charts.by_city.series] }} unit="suppliers" label="Suppliers with PO issued and pending per city" sortBy="Waiting for PO" max={10} />
            </Panel>
          </div>
        </div>
      </Section>
      <Section title="Every supplier listed" sub="Waiting longest first · ‘As written’ is the order date exactly as typed in the sheet">
        <Panel flush>
          <DataTable table={searchTable(c.tables.list, text)} name="po_by_city_list" maxRows={20} titleCaseFirst={false} />
        </Panel>
      </Section>
    </>
  );
}

import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useDashboard } from "../api/hooks";
import type { TodayData, TodaySection } from "../api/types";
import { DataTable } from "../components/DataTable";
import { RoleFilter, useRole } from "../components/ExtraFilters";
import { FilterBar } from "../components/Filters";
import { Empty, KpiStrip, Notices, Panel, Section } from "../components/ui";
import { useFilters } from "../lib/filters";
import { PageHead, PageState } from "./common";

const KEYS = ["role"];

export default function Today() {
  const f = useFilters(KEYS);
  const { role, setRole } = useRole(f);
  const q = useDashboard<TodayData>("/today", { role });
  return (
    <div className="page">
      <PageState q={q}>
        {(d) => (
          <>
            <PageHead
              title="Today"
              meta={d.meta}
              lede={
                <>
                  <strong>{d.date}</strong>
                  {d.lede.length ? <> · {d.lede.join(" · ")}.</> : null}
                </>
              }
            />
            <FilterBar active={f.active} onReset={f.reset}>
              <RoleFilter options={d.options.role ?? []} role={role} setRole={setRole} />
              <span className="applied">
                Happened: last 7 days ({d.windows.last7}) · Due: today and next 7 days ({d.windows.next7})
              </span>
            </FilterBar>
            {d.sections.length === 0 ? (
              <Empty title="Nothing to show">No sheet has data for this view.</Empty>
            ) : (
              d.sections.map((s) => <TodayBlock key={s.id} s={s} />)
            )}
          </>
        )}
      </PageState>
    </div>
  );
}

function TodayBlock({ s }: { s: TodaySection }) {
  return (
    <Section
      title={s.title}
      sub={s.sub}
      right={
        s.link ? (
          <Link className="btn sm" to={s.link}>
            Open page <ArrowUpRight />
          </Link>
        ) : undefined
      }
    >
      <Notices items={s.notices ?? []} />
      <KpiStrip kpis={s.kpis} cols={s.kpis.length <= 6 ? s.kpis.length : 4} />
      {s.tables.length > 0 && (
        <div className="grid mt">
          {s.tables.map((t) => (
            <div key={t.title} className={s.tables.length === 1 ? "span-12" : "span-6"}>
              <Panel title={t.title} sub={t.sub} flush={t.table.rows.length > 0}>
                {t.table.rows.length ? (
                  <DataTable table={t.table} name={`today_${s.id}_${t.title.toLowerCase().replace(/\W+/g, "_")}`} maxRows={8} titleCaseFirst={false} />
                ) : (
                  <div className="state">Nothing here.</div>
                )}
              </Panel>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

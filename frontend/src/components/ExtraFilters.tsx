import { CalendarRange, Check, Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { MultiSelect, usePopover, Trigger } from "./Filters";

type F = { values: Record<string, string[]>; set: (k: string, v: string[]) => void; setMany: (p: Record<string, string[]>) => void };

const PRESETS = ["Today", "Yesterday", "Last 7 days", "This week", "This month", "Last month", "Last 30 days", "This quarter", "This FY"];

/** Date period: presets or a custom from / to range. `dateOf` says which date the page filters on. */
export function PeriodFilter({ f, label, dateOf }: { f: F; label?: string | null; dateOf: string }) {
  const { open, setOpen, btn, pop, pos } = usePopover();
  const id = useId();
  const period = f.values.period?.[0] ?? "";
  const [from, setFrom] = useState(f.values.date_from?.[0] ?? "");
  const [to, setTo] = useState(f.values.date_to?.[0] ?? "");
  useEffect(() => {
    if (open) {
      setFrom(f.values.date_from?.[0] ?? "");
      setTo(f.values.date_to?.[0] ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const pick = (p: string) => {
    f.setMany({ period: p ? [p] : [], date_from: [], date_to: [] });
    setOpen(false);
  };
  const applyCustom = () => {
    if (!from && !to) return pick("");
    f.setMany({ period: ["Custom"], date_from: from ? [from] : [], date_to: to ? [to] : [] });
    setOpen(false);
  };
  const shown = !period ? "All dates" : period === "Custom" ? label || "Custom" : period;
  return (
    <>
      <Trigger label="Period" value={shown} title={label ?? undefined} isSet={!!period} open={open} onClick={() => setOpen(!open)} btnRef={btn} icon={<CalendarRange aria-hidden="true" />} controls={id} />
      {open &&
        createPortal(
          <div className="popover" ref={pop} id={id} role="dialog" aria-label="Filter by period" style={{ top: pos.top, left: pos.left }}>
            <div className="opt-list" role="listbox">
              {["", ...PRESETS].map((p) => (
                <button type="button" key={p || "all"} className="opt" role="option" aria-selected={period === p} aria-checked={period === p} onClick={() => pick(p)}>
                  <span className="check">{period === p && <Check />}</span>
                  {p || "All dates"}
                </button>
              ))}
            </div>
            <div className="popover-head">
              <div className="range-row">
                <label>
                  From
                  <input className="field" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                </label>
                <label>
                  To
                  <input className="field" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
                </label>
              </div>
            </div>
            <div className="popover-foot">
              <span>
                By {dateOf}
                {label ? ` · ${label}` : ""}
              </span>
              <button type="button" className="btn sm" onClick={applyCustom}>
                Apply dates
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

/** One search box that filters the whole page on the server (KPIs, charts and tables all follow it). */
export function SearchBox({ f, placeholder }: { f: F; placeholder: string }) {
  const current = f.values.q?.[0] ?? "";
  const [text, setText] = useState(current);
  useEffect(() => setText(current), [current]);
  useEffect(() => {
    if (text.trim() === current) return;
    const t = setTimeout(() => f.set("q", text.trim() ? [text.trim()] : []), 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <label className="search-inline">
      <Search aria-hidden />
      <input className="field" type="search" placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} aria-label="Search this page" />
    </label>
  );
}

const same = (x: string) => x;

/** The filters every page shares: period, due / delivery window, supplier type, amount and search. */
export function ExtraFilters({ f, options, periodLabel, dateOf, windowLabel = "Window", search }: { f: F; options: Record<string, string[] | undefined>; periodLabel?: string | null; dateOf: string; windowLabel?: string; search: string }) {
  return (
    <>
      {!!options.period?.length && <PeriodFilter f={f} label={periodLabel} dateOf={dateOf} />}
      {!!options.window?.length && <MultiSelect label={windowLabel} options={options.window} value={f.values.window ?? []} onChange={(v) => f.set("window", v)} pretty={same} />}
      {!!options.supplier_type?.length && <MultiSelect label="Supplier type" options={options.supplier_type} value={f.values.supplier_type ?? []} onChange={(v) => f.set("supplier_type", v)} pretty={same} />}
      {!!options.amount?.length && <MultiSelect label="Amount" options={options.amount} value={f.values.amount ?? []} onChange={(v) => f.set("amount", v)} pretty={same} />}
      <SearchBox f={f} placeholder={search} />
    </>
  );
}

const ROLE_KEY = "flowing-view-as";

/** "View as": Management / Purchase team / Accounts, remembered on this device. */
export function useRole(f: F) {
  let saved = "";
  try {
    saved = localStorage.getItem(ROLE_KEY) ?? "";
  } catch {
    /* storage may be blocked */
  }
  const role = f.values.role?.[0] ?? saved;
  const setRole = (v: string[]) => {
    f.set("role", v);
    try {
      if (v[0]) localStorage.setItem(ROLE_KEY, v[0]);
      else localStorage.removeItem(ROLE_KEY);
    } catch {
      /* ignore */
    }
  };
  return { role, setRole };
}

export function RoleFilter({ options, role, setRole }: { options: string[]; role: string; setRole: (v: string[]) => void }) {
  return <MultiSelect label="View as" options={options} value={role ? [role] : []} onChange={setRole} pretty={same} single allLabel="Management" />;
}

import { Building2, CalendarCheck, ClipboardList, MessageSquareText, IndianRupee, LayoutDashboard, Menu, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, Sheet, Sun, Truck, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useFetchingReporter, useRefreshAll } from "../../api/hooks";
import { useLive } from "../../lib/live";
import { useTheme } from "../../lib/theme";
import { Wordmark } from "../Brand";
import { LiveStatus } from "./LiveStatus";

export const NAV = [
  { group: "Operations", items: [
    { to: "/", label: "Overview", icon: LayoutDashboard },
    { to: "/today", label: "Today", icon: CalendarCheck },
    { to: "/orders", label: "Orders", icon: ClipboardList },
    { to: "/vendors", label: "Vendors", icon: Building2 },
  ] },
  { group: "Purchasing and accounts", items: [
    { to: "/order-to-vendors", label: "Order to vendors", icon: Truck },
    { to: "/dues", label: "Supplier dues", icon: IndianRupee },
    { to: "/enquiries", label: "Supplier enquiries", icon: MessageSquareText },
  ] },
  { group: "Data", items: [
    { to: "/sheets", label: "Sheets", icon: Sheet },
  ] },
];

export function pageLabel(path: string) {
  for (const g of NAV) for (const it of g.items) if (it.to === path) return it.label;
  return "Overview";
}

const NAV_KEY = "flowing-nav";

/** Desktop: the sidebar can fold into an icon rail. Remembered per device. */
export function navCollapsed(): boolean {
  try {
    return localStorage.getItem(NAV_KEY) === "rail";
  } catch {
    return false;
  }
}

export function Shell({ children }: { children: ReactNode }) {
  useFetchingReporter();
  const { resolved, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const [rail, setRail] = useState(navCollapsed);
  const toggleRail = () =>
    setRail((r) => {
      try {
        localStorage.setItem(NAV_KEY, r ? "full" : "rail");
      } catch {
        /* ignore */
      }
      return !r;
    });
  useEffect(() => {
    // "[" folds or unfolds the sidebar, unless the person is typing
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key !== "[" || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable) return;
      e.preventDefault();
      toggleRail();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [spinning, setSpinning] = useState(false);
  const loc = useLocation();
  const live = useLive();
  const refresh = useRefreshAll();
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    document.title = `${pageLabel(loc.pathname)} · Flo-Wing Operations`;
  }, [loc.pathname]);

  const doRefresh = async () => {
    setSpinning(true);
    await refresh();
    setTimeout(() => setSpinning(false), 500);
  };

  return (
    <div className={`app${open ? " nav-open" : ""}${rail ? " nav-rail" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <NavLink to="/" className="brand" aria-label="Flo-Wing Operations home">
          <Wordmark variant="letters" height={rail ? 15 : 22} wing={!rail} />
          <span className="brand-scope">
            Operations
            <br />
            {live.meta?.fy ?? "FY 2026-27"}
          </span>
        </NavLink>
        <nav className="nav">
          {NAV.map((g) => (
            <div key={g.group} style={{ display: "contents" }}>
              <div className="nav-group">{g.group}</div>
              {g.items.map((it) => (
                <NavLink key={it.to} to={{ pathname: it.to }} end={it.to === "/"} title={rail ? it.label : undefined}>
                  <it.icon aria-hidden="true" />
                  <span className="label">{it.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="stamp" style={{ padding: "0 8px", whiteSpace: "normal" }}>
            Read-only view of the Flo-Wing Google Sheets. Edit data in the sheets; it shows here within a minute.
          </div>
        </div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <header className="topbar">
        <button className="btn ghost icon menu-btn" onClick={() => setOpen(!open)} aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open}>
          {open ? <X /> : <Menu />}
        </button>
        <button className="btn ghost icon rail-btn" onClick={toggleRail} aria-label={rail ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!rail} title={`${rail ? "Expand" : "Collapse"} sidebar  [`}>
          {rail ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
        <div className="crumb">
          <span className="scope">FLO-WING · </span>
          <b>{pageLabel(loc.pathname)}</b>
        </div>
        <div className="topbar-right">
          {live.meta?.source === "demo" && (
            <span className="demo-chip" title="No Google key is configured, so built-in sample data is shown.">
              Demo data
            </span>
          )}
          <LiveStatus />
          <button className="btn ghost icon refresh" onClick={doRefresh} aria-label="Read the sheets again now" title="Read the sheets again now">
            <RefreshCw style={{ transition: "transform 500ms var(--ease-out)", transform: spinning ? "rotate(360deg)" : "none" }} />
          </button>
          <button className="btn ghost icon" onClick={toggle} aria-label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={resolved === "dark" ? "Light mode" : "Dark mode"}>
            {resolved === "dark" ? <Sun /> : <Moon />}
          </button>
        </div>
      </header>
      <main className="sheet" id="main">
        {children}
      </main>
    </div>
  );
}

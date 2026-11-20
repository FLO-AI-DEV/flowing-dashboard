/* Shapes returned by the Flo-Wing API (backend/app). */

export type Fmt = "text" | "int" | "dec" | "dec1" | "pct" | "inr" | "inr_full" | "date";
export type Tone = "good" | "alert";
export type NoticeKind = "info" | "success" | "warning" | "error";

export interface Kpi {
  id: string;
  label: string;
  value: number | string | null;
  unit: string;
  format: Fmt;
  hint?: string;
  tone?: Tone;
}

export interface Rate {
  good: number;
  mid: number;
}

export interface Column {
  key: string;
  label: string;
  format: Fmt;
  rate?: Rate;
}

export type Cell = number | string | boolean | null;

export interface TableData {
  title: string | null;
  note: string | null;
  columns: Column[];
  rows: Cell[][];
  meta: { kind: "total" | "ref" | null; muted: boolean }[];
  key_col: string | null;
  sorted: boolean;
}

export interface Series {
  name: string;
  values: number[];
  axis?: "left" | "right";
}

export interface SeriesChart {
  categories: string[];
  series: Series[];
}

export interface Slice {
  label: string;
  value: number;
}

export interface Notice {
  kind: NoticeKind;
  text: string;
}

export interface SourceMeta {
  source: string;
  synced_at: string | null;
  version: string;
  stale: boolean;
  error: string | null;
}

export interface Meta {
  fy: string;
  fy_months: string[];
  source: "google" | "demo";
  ttl: number;
  server_time: string;
  synced_at: string | null;
  version: string;
  stale: boolean;
  sources: SourceMeta[];
}

export interface Envelope {
  meta: Meta;
}

export type Options = Record<string, string[]>;

export interface OrdersData extends Envelope {
  empty?: boolean;
  options: Options;
  notices: Notice[];
  kpis: Kpi[];
  summary: { overdue_lines: number; pending_pcs: number; pending: number; overdue: number; vendors: number; oldest: { po: string; vendor: string; days: number } | null };
  tables: { monthly: TableData; vendors: TableData; categories: TableData; departments: TableData; cities: TableData; overdue: TableData };
  overdue_total: number;
  charts: { monthly: SeriesChart; receivable: SeriesChart; vendors: SeriesChart; categories: SeriesChart; timing: Slice[] };
}

export interface VendorsData extends Envelope {
  empty?: boolean;
  options: Options;
  notices: Notice[];
  kpis: Kpi[];
  summary: {
    late_vendors: number;
    vendors: number;
    most_overdue: { name: string; value: number } | null;
    most_pending: { name: string; value: number } | null;
    most_reliable: { name: string; value: number } | null;
  };
  tables: { scorecard: TableData };
  charts: { pending: SeriesChart; overdue: Slice[]; ontime: Slice[] };
}

export interface DuesData extends Envelope {
  empty?: boolean;
  options: Options;
  title: string;
  notices: Notice[];
  kpis: Kpi[];
  tab: string;
  tabs: string[];
  summary: { total: number; overdue: number; due7: number; bills: number; suppliers: number; oldest: number };
  tables: { suppliers: TableData; agencies: TableData; bills: TableData };
  charts: { ageing: Slice[]; suppliers: Slice[]; agencies: Slice[] };
}

export interface OtvData extends Envelope {
  empty?: boolean;
  options: Options;
  notices: Notice[];
  kpis: Kpi[];
  tab: string;
  tabs: string[];
  detected: { vendor: string | null; status: string | null; amount: string | null; qty: string | null; header_row: number };
  charts: { by_status: Slice[]; by_vendor: Slice[]; money: boolean };
  tables: { rows: TableData };
  rows_total: number;
}

export interface SheetInfo {
  key: string;
  name: string;
  url: string;
  tabs: string[];
  default_tab: string;
  error: string | null;
}

export interface SheetView extends Envelope {
  name: string;
  tab: string;
  header_row: number;
  total: number;
  shown: number;
  table: TableData;
}

export interface Alert {
  kind: NoticeKind;
  area: string;
  title: string;
  text: string;
  money?: boolean;
  top?: { dimension: string; name: string; value: number }[];
}

export interface OverviewData extends Envelope {
  options: Options;
  alerts: Alert[];
  errors: Notice[];
  sections: {
    orders?: {
      kpis: Kpi[];
      charts: { monthly: SeriesChart; vendors: SeriesChart; timing: Slice[] };
      tables: { vendors: TableData; overdue: TableData };
      overdue_total: number;
    };
    dues?: { kpis: Kpi[]; title: string; notices: Notice[]; tables: { suppliers: TableData }; charts: { ageing: Slice[] } };
    otv?: { kpis: Kpi[]; charts: { by_status: Slice[]; by_vendor: Slice[]; money: boolean } };
  };
}

export interface SourceStatus {
  name: string;
  ok: boolean;
  error: string | null;
  stale: boolean;
  synced_at: string | null;
  version: string;
  tabs: string[];
}

export interface StatusData {
  source: "google" | "demo";
  ttl: number;
  fy: string;
  server_time: string;
  sources: Record<string, SourceStatus>;
}

export interface Health {
  ok: boolean;
  version: string;
  source: "google" | "demo";
  ttl: number;
  auth_required: boolean;
}

/* Shapes returned by the Flo-Wing API (backend/app). Copied by hand into mobile/src/lib/types.ts. */

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

export type Tone3 = "bad" | "warn" | "good";

export interface Action {
  who: string;
  stage: string;
  what: string;
  late: number;
  due: number;
  oldest_days: number;
  tone: Tone3;
}

export interface PipelineStep {
  key: "reply" | "po" | "bill" | "hold" | "old" | "done";
  label: string;
  owner: string;
  count: number;
  late: number;
}

export interface Wrong {
  key: "reply" | "po" | "bill" | "hold";
  label: string;
  who: string;
  backlog: number;
  today: number;
  oldest_days: number;
}

export interface CauseData extends Envelope {
  title: string;
  count: number;
  total: number;
  table: TableData;
}
export interface DailyClose {
  received: number;
  done: number;
  pending: number;
  backlog: number;
  after_cutoff: boolean;
  cutoff: string;
  by_channel: { channel: string; received: number; done: number }[];
  wrong: Wrong[];
  never_marked: number;
}

export interface HomeData extends Envelope {
  title: string;
  month: string[];
  kpis: Kpi[];
  close: DailyClose;
  pipeline: PipelineStep[];
  actions: Action[];
  channels: { channel: string; orders: number; sets: number }[];
  notices: Notice[];
  options: Options;
}

export type OrderState = "late" | "due" | "ok" | "hold" | "old" | "done";

export interface OrdersData extends Envelope {
  title: string;
  kpis: Kpi[];
  table: TableData & { states: OrderState[] };
  options: Options;
}

export interface TeamData extends Envelope {
  title: string;
  sales: TableData;
  owners: TableData;
  fixes: TableData;
  options: Options;
}

export interface ClientsData extends Envelope {
  title: string;
  kpis: Kpi[];
  table: TableData;
  options: Options;
}

export interface PaymentsData extends Envelope {
  title: string;
  kpis: Kpi[];
  members: TableData;
  pending: TableData & { states?: OrderState[] };
  notices: Notice[];
  options: Options;
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

export interface NudgeWho {
  enabled: boolean;
  test_mode: boolean;
  who: Record<string, string[]>;
  error?: string;
}

export interface NudgePreview {
  count: number;
  to: string[];
  message: string;
  already_sent_minutes: number | null;
  test_mode: boolean;
  sent?: boolean;
  sent_at?: string;
}

export interface EnquiryCause {
  key: string;
  label: string;
  open: number;
  today: number;
  older: number;
  oldest_days: number;
}
export interface EnquiriesData extends Envelope {
  kpis: Kpi[];
  today: { received: number; status: Record<string, number> };
  causes: EnquiryCause[];
  by_source: { source: string; open: number; total: number }[];
  total_open: number;
  notices: Notice[];
}

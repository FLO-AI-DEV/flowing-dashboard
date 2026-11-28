/* PO follow-up: how long open POs have waited (tap a box to see only those), the calling team or the sales people
   with today's work, and WhatsApp "Message everyone". Tap a name for their POs, or "Report" for their numbers. */
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ChipRow, Toggle } from "../../components/Chips";
import { Stat, TapRow } from "../../components/Rows";
import { Em, Screen } from "../../components/Screen";
import { SendAllButton } from "../../components/SendSheet";
import { Notices, Panel, T } from "../../components/ui";
import { inrShort } from "../../lib/format";
import { useDashboard } from "../../lib/query";
import { font, useTheme } from "../../lib/theme";
import type { PoBucket, PoOverview, PoPersonStat } from "../../lib/types";

type Role = "crm" | "sp";
const TONE: Record<string, "bad" | "warn" | "good"> = { not_sent: "bad", past_limit: "bad", overdue: "bad", due_soon: "warn", on_track: "good" };
const AGE: [keyof PoPersonStat & string, string, string][] = [
  ["due_soon", "due_soon", "5–7 days"],
  ["overdue", "overdue", "8–10 days"],
  ["past_limit", "past_limit", "11+ days"],
  ["not_sent", "not_sent", "PO not sent"],
];

function Bucket({ b, on, onPress }: { b: PoBucket; on: boolean; onPress: () => void }) {
  const c = useTheme();
  const tone = TONE[b.key];
  const [bg, fg] = tone === "bad" ? [c.negSoft, c.negInk] : tone === "warn" ? [c.warnSoft, c.warnInk] : [c.posSoft, c.posInk];
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
      style={({ pressed }) => [st.bucket, { backgroundColor: bg, borderColor: on ? c.ink : "transparent", opacity: pressed ? 0.85 : 1 }]}
    >
      <Text style={{ fontFamily: font.uiBold, fontSize: 24, color: fg }}>{b.count}</Text>
      <T v="small" color={fg} numberOfLines={2}>{b.label}</T>
      <T v="small" color={fg} style={{ fontFamily: font.uiBold }}>{inrShort(b.amount)}</T>
    </Pressable>
  );
}

function Person({ p, role, window, bucket, order, first }: { p: PoPersonStat; role: Role; window: string; bucket: string; order: string; first: boolean }) {
  const open = (extra: Record<string, string> = {}) =>
    router.push({ pathname: "/po-person", params: { role, name: p.name, window, bucket, order, ...extra } });
  const late = p.overdue + p.past_limit;
  const c = useTheme();
  return (
    <View style={{ borderColor: c.rule, borderTopWidth: first ? 0 : StyleSheet.hairlineWidth }}>
      <TapRow first tone={late ? "bad" : p.due_soon ? "warn" : "good"} title={p.name} right="Open POs" onPress={() => open()} />
      <View style={st.stats}>
        {role === "crm" ? (
          <>
            <Stat n={p.todo} label="to call today" />
            {AGE.map(([k, b, label]) => (p[k] as number) > 0 && (
              <Stat key={b} n={p[k] as number} label={label} bad={b !== "due_soon"} onPress={() => open({ bucket: b })} />
            ))}
          </>
        ) : (
          <>
            <Stat n={p.open} label={`open · ${inrShort(p.open_amt)}`} />
            {p.past_limit > 0 && <Stat n={p.past_limit} label="at risk (11+ days)" bad onPress={() => open({ bucket: "past_limit" })} />}
            <Stat n={`${p.cancel_pct.toFixed(1)}%`} label="cancelled" bad={p.cancelled > 0} />
            <Stat n={`${Math.round(p.paid_pct)}%`} label="paid" />
          </>
        )}
        {p.stale > 0 && <Stat n={p.stale} label="follow-up due" bad onPress={() => open({ focus: "stale", bucket: "" })} />}
        <Stat n={`${Math.round(p.compliance)}%`} label={`daily calls made${p.fu_missed ? ` (${p.fu_missed} missed)` : ""}`} bad={p.compliance < 80} />
        <Stat n="Report" label="›" onPress={() => router.push({ pathname: "/po-report", params: { role, name: p.name, window } })} />
      </View>
    </View>
  );
}

export default function Payments() {
  const [window, setWindow] = useState("60d");
  const [bucket, setBucket] = useState("");
  const [role, setRole] = useState<Role>("crm");
  const [order, setOrder] = useState("oldest");
  const q = useDashboard<PoOverview>("/po", { window, bucket });
  return (
    <Screen
      title="PO follow-up"
      q={q}
      lede={(d) => {
        const late = Number(d.kpis.find((k) => k.id === "late")?.value ?? 0);
        return (
          <>
            Payment is due {d.rules.due_days} days after the PO goes to the client, {d.rules.limit_days} at most.
            {late ? <> <Em bad>{late} POs overdue.</Em></> : ""}
          </>
        );
      }}
      filters={(d) => (
        <>
          <ChipRow items={d.windows.map((w) => [w.key, w.label])} value={window} onChange={(v) => { setWindow(v); setBucket(""); }} required />
        </>
      )}
    >
      {(d) => {
        const people = d.people[role];
        const paid = d.kpis.find((k) => k.id === "paid_today");
        const open = d.buckets.filter((b) => b.key !== "not_sent").reduce((n, b) => n + b.count, 0);
        return (
          <View style={{ gap: 14 }}>
            <Notices items={d.notices.filter((n) => n.kind !== "info")} />
            <Panel title="How long POs have waited" sub={`${open} open POs. Tap a box to see only those.${paid ? ` Paid today: ${paid.value} (${paid.hint}).` : ""}`}>
              <View style={st.buckets}>
                {d.buckets.map((b) => (
                  <View key={b.key} style={st.bucketCell}>
                    <Bucket b={b} on={bucket === b.key} onPress={() => setBucket(bucket === b.key ? "" : b.key)} />
                  </View>
                ))}
              </View>
              <T v="small" style={{ marginTop: 8 }}>History read from {d.window.start}, plus {d.window.older_open} older open POs.</T>
            </Panel>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              <Toggle label="Calling team" on={role === "crm"} onPress={() => setRole("crm")} />
              <Toggle label="Sales people" on={role === "sp"} onPress={() => setRole("sp")} />
              <Toggle label={order === "oldest" ? "Oldest first ↑" : "Newest first ↓"} on={false} onPress={() => setOrder(order === "oldest" ? "newest" : "oldest")} />
            </View>
            <SendAllButton startRole={role} />
            <Panel
              title={role === "crm" ? "Calling team" : "Sales people"}
              sub={`Tap a name for their POs${bucket ? ` (${d.buckets.find((b) => b.key === bucket)?.label})` : ""}, or a red figure for exactly those POs.`}
              flush
            >
              {people.length ? (
                people.map((p, i) => <Person key={p.name} p={p} role={role} window={window} bucket={bucket} order={order} first={i === 0} />)
              ) : (
                <View style={{ padding: 16 }}><T>No one has open POs in this selection.</T></View>
              )}
            </Panel>
            {d.notices.some((n) => n.kind === "info") && (
              <Panel title="Data checks">
                <Notices items={d.notices.filter((n) => n.kind === "info")} />
              </Panel>
            )}
          </View>
        );
      }}
    </Screen>
  );
}

const st = StyleSheet.create({
  buckets: { flexDirection: "row", flexWrap: "wrap", marginHorizontal: -4, rowGap: 8 },
  bucketCell: { width: "50%", paddingHorizontal: 4 },
  bucket: { borderRadius: 12, padding: 12, gap: 2, borderWidth: 1.5, minHeight: 96 },
  stats: { flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: 16, paddingBottom: 14, marginTop: -4 },
});

/* Today: every sheet at a glance (orders, PO follow-up, enquiries) and who must act, worst first. Tap a card or a
   line to see what is behind it. */
import Ionicons from "@expo/vector-icons/Ionicons";
import { router, type Href } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Dot, TapRow, type Tone3 } from "../../components/Rows";
import { Em, Screen } from "../../components/Screen";
import { Card, Notices, Panel, T } from "../../components/ui";
import { fmtKpi } from "../../lib/format";
import { actionHref } from "../../lib/links";
import { useDashboard } from "../../lib/query";
import { font, useTheme } from "../../lib/theme";
import type { EnquiriesData, HomeData, Kpi, PoOverview } from "../../lib/types";

type Stat = { label: string; value: string; hint?: string };

const kv = (k: Kpi | undefined) => {
  if (!k) return "—";
  const f = fmtKpi(k.value, k.format);
  return `${f.value}${f.unit ? ` ${f.unit}` : ""}`;
};

function SheetCard({ title, to, tone, line, stats }: { title: string; to: Href; tone: Tone3; line: string; stats: Stat[] }) {
  const c = useTheme();
  return (
    <Pressable onPress={() => router.navigate(to)} accessibilityRole="button" style={({ pressed }) => [{ opacity: pressed ? 0.85 : 1 }]}>
      <Card style={{ gap: 10 }}>
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <T v="label" style={{ flex: 1 }}>CRM</T>
          <Ionicons name="chevron-forward" size={18} color={c.faint} />
        </View>
        <Text style={{ fontFamily: font.display, fontSize: 24, lineHeight: 30, color: c.brand }}>{title}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Dot tone={tone} />
          <T v="strong" color={tone === "bad" ? c.neg : tone === "warn" ? c.warn : c.pos} style={{ flex: 1 }}>{line}</T>
        </View>
        <View style={[st.stats, { borderColor: c.rule }]}>
          {stats.map((x) => (
            <View key={x.label} style={st.stat}>
              <T v="label" numberOfLines={1}>{x.label}</T>
              <T v="strong" style={{ fontSize: 18 }}>{x.value}</T>
              {!!x.hint && <T v="small" style={{ fontSize: 11.5 }} numberOfLines={1}>{x.hint}</T>}
            </View>
          ))}
        </View>
      </Card>
    </Pressable>
  );
}

export default function Today() {
  const q = useDashboard<HomeData>("/home");
  const pay = useDashboard<PoOverview>("/po");
  const enq = useDashboard<EnquiriesData>("/enquiries");
  return (
    <Screen
      title="Today"
      q={q}
      lede={(d) => {
        const late = Number(d.kpis.find((k) => k.id === "late")?.value ?? 0);
        return (
          <>
            <Em>{d.close.done} of {d.close.received}</Em> of today&apos;s orders done
            {d.close.backlog ? <>, <Em bad>{d.close.backlog} left from earlier days</Em></> : ""}
            {late ? <>, <Em bad>{late} late</Em></> : ""}.
          </>
        );
      }}
    >
      {(d) => {
        const cl = d.close;
        const orderTone: Tone3 = cl.backlog > 0 || (cl.after_cutoff && cl.pending > 0) ? "bad" : cl.pending > 0 ? "warn" : "good";
        const pk = (id: string) => pay.data?.kpis.find((k) => k.id === id);
        const late7 = Number(pk("late")?.value ?? 0);
        const ek = (id: string) => enq.data?.kpis.find((k) => k.id === id);
        const notPicked = Number(ek("notpicked")?.value ?? 0);
        return (
          <View style={{ gap: 14 }}>
            <Notices items={d.notices} />
            <SheetCard
              title="Orders"
              to="/orders"
              tone={orderTone}
              line={cl.pending === 0 && cl.backlog === 0 ? "All bills done" : cl.backlog > 0 ? `${cl.backlog} left from earlier days` : `${cl.pending} still to do today`}
              stats={[
                { label: "Done today", value: `${cl.done} of ${cl.received}` },
                { label: "Earlier days", value: cl.backlog === 0 ? "none" : String(cl.backlog) },
                { label: "Late", value: kv(d.kpis.find((k) => k.id === "late")) },
              ]}
            />
            {pay.data && (
              <SheetCard
                title="PO follow-up"
                to="/payments"
                tone={late7 > 0 ? "bad" : Number(pk("soon")?.value ?? 0) > 0 ? "warn" : "good"}
                line={late7 > 0 ? `${late7} POs overdue for payment` : "No PO is overdue"}
                stats={[
                  { label: "Open POs", value: kv(pk("open")), hint: pk("open")?.hint },
                  { label: "Due in 7 days", value: kv(pk("soon")), hint: pk("soon")?.hint },
                  { label: "Overdue", value: kv(pk("late")), hint: pk("late")?.hint },
                ]}
              />
            )}
            {enq.data && (
              <SheetCard
                title="Enquiries"
                to="/enquiries"
                tone={notPicked > 0 ? "warn" : "good"}
                line={notPicked > 0 ? `${notPicked} not picked up yet` : "Every recent enquiry is picked up"}
                stats={[
                  { label: "Today", value: kv(ek("today")) },
                  { label: "Open now", value: kv(ek("open")) },
                  { label: "Older than 30 days", value: kv(ek("old")) },
                ]}
              />
            )}
            <Panel title="Needs action" sub="Who must act, worst first. Tap a line to see what is behind it." flush>
              {d.actions.length ? (
                d.actions.map((a, i) => (
                  <TapRow
                    key={`${a.who}-${a.stage}-${i}`}
                    first={i === 0}
                    tone={a.tone}
                    title={a.who}
                    sub={a.what}
                    right={a.oldest_days > 0 && a.tone !== "good" ? `oldest ${a.oldest_days} days` : undefined}
                    onPress={() => router.push(actionHref(a))}
                  />
                ))
              ) : (
                <View style={{ padding: 16 }}>
                  <T>Nobody needs to act right now.</T>
                </View>
              )}
            </Panel>
          </View>
        );
      }}
    </Screen>
  );
}

const st = StyleSheet.create({
  stats: { flexDirection: "row", gap: 8, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10 },
  stat: { flex: 1, gap: 2 },
});

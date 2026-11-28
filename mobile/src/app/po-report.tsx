/* One person's PO report: open and late POs, paid %, days to pay, ages, follow-up discipline, cancellations and the
   most overdue POs. "Share summary" sends the WhatsApp-ready text through the phone's share sheet. */
import { useLocalSearchParams } from "expo-router";
import { Share, StyleSheet, View } from "react-native";
import { Screen } from "../components/Screen";
import { Button, Panel, T } from "../components/ui";
import { inrShort } from "../lib/format";
import { useDashboard } from "../lib/query";
import { useTheme } from "../lib/theme";
import type { PoReport } from "../lib/types";

function Line({ label, value, extra, bad }: { label: string; value: string | number; extra?: string; bad?: boolean }) {
  const c = useTheme();
  return (
    <View style={[st.line, { borderColor: c.rule }]}>
      <T style={{ flex: 1 }}>{label}</T>
      <View style={{ alignItems: "flex-end" }}>
        <T v="strong" color={bad ? c.neg : undefined}>{value}</T>
        {!!extra && <T v="small">{extra}</T>}
      </View>
    </View>
  );
}

function Tile({ n, label, extra, bad }: { n: string | number; label: string; extra?: string; bad?: boolean }) {
  const c = useTheme();
  return (
    <View style={[st.tile, { backgroundColor: c.sheet, borderColor: c.sheetEdge }]}>
      <T v="kpi" color={bad ? c.neg : undefined}>{n}</T>
      <T v="label">{label}</T>
      {!!extra && <T v="small">{extra}</T>}
    </View>
  );
}

export default function PoReportScreen() {
  const p = useLocalSearchParams<{ role: "crm" | "sp"; name: string; window?: string }>();
  const q = useDashboard<PoReport>("/po/report", { role: p.role === "sp" ? "sp" : "crm", name: p.name, window: p.window ?? "60d" });
  return (
    <Screen title={`${p.name}: report`} inStack q={q} lede={(r) => <>{r.role_label} · PO follow-up report</>}>
      {(r) => (
        <View style={{ gap: 14 }}>
          <Button label="Share summary" kind="primary" onPress={() => void Share.share({ message: r.summary }).catch(() => undefined)} />
          <View style={st.tiles}>
            <Tile n={r.open.count} label="open POs" extra={inrShort(r.open.amount)} />
            <Tile n={r.late.count} label="overdue or past limit" extra={inrShort(r.late.amount)} bad={r.late.count > 0} />
            <Tile n={`${r.paid_pct}%`} label="paid (by value)" extra={`${r.paid.count} POs · ${inrShort(r.paid.amount)}`} />
            <Tile n={r.days_to_pay == null ? "—" : Math.round(r.days_to_pay)} label="days to pay (median)" extra={`${r.cancelled.count} cancelled`} />
          </View>
          <Panel title="Unpaid POs by age">
            {r.ages.map((a) => (
              <Line key={a.key} label={a.label} value={a.count} extra={inrShort(a.amount)} bad={(a.key === "past_limit" || a.key === "overdue") && a.count > 0} />
            ))}
          </Panel>
          <Panel title="Last 30 days">
            <Line label="POs sent" value={r.recent.sent} extra={inrShort(r.recent.sent_amount)} />
            <Line label="Paid" value={r.recent.paid} extra={`${inrShort(r.recent.paid_amount)} · ${r.recent.paid_pct}%`} />
          </Panel>
          <Panel title="Follow-up">
            <Line label="Follow-up due today" value={r.followup.not_followed_up} bad={r.followup.not_followed_up > 0} />
            <Line label="Never called" value={r.followup.never_called} bad={r.followup.never_called > 0} />
            <Line label="Average calls per client" value={r.followup.calls_per_client} extra={`${r.followup.calls_per_po} per PO`} />
            <Line label="Follow-ups per open PO" value={r.followup.avg_calls} />
            {r.followup.on_hold > 0 && <Line label="On hold (part payment)" value={r.followup.on_hold} />}
          </Panel>
          <Panel title="Daily follow-up discipline">
            <Line label="Daily calls made" value={`${r.discipline.compliance_pct}%`} extra={`${r.discipline.done} of ${r.discipline.expected}`} bad={r.discipline.compliance_pct < 80} />
            <Line label="Missed days" value={r.discipline.missed} extra="Sundays not counted" />
            <Line label="Escalated: 5–7 · 8–10 · 11+ days" value={`${r.discipline.escalated.l1} · ${r.discipline.escalated.l2} · ${r.discipline.escalated.l3}`} />
            {r.discipline.worst.map((w) => (
              <Line key={w.so} label={`${w.client} · ${w.so}`} value={`${w.missed} missed`} extra={`of ${w.expected} daily calls`} bad />
            ))}
          </Panel>
          <Panel title="Cancellations">
            <Line label="Cancelled POs" value={r.cancellations.count} extra={`${inrShort(r.cancellations.amount)} · ${r.cancellations.rate_pct}% of ${r.cancellations.pos}`} bad={r.cancellations.count > 0} />
            <Line label="At risk (11+ days, unpaid)" value={r.cancellations.at_risk.count} extra={inrShort(r.cancellations.at_risk.amount)} bad={r.cancellations.at_risk.count > 0} />
            {r.cancellations.recent.map((x) => (
              <Line key={x.so} label={`${x.client} · ${x.so}`} value={inrShort(x.amount)} extra={`made ${x.made}${x.note ? ` · “${x.note}”` : ""}`} />
            ))}
          </Panel>
          {r.worst.length > 0 && (
            <Panel title="Most overdue POs">
              {r.worst.map((w) => (
                <Line key={w.so} label={`${w.client} · ${w.so}`} value={inrShort(w.amount)} extra={`Day ${w.day} · called ${w.calls}×${w.note ? ` · “${w.note}”` : ""}`} bad />
              ))}
            </Panel>
          )}
          {r.split.length > 0 && (
            <Panel title={r.role === "sp" ? "Who is calling their clients" : "Whose clients they call"}>
              {r.split.map((x) => (
                <Line key={x.name} label={x.name} value={`${x.open} open · ${inrShort(x.amount)}`} extra={`${x.late} late · ${x.stale} not followed up`} />
              ))}
            </Panel>
          )}
        </View>
      )}
    </Screen>
  );
}

const st = StyleSheet.create({
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: { width: "47.5%", borderRadius: 14, borderWidth: StyleSheet.hairlineWidth, padding: 14, gap: 4 },
  line: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 9, borderTopWidth: StyleSheet.hairlineWidth },
});

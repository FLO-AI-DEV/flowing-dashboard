/* One caller's (or sales person's) open POs: client, amount, how long, the last note and what to do, with a Call button
   for each client. The calling team also sees today's progress and a call list by client (one call covers all of a
   client's POs). */
import Ionicons from "@expo/vector-icons/Ionicons";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { ChipRow } from "../components/Chips";
import { Em, Screen } from "../components/Screen";
import { SendButton } from "../components/SendSheet";
import { Button, Card, Empty, Panel, T } from "../components/ui";
import { inrShort } from "../lib/format";
import { useDashboard } from "../lib/query";
import { font, useTheme } from "../lib/theme";
import type { Cell, PoPerson } from "../lib/types";

const FOCUS: [string, string][] = [["", "All"], ["stale", "Follow-up due"]];
const BOX: Record<string, string> = { on_track: "0–4 days", due_soon: "5–7 days", overdue: "8–10 days", past_limit: "11+ days", not_sent: "PO not sent" };
const SCOPES: [string, string][] = [["todo", "To do today"], ["stale", "Follow-up due"], ["escalated", "Escalated (8+ days)"], ["all", "All open"]];

function phoneOf(v: Cell): string {
  return String(v ?? "").split(/\s{2,}|\//)[0].replace(/[^\d+]/g, "");
}

function CallButton({ phone }: { phone: string }) {
  const c = useTheme();
  if (phone.length < 8) return null;
  return (
    <Pressable
      onPress={() => void Linking.openURL(`tel:${phone}`)}
      accessibilityRole="button"
      accessibilityLabel={`Call ${phone}`}
      style={({ pressed }) => [st.call, { backgroundColor: pressed ? c.pressed : c.accentSoft }]}
    >
      <Ionicons name="call" size={15} color={c.accent} />
      <Text style={{ fontFamily: font.uiBold, fontSize: 13, color: c.accent }}>{phone}</Text>
    </Pressable>
  );
}

export default function PoPersonScreen() {
  const c = useTheme();
  const p = useLocalSearchParams<{ role: "crm" | "sp"; name: string; window?: string; bucket?: string; order?: string; focus?: string }>();
  const role = p.role === "sp" ? "sp" : "crm";
  const [bucket, setBucket] = useState(p.bucket ?? "");
  const [focus, setFocus] = useState(p.focus ?? "");
  const [allCalls, setAllCalls] = useState(false);
  const q = useDashboard<PoPerson>("/po/person", { role, name: p.name, window: p.window ?? "60d", bucket, order: p.order ?? "oldest", focus });
  const startScope = focus === "stale" ? "stale" : bucket ? `b:${bucket}` : role === "crm" ? "todo" : "all";
  return (
    <Screen
      title={p.name}
      inStack
      q={q}
      lede={(d) => (
        <>
          {d.role_label}: <Em bad={d.count > 0}>{d.count} PO{d.count === 1 ? "" : "s"}</Em> in this list
          {role === "crm" && d.progress.total > 0 ? <>, <Em>{d.progress.done} of {d.progress.total}</Em> followed up today</> : ""}.
        </>
      )}
      filters={() => (
        <>
          <ChipRow items={FOCUS} value={focus} onChange={(v) => { setFocus(v); if (v) setBucket(""); }} required />
          <ChipRow items={Object.entries(BOX)} value={bucket} onChange={(v) => { setBucket(v); if (v) setFocus(""); }} />
          <SendButton
            cause="payment"
            group={`${role}:${p.name}`}
            noun="PO"
            names={[String(p.name)]}
            startScope={startScope}
            scopes={bucket ? [[`b:${bucket}`, `These POs (${BOX[bucket] ?? bucket})`], ...SCOPES] : SCOPES}
          />
        </>
      )}
    >
      {(d) => {
        const cols = d.table.columns.map((x) => x.key);
        const ix = (k: string) => cols.indexOf(k);
        const pct = d.progress.total ? Math.round((d.progress.done / d.progress.total) * 100) : 0;
        return (
          <View style={{ gap: 14 }}>
            {role === "crm" && d.progress.total > 0 && (
              <View style={{ gap: 6 }}>
                <View style={[st.bar, { backgroundColor: c.well }]}>
                  <View style={{ width: `${pct}%`, height: "100%", backgroundColor: c.pos, borderRadius: 4 }} />
                </View>
                <T v="small">
                  {d.progress.done} of {d.progress.total} done today
                  {d.call_clients.length ? ` · ${d.call_clients.length} client${d.call_clients.length === 1 ? "" : "s"} to call` : ""}
                </T>
              </View>
            )}
            {role === "crm" && d.call_clients.length > 0 && (
              <Panel title="Call list by client" sub="One call covers all of a client's POs">
                <View style={{ gap: 12 }}>
                  {(allCalls ? d.call_clients : d.call_clients.slice(0, 5)).map((cc) => (
                    <View key={cc.client} style={{ gap: 4 }}>
                      <T v="strong">{cc.client}</T>
                      <T v="small">{inrShort(cc.amount)} · {cc.pos} PO{cc.pos === 1 ? "" : "s"} ({cc.so.join(", ")}) · oldest day {cc.day}</T>
                      <View style={{ flexDirection: "row" }}><CallButton phone={phoneOf(cc.phone)} /></View>
                    </View>
                  ))}
                  {d.call_clients.length > 5 && (
                    <Button label={allCalls ? "Show fewer" : `Show all ${d.call_clients.length} clients`} kind="ghost" onPress={() => setAllCalls(!allCalls)} />
                  )}
                </View>
              </Panel>
            )}
            {!d.table.rows.length ? (
              <Empty title="Nothing here" text={`No POs match this filter for ${d.name}.`} />
            ) : (
              d.table.rows.map((r, i) => {
                const state = d.table.states[i];
                const tone = state === "late" ? c.neg : state === "due" ? c.warn : c.pos;
                const last = String(r[ix("Last note")] ?? "");
                const level = String(r[ix("Level")] ?? "");
                const promised = String(r[ix("Promised")] ?? "");
                const part = Number(r[ix("Part paid ₹")] ?? 0);
                const missed = Number(r[ix("Missed")] ?? 0);
                return (
                  <Card key={i} style={{ gap: 6, borderLeftWidth: 4, borderLeftColor: tone, opacity: d.table.done[i] ? 0.7 : 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
                      <View style={{ flex: 1 }}>
                        <T v="strong">{String(r[ix("Client")])}</T>
                        <T v="small">{String(r[ix("PO")])}</T>
                      </View>
                      <View style={{ alignItems: "flex-end" }}>
                        <T v="strong">{inrShort(Number(r[ix("Amount ₹")]))}</T>
                        <T v="small" color={tone} style={{ fontFamily: font.uiBold }}>
                          Day {String(r[ix("Day")])}{level ? ` · ${level}` : ""}
                        </T>
                      </View>
                    </View>
                    <T v="small" color={tone}>{String(r[ix("Timer")])}</T>
                    <T v="small">
                      Follow-ups: {String(r[ix("Calls")] ?? 0)} · next #{String(r[ix("Next")] ?? "").replace("#", "")}
                      {missed > 0 ? ` · ${missed} daily call${missed === 1 ? "" : "s"} missed` : ""} · last: {String(r[ix("Last follow-up")])}
                      {last ? ` · “${last}”` : " · never followed up"}
                      {promised ? ` · promised ${promised}` : ""}
                      {part > 0 ? ` · part paid ${inrShort(part)} (on hold)` : ""}
                    </T>
                    <T>
                      {d.table.done[i] ? "Followed up today · " : ""}
                      {String(r[ix("What to do")])} · {role === "crm" ? "sold by " : "called by "}
                      <Text style={{ fontFamily: font.uiBold }}>{String(r[ix(role === "crm" ? "Sales person" : "CRM member")] ?? "")}</Text>
                    </T>
                    <View style={{ flexDirection: "row" }}><CallButton phone={phoneOf(r[ix("Phone")])} /></View>
                  </Card>
                );
              })
            )}
          </View>
        );
      }}
    </Screen>
  );
}

const st = StyleSheet.create({
  bar: { height: 8, borderRadius: 4, overflow: "hidden" },
  call: { flexDirection: "row", alignItems: "center", gap: 6, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, marginTop: 2 },
});

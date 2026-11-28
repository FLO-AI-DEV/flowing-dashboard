/* WhatsApp reminders from the phone, the same as the web's Send buttons: pick which orders / POs / enquiries, see the
   exact message and who gets it, then send. The message is added to the nudges sheet and Iris sends it from the
   company number; the order, payment and enquiry sheets are never touched. Shown only when sending is set up. */
import Ionicons from "@expo/vector-icons/Ionicons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "../lib/api";
import { useNudgeWho } from "../lib/query";
import { font, useTheme } from "../lib/theme";
import type { NudgeAllPreview, NudgeAllResult, NudgePreview } from "../lib/types";
import { ChipRow } from "./Chips";
import { Button, Card, T } from "./ui";

export const SCOPES: [string, string][] = [
  ["today", "Today"],
  ["week", "Yesterday – 7 days"],
  ["month", "8 – 30 days"],
  ["older", "Older than 30 days"],
];

const post = <T,>(path: string, body: object) => api<T>(path, undefined, { method: "POST", body, timeoutMs: 60_000 });

function Sheet({ open, title, onClose, testMode, children }: { open: boolean; title: string; onClose: () => void; testMode: boolean; children: React.ReactNode }) {
  const c = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={open} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.frame }}>
        <View style={[st.head, { borderColor: c.rule }]}>
          <View style={{ flex: 1 }}>
            <Text style={{ fontFamily: font.display, fontSize: 24, color: c.brand }}>{title}</Text>
            {testMode && <T v="small" color={c.warn}>Test mode: nothing is really sent</T>}
          </View>
          <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button" accessibilityLabel="Close">
            <Ionicons name="close" size={26} color={c.ink} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={{ padding: 16, gap: 14, paddingBottom: 24 + insets.bottom }}>{children}</ScrollView>
      </View>
    </Modal>
  );
}

function OpenButton({ label, onPress }: { label: string; onPress: () => void }) {
  return <Button label={label} onPress={onPress} icon={<Ionicons name="logo-whatsapp" size={18} color="#25D366" />} />;
}

/** "Send to Mona": one cause (reply / po / bill / hold / enquiry / payment) to the people the Staff tab names. */
export function SendButton({ cause, group, noun = "order", startScope = "today", scopes = SCOPES, names }: {
  cause: string;
  group?: string;
  noun?: string;
  startScope?: string;
  scopes?: [string, string][];
  /** who it goes to; defaults to the Staff tab's names for this cause */
  names?: string[];
}) {
  const c = useTheme();
  const who = useNudgeWho();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState(startScope);
  const body = { cause, scope, min_days: 0, ...(group ? { group } : {}) };
  const plural = noun === "enquiry" ? "enquiries" : `${noun}s`;
  const preview = useQuery<NudgePreview, Error>({
    queryKey: ["/nudge/preview", body],
    queryFn: () => post<NudgePreview>("/nudge/preview", body),
    enabled: open,
    retry: false,
    staleTime: 5_000,
  });
  const send = useMutation<NudgePreview, Error, boolean>({
    mutationFn: (force) => post<NudgePreview>("/nudge/send", { ...body, force }),
    onSuccess: () => void preview.refetch(),
  });
  const to = names ?? (who.data?.enabled ? who.data.who[cause] ?? [] : []);
  if (!who.data?.enabled || !to.length) return null;
  const p = preview.data;
  return (
    <>
      <OpenButton label={`Send to ${to.join(" and ")}`} onPress={() => { send.reset(); setScope(startScope); setOpen(true); }} />
      <Sheet open={open} title={`Send to ${to.join(" and ")}`} onClose={() => setOpen(false)} testMode={!!who.data.test_mode}>
        <T v="label">Which {plural}</T>
        <ChipRow items={scopes} value={scope} onChange={(v) => { send.reset(); setScope(v); }} required />
        {preview.isPending && <T v="small">Checking…</T>}
        {preview.error && <T color={c.neg}>{preview.error.message}</T>}
        {p && (
          <>
            <T v="strong">{p.count} {p.count === 1 ? noun : plural} · to {p.to.join(", ")}</T>
            {p.count > 0 ? (
              <Card><Text selectable style={{ fontFamily: font.ui, fontSize: 14, lineHeight: 20, color: c.ink }}>{p.message}</Text></Card>
            ) : (
              <T>No {plural} in this selection.</T>
            )}
            {send.error && <T color={c.neg}>{send.error.message}</T>}
            {send.data?.sent ? (
              <T color={c.pos}>Sent at {send.data.sent_at}. Iris delivers it within a minute.</T>
            ) : (
              p.count > 0 && (
                <View style={{ gap: 8 }}>
                  {p.already_sent_minutes !== null && <T color={c.warn}>Already sent {p.already_sent_minutes} min ago.</T>}
                  <Button
                    kind="primary"
                    disabled={send.isPending}
                    label={send.isPending ? "Sending…" : p.already_sent_minutes !== null ? "Send again" : `Send ${p.count} to ${to.join(" and ")}`}
                    onPress={() => send.mutate(p.already_sent_minutes !== null)}
                  />
                </View>
              )
            )}
          </>
        )}
      </Sheet>
    </>
  );
}

const ROLES: [string, string][] = [["crm", "Calling team"], ["sp", "Sales people"], ["kavita", "Kavita: escalations"]];
const ALL_SCOPES: Record<string, [string, string][]> = {
  crm: [["todo", "To call today"], ["escalated", "Escalated (8+ days)"], ["all", "All open"]],
  sp: [["escalated", "Escalated (8+ days)"], ["overdue", "Overdue"], ["all", "All open"]],
  kavita: [["escalated", "Escalated (8+ days)"]],
};

/** "Message everyone": each caller or sales person gets their own list of POs. */
export function SendAllButton({ startRole }: { startRole: "crm" | "sp" }) {
  const c = useTheme();
  const who = useNudgeWho();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<string>(startRole);
  const [scope, setScope] = useState(startRole === "crm" ? "todo" : "escalated");
  const body = { role, scope };
  const preview = useQuery<NudgeAllPreview, Error>({
    queryKey: ["/nudge/all/preview", body],
    queryFn: () => post<NudgeAllPreview>("/nudge/all/preview", body),
    enabled: open,
    retry: false,
    staleTime: 5_000,
  });
  const send = useMutation<NudgeAllResult, Error, boolean>({
    mutationFn: (force) => post<NudgeAllResult>("/nudge/all/send", { ...body, force }),
    onSuccess: () => void preview.refetch(),
  });
  if (!who.data) return null;
  if (!who.data.enabled) return <T v="small">WhatsApp messages are off (no nudges sheet is set up on the server).</T>;
  const p = preview.data;
  const r = send.data;
  const again = !!p?.items.some((i) => i.already_sent_minutes !== null);
  return (
    <>
      <OpenButton label="Message everyone" onPress={() => { send.reset(); setRole(startRole); setScope(startRole === "crm" ? "todo" : "escalated"); setOpen(true); }} />
      <Sheet open={open} title="Message everyone" onClose={() => setOpen(false)} testMode={!!who.data.test_mode}>
        <ChipRow items={ROLES} value={role} onChange={(v) => { send.reset(); setRole(v); setScope(ALL_SCOPES[v][0][0]); }} required />
        {role !== "kavita" && <ChipRow items={ALL_SCOPES[role]} value={scope} onChange={(v) => { send.reset(); setScope(v); }} required />}
        {preview.isPending && <T v="small">Checking…</T>}
        {preview.error && <T color={c.neg}>{preview.error.message}</T>}
        {p && (
          <>
            <T v="strong">{p.items.length} {p.items.length === 1 ? "person has" : "people have"} POs in this list · {p.ready} can be messaged</T>
            {p.missing.length > 0 && <T color={c.warn}>Not in the Staff tab (no message): {p.missing.join(", ")}.</T>}
            {p.items.map((i) => (
              <Card key={i.group} style={{ gap: 6 }}>
                <T v="strong">
                  {i.name} · {i.count} PO{i.count === 1 ? "" : "s"}
                  {!i.ready ? " · no number" : ""}
                  {i.already_sent_minutes !== null ? ` · sent ${i.already_sent_minutes} min ago` : ""}
                </T>
                {!!i.message && <Text selectable style={{ fontFamily: font.ui, fontSize: 13.5, lineHeight: 19, color: c.ink2 }}>{i.message}</Text>}
              </Card>
            ))}
            {send.error && <T color={c.neg}>{send.error.message}</T>}
            {r ? (
              <T color={c.pos}>
                Sent to {r.sent.length}: {r.sent.join(", ") || "nobody"} at {r.sent_at}.
                {r.skipped_recent.length > 0 ? ` Skipped (sent in the last 30 minutes): ${r.skipped_recent.join(", ")}.` : ""} Iris delivers within a minute.
              </T>
            ) : (
              p.ready > 0 && (
                <View style={{ gap: 8 }}>
                  {again && <T color={c.warn}>Some of these were sent recently and are skipped unless you send again.</T>}
                  <Button kind="primary" disabled={send.isPending} label={send.isPending ? "Sending…" : `Send to ${p.ready} ${p.ready === 1 ? "person" : "people"}`} onPress={() => send.mutate(false)} />
                  {again && <Button disabled={send.isPending} label="Send all again" onPress={() => send.mutate(true)} />}
                </View>
              )
            )}
          </>
        )}
      </Sheet>
    </>
  );
}

const st = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingTop: 18, paddingBottom: 12, borderBottomWidth: StyleSheet.hairlineWidth },
});

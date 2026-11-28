/* Tappable list rows used on every Flo-Wing screen: "who must act", "what is holding things up", enquiry groups, the
   calling team. A coloured dot says how urgent (red late, amber needs a look, green clear). */
import Ionicons from "@expo/vector-icons/Ionicons";
import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { font, useTheme } from "../lib/theme";
import { T } from "./ui";

export type Tone3 = "bad" | "warn" | "good" | "none";

export function Dot({ tone }: { tone: Tone3 }) {
  const c = useTheme();
  if (tone === "none") return null;
  const color = tone === "bad" ? c.neg : tone === "warn" ? c.warn : c.pos;
  return <View style={[st.dot, { backgroundColor: color }]} />;
}

export function TapRow({ title, sub, right, tone = "none", onPress, first, children }: {
  title: string;
  sub?: ReactNode;
  right?: string;
  tone?: Tone3;
  onPress?: () => void;
  first?: boolean;
  children?: ReactNode;
}) {
  const c = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : undefined}
      style={({ pressed }) => [st.row, { borderColor: c.rule, borderTopWidth: first ? 0 : StyleSheet.hairlineWidth, backgroundColor: pressed ? c.pressed : "transparent" }]}
    >
      <Dot tone={tone} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ fontFamily: font.uiBold, fontSize: 15, lineHeight: 20, color: c.ink }}>{title}</Text>
        {typeof sub === "string" ? <T v="small">{sub}</T> : sub}
        {children}
      </View>
      {!!right && <T v="small" style={{ fontFamily: font.uiMedium, textAlign: "right", maxWidth: 110 }}>{right}</T>}
      {onPress && <Ionicons name="chevron-forward" size={18} color={c.faint} />}
    </Pressable>
  );
}

/** A small figure chip inside a row: "62 to call today". Tappable when it opens a list. */
export function Stat({ n, label, bad, onPress }: { n: string | number; label: string; bad?: boolean; onPress?: () => void }) {
  const c = useTheme();
  const body = (
    <Text style={{ fontFamily: font.ui, fontSize: 13, color: bad ? c.neg : c.ink2 }}>
      <Text style={{ fontFamily: font.uiBold, color: bad ? c.neg : c.ink }}>{n}</Text> {label}
    </Text>
  );
  if (!onPress) return <View style={[st.stat, { backgroundColor: c.well }]}>{body}</View>;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={({ pressed }) => [st.stat, { backgroundColor: pressed ? c.pressed : c.well, borderColor: bad ? c.neg : c.controlEdge, borderWidth: StyleSheet.hairlineWidth }]}>
      {body}
    </Pressable>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 13 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  stat: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 5 },
});

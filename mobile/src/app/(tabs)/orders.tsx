/* Orders: are today's orders done, and what is holding up the rest (Mona's reply, PO, billing, on hold). Tap a cause
   for every order behind it, or open the full list with filters. */
import { router } from "expo-router";
import { StyleSheet, View } from "react-native";
import { TapRow } from "../../components/Rows";
import { Em, Screen } from "../../components/Screen";
import { Button, Card, Panel, T } from "../../components/ui";
import { useDashboard } from "../../lib/query";
import { useTheme } from "../../lib/theme";
import type { DailyClose, HomeData } from "../../lib/types";

const OLD_DAYS = 45;

function CloseCard({ c: cl }: { c: DailyClose }) {
  const c = useTheme();
  const pct = cl.received ? Math.round((100 * cl.done) / cl.received) : 100;
  const clear = cl.pending === 0 && cl.backlog === 0;
  const bad = !clear && (cl.after_cutoff || cl.backlog > 0);
  const line = clear
    ? "Everything is done. Fresh start tomorrow."
    : cl.after_cutoff
      ? `${cl.pending} of today's orders were not done by ${cl.cutoff}${cl.backlog ? `, and ${cl.backlog} are left from earlier days` : ""}.`
      : `${cl.pending} of today's orders still to do before ${cl.cutoff}${cl.backlog ? `. ${cl.backlog} are left from earlier days` : ""}.`;
  return (
    <Card style={{ gap: 10 }}>
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: 6 }}>
        <T v="kpi" style={{ fontSize: 34, lineHeight: 40 }}>{cl.done}</T>
        <T>of {cl.received} done today</T>
      </View>
      <T v="strong" color={clear ? c.pos : bad ? c.neg : c.warn}>{line}</T>
      <View style={[st.bar, { backgroundColor: c.well }]}>
        <View style={{ width: `${pct}%`, height: "100%", borderRadius: 4, backgroundColor: clear ? c.pos : bad ? c.neg : c.warn }} />
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 14 }}>
        {cl.by_channel.map((ch) => (
          <T key={ch.channel} v="small">
            {ch.channel} <T v="strong" style={{ fontSize: 13 }}>{ch.done}/{ch.received}</T>
          </T>
        ))}
        <T v="small" color={cl.backlog ? c.neg : c.pos}>Earlier days: {cl.backlog === 0 ? "none left" : cl.backlog}</T>
      </View>
    </Card>
  );
}

export default function Orders() {
  const q = useDashboard<HomeData>("/home");
  return (
    <Screen
      title="Orders"
      q={q}
      lede={() => (
        <>
          Are today&apos;s orders done, and what is holding up the rest. <Em>Tap a cause</Em> to see the orders.
        </>
      )}
    >
      {(d) => (
        <View style={{ gap: 14 }}>
          <CloseCard c={d.close} />
          <Panel title="What is holding things up" sub="Tap a cause to open every order behind it" flush>
            {d.close.wrong.length ? (
              d.close.wrong.map((w, i) => (
                <TapRow
                  key={w.key}
                  first={i === 0}
                  tone={w.backlog > 0 ? "bad" : w.today > 0 ? "warn" : "good"}
                  title={w.label}
                  sub={[w.backlog > 0 ? `${w.backlog} from earlier days` : "", w.today > 0 ? `${w.today} today` : "", w.oldest_days > 0 ? `oldest ${w.oldest_days} days` : ""].filter(Boolean).join(" · ")}
                  right={w.who}
                  onPress={() => router.push({ pathname: "/cause/[key]", params: { key: w.key, label: w.label } })}
                />
              ))
            ) : (
              <View style={{ padding: 16 }}>
                <T v="title">Nothing is stuck</T>
                <T>Every order up to today is done.</T>
              </View>
            )}
          </Panel>
          {d.close.never_marked > 0 && (
            <T v="small">{d.close.never_marked} older orders (over {OLD_DAYS} days) were never marked billed in the sheet. They are left out here.</T>
          )}
          <Button label="See every open order" onPress={() => router.push("/orders-all")} />
        </View>
      )}
    </Screen>
  );
}

const st = StyleSheet.create({
  bar: { height: 8, borderRadius: 4, overflow: "hidden" },
});

/* A sideways-scrolling row of choice chips: periods, windows, statuses, "oldest first". One tap picks, a second tap on
   the same chip clears it (unless `required`). */
import { ScrollView } from "react-native";
import { Chip } from "./Filters";

export function ChipRow({ items, value, onChange, required }: { items: [string, string][]; value: string; onChange: (v: string) => void; required?: boolean }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 16 }} style={{ marginHorizontal: -16 }}>
      {items.map(([k, label]) => (
        <Chip key={k} label={label} on={value === k} onPress={() => onChange(value === k && !required ? "" : k)} />
      ))}
    </ScrollView>
  );
}

/** A single on / off chip, for toggles like "Oldest first ↑" and "Late only". */
export function Toggle({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  return <Chip label={label} on={on} onPress={onPress} />;
}

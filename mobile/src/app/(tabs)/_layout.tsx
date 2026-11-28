/* Bottom tabs: the four screens the team opens most (Today, Orders, PO follow-up, Enquiries); Sales returns, Team,
   Clients, the assistant and the sheets' status live under More. */
import Ionicons from "@expo/vector-icons/Ionicons";
import { Tabs } from "expo-router/js-tabs";
import type { ComponentProps } from "react";
import type { ColorValue } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { font, useTheme } from "../../lib/theme";

type Icon = ComponentProps<typeof Ionicons>["name"];

function icon(on: Icon, off: Icon) {
  return function TabIcon({ color, focused, size }: { color: ColorValue; focused: boolean; size: number }) {
    return <Ionicons name={focused ? on : off} color={color as string} size={size - 2} />;
  };
}

export default function TabsLayout() {
  const c = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: c.brand,
        tabBarInactiveTintColor: c.muted,
        tabBarLabelStyle: { fontFamily: font.uiMedium, fontSize: 11.5, lineHeight: 14 },
        tabBarStyle: { backgroundColor: c.sheet, borderTopColor: c.sheetEdge, height: 64 + insets.bottom, paddingTop: 4, paddingBottom: insets.bottom + 6 },
        sceneStyle: { backgroundColor: c.frame },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Today", tabBarIcon: icon("home", "home-outline") }} />
      <Tabs.Screen name="orders" options={{ title: "Orders", tabBarIcon: icon("clipboard", "clipboard-outline") }} />
      <Tabs.Screen name="payments" options={{ title: "PO follow-up", tabBarIcon: icon("cash", "cash-outline") }} />
      <Tabs.Screen name="enquiries" options={{ title: "Enquiries", tabBarIcon: icon("chatbubbles", "chatbubbles-outline") }} />
      <Tabs.Screen name="more" options={{ title: "More", tabBarIcon: icon("grid", "grid-outline") }} />
    </Tabs>
  );
}

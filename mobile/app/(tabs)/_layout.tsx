import { Feather } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { colors } from "@/lib/theme";

const ICONS = { index: "home", create: "edit-3", calendar: "calendar", campaigns: "trending-up", profile: "user" } as const;

export default function TabsLayout() {
  return (
    <Tabs screenOptions={({ route }) => ({
      headerShown: false,
      tabBarActiveTintColor: colors.ink,
      tabBarInactiveTintColor: colors.faint,
      tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.rule },
      tabBarIcon: ({ color, size }) => <Feather name={ICONS[route.name as keyof typeof ICONS] ?? "circle"} color={String(color)} size={size} />,
    })}>
      <Tabs.Screen name="index" options={{ title: "Home" }} />
      <Tabs.Screen name="create" options={{ title: "Create" }} />
      <Tabs.Screen name="calendar" options={{ title: "Calendar" }} />
      <Tabs.Screen name="campaigns" options={{ title: "Campaigns" }} />
      <Tabs.Screen name="profile" options={{ title: "Profile" }} />
    </Tabs>
  );
}

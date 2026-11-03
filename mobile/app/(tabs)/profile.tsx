import { useQueryClient } from "@tanstack/react-query";
import { Pressable, Text, View } from "react-native";
import { Button, Card, Screen, s } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { registerForPush } from "@/lib/push";
import { useSession } from "@/lib/session";
import { colors } from "@/lib/theme";

export default function Profile() {
  const { user, workspaceId, setWorkspace, clear, refreshToken } = useSession();
  const qc = useQueryClient();
  const { data: credits } = useApi<{ balance: number }>("/billing/credits");
  if (!user) return null;
  return (
    <Screen title="Profile" subtitle={user.email}>
      <Card>
        <Text style={s.h2}>Workspace</Text>
        {user.workspaces.map((w) => (
          <Pressable key={w.id} accessibilityRole="radio" accessibilityState={{ checked: w.id === workspaceId }} onPress={() => { setWorkspace(w.id); qc.clear(); }}
            style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.rule, flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={{ color: colors.ink, fontWeight: w.id === workspaceId ? "700" : "400" }}>{w.name}</Text>
            <Text style={s.muted}>{w.kind === "client" ? "Client" : w.kind === "agency" ? "Agency" : "Business"}</Text>
          </Pressable>
        ))}
      </Card>
      <Card>
        <Text style={s.h2}>AI credits</Text>
        <Text style={{ fontSize: 28, fontWeight: "800", color: colors.ink }}>{credits?.balance ?? "…"}</Text>
        <Text style={s.muted}>Buy credits and change plans on the web.</Text>
      </Card>
      <View style={{ gap: 10 }}>
        <Button label="Turn on notifications" onPress={() => registerForPush().catch(() => undefined)} />
        <Button label="Sign out" variant="danger" onPress={async () => {
          if (refreshToken) await api.post("/auth/logout", { refresh_token: refreshToken }).catch(() => undefined);
          qc.clear();
          clear();
        }} />
      </View>
    </Screen>
  );
}

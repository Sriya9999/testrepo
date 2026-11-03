import { formatMoney, formatNumber, type Campaign } from "@marketingos/api-client";
import { useState } from "react";
import { Alert, Text, View } from "react-native";
import { Badge, Button, Card, Empty, ErrorText, Screen, s } from "@/components/ui";
import { api, useAction, useApi } from "@/lib/api";
import { colors } from "@/lib/theme";

function Row({ c }: { c: Campaign }) {
  const [msg, setMsg] = useState("");
  const act = useAction((path: string) => api.post<{ requires_approval?: boolean }>(path));
  const t = c.last_30_days;
  const run = (path: string, label: string) => act.mutate(path, {
    onSuccess: (r) => setMsg(r?.requires_approval ? "Sent for approval." : `${label}.`), onError: (e) => setMsg(e.message) });
  return (
    <Card>
      <View style={[s.row, { justifyContent: "space-between" }]}><Text style={{ fontWeight: "700", color: colors.ink, flex: 1 }}>{c.name}</Text><Badge status={c.status} /></View>
      <Text style={s.muted}>{c.platform === "meta" ? "Meta" : "Google"} · {c.objective} · {formatMoney(c.daily_budget_minor, c.currency)}/day</Text>
      {t && (
        <View style={s.row}>
          {[["Spend", formatMoney(t.spend_minor, c.currency)], ["Clicks", formatNumber(t.clicks)], ["Results", formatNumber(t.results)], ["CPA", formatMoney(t.cpa_minor, c.currency)]].map(([k, v]) => (
            <View key={k} style={{ minWidth: "22%" }}><Text style={s.muted}>{k}</Text><Text style={{ fontWeight: "700", color: colors.ink }}>{v}</Text></View>
          ))}
        </View>
      )}
      {msg ? <Text style={s.muted}>{msg}</Text> : null}
      {c.status === "active" && <Button label="Pause" loading={act.isPending} onPress={() => Alert.alert("Pause campaign?", c.name, [{ text: "Cancel", style: "cancel" }, { text: "Pause", onPress: () => run(`/ads/${c.platform}/campaigns/${c.id}/pause`, "Pausing") }])} />}
      {c.status === "paused" && <Button label="Request activation" loading={act.isPending} onPress={() => run(`/ads/${c.platform}/campaigns/${c.id}/activate`, "Requested")} />}
    </Card>
  );
}

export default function Campaigns() {
  const meta = useApi<Campaign[]>("/ads/meta/campaigns", undefined, 60_000);
  const google = useApi<Campaign[]>("/ads/google/campaigns", undefined, 60_000);
  const all = [...(meta.data ?? []), ...(google.data ?? [])];
  return (
    <Screen title="Campaigns" subtitle="Monitor ads. Budget increases and launches always need approval.">
      <ErrorText>{meta.error?.message ?? google.error?.message}</ErrorText>
      {!all.length ? <Empty title="No campaigns yet" body="Create campaigns on the web; monitor and approve them here." /> : all.map((c) => <Row key={c.id} c={c} />)}
    </Screen>
  );
}

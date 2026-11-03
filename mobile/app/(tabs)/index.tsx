import { formatKpi, type Approval, type Kpi } from "@marketingos/api-client";
import { Link } from "expo-router";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Card, Empty, Metric, s } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useSession } from "@/lib/session";
import { colors } from "@/lib/theme";

interface Dashboard { currency: string; kpis: Record<string, Kpi>; summary: string[]; contains_demo_data: boolean; pending_approvals: Approval[]; pending_approvals_count: number;
  credits: { balance: number }; data_freshness: { name: string; error: string | null }[] }
interface Note { id: string; title: string; body: string; read: boolean; created_at: string }

export default function Home() {
  const user = useSession((st) => st.user);
  const ws = useSession((st) => user?.workspaces.find((w) => w.id === st.workspaceId));
  const { data, refetch, isRefetching } = useApi<Dashboard>("/dashboard", undefined, 60_000);
  const { data: notes } = useApi<Note[]>("/notifications", { unread: true }, 60_000);
  const k = data?.kpis;
  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={s.content} refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={() => { refetch(); }} />}>
        <Text style={s.title}>Hello{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}</Text>
        <Text style={s.subtitle}>{ws?.name} · last 30 days</Text>
        {data?.contains_demo_data && <Text style={{ backgroundColor: colors.marigoldWash, padding: 10, borderRadius: 8, color: colors.ink }}>Includes demo data.</Text>}
        <Link href="/approvals" asChild>
          <Pressable accessibilityRole="button">
            <Card accent={(data?.pending_approvals_count ?? 0) > 0}>
              <Text style={s.h2}>Waiting for your sign-off</Text>
              <Text style={{ fontSize: 34, fontWeight: "800", color: colors.ink }}>{data?.pending_approvals_count ?? "…"}</Text>
              <Text style={s.muted}>{data?.pending_approvals_count ? "Tap to review and approve." : "Nothing needs you right now."}</Text>
            </Card>
          </Pressable>
        </Link>
        {k && (
          <View style={{ flexDirection: "row", flexWrap: "wrap", backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.rule, overflow: "hidden" }}>
            {([["spend", "Ad spend"], ["conversions", "Conversions"], ["cpa", "CPA"], ["roas", "ROAS"], ["organic_traffic", "Organic traffic"], ["engagement", "Engagement"]] as const).map(([key, label]) => (
              <Metric key={key} label={label} value={formatKpi(k[key], data.currency)} change={k[key].change_pct}
                good={k[key].change_pct == null ? null : k[key].lower_is_better ? k[key].change_pct! < 0 : k[key].change_pct! > 0} />
            ))}
          </View>
        )}
        {data?.summary && <Card>{data.summary.map((line) => <Text key={line} style={{ color: colors.ink, lineHeight: 20 }}>{line}</Text>)}</Card>}
        <Text style={s.h2}>Alerts</Text>
        {notes?.length ? notes.slice(0, 8).map((n) => (
          <Card key={n.id}><Text style={{ fontWeight: "600", color: colors.ink }}>{n.title}</Text>{n.body ? <Text style={s.muted}>{n.body}</Text> : null}</Card>
        )) : <Empty title="No new alerts" />}
        {data?.data_freshness.filter((d) => d.error).map((d) => <Text key={d.name} style={{ color: colors.danger }}>{d.name}: {d.error}</Text>)}
        <Text style={s.muted}>{data?.credits.balance ?? "…"} AI credits available</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

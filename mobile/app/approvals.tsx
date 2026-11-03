import { formatMoney, type Approval } from "@marketingos/api-client";
import { Image } from "expo-image";
import { router } from "expo-router";
import { useState } from "react";
import { Alert, Text, View } from "react-native";
import { Badge, Button, Card, Empty, ErrorText, Input, Screen, s } from "@/components/ui";
import { api, useAction, useApi } from "@/lib/api";
import { colors } from "@/lib/theme";

function Item({ a }: { a: Approval }) {
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState(false);
  const decide = useAction((d: { action: string; note?: string }) => api.post(`/approvals/${a.id}/${d.action}`, { note: d.note }));
  const p = a.preview ?? {};
  const image = p.media?.[0]?.url;
  const text = p.caption ?? p.body?.caption ?? p.body?.primary_text ?? p.campaign?.config?.copy?.primary_text ?? "";
  return (
    <Card accent={a.status === "pending"}>
      <Text style={{ fontWeight: "700", color: colors.ink, fontSize: 15 }}>{a.title}</Text>
      <Text style={s.muted}>{a.action_label}{a.requested_by_agent ? ` · prepared by the ${a.requested_by_agent.replace("_", " ")} agent` : a.requested_by ? ` · from ${a.requested_by}` : ""}</Text>
      {image ? <Image source={{ uri: image }} style={{ width: "100%", aspectRatio: 1, borderRadius: 8, backgroundColor: colors.sunk }} contentFit="cover" accessibilityLabel="Post image" /> : null}
      {text ? <Text style={{ color: colors.ink2 }} numberOfLines={6}>{text}</Text> : null}
      {a.budget_impact_minor != null && <Text style={{ fontWeight: "700", color: colors.ink }}>Budget impact: {formatMoney(a.budget_impact_minor, a.currency ?? "INR")}</Text>}
      {a.ai_reasoning ? <Text style={s.muted}>Why: {a.ai_reasoning}</Text> : null}
      <ErrorText>{decide.error?.message}</ErrorText>
      {a.status !== "pending" ? <Badge status={a.status} /> : a.can_decide ? (
        asking ? (
          <View style={{ gap: 8 }}>
            <Input label="What should change?" value={note} onChangeText={setNote} multiline />
            <View style={s.row}><Button label="Send back" variant="primary" disabled={!note} loading={decide.isPending} onPress={() => decide.mutate({ action: "request-changes", note })} />
              <Button label="Cancel" onPress={() => setAsking(false)} /></View>
          </View>
        ) : (
          <View style={s.row}>
            <Button label="Approve" variant="approve" loading={decide.isPending} onPress={() => a.budget_impact_minor
              ? Alert.alert("Approve spend?", `This can spend up to ${formatMoney(a.budget_impact_minor, a.currency ?? "INR")}.`, [{ text: "Cancel", style: "cancel" }, { text: "Approve", onPress: () => decide.mutate({ action: "approve" }) }])
              : decide.mutate({ action: "approve" })} />
            <Button label="Request changes" onPress={() => setAsking(true)} />
            <Button label="Reject" variant="danger" onPress={() => decide.mutate({ action: "reject" })} />
          </View>
        )
      ) : <Text style={s.muted}>Waiting for someone who can approve this.</Text>}
    </Card>
  );
}

export default function Approvals() {
  const { data, isLoading } = useApi<Approval[]>("/approvals", { status: "pending" }, 30_000);
  return (
    <Screen title="Approvals" subtitle="What you approve is exactly what runs." right={<Button label="Done" onPress={() => router.back()} />}>
      {isLoading ? <Text style={s.muted}>Loading…</Text> : !data?.length ? <Empty title="Nothing is waiting for you" /> : data.map((a) => <Item key={a.id} a={a} />)}
    </Screen>
  );
}

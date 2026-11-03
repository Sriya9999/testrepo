import type { ContentAsset } from "@marketingos/api-client";
import { Image } from "expo-image";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { Badge, Button, Card, ErrorText, Input, Screen, s } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { colors } from "@/lib/theme";

const TYPES: [string, string, string][] = [["instagram", "post", "Instagram post"], ["instagram", "carousel", "Carousel"], ["instagram", "reel", "Reel script"],
  ["instagram", "story", "Story"], ["facebook", "ad", "Facebook ad"], ["google_ads", "search_ad", "Google ad"]];

export default function Create() {
  const [type, setType] = useState(0);
  const [topic, setTopic] = useState("");
  const [contentId, setContentId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: asset, refetch } = useApi<ContentAsset>(contentId ? `/content/${contentId}` : null, undefined, 1500);
  const [platform, format] = TYPES[type];
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setError(""); try { await fn(); await refetch(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } };
  const b = asset?.body ?? {};
  return (
    <Screen title="Create" subtitle="Generate an on-brand draft and send it for approval.">
      <View style={s.row}>
        {TYPES.map(([, , label], i) => (
          <Pressable key={label} accessibilityRole="button" accessibilityState={{ selected: i === type }} onPress={() => setType(i)}
            style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: i === type ? colors.ink : colors.rule, backgroundColor: i === type ? colors.ink : colors.surface }}>
            <Text style={{ color: i === type ? "#fff" : colors.ink }}>{label}</Text>
          </Pressable>
        ))}
      </View>
      <Input label="Topic or occasion" value={topic} onChangeText={setTopic} placeholder="Weekend special" />
      <ErrorText>{error}</ErrorText>
      <Button label="Generate" variant="primary" loading={busy || asset?.generation_status === "pending"} onPress={() => run(async () => {
        const r = await api.post<{ content_id: string }>("/content/generate", { platform, format, topic });
        setContentId(r.content_id);
      })} />
      {asset && asset.generation_status === "ready" && (
        <Card>
          <View style={[s.row, { justifyContent: "space-between" }]}><Text style={s.h2}>{asset.title}</Text><Badge status={asset.status} /></View>
          {b.media?.[0]?.url ? <Image source={{ uri: b.media[0].url }} style={{ width: "100%", aspectRatio: 1, borderRadius: 8 }} accessibilityLabel="Generated image" /> : null}
          {(b.hook || b.headline) ? <Text style={{ fontWeight: "700", color: colors.ink }}>{b.hook ?? b.headline}</Text> : null}
          <Text style={{ color: colors.ink2, lineHeight: 20 }}>{b.caption ?? b.primary_text ?? (b.headlines ?? []).join("\n") ?? ""}</Text>
          {b.hashtags ? <Text style={{ color: colors.series1 }}>{b.hashtags.join(" ")}</Text> : null}
          {b.script ? b.script.map((sc: { scene: number; visual: string; voiceover: string }) => <Text key={sc.scene} style={s.muted}>Scene {sc.scene}: {sc.visual} — “{sc.voiceover}”</Text>) : null}
          {asset.quality?.issues?.map((i) => <Text key={i.message} style={{ color: i.level === "error" ? colors.danger : colors.marigoldDeep }}>{i.message}</Text>)}
          <View style={s.row}>
            <Button label="Submit for approval" variant="signoff" disabled={asset.status !== "draft"} loading={busy} onPress={() => run(() => api.post(`/content/${asset.id}/submit`))} />
            {platform === "instagram" && <Button label="Generate image" loading={busy} onPress={() => run(() => api.post("/content/images/generate", { prompt: b.image_prompt ?? asset.title, content_id: asset.id }))} />}
          </View>
        </Card>
      )}
      {asset?.generation_status === "failed" && <ErrorText>Generation failed: {asset.generation_error}. No credits were charged.</ErrorText>}
    </Screen>
  );
}

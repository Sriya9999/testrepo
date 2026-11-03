import type { SocialPost } from "@marketingos/api-client";
import { Image } from "expo-image";
import { Text, View } from "react-native";
import { Badge, Card, Empty, Screen, s } from "@/components/ui";
import { useApi } from "@/lib/api";
import { colors } from "@/lib/theme";

export default function Calendar() {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = new Date(start.getTime() + 30 * 86_400_000);
  const { data } = useApi<SocialPost[]>("/social/posts", { start: start.toISOString(), end: end.toISOString() }, 60_000);
  const byDay = new Map<string, SocialPost[]>();
  for (const p of data ?? []) {
    const when = p.published_at ?? p.scheduled_at;
    if (!when) continue;
    const key = new Date(when).toDateString();
    byDay.set(key, [...(byDay.get(key) ?? []), p]);
  }
  return (
    <Screen title="Calendar" subtitle="The next 30 days on Instagram.">
      {!byDay.size && <Empty title="Nothing scheduled" body="Approved posts appear here with their publish time." />}
      {[...byDay.entries()].map(([day, posts]) => (
        <View key={day} style={{ gap: 8 }}>
          <Text style={{ fontWeight: "700", color: colors.ink }}>{new Date(day).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" })}</Text>
          {posts.map((p) => (
            <Card key={p.id} style={{ flexDirection: "row", gap: 12 }}>
              {p.media[0]?.url ? <Image source={{ uri: p.media[0].url }} style={{ width: 64, height: 64, borderRadius: 6 }} accessibilityLabel="Post image" /> : null}
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={s.muted}>{new Date(p.published_at ?? p.scheduled_at!).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })} · {p.format} · {p.account?.name ?? "no account"}</Text>
                <Text numberOfLines={2} style={{ color: colors.ink }}>{p.caption || "No caption"}</Text>
                <Badge status={p.status} />
              </View>
            </Card>
          ))}
        </View>
      ))}
    </Screen>
  );
}

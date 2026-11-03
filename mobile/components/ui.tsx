import { STATUS_LABELS } from "@marketingos/api-client";
import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, radius } from "@/lib/theme";

export function Screen({ title, subtitle, children, right, scroll = true }: { title: string; subtitle?: string; children: ReactNode; right?: ReactNode; scroll?: boolean }) {
  const body = (
    <>
      <View style={s.header}>
        <View style={{ flex: 1 }}>
          <Text style={s.title} accessibilityRole="header">{title}</Text>
          {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
        </View>
        {right}
      </View>
      {children}
    </>
  );
  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      {scroll ? <ScrollView contentContainerStyle={s.content}>{body}</ScrollView> : <View style={[s.content, { flex: 1 }]}>{body}</View>}
    </SafeAreaView>
  );
}

export function Card({ children, style, accent }: { children: ReactNode; style?: ViewStyle; accent?: boolean }) {
  return <View style={[s.card, accent && s.cardAccent, style]}>{children}</View>;
}

type Variant = "primary" | "secondary" | "approve" | "danger" | "signoff";
export function Button({ label, onPress, variant = "secondary", loading, disabled }: { label: string; onPress: () => void; variant?: Variant; loading?: boolean; disabled?: boolean }) {
  const v = { primary: [colors.ink, "#fff"], secondary: [colors.surface, colors.ink], approve: [colors.leaf, "#fff"], danger: [colors.surface, colors.danger], signoff: [colors.marigold, colors.ink] }[variant];
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ disabled: disabled || loading }} disabled={disabled || loading} onPress={onPress}
      style={({ pressed }) => [s.button, { backgroundColor: v[0], borderColor: variant === "secondary" || variant === "danger" ? colors.rule : v[0], opacity: disabled ? 0.5 : pressed ? 0.85 : 1 }]}>
      {loading ? <ActivityIndicator color={v[1]} /> : <Text style={[s.buttonText, { color: v[1] }]}>{label}</Text>}
    </Pressable>
  );
}

export function Input(props: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={s.label}>{props.label}</Text>
      <TextInput placeholderTextColor={colors.faint} {...props} style={[s.input, props.multiline && { minHeight: 80, textAlignVertical: "top" }, props.style]} />
    </View>
  );
}

const STATUS: Record<string, [string, string]> = {
  good: [colors.leafWash, colors.leaf], wait: [colors.marigoldWash, colors.marigoldDeep], bad: [colors.dangerWash, colors.danger], neutral: [colors.sunk, colors.ink2],
};
const GROUP: Record<string, string> = {
  approved: "good", published: "good", executed: "good", active: "good", completed: "good",
  pending: "wait", in_review: "wait", pending_approval: "wait", scheduled: "wait", awaiting_approval: "wait",
  failed: "bad", rejected: "bad",
};
export function Badge({ status }: { status: string }) {
  const [bg, fg] = STATUS[GROUP[status] ?? "neutral"];
  return <View style={[s.badge, { backgroundColor: bg }]}><Text style={[s.badgeText, { color: fg }]}>{STATUS_LABELS[status] ?? status.replace(/_/g, " ")}</Text></View>;
}

export function Metric({ label, value, change, good }: { label: string; value: string; change?: number | null; good?: boolean | null }) {
  return (
    <View style={s.metric}>
      <Text style={s.metricLabel}>{label}</Text>
      <Text style={s.metricValue}>{value}</Text>
      {change != null ? <Text style={{ fontSize: 12, color: good ? colors.leaf : colors.danger }}>{change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(1)}%</Text> : null}
    </View>
  );
}

export function Empty({ title, body }: { title: string; body?: string }) {
  return (
    <View style={s.empty}>
      <Text style={{ fontWeight: "600", color: colors.ink }}>{title}</Text>
      {body ? <Text style={{ color: colors.muted, textAlign: "center", marginTop: 4 }}>{body}</Text> : null}
    </View>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return children ? <Text accessibilityRole="alert" style={{ color: colors.danger, backgroundColor: colors.dangerWash, padding: 10, borderRadius: radius.control }}>{children}</Text> : null;
}

export const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.paper },
  content: { padding: 16, gap: 14, paddingBottom: 40 },
  header: { flexDirection: "row", alignItems: "flex-end", gap: 12, marginBottom: 4 },
  title: { fontSize: 26, fontWeight: "700", color: colors.ink, letterSpacing: -0.4 },
  subtitle: { fontSize: 14, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderColor: colors.rule, borderWidth: 1, borderRadius: radius.panel, padding: 14, gap: 8 },
  cardAccent: { borderLeftWidth: 4, borderLeftColor: colors.marigold, borderColor: "#f0d38f" },
  button: { minHeight: 44, borderRadius: radius.control, borderWidth: 1, paddingHorizontal: 14, alignItems: "center", justifyContent: "center" },
  buttonText: { fontSize: 15, fontWeight: "600" },
  label: { fontSize: 13, fontWeight: "500", color: colors.ink2 },
  input: { minHeight: 44, borderWidth: 1, borderColor: colors.rule, borderRadius: radius.control, backgroundColor: colors.surface, paddingHorizontal: 12, fontSize: 15, color: colors.ink },
  badge: { alignSelf: "flex-start", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontSize: 12, fontWeight: "500" },
  metric: { width: "50%", padding: 12, borderColor: colors.rule, borderRightWidth: 1, borderBottomWidth: 1 },
  metricLabel: { fontSize: 12, color: colors.muted },
  metricValue: { fontSize: 20, fontWeight: "700", color: colors.ink, fontVariant: ["tabular-nums"] },
  empty: { borderWidth: 1, borderStyle: "dashed", borderColor: colors.rule, borderRadius: radius.panel, padding: 24, alignItems: "center" },
  h2: { fontSize: 17, fontWeight: "700", color: colors.ink },
  muted: { color: colors.muted, fontSize: 13 },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" },
});

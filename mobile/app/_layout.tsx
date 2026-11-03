import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { registerForPush } from "@/lib/push";
import { useSession } from "@/lib/session";
import { colors } from "@/lib/theme";

function AuthGate() {
  const { ready, accessToken, load } = useSession();
  const segments = useSegments();
  const router = useRouter();
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!ready) return;
    const onLogin = segments[0] === "login";
    if (!accessToken && !onLogin) router.replace("/login");
    if (accessToken && onLogin) router.replace("/");
  }, [ready, accessToken, segments, router]);
  useEffect(() => { if (accessToken) registerForPush().catch(() => undefined); }, [accessToken]);
  return null;
}

export default function RootLayout() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1 } } }));
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={client}>
        <StatusBar style="dark" />
        <AuthGate />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.paper } }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="login" />
          <Stack.Screen name="approvals" options={{ presentation: "modal" }} />
        </Stack>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}

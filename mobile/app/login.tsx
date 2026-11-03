import type { Session } from "@marketingos/api-client";
import { useState } from "react";
import { KeyboardAvoidingView, Platform, Text, View } from "react-native";
import { Button, ErrorText, Input, Screen } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { colors } from "@/lib/theme";

export default function Login() {
  const setSession = useSession((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setError("");
    try {
      if (mfaToken) setSession(await api.post<Session>("/auth/login/mfa", { mfa_token: mfaToken, code }));
      else {
        const r = await api.post<Session | { mfa_required: true; mfa_token: string }>("/auth/login", { email: email.trim(), password });
        if ("mfa_required" in r) setMfaToken(r.mfa_token); else setSession(r);
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
      <Screen title={mfaToken ? "Enter your code" : "Sign in"} subtitle={mfaToken ? "From your authenticator app." : "Approve your team's marketing from anywhere."}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <View style={{ width: 28, height: 28, borderRadius: 6, backgroundColor: colors.marigold, alignItems: "center", justifyContent: "center" }}><Text style={{ fontWeight: "900" }}>M</Text></View>
          <Text style={{ fontWeight: "700", fontSize: 16, color: colors.ink }}>MarketingOS</Text>
        </View>
        <ErrorText>{error}</ErrorText>
        {mfaToken ? <Input label="Code" value={code} onChangeText={setCode} keyboardType="number-pad" autoFocus /> : (
          <>
            <Input label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
            <Input label="Password" value={password} onChangeText={setPassword} secureTextEntry autoComplete="password" textContentType="password" />
          </>
        )}
        <Button label={mfaToken ? "Verify" : "Sign in"} variant="primary" loading={busy} onPress={submit} />
        <Text style={{ color: colors.muted, fontSize: 13 }}>New here? Create your account on the web, then sign in.</Text>
      </Screen>
    </KeyboardAvoidingView>
  );
}

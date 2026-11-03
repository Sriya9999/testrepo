"use client";

import type { SocialPost } from "@marketingos/api-client";
import { useState } from "react";
import { Button, Empty, KeyValue, LinkButton, Notice, PageHeader, Panel, StatusBadge, Table, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Account { id: string; display_name: string; mode: string; status: string; scopes: string[]; details: Record<string, any>; last_sync_at: string | null; last_error: string | null; external_id: string }
interface SocialAnalytics { published_posts: number; posts_with_metrics: number; engagement: number; engagement_rate: number | null; totals: Record<string, number>; note: string | null; followers: { date: string; followers: number | null }[] }

export default function SocialAccountsPage() {
  const canManage = useCan("integrations:manage");
  const [error, setError] = useState("");
  const { data: accounts } = useApiQuery<Account[]>("/integrations/instagram/accounts");
  const { data: posts } = useApiQuery<SocialPost[]>("/social/posts", { status: "published" });
  const { data: stats } = useApiQuery<SocialAnalytics>("/social/analytics");
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/integrations", "/social"]);
  const run = (fn: () => Promise<unknown>) => m.mutate(fn, { onError: (e) => setError(errorMessage(e)) });
  const connect = (mode: "live" | "sandbox") => run(async () => {
    const r = await api.post<{ authorize_url?: string }>("/integrations/instagram/connect", { mode });
    if (r.authorize_url) window.location.href = r.authorize_url;
  });

  return (
    <>
      <PageHeader title="Instagram accounts" description="Instagram Professional (Business or Creator) accounts linked to a Facebook Page can be published to through Meta's official API."
        actions={canManage && <><Button onClick={() => connect("sandbox")}>Add sandbox account</Button><Button variant="primary" onClick={() => connect("live")}>Connect Instagram</Button></>} />
      {error && <Notice tone="error" className="mb-4">{error}</Notice>}
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-4">
          {!accounts?.length && <Empty title="No accounts yet" body="Connect a real account, or add a sandbox account to try scheduling and approvals without posting anything." />}
          {accounts?.map((a) => (
            <Panel key={a.id} title={<span className="flex items-center gap-2">{a.display_name} {a.mode === "sandbox" && <Tag tone="sandbox">sandbox</Tag>}</span>}
              actions={canManage && (
                <>
                  <Button size="sm" onClick={() => run(() => api.post(`/integrations/accounts/${a.id}/sync`))}>Sync now</Button>
                  <Button size="sm" variant="danger" onClick={() => confirm(`Disconnect ${a.display_name}? Scheduled posts for it will fail until you reconnect.`) && run(() => api.del(`/integrations/accounts/${a.id}`))}>Disconnect</Button>
                </>
              )}>
              {a.last_error && <Notice tone="error" className="mb-3">{a.last_error}</Notice>}
              <KeyValue items={[
                ["Status", <StatusBadge key="s" status={a.status} />],
                ["Instagram user id", a.details.ig_user_id ?? a.external_id],
                ["Facebook Page", a.details.page_name ?? a.details.page_id ?? "—"],
                ["Followers", a.details.followers_count ?? "—"],
                ["Permissions", a.scopes.length ? a.scopes.join(", ") : a.mode === "sandbox" ? "Sandbox: nothing is sent to Instagram" : "—"],
                ["Last sync", a.last_sync_at ? new Date(a.last_sync_at).toLocaleString("en-IN") : "Never"],
              ]} />
            </Panel>
          ))}
        </div>
        <Panel title="Account analytics" description="Last 30 days, from Instagram insights.">
          {stats?.note && <p className="mb-3 text-[13px] text-muted">{stats.note}</p>}
          <KeyValue items={[
            ["Posts published", stats?.published_posts ?? "—"],
            ["Posts with metrics", stats?.posts_with_metrics ?? "—"],
            ["Interactions", stats?.engagement ?? "—"],
            ["Reach", stats?.totals?.reach ?? "—"],
            ["Engagement rate", stats?.engagement_rate != null ? `${(stats.engagement_rate * 100).toFixed(2)}%` : "—"],
          ]} />
        </Panel>
      </div>
      <Panel title="Publishing history" className="mt-6" actions={<LinkButton href="/social/calendar">Open calendar</LinkButton>}>
        {posts?.length ? (
          <Table head={["Published", "Post", "Account", "Attempts", "Result"]}>
            {posts.map((p) => (
              <tr key={p.id}>
                <td className="whitespace-nowrap tabular">{p.published_at ? new Date(p.published_at).toLocaleString("en-IN") : "—"}</td>
                <td className="max-w-md"><span className="line-clamp-1">{p.caption}</span></td>
                <td>{p.account?.name}</td>
                <td className="tabular">{p.attempts}</td>
                <td>{p.permalink ? <a href={p.permalink} className="underline" target="_blank" rel="noreferrer">View</a> : <StatusBadge status={p.status} />}</td>
              </tr>
            ))}
          </Table>
        ) : <p className="text-[13px] text-muted">Nothing published yet.</p>}
      </Panel>
    </>
  );
}

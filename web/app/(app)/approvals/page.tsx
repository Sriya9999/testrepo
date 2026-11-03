"use client";

import type { Approval } from "@marketingos/api-client";
import { useState } from "react";
import { ApprovalItem } from "@/components/approval";
import { Button, Empty, Notice, PageHeader, Spinner, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery } from "@/lib/hooks";

type Tab = "pending" | "approved,executed" | "rejected,changes_requested" | "history";

export default function ApprovalsPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const { data, isLoading } = useApiQuery<Approval[]>("/approvals", { status: tab });
  const { data: pending } = useApiQuery<Approval[]>("/approvals", { status: "pending" });
  const groups = new Map<string, Approval[]>();
  for (const a of data ?? []) {
    const key = a.group_id ?? a.id;
    groups.set(key, [...(groups.get(key) ?? []), a]);
  }
  const bulk = useApiMutation((ids: string[]) => api.post("/approvals/bulk-approve", { ids }), ["/approvals", "/dashboard"]);

  return (
    <>
      <PageHeader title="Approvals"
        description="Anything that publishes, spends money or changes a live campaign waits here. What you approve is exactly what runs." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: "pending", label: "Waiting", count: pending?.length },
        { value: "approved,executed", label: "Approved" },
        { value: "rejected,changes_requested", label: "Sent back" },
        { value: "history", label: "History" },
      ]} />
      <div className="mt-5 space-y-6">
        {isLoading && <Spinner />}
        {bulk.error && <Notice tone="error">{errorMessage(bulk.error)}</Notice>}
        {data && !data.length && (
          <Empty title={tab === "pending" ? "Nothing is waiting for you" : "Nothing here yet"}
            body={tab === "pending" ? "New requests from your team and from agents appear here." : undefined} />
        )}
        {[...groups.entries()].map(([key, items]) =>
          items.length > 1 && items[0].group_id ? (
            <section key={key} className="space-y-3 rounded-[var(--radius-panel)] border border-dashed border-rule-strong p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13px] text-ink-2"><b>{items.length} items</b> prepared together by an agent run</p>
                {tab === "pending" && items.some((i) => i.can_decide) && (
                  <Button size="sm" variant="approve" loading={bulk.isPending} onClick={() => bulk.mutate(items.filter((i) => i.can_decide).map((i) => i.id))}>
                    Approve all {items.length}
                  </Button>
                )}
              </div>
              {items.map((a) => <ApprovalItem key={a.id} a={a} />)}
            </section>
          ) : (
            items.map((a) => <ApprovalItem key={a.id} a={a} />)
          ),
        )}
      </div>
    </>
  );
}

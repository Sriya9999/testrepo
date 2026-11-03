"use client";

import { formatMoney, formatNumber } from "@marketingos/api-client";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useWebsites, WebsitePicker } from "@/components/search-pickers";
import { Button, Empty, Field, Notice, PageHeader, Panel, Select, Table, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

interface Kw { id: string; text: string; country: string; search_volume: number | null; difficulty: number | null; cpc_minor: number | null; cpc_currency: string | null;
  competition: string | null; metrics_source: string | null; intent: string | null; cluster: string | null; position: number | null; position_change: number | null; ranking_url: string | null }

export default function KeywordsPage() {
  const { current } = useWebsites();
  const canWrite = useCan("seo:write");
  const [text, setText] = useState("");
  const [country, setCountry] = useState("IN");
  const [group, setGroup] = useState(true);
  const [error, setError] = useState("");
  const { data } = useApiQuery<{ keywords: Kw[]; metrics_provider: string | null; note: string | null }>("/seo/keywords", { website_id: current?.id });
  const add = useApiMutation(() => api.post("/seo/keywords", { website_id: current?.id ?? null, keywords: text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean), country }), ["/seo"]);
  const refresh = useApiMutation(() => api.post("/seo/keywords/refresh"), ["/seo"]);
  const del = useApiMutation((id: string) => api.del(`/seo/keywords/${id}`), ["/seo"]);
  const clusters = useMemo(() => {
    const m = new Map<string, Kw[]>();
    for (const k of data?.keywords ?? []) m.set(group ? k.cluster ?? k.text : "All keywords", [...(m.get(group ? k.cluster ?? k.text : "All keywords") ?? []), k]);
    return [...m.entries()];
  }, [data, group]);

  return (
    <>
      <PageHeader title="Keyword research" description="Track the searches that matter. Volumes, difficulty and CPC come from a connected data source; positions come from Search Console." actions={<WebsitePicker />} />
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <Panel title="Add keywords">
          <div className="space-y-3">
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Keywords" hint="One per line or comma separated"><Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder={"thali near me\nbest thali in pune"} /></Field>
            <Field label="Country"><Select value={country} onChange={(e) => setCountry(e.target.value)} options={["IN", "US", "GB", "AE", "SG", "AU", "CA"].map((c) => ({ value: c, label: c }))} /></Field>
            <Button variant="primary" disabled={!canWrite || !text.trim()} loading={add.isPending} className="w-full"
              onClick={() => add.mutate(undefined, { onSuccess: () => { setText(""); setError(""); }, onError: (e) => setError(errorMessage(e)) })}>Track keywords</Button>
          </div>
        </Panel>
        <Panel title="Tracked keywords" actions={
          <>
            <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)} /> Group into clusters</label>
            {data?.metrics_provider && <Button size="sm" loading={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Refresh metrics</Button>}
          </>
        }>
          {data?.note && <Notice tone="warning" className="mb-3">{data.note}</Notice>}
          {!data?.keywords.length ? <Empty title="No keywords yet" body="Add the searches you want to rank for." /> : (
            <div className="space-y-5">
              {clusters.map(([name, kws]) => (
                <div key={name}>
                  {group && <p className="mb-1 text-[13px] font-semibold">{name} <span className="font-normal text-muted">· {kws.length}</span></p>}
                  <Table head={["Keyword", "Intent (estimated)", "Volume", "Difficulty", "CPC", "Position", ""]}>
                    {kws.map((k) => (
                      <tr key={k.id}>
                        <td>{k.text}</td><td className="capitalize">{k.intent ?? "—"}</td><td className="tabular">{formatNumber(k.search_volume)}</td>
                        <td className="tabular">{k.difficulty ?? "—"}</td><td className="tabular">{formatMoney(k.cpc_minor, k.cpc_currency ?? "INR", 2)}</td>
                        <td className="tabular">{k.position?.toFixed(1) ?? "—"}{k.position_change ? <span className={k.position_change > 0 ? "ml-1 text-leaf" : "ml-1 text-danger"}>{k.position_change > 0 ? "▲" : "▼"}{Math.abs(k.position_change)}</span> : null}</td>
                        <td>{canWrite && <button aria-label={`Stop tracking ${k.text}`} onClick={() => del.mutate(k.id)} className="text-muted hover:text-danger"><Trash2 className="size-3.5" /></button>}</td>
                      </tr>
                    ))}
                  </Table>
                </div>
              ))}
              {data?.metrics_provider && <p className="text-xs text-muted">Metrics source: {data.metrics_provider.replace(/_/g, " ")}</p>}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

"use client";

import type { ContentAsset, SocialPost } from "@marketingos/api-client";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Button, cn, Drawer, Empty, Field, Notice, PageHeader, Select, StatusBadge, Tabs, Tag, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";

type View = "month" | "week" | "day";
interface Account { id: string; provider: string; display_name: string; mode: string; status: string }

const DOT: Record<string, string> = {
  draft: "bg-faint", in_review: "bg-marigold", approved: "bg-leaf", scheduled: "bg-series-1", publishing: "bg-series-1",
  published: "bg-leaf", failed: "bg-danger", cancelled: "bg-rule-strong", changes_requested: "bg-marigold",
};

function startOfWeek(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
function toLocalInput(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function PostDrawer({ post, accounts, onClose }: { post: SocialPost | "new"; accounts: Account[]; onClose: () => void }) {
  const isNew = post === "new";
  const p = isNew ? null : post;
  const [caption, setCaption] = useState(p?.caption ?? "");
  const [accountId, setAccountId] = useState(p?.connected_account_id ?? accounts[0]?.id ?? "");
  const [format, setFormat] = useState(p?.format ?? "image");
  const [when, setWhen] = useState(toLocalInput(p?.scheduled_at ?? null));
  const [mediaIds, setMediaIds] = useState<string[]>(p?.media.map((m) => m.media_asset_id ?? "").filter(Boolean) ?? []);
  const [contentId, setContentId] = useState("");
  const [error, setError] = useState("");
  const { data: media, refetch: refetchMedia } = useApiQuery<{ id: string; url: string; kind: string }[]>("/media");
  const { data: content } = useApiQuery<ContentAsset[]>("/content", { platform: "instagram" });
  const m = useApiMutation((fn: () => Promise<unknown>) => fn(), ["/social", "/approvals", "/dashboard"]);
  const run = (fn: () => Promise<unknown>, close = true) => m.mutate(fn, { onSuccess: () => close && onClose(), onError: (e) => setError(errorMessage(e)) });
  const scheduledIso = when ? new Date(when).toISOString() : null;
  const save = async () => {
    const body = { caption, connected_account_id: accountId || null, format, media_asset_ids: mediaIds, scheduled_at: scheduledIso };
    if (isNew) return api.post<SocialPost>("/social/posts", { ...body, content_asset_id: contentId || null });
    return api.patch<SocialPost>(`/social/posts/${p!.id}`, body);
  };
  const upload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try { const r = await api.upload<{ id: string }>("/media", fd); setMediaIds([...mediaIds, r.id]); refetchMedia(); } catch (e) { setError(errorMessage(e)); }
  };
  const locked = p && ["publishing", "published"].includes(p.status);

  return (
    <Drawer open onClose={onClose} title={isNew ? "New Instagram post" : "Post"}>
      <div className="space-y-4">
        {p && <div className="flex flex-wrap items-center gap-2"><StatusBadge status={p.status} />{p.account?.mode === "sandbox" && <Tag tone="sandbox">sandbox account</Tag>}
          {p.permalink && <a className="text-[13px] underline" href={p.permalink} target="_blank" rel="noreferrer">View on Instagram</a>}</div>}
        {p?.last_error && <Notice tone="error">{p.last_error}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        {isNew && content && content.length > 0 && (
          <Field label="Start from content" hint="Uses its caption, hashtags and images.">
            <Select value={contentId} onChange={(e) => setContentId(e.target.value)} options={[{ value: "", label: "Write from scratch" }, ...content.filter((c) => c.generation_status === "ready").map((c) => ({ value: c.id, label: `${c.title} (${c.status})` }))]} />
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Account"><Select value={accountId} onChange={(e) => setAccountId(e.target.value)} disabled={Boolean(locked)}
            options={[{ value: "", label: "Choose…" }, ...accounts.map((a) => ({ value: a.id, label: `${a.display_name}${a.mode === "sandbox" ? " (sandbox)" : ""}` }))]} /></Field>
          <Field label="Format"><Select value={format} onChange={(e) => setFormat(e.target.value)} disabled={Boolean(locked)}
            options={[["image", "Image post"], ["carousel", "Carousel"], ["reel", "Reel"], ["story", "Story"]].map(([value, label]) => ({ value, label }))} /></Field>
        </div>
        {!contentId && <Field label="Caption" hint={`${caption.length} / 2,200 characters · ${(caption.match(/#/g) ?? []).length} / 30 hashtags`}>
          <Textarea rows={6} value={caption} onChange={(e) => setCaption(e.target.value)} disabled={Boolean(locked)} /></Field>}
        {!contentId && (
          <Field label="Media" hint="Live Instagram accounts accept JPEG images and MP4/MOV videos.">
            <div className="flex flex-wrap gap-2">
              {(media ?? []).slice(0, 15).map((mm) => (
                <button key={mm.id} type="button" disabled={Boolean(locked)} onClick={() => setMediaIds(mediaIds.includes(mm.id) ? mediaIds.filter((x) => x !== mm.id) : [...mediaIds, mm.id])}
                  className={cn("relative size-16 overflow-hidden rounded border", mediaIds.includes(mm.id) ? "border-ink ring-2 ring-ink/30" : "border-rule")}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {mm.kind === "image" ? <img src={mm.url} alt="" className="size-full object-cover" /> : <span className="text-[11px]">video</span>}
                  {mediaIds.includes(mm.id) && <span className="absolute right-0.5 top-0.5 rounded bg-ink px-1 text-[10px] text-white">{mediaIds.indexOf(mm.id) + 1}</span>}
                </button>
              ))}
              <label className="grid size-16 cursor-pointer place-items-center rounded border border-dashed border-rule-strong text-xs text-muted">
                Upload<input type="file" accept="image/jpeg,image/png,video/mp4,video/quicktime" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              </label>
            </div>
          </Field>
        )}
        <Field label="Publish at" hint="Your local time. Scheduling needs approval before the post is queued.">
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="h-9 w-full rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-sm" />
        </Field>
        <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
          {!locked && <Button variant="primary" loading={m.isPending} onClick={() => run(save)}>{isNew ? "Save draft" : "Save changes"}</Button>}
          {!locked && (
            <Button variant="signoff" loading={m.isPending} onClick={() => run(async () => {
              const saved = await save();
              await api.post(`/social/posts/${saved.id}/schedule`, { scheduled_at: scheduledIso });
            })}>{when ? "Request scheduling" : "Request publishing now"}</Button>
          )}
          {p && ["approved", "scheduled"].includes(p.status) && <Button variant="approve" onClick={() => run(() => api.post(`/social/posts/${p.id}/publish`))}>Publish now</Button>}
          {p?.status === "failed" && <Button onClick={() => run(() => api.post(`/social/posts/${p.id}/retry`))}>Retry</Button>}
          {p && !locked && p.status !== "cancelled" && <Button variant="danger" onClick={() => run(() => api.post(`/social/posts/${p.id}/cancel`))}>Cancel post</Button>}
        </div>
        {p && p.metrics && Object.keys(p.metrics).length > 0 && (
          <div className="grid grid-cols-3 gap-2 border-t border-rule pt-3 text-center">
            {Object.entries(p.metrics).map(([k, v]) => <div key={k}><p className="text-lg font-bold tabular">{v}</p><p className="text-xs capitalize text-muted">{k}</p></div>)}
          </div>
        )}
      </div>
    </Drawer>
  );
}

export default function CalendarPage() {
  const canWrite = useCan("social:write");
  const [view, setView] = useState<View>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [open, setOpen] = useState<SocialPost | "new" | null>(null);
  const [error, setError] = useState("");
  const { data: accounts } = useApiQuery<Account[]>("/integrations/accounts", { provider: "instagram" });
  const [accountFilter, setAccountFilter] = useState("");

  const days = useMemo(() => {
    if (view === "day") return [new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate())];
    if (view === "week") { const s = startOfWeek(cursor); return Array.from({ length: 7 }, (_, i) => new Date(s.getTime() + i * 86_400_000)); }
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const s = startOfWeek(first);
    return Array.from({ length: 42 }, (_, i) => new Date(s.getFullYear(), s.getMonth(), s.getDate() + i));
  }, [view, cursor]);
  const start = days[0];
  const end = new Date(days[days.length - 1].getTime() + 86_400_000);
  const { data: posts } = useApiQuery<SocialPost[]>("/social/posts", { start: start.toISOString(), end: end.toISOString(), account_id: accountFilter || undefined });
  const { data: unscheduled } = useApiQuery<SocialPost[]>("/social/posts", { status: "draft" });
  const move = useApiMutation((p: { id: string; scheduled_at: string }) => api.patch(`/social/posts/${p.id}`, { scheduled_at: p.scheduled_at }), ["/social"]);

  const shift = (dir: number) => {
    const d = new Date(cursor);
    if (view === "month") d.setMonth(d.getMonth() + dir); else d.setDate(d.getDate() + dir * (view === "week" ? 7 : 1));
    setCursor(d);
  };
  const postsOn = (d: Date) => (posts ?? []).filter((p) => { const t = p.published_at ?? p.scheduled_at; return t && sameDay(new Date(t), d); });
  const drop = (d: Date, id: string) => {
    const p = [...(posts ?? []), ...(unscheduled ?? [])].find((x) => x.id === id);
    if (!p) return;
    const old = p.scheduled_at ? new Date(p.scheduled_at) : new Date(d.getFullYear(), d.getMonth(), d.getDate(), 19, 0);
    const next = new Date(d.getFullYear(), d.getMonth(), d.getDate(), old.getHours(), old.getMinutes());
    move.mutate({ id, scheduled_at: next.toISOString() }, { onError: (e) => setError(errorMessage(e)), onSuccess: () => setError("") });
  };
  const title = view === "month" ? cursor.toLocaleDateString("en-IN", { month: "long", year: "numeric" })
    : view === "week" ? `Week of ${start.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : cursor.toLocaleDateString("en-IN", { dateStyle: "full" });

  return (
    <>
      <PageHeader title="Social calendar" description="Drag a post to another day to move it. Scheduled posts keep their approval; changing the content sends them back for approval."
        actions={canWrite && <Button variant="primary" onClick={() => setOpen("new")}><Plus className="size-4" aria-hidden /> New post</Button>} />
      {!accounts?.length && <Notice tone="warning" className="mb-4">No Instagram account connected. <Link href="/integrations" className="underline">Connect one</Link> to schedule posts.</Notice>}
      {error && <Notice tone="error" className="mb-4">{error}</Notice>}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => shift(-1)} aria-label="Previous"><ChevronLeft className="size-4" /></Button>
          <Button size="sm" onClick={() => setCursor(new Date())}>Today</Button>
          <Button size="sm" variant="ghost" onClick={() => shift(1)} aria-label="Next"><ChevronRight className="size-4" /></Button>
          <h2 className="ml-1 text-base font-semibold">{title}</h2>
        </div>
        <div className="flex items-center gap-2">
          <Select aria-label="Platform" className="w-32" value="instagram" onChange={() => undefined} options={[{ value: "instagram", label: "Instagram" }]} />
          <Select aria-label="Account" className="w-44" value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}
            options={[{ value: "", label: "All accounts" }, ...(accounts ?? []).map((a) => ({ value: a.id, label: a.display_name }))]} />
          <Tabs value={view} onChange={setView} tabs={[{ value: "month", label: "Month" }, { value: "week", label: "Week" }, { value: "day", label: "Day" }]} />
        </div>
      </div>
      <div className="overflow-x-auto">
        <div className={cn("grid min-w-[700px] overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-rule gap-px", view === "day" ? "grid-cols-1" : "grid-cols-7")}>
          {view !== "day" && ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="bg-sunk px-2 py-1.5 text-xs font-medium text-muted">{d}</div>)}
          {days.map((d) => {
            const outside = view === "month" && d.getMonth() !== cursor.getMonth();
            const today = sameDay(d, new Date());
            return (
              <div key={d.toISOString()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => drop(d, e.dataTransfer.getData("text/plain"))}
                className={cn("bg-surface p-1.5", view === "month" ? "min-h-28" : "min-h-72", outside && "bg-paper")}>
                <p className={cn("mb-1 text-xs tabular", today ? "inline-block rounded bg-ink px-1.5 font-semibold text-white" : outside ? "text-faint" : "text-muted")}>{d.getDate()}</p>
                <ul className="space-y-1">
                  {postsOn(d).map((p) => (
                    <li key={p.id}>
                      <button draggable={canWrite && !["published", "publishing"].includes(p.status)} onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)} onClick={() => setOpen(p)}
                        className="flex w-full items-start gap-1.5 rounded border border-rule bg-surface px-1.5 py-1 text-left text-[12px] hover:border-rule-strong">
                        <span className={cn("mt-1 size-2 shrink-0 rounded-full", DOT[p.status] ?? "bg-faint")} title={p.status} />
                        <span className="min-w-0">
                          <span className="block text-[11px] text-muted tabular">{new Date(p.published_at ?? p.scheduled_at!).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })} · {p.format}</span>
                          <span className="line-clamp-2">{p.caption || "No caption"}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        {["draft", "in_review", "scheduled", "published", "failed"].map((s) => <span key={s} className="inline-flex items-center gap-1"><span className={cn("size-2 rounded-full", DOT[s])} /> <StatusBadge status={s} /></span>)}
      </div>
      <section className="mt-6">
        <h2 className="mb-2 text-base font-semibold">Unscheduled drafts</h2>
        {unscheduled?.filter((p) => !p.scheduled_at).length ? (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {unscheduled.filter((p) => !p.scheduled_at).map((p) => (
              <li key={p.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)}>
                <button onClick={() => setOpen(p)} className="w-full rounded-md border border-rule bg-surface p-2.5 text-left text-[13px] hover:border-rule-strong">
                  <span className="line-clamp-2">{p.caption || "No caption"}</span>
                  <span className="mt-1 block text-xs text-muted">Drag onto a day to schedule</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty title="No unscheduled drafts" body="Posts created from the Content studio without a date appear here." />}
      </section>
      {open && <PostDrawer post={open} accounts={accounts ?? []} onClose={() => setOpen(null)} />}
    </>
  );
}

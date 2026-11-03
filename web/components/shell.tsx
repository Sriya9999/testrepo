"use client";

import type { User, WorkspaceRef } from "@marketingos/api-client";
import { useQueryClient } from "@tanstack/react-query";
import {
  BarChart3, Bell, Bot, Building2, CalendarDays, CheckSquare, ChevronsUpDown, CreditCard, Gauge, Globe2, LayoutDashboard,
  LogOut, Megaphone, Menu, PenSquare, Plug, Search, Settings, Sparkles, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useApiQuery, useWorkspace } from "@/lib/hooks";
import { useAuth } from "@/lib/store";
import { cn } from "./ui";

interface NavItem { href: string; label: string; icon: typeof Gauge; children?: { href: string; label: string }[]; agencyOnly?: boolean }

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/assistant", label: "AI assistant", icon: Sparkles },
  { href: "/content-studio", label: "Content studio", icon: PenSquare },
  { href: "/social/calendar", label: "Social media", icon: CalendarDays, children: [
    { href: "/social/calendar", label: "Calendar" }, { href: "/social/accounts", label: "Accounts" }] },
  { href: "/advertising/meta", label: "Advertising", icon: Megaphone, children: [
    { href: "/advertising/meta", label: "Meta Ads" }, { href: "/advertising/google", label: "Google Ads" }] },
  { href: "/seo", label: "Search", icon: Search, children: [
    { href: "/seo", label: "SEO" }, { href: "/seo/audit", label: "Website audit" }, { href: "/seo/keywords", label: "Keywords" },
    { href: "/geo", label: "AI search (GEO)" }, { href: "/geo/prompts", label: "Prompts" }] },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/agents", label: "AI agents", icon: Bot },
  { href: "/agency/clients", label: "Clients", icon: Building2, agencyOnly: true },
  { href: "/approvals", label: "Approvals", icon: CheckSquare },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
];

function WorkspaceSwitcher({ user }: { user: User }) {
  const [open, setOpen] = useState(false);
  const workspaceId = useAuth((s) => s.workspaceId);
  const setWorkspace = useAuth((s) => s.setWorkspace);
  const qc = useQueryClient();
  const router = useRouter();
  const current = user.workspaces.find((w) => w.id === workspaceId) ?? user.workspaces[0];
  const groups: [string, WorkspaceRef[]][] = [
    ["Your workspaces", user.workspaces.filter((w) => w.kind !== "client")],
    ["Clients", user.workspaces.filter((w) => w.kind === "client")],
  ];
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-[var(--radius-control)] border border-rule bg-surface px-2.5 py-2 text-left hover:border-rule-strong">
        <span className="grid size-7 shrink-0 place-items-center rounded bg-ink text-[13px] font-bold text-white">{current?.name.slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold">{current?.name}</span>
          <span className="block text-[11px] text-muted">{current?.kind === "client" ? "Client workspace" : current?.kind === "agency" ? "Agency" : "Business"}</span>
        </span>
        <ChevronsUpDown className="size-3.5 text-muted" aria-hidden />
      </button>
      {open && (
        <div className="absolute inset-x-0 top-full z-40 mt-1 max-h-80 overflow-y-auto rounded-[var(--radius-control)] border border-rule bg-surface p-1 shadow-lg">
          {groups.map(([label, items]) =>
            items.length ? (
              <div key={label}>
                <p className="px-2 pb-1 pt-2 text-[11px] font-medium text-faint">{label}</p>
                {items.map((w) => (
                  <button key={w.id} onClick={() => { setWorkspace(w.id); setOpen(false); qc.clear(); router.push("/dashboard"); }}
                    className={cn("block w-full truncate rounded px-2 py-1.5 text-left text-[13px] hover:bg-sunk", w.id === current?.id && "font-semibold")}>
                    {w.name}
                  </button>
                ))}
              </div>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const { data, refetch } = useApiQuery<{ id: string; title: string; body: string; read: boolean; created_at: string; data: Record<string, string> }[]>(
    "/notifications", undefined, { refetchInterval: 30_000 });
  const unread = data?.filter((n) => !n.read).length ?? 0;
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="relative rounded p-2 text-ink-2 hover:bg-sunk" aria-label={`Notifications (${unread} unread)`}>
        <Bell className="size-4" />
        {unread > 0 && <span className="absolute right-1 top-1 size-2 rounded-full bg-marigold" />}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-1 w-80 rounded-[var(--radius-panel)] border border-rule bg-surface shadow-lg">
          <div className="flex items-center justify-between border-b border-rule px-3 py-2">
            <span className="text-[13px] font-semibold">Notifications</span>
            <button className="text-xs text-muted hover:text-ink" onClick={async () => { await api.post("/notifications/read-all"); refetch(); }}>Mark all read</button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {!data?.length && <li className="px-3 py-6 text-center text-[13px] text-muted">You're all caught up.</li>}
            {data?.slice(0, 20).map((n) => (
              <li key={n.id} className={cn("border-b border-rule px-3 py-2 last:border-0", !n.read && "bg-marigold-wash/50")}>
                <Link href={n.data?.approval_id ? "/approvals" : "/dashboard"} onClick={() => setOpen(false)} className="block">
                  <p className="text-[13px] font-medium">{n.title}</p>
                  {n.body && <p className="line-clamp-2 text-xs text-muted">{n.body}</p>}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Sidebar({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { data: ws } = useWorkspace();
  const { data: pending } = useApiQuery<unknown[]>("/approvals", { status: "pending" }, { refetchInterval: 30_000 });
  const isAgency = ws?.kind === "agency";
  return (
    <nav className="flex h-full flex-col gap-4" aria-label="Main">
      <div className="flex items-center gap-2 px-1">
        <span className="grid size-7 place-items-center rounded-md bg-marigold text-[15px] font-black text-ink">M</span>
        <span className="text-[15px] font-bold tracking-tight">MarketingOS</span>
      </div>
      <WorkspaceSwitcher user={user} />
      <ul className="flex-1 space-y-0.5 overflow-y-auto">
        {NAV.filter((n) => !n.agencyOnly || isAgency).map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/") ||
            item.children?.some((c) => pathname === c.href || pathname.startsWith(c.href + "/"));
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link href={item.href} onClick={onNavigate}
                className={cn("flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13.5px]",
                  active ? "bg-surface font-semibold text-ink shadow-[inset_0_0_0_1px_var(--color-rule)]" : "text-ink-2 hover:bg-sunk")}>
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="flex-1">{item.label}</span>
                {item.href === "/approvals" && pending && pending.length > 0 && (
                  <span className="rounded-full bg-marigold px-1.5 text-[11px] font-bold tabular text-ink" aria-label={`${pending.length} waiting`}>{pending.length}</span>
                )}
              </Link>
              {active && item.children && (
                <ul className="ml-[22px] mt-0.5 space-y-0.5 border-l border-rule pl-3">
                  {item.children.map((c) => (
                    <li key={c.href}>
                      <Link href={c.href} onClick={onNavigate}
                        className={cn("block rounded px-2 py-1 text-[13px]", pathname === c.href ? "font-semibold text-ink" : "text-muted hover:text-ink")}>
                        {c.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between gap-2 border-t border-rule pt-3 text-[13px]">
        <Link href="/billing" className="text-muted hover:text-ink" onClick={onNavigate}>
          <span className="tabular font-semibold text-ink">{ws?.credit_balance ?? "…"}</span> credits
        </Link>
        <span className="text-xs text-faint">{ws?.plan?.name}</span>
      </div>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, accessToken, hydrated, clear, refreshToken } = useAuth();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    if (hydrated && !accessToken) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (hydrated && user && !user.onboarding_completed) router.replace("/onboarding");
  }, [hydrated, accessToken, user, router, pathname]);

  if (!hydrated || !user) return <div className="grid min-h-screen place-items-center text-muted">Loading…</div>;

  const signOut = async () => {
    if (refreshToken) await api.post("/auth/logout", { refresh_token: refreshToken }).catch(() => undefined);
    clear();
    router.replace("/login");
  };

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="hidden border-r border-rule px-3 py-4 lg:sticky lg:top-0 lg:block lg:h-screen">
        <Sidebar user={user} />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-ink/30" aria-label="Close menu" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-72 bg-paper px-3 py-4">
            <button className="absolute right-3 top-4 p-1" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X className="size-4" /></button>
            <Sidebar user={user} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-rule bg-paper/95 px-4 py-2 backdrop-blur sm:px-8">
          <button className="rounded p-2 hover:bg-sunk lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu className="size-4" /></button>
          <div className="hidden text-[13px] text-muted sm:block">
            {!user.email_verified && <span>Check your inbox to verify <b className="text-ink">{user.email}</b>.</span>}
          </div>
          <div className="flex items-center gap-1">
            <Notifications />
            <Link href="/settings" className="rounded p-2 text-ink-2 hover:bg-sunk" aria-label="Your profile"><Users className="size-4" /></Link>
            <button onClick={signOut} className="rounded p-2 text-ink-2 hover:bg-sunk" aria-label="Sign out"><LogOut className="size-4" /></button>
          </div>
        </header>
        <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-8 sm:py-8">{children}</main>
      </div>
    </div>
  );
}

export { Globe2 };

"use client";

import { useEffect, useState } from "react";
import { Button, Drawer, Field, Input, Notice, Select, Textarea } from "./ui";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation, useApiQuery, useCan } from "@/lib/hooks";
import { useUi } from "@/lib/store";

export interface Website { id: string; domain: string; target_location: string | null; latest_score: number | null; last_audit_at: string | null;
  competitors: { id: string; name: string; domain: string | null }[]; search_console_property: string | null; analytics_property: string | null }
export interface GeoProject { id: string; name: string; brand_name: string; brand_aliases: string[]; domain: string | null;
  competitors: { name: string; domain: string | null; aliases: string[] }[]; providers: string[]; schedule: string; last_run_at: string | null; prompt_count: number | null }

export function useWebsites() {
  const { data, ...rest } = useApiQuery<Website[]>("/seo/websites");
  const { websiteId, setWebsite } = useUi();
  const current = data?.find((w) => w.id === websiteId) ?? data?.[0] ?? null;
  return { websites: data, current, setWebsite, ...rest };
}

export function useGeoProjects() {
  const { data, ...rest } = useApiQuery<GeoProject[]>("/geo/projects");
  const { geoProjectId, setGeoProject } = useUi();
  const current = data?.find((p) => p.id === geoProjectId) ?? data?.[0] ?? null;
  return { projects: data, current, setGeoProject, ...rest };
}

export function WebsitePicker() {
  const { websites, current, setWebsite } = useWebsites();
  const canWrite = useCan("seo:write");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ domain: "", target_location: "", competitors: "", search_console_property: "", analytics_property: "" });
  const [error, setError] = useState("");
  const add = useApiMutation((b: typeof form) => api.post<Website>("/seo/websites", {
    ...b, competitors: b.competitors.split(",").map((s) => s.trim()).filter(Boolean),
    search_console_property: b.search_console_property || null, analytics_property: b.analytics_property || null, target_location: b.target_location || null,
  }), ["/seo"]);
  return (
    <div className="flex items-center gap-2">
      {websites && websites.length > 0 && (
        <Select aria-label="Website" className="w-52" value={current?.id ?? ""} onChange={(e) => setWebsite(e.target.value)} options={websites.map((w) => ({ value: w.id, label: w.domain }))} />
      )}
      {canWrite && <Button onClick={() => setAdding(true)}>Add website</Button>}
      <Drawer open={adding} onClose={() => setAdding(false)} title="Add a website">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(form, { onSuccess: (w) => { setWebsite(w.id); setAdding(false); }, onError: (er) => setError(errorMessage(er)) }); }}>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Domain"><Input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="yourbusiness.in" required /></Field>
          <Field label="Target location" hint="City or region you serve"><Input value={form.target_location} onChange={(e) => setForm({ ...form, target_location: e.target.value })} /></Field>
          <Field label="Competitor domains" hint="Comma separated"><Textarea rows={2} value={form.competitors} onChange={(e) => setForm({ ...form, competitors: e.target.value })} /></Field>
          <Field label="Search Console property" hint="e.g. sc-domain:yourbusiness.in"><Input value={form.search_console_property} onChange={(e) => setForm({ ...form, search_console_property: e.target.value })} /></Field>
          <Field label="GA4 property" hint="e.g. properties/123456789"><Input value={form.analytics_property} onChange={(e) => setForm({ ...form, analytics_property: e.target.value })} /></Field>
          <Button variant="primary" loading={add.isPending}>Add website</Button>
        </form>
      </Drawer>
    </div>
  );
}

export function GeoProjectPicker() {
  const { projects, current, setGeoProject } = useGeoProjects();
  const canWrite = useCan("geo:write");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", brand_name: "", brand_aliases: "", domain: "", competitors: "", schedule: "weekly" });
  const [error, setError] = useState("");
  const { data: brands } = useApiQuery<{ name: string; website_url: string | null; competitor_references: string[] }[]>("/brands");
  useEffect(() => {
    const b = brands?.[0];
    if (b && !form.brand_name) setForm((f) => ({ ...f, name: `${b.name} AI visibility`, brand_name: b.name, domain: (b.website_url ?? "").replace(/^https?:\/\//, "").replace(/\/.*$/, ""), competitors: b.competitor_references.join(", ") }));
  }, [brands]); // eslint-disable-line react-hooks/exhaustive-deps
  const add = useApiMutation((b: typeof form) => api.post<GeoProject>("/geo/projects", {
    name: b.name, brand_name: b.brand_name, domain: b.domain || null, schedule: b.schedule,
    brand_aliases: b.brand_aliases.split(",").map((s) => s.trim()).filter(Boolean),
    competitors: b.competitors.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name, domain: null, aliases: [] })),
  }), ["/geo"]);
  return (
    <div className="flex items-center gap-2">
      {projects && projects.length > 0 && <Select aria-label="GEO project" className="w-56" value={current?.id ?? ""} onChange={(e) => setGeoProject(e.target.value)} options={projects.map((p) => ({ value: p.id, label: p.name }))} />}
      {canWrite && <Button onClick={() => setAdding(true)}>New project</Button>}
      <Drawer open={adding} onClose={() => setAdding(false)} title="New GEO project">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(form, { onSuccess: (p) => { setGeoProject(p.id); setAdding(false); }, onError: (er) => setError(errorMessage(er)) }); }}>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Project name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="Brand name as people write it"><Input value={form.brand_name} onChange={(e) => setForm({ ...form, brand_name: e.target.value })} required /></Field>
          <Field label="Other spellings" hint="Comma separated"><Input value={form.brand_aliases} onChange={(e) => setForm({ ...form, brand_aliases: e.target.value })} /></Field>
          <Field label="Your domain" hint="Used to detect when AI answers cite your site"><Input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} /></Field>
          <Field label="Competitors" hint="Comma separated names"><Input value={form.competitors} onChange={(e) => setForm({ ...form, competitors: e.target.value })} /></Field>
          <Field label="Check automatically"><Select value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} options={[{ value: "weekly", label: "Weekly" }, { value: "daily", label: "Daily" }, { value: "off", label: "Only when I run it" }]} /></Field>
          <Button variant="primary" loading={add.isPending}>Create project</Button>
        </form>
      </Drawer>
    </div>
  );
}

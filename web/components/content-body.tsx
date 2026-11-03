"use client";

import { RefreshCw } from "lucide-react";
import { Input, Textarea } from "./ui";

const LABELS: Record<string, string> = {
  hook: "Hook", caption: "Caption", hashtags: "Hashtags", cta: "Call to action", image_prompt: "Image prompt", alt_text: "Alt text",
  slides: "Slides", hooks: "Hook options", script: "Script", shot_suggestions: "Shot suggestions", music_mood: "Music mood",
  frames: "Frames", primary_text: "Primary text", headline: "Headline", description: "Description", headlines: "Headlines",
  descriptions: "Descriptions", paths: "Display paths", keywords: "Keywords", title: "Title", meta_title: "Meta title",
  meta_description: "Meta description", slug: "URL slug", sections: "Sections", faq: "FAQ", hero: "Hero", question: "Question",
  short_answer: "Short answer", schema_suggestion: "Structured data", subject_lines: "Subject lines", preview_text: "Preview text",
  body: "Body", media: "Media",
};

export function label(key: string) {
  return LABELS[key] ?? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function Value({ v }: { v: unknown }) {
  if (v === null || v === undefined || v === "") return <span className="text-faint">—</span>;
  if (typeof v === "string" || typeof v === "number") return <p className="whitespace-pre-line">{String(v)}</p>;
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x === "string")) {
      return (v as string[]).some((s) => s.startsWith("#")) ? (
        <p className="text-series-1">{(v as string[]).join(" ")}</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-4">{(v as string[]).map((s, i) => <li key={i}>{s} <span className="text-xs text-faint tabular">{s.length}</span></li>)}</ul>
      );
    }
    return (
      <ol className="space-y-2">
        {v.map((item, i) => (
          <li key={i} className="rounded-md border border-rule p-2.5">
            {typeof item === "object" && item
              ? Object.entries(item as Record<string, unknown>).filter(([, x]) => x !== null && x !== "").map(([k, x]) => (
                  <p key={k} className="text-[13px]"><span className="text-muted">{label(k)}: </span>{typeof x === "object" ? JSON.stringify(x) : String(x)}</p>
                ))
              : String(item)}
          </li>
        ))}
      </ol>
    );
  }
  if (typeof v === "object") {
    return (
      <div className="space-y-1">
        {Object.entries(v as Record<string, unknown>).map(([k, x]) => (
          <p key={k} className="text-[13px]"><span className="text-muted">{label(k)}: </span>{typeof x === "object" ? JSON.stringify(x) : String(x)}</p>
        ))}
      </div>
    );
  }
  return <span>{String(v)}</span>;
}

/** Read-only rendering of any generated content body, with per-section regenerate buttons. */
export function ContentView({ body, sections, onRegenerate, busySection }: {
  body: Record<string, any>; sections: string[]; onRegenerate?: (s: string) => void; busySection?: string | null;
}) {
  return (
    <div className="space-y-4">
      {body.media?.length > 0 && (
        <div className="flex gap-2 overflow-x-auto">
          {body.media.map((m: { url: string }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={m.url} src={m.url} alt="" className="h-40 rounded-md border border-rule object-cover" />
          ))}
        </div>
      )}
      {Object.entries(body).filter(([k]) => k !== "media" && k !== "design").map(([k, v]) => (
        <section key={k}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-muted">{label(k)}</h3>
            {onRegenerate && sections.includes(k) && (
              <button onClick={() => onRegenerate(k)} disabled={busySection === k}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-ink-2 hover:bg-sunk disabled:opacity-50">
                <RefreshCw className={busySection === k ? "size-3 animate-spin" : "size-3"} aria-hidden /> Rewrite
              </button>
            )}
          </div>
          <div className="text-[14px] leading-relaxed"><Value v={v} /></div>
        </section>
      ))}
    </div>
  );
}

/** Field-by-field editor: strings become text areas, string lists become one-per-line text areas. */
export function ContentEditor({ body, onChange }: { body: Record<string, any>; onChange: (b: Record<string, any>) => void }) {
  return (
    <div className="space-y-4">
      {Object.entries(body).filter(([k]) => k !== "media" && k !== "design").map(([k, v]) => {
        if (typeof v === "string") {
          return (
            <label key={k} className="block space-y-1">
              <span className="text-xs font-semibold text-muted">{label(k)}</span>
              {v.length > 60 || v.includes("\n") ? (
                <Textarea rows={Math.min(10, Math.max(3, Math.ceil(v.length / 70)))} value={v} onChange={(e) => onChange({ ...body, [k]: e.target.value })} />
              ) : (
                <Input value={v} onChange={(e) => onChange({ ...body, [k]: e.target.value })} />
              )}
            </label>
          );
        }
        if (Array.isArray(v) && v.every((x) => typeof x === "string")) {
          return (
            <label key={k} className="block space-y-1">
              <span className="text-xs font-semibold text-muted">{label(k)} <span className="font-normal">(one per line)</span></span>
              <Textarea rows={Math.min(12, v.length + 1)} value={(v as string[]).join("\n")}
                onChange={(e) => onChange({ ...body, [k]: e.target.value.split("\n").filter((s, i, arr) => s || i < arr.length - 1) })} />
            </label>
          );
        }
        if (Array.isArray(v) && v.every((x) => x && typeof x === "object")) {
          return (
            <fieldset key={k} className="space-y-2">
              <legend className="text-xs font-semibold text-muted">{label(k)}</legend>
              {v.map((item: Record<string, any>, i: number) => (
                <div key={i} className="space-y-1.5 rounded-md border border-rule p-2.5">
                  {Object.entries(item).filter(([, x]) => typeof x === "string" || x === null).map(([ik, x]) => (
                    <label key={ik} className="block">
                      <span className="text-[11px] text-muted">{label(ik)}</span>
                      <Input value={(x as string) ?? ""} onChange={(e) => {
                        const next = [...v];
                        next[i] = { ...item, [ik]: e.target.value };
                        onChange({ ...body, [k]: next });
                      }} />
                    </label>
                  ))}
                </div>
              ))}
            </fieldset>
          );
        }
        return null;
      })}
    </div>
  );
}
